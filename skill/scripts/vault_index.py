#!/usr/bin/env python3
"""
Índice semántico + híbrido para las notas de ~/Notas usando Ollama.

Vectoriza fragmentos (chunks por cabeceras) enriquecidos con los metadatos
del frontmatter (título, aliases, tags, descripción, eventos) y los fusiona
con un índice FTS5 de palabras clave. La BD vive fuera del vault
(regla de AGENTS.md): ~/.local/share/notas-index/index.db

Comandos:
  build [--full]     Indexa el vault (incremental por sha256).
  find <consulta>    Búsqueda híbrida con filtros de metadatos.
  status             Estado del índice y cambios pendientes.
"""

import os
import re
import sys
import json
import math
import sqlite3
import hashlib
import argparse
import unicodedata
import urllib.error
import urllib.request
from array import array
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from resolve_note import parse_frontmatter, VAULT_PATH  # noqa: E402

# Fallback env name for compatibility
if not os.getenv("NOTES_VAULT_PATH") and os.getenv("NOTES_BASE_DIR"):
    os.environ["NOTES_VAULT_PATH"] = os.environ["NOTES_BASE_DIR"]

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.getenv("NOTES_EMBED_MODEL", "snowflake-arctic-embed2")
DB_PATH = Path(os.getenv(
    "NOTES_INDEX_DB",
    Path.home() / ".local" / "share" / "notas-rag" / "index.db"))

EXCLUDED_TOP = {"archived", "assets"}
EXCLUDED_PARTS = {".obsidian", ".trash", ".git"}
MAX_CHUNK_CHARS = 2400
EMBED_BATCH = 32

TYPE_ALIASES = {
    "journal": "journal", "diaria": "journal", "diario": "journal",
    "bitacora": "journal", "bitácora": "journal",
    "zettelkasten": "zettelkasten", "zettel": "zettelkasten",
    "nota": "zettelkasten", "notas": "zettelkasten",
    "projects": "projects", "project": "projects",
    "proyectos": "projects", "proyecto": "projects",
    "finanzas": "finanzas", "finanza": "finanzas",
    "todo": "todo", "inbox": "inbox",
    "templates": "templates", "plantilla": "templates",
    "plantillas": "templates", "prompts": "prompts",
}

STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "en", "y", "o", "u", "a", "al", "con", "por", "para", "que", "se",
    "su", "sus", "mi", "mis", "tu", "tus", "es", "son", "fue", "era",
    "lo", "le", "les", "me", "te", "nos", "este", "esta", "estos",
    "estas", "ese", "esa", "eso", "como", "cuando", "donde", "que",
    "quien", "cuanto", "mas", "menos", "ya", "no", "si", "tambien",
    "muy", "entre", "sobre", "tras", "cada", "sin", "algo", "cual",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes(
  path TEXT PRIMARY KEY,
  hash TEXT NOT NULL,
  mtime REAL,
  title TEXT,
  description TEXT,
  aliases TEXT,
  tags TEXT,
  type TEXT,
  date TEXT
);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL,
  ord INTEGER NOT NULL,
  heading TEXT,
  text TEXT,
  dim INTEGER NOT NULL,
  vector BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, heading, title, aliases, tags,
  tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def db_connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def list_md_files():
    for md in VAULT_PATH.glob("**/*.md"):
        rel_parts = md.relative_to(VAULT_PATH).parts
        if any(p in EXCLUDED_PARTS for p in rel_parts):
            continue
        if rel_parts and rel_parts[0] in EXCLUDED_TOP:
            continue
        yield md


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_type(rel: Path) -> str:
    top = rel.parts[0].lower() if len(rel.parts) > 1 else ""
    return TYPE_ALIASES.get(top, top or "other")


def extract_date(rel: Path, meta: dict, mtime: float) -> str:
    candidates = [meta.get("id"), rel.name, *rel.parts]
    for cand in candidates:
        if not isinstance(cand, str):
            continue
        m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", cand)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                pass
        m = re.search(r"\b(\d{4})-(\d{2})\b", cand)
        if m:
            return f"{m.group(1)}-{m.group(2)}-01"
    for cand in candidates:
        m = re.match(r"(1\d{9})-", str(cand))
        if m:
            try:
                return datetime.fromtimestamp(int(m.group(1))).date().isoformat()
            except (ValueError, OSError):
                pass
    return datetime.fromtimestamp(mtime).date().isoformat()


def norm_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return [str(v) for v in val if v is not None]
    return [str(val)]


def first_heading(body: str) -> str:
    m = re.search(r"^# (.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else ""


def chunk_body(body: str) -> list:
    chunks, ctx, buf = [], {}, []

    def flush():
        if buf:
            text = "\n".join(buf).strip()
            if text:
                heading = " › ".join(ctx[k] for k in sorted(ctx))
                chunks.append((heading, text[:MAX_CHUNK_CHARS]))

    for line in body.splitlines():
        m = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if m:
            flush()
            buf = [line]
            level = len(m.group(1))
            ctx[level] = m.group(2).strip()
            for deeper in [k for k in ctx if k > level]:
                del ctx[deeper]
        else:
            buf.append(line)
    flush()
    return chunks


def embed_texts(texts: list) -> list:
    all_vecs = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i:i + EMBED_BATCH]
        payload = json.dumps({"model": EMBED_MODEL, "input": batch}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        vecs = data.get("embeddings") or []
        if len(vecs) != len(batch):
            raise RuntimeError(f"Ollama devolvió {len(vecs)} vectores para {len(batch)} textos")
        all_vecs.extend(vecs)
    return all_vecs


def header_line(title, aliases, tags, description, events, heading) -> str:
    parts = []
    if title:
        parts.append(f"TITLE: {title}")
    if aliases:
        parts.append(f"ALIASES: {', '.join(aliases)}")
    if tags:
        parts.append(f"TAGS: {', '.join(tags)}")
    if description:
        parts.append(f"DESCRIPTION: {description}")
    if events:
        parts.append(f"EVENTS: {', '.join(events)}")
    if heading:
        parts.append(f"SECTION: {heading}")
    return " | ".join(parts)


def remove_note(conn, rel_path: str):
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE path=?", (rel_path,))]
    if ids:
        conn.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        conn.execute("DELETE FROM chunks WHERE path=?", (rel_path,))


def index_note(conn, md: Path, verbose: bool = False) -> int:
    rel = md.relative_to(VAULT_PATH)
    content = md.read_text(encoding="utf-8", errors="ignore")
    meta, body = parse_frontmatter(content)
    mtime = md.stat().st_mtime

    aliases = norm_list(meta.get("aliases"))
    tags = norm_list(meta.get("tags"))
    events = norm_list(meta.get("events"))
    description = str(meta.get("description") or "")
    title = first_heading(body) or (aliases[0] if aliases else rel.stem)
    note_date = extract_date(rel, meta, mtime)

    remove_note(conn, str(rel))

    chunks = chunk_body(body) or [("", description or title)]
    embed_inputs = []
    for heading, text in chunks:
        head = header_line(title, aliases, tags, description, events, heading)
        embed_inputs.append(f"{head}\n{text}" if head else text)

    vectors = embed_texts(embed_inputs)
    for ordn, ((heading, text), vec) in enumerate(zip(chunks, vectors)):
        cur = conn.execute(
            "INSERT INTO chunks(path, ord, heading, text, dim, vector) VALUES(?,?,?,?,?,?)",
            (str(rel), ordn, heading, text, len(vec), array("f", vec).tobytes()),
        )
        conn.execute(
            "INSERT INTO chunks_fts(rowid, text, heading, title, aliases, tags) VALUES(?,?,?,?,?,?)",
            (cur.lastrowid, text, heading, title, " ".join(aliases), " ".join(tags)),
        )

    conn.execute(
        "INSERT OR REPLACE INTO notes(path, hash, mtime, title, description, aliases, tags, type, date) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (str(rel), file_hash(md), mtime, title, description,
         " | ".join(aliases), " | ".join(tags), derive_type(rel), note_date),
    )
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('model', ?)", (EMBED_MODEL,))
    conn.commit()
    if verbose:
        print(f"  + {rel} ({len(chunks)} chunks)", flush=True)
    return len(chunks)


def pending_files(conn):
    indexed = dict(conn.execute("SELECT path, hash FROM notes"))
    changed, missing = [], set(indexed)
    for md in list_md_files():
        rel = str(md.relative_to(VAULT_PATH))
        missing.discard(rel)
        try:
            if file_hash(md) != indexed.get(rel):
                changed.append((rel, md))
        except OSError:
            continue
    return changed, missing


def cmd_build(args):
    conn = db_connect()
    if args.full:
        conn.executescript("DELETE FROM chunks_fts; DELETE FROM chunks; DELETE FROM notes;"
                           "DELETE FROM meta;")
        print("Índice vaciado (build completo)")

    changed, missing = pending_files(conn)
    for rel in missing:
        remove_note(conn, rel)
        conn.execute("DELETE FROM notes WHERE path=?", (rel,))
    conn.commit()

    if args.full:
        todo = [(str(md.relative_to(VAULT_PATH)), md) for md in list_md_files()]
    else:
        todo = changed

    if not todo and not missing:
        print("Índice al día, nada que hacer.")
        return

    t0 = datetime.now()
    total_chunks = 0
    for i, (rel, md) in enumerate(todo, 1):
        total_chunks += index_note(conn, md, verbose=args.verbose)
        if not args.verbose and (i % 20 == 0 or i == len(todo)):
            print(f"  {i}/{len(todo)} notas...", flush=True)
    dt = (datetime.now() - t0).total_seconds()
    print(f"Indexadas {len(todo)} notas ({total_chunks} chunks) en {dt:.1f}s -> {DB_PATH}")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def fts_query(query: str) -> str:
    toks = []
    seen = set()
    for w in re.findall(r"\w+", strip_accents(query.lower())):
        if len(w) >= 3 and w not in STOPWORDS and w not in seen:
            seen.add(w)
            toks.append(f'"{w}"*')
    return " OR ".join(toks[:12])


def cosine(a, b):
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


def load_allowed(conn, args):
    sql, params = "SELECT path, title, type, tags, date FROM notes", []
    where = []
    ntype = None
    if args.type:
        ntype = TYPE_ALIASES.get(args.type.lower(), args.type.lower())
        where.append("type = ?")
        params.append(ntype)
    rows = conn.execute(sql + (" WHERE " + " AND ".join(where) if where else ""), params).fetchall()
    allowed = {}
    for path, title, t, tags, ddate in rows:
        if args.tag:
            tag_l = args.tag.lower()
            parts = [p.strip().lower() for p in (tags or "").split("|")]
            if not any(p == tag_l or p.startswith(tag_l + "/") or tag_l in p for p in parts):
                continue
        if args.since and ddate and ddate < args.since:
            continue
        if args.until and ddate and ddate > args.until:
            continue
        allowed[path] = {"title": title, "type": t, "tags": tags, "date": ddate}
    return allowed


def find_snippet(text: str, query: str, width: int = 160) -> str:
    toks = [w for w in re.findall(r"\w+", strip_accents(query.lower())) if len(w) >= 3]
    plain = re.sub(r"[#>*`\n]+", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    for line_only in text.splitlines():
        l = strip_accents(line_only.lower())
        for w in toks:
            if w in l:
                s = re.sub(r"[#>*`]+", "", line_only).strip()
                return (s[:width] + "…") if len(s) > width else s
    return (plain[:width] + "…") if len(plain) > width else plain


def cmd_find(args):
    conn = db_connect()
    db_model = conn.execute("SELECT value FROM meta WHERE key='model'").fetchone()
    if db_model and db_model[0] != EMBED_MODEL:
        sys.exit(f"Modelo cambiado ({db_model[0]} -> {EMBED_MODEL}); ejecuta: notas_index.py build --full")

    changed, missing = pending_files(conn)
    if missing or changed:
        print(f"[resinc] {len(changed)} modificadas, {len(missing)} eliminadas...", file=sys.stderr, flush=True)
        for rel in missing:
            remove_note(conn, rel)
            conn.execute("DELETE FROM notes WHERE path=?", (rel,))
        for _, md in changed:
            index_note(conn, md)
        conn.commit()

    allowed = load_allowed(conn, args)
    if not allowed:
        sys.exit("Ninguna nota coincide con los filtros.")

    qvec = embed_texts([args.query])[0]

    vec_scores = {}
    for path, vecblob, dim in conn.execute("SELECT path, vector, dim FROM chunks"):
        if path not in allowed or dim != len(qvec):
            continue
        s = cosine(qvec, array("f", vecblob))
        if s > vec_scores.get(path, (-2,))[0]:
            vec_scores[path] = (s, None)
    vec_ranked = sorted(vec_scores, key=lambda p: -vec_scores[p][0])

    fts_ranked = []
    match = fts_query(args.query)
    if match:
        hits = conn.execute(
            "SELECT rowid, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 100",
            (match,),
        ).fetchall()
        seen = set()
        for rowid, _rank in hits:
            row = conn.execute("SELECT path FROM chunks WHERE id=?", (rowid,)).fetchone()
            if row and row[0] in allowed and row[0] not in seen:
                seen.add(row[0])
                fts_ranked.append(row[0])

    fused = {}
    for ch, ranked in enumerate((vec_ranked, fts_ranked)):
        for r, p in enumerate(ranked):
            fused.setdefault(p, 0.0)
            fused[p] += 1.0 / (60 + r + 1)
    top = sorted(fused, key=lambda p: -fused[p])[: args.limit]

    results = []
    for p in top:
        cos = vec_scores.get(p, (0.0,))[0]
        chunk_row = None
        best = -2.0
        for cid, heading, text, vecblob in conn.execute(
                "SELECT id, heading, text, vector FROM chunks WHERE path=?", (p,)):
            s = cosine(qvec, array("f", vecblob))
            if s > best:
                best, chunk_row = s, (heading, text)
        info = allowed[p]
        results.append({
            "path": p,
            "full_path": str(VAULT_PATH / p),
            "title": info["title"],
            "type": info["type"],
            "date": info["date"],
            "tags": info["tags"],
            "score": round(cos, 4),
            "fused": round(fused[p], 5),
            "heading": chunk_row[0] if chunk_row else "",
            "snippet": find_snippet(chunk_row[1] if chunk_row else "", args.query),
        })

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        if not results:
            print("Sin resultados.")
            return
        print(f"Top {len(results)} para: {args.query!r}\n")
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r['score']:.3f}] {r['path']}  ({r['type']} · {r['date']})")
            if r["heading"]:
                print(f"      § {r['heading']}")
            print(f"      {r['snippet']}")
            if r["tags"]:
                print(f"      tags: {r['tags'].replace('|', ',').strip()}")
            print()


def cmd_status(args):
    conn = db_connect()
    n_notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    model = conn.execute("SELECT value FROM meta WHERE key='model'").fetchone()
    changed, missing = pending_files(conn)
    print(f"BD:      {DB_PATH} ({DB_PATH.stat().st_size / 1024 / 1024:.1f} MB)" if DB_PATH.exists() else f"BD:      {DB_PATH} (no existe)")
    print(f"Modelo:  {model[0] if model else EMBED_MODEL}")
    print(f"Notas:   {n_notes} indexadas · {n_chunks} chunks")
    print(f"Pendiente: {len(changed)} nuevas/modificadas · {len(missing)} eliminadas del vault")
    types = conn.execute("SELECT type, COUNT(*) FROM notes GROUP BY type ORDER BY 2 DESC").fetchall()
    if types:
        print("Tipos:  " + ", ".join(f"{t}={c}" for t, c in types))


def main():
    parser = argparse.ArgumentParser(description="Índice semántico para ~/Notas (Ollama + SQLite)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Indexa el vault")
    p_build.add_argument("--full", action="store_true", help="Reindexar todo desde cero")
    p_build.add_argument("-v", "--verbose", action="store_true")
    p_build.set_defaults(func=cmd_build)

    p_find = sub.add_parser("find", help="Búsqueda híbrida semántica + palabras clave")
    p_find.add_argument("query")
    p_find.add_argument("-k", "--limit", type=int, default=6)
    p_find.add_argument("--type", help="journal|zettelkasten|projects|finanzas|todo|inbox|templates|prompts")
    p_find.add_argument("--tag", help="Filtrar por tag (prefijo jerárquico soportado)")
    p_find.add_argument("--since", help="YYYY-MM-DD")
    p_find.add_argument("--until", help="YYYY-MM-DD")
    p_find.add_argument("--json", action="store_true")
    p_find.set_defaults(func=cmd_find)

    p_status = sub.add_parser("status", help="Estado del índice")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    try:
        args.func(args)
    except urllib.error.URLError as e:
        sys.exit(f"Sin conexión con Ollama en {OLLAMA_URL}: {e}\n¿Modelo descargado? ollama pull {EMBED_MODEL}")


if __name__ == "__main__":
    main()
