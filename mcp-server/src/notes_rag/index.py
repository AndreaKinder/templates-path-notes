"""Semantic + hybrid indexing over notes vault using Ollama + SQLite (FTS5 + vector BLOBs)."""

import json
import math
import os
import re
import sqlite3
import hashlib
import unicodedata
import urllib.error
import urllib.request
from array import array
from datetime import date, datetime
from pathlib import Path

from .vault import parse_frontmatter

EXCLUDED_TOP = {"archived", "assets"}
EXCLUDED_PARTS = {".obsidian", ".trash", ".git"}
MAX_CHUNK_CHARS = 2400
EMBED_BATCH = 32


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


def _norm_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return [str(v) for v in val if v is not None]
    return [str(val)]


def _first_heading(body: str) -> str:
    m = re.search(r"^# (.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _derive_type(rel: Path, type_aliases: dict) -> str:
    top = rel.parts[0].lower() if len(rel.parts) > 1 else ""
    return type_aliases.get(top, top or "other")


def _extract_date(rel: Path, meta: dict, mtime: float) -> str:
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
        m = re.match(r"(1\d{9})-", str(cand))
        if m:
            try:
                return datetime.fromtimestamp(int(m.group(1))).date().isoformat()
            except (ValueError, OSError):
                pass
    return datetime.fromtimestamp(mtime).date().isoformat()


def _chunk_body(body: str) -> list[tuple[str, str]]:
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


def _header_line(title: str, aliases: list, tags: list, description: str, events: list, heading: str) -> str:
    parts = []
    if title:
        parts.append(f"TITLE: {title}")
    if aliases:
        parts.append(f"ALIAS: {', '.join(aliases)}")
    if tags:
        parts.append(f"TAGS: {', '.join(tags)}")
    if description:
        parts.append(f"DESCRIPTION: {description}")
    if events:
        parts.append(f"EVENTS: {', '.join(events)}")
    if heading:
        parts.append(f"SECTION: {heading}")
    return " | ".join(parts)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _list_md_files(vault_path: Path):
    for md in vault_path.glob("**/*.md"):
        rel_parts = md.relative_to(vault_path).parts
        if any(p in EXCLUDED_PARTS for p in rel_parts):
            continue
        if rel_parts and rel_parts[0] in EXCLUDED_TOP:
            continue
        yield md


def _db_connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def _embed_texts(texts: list[str], ollama_url: str, embed_model: str) -> list[list[float]]:
    if not texts:
        return []
    all_vecs = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i:i + EMBED_BATCH]
        payload = json.dumps({"model": embed_model, "input": batch}).encode()
        req = urllib.request.Request(
            f"{ollama_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        vecs = data.get("embeddings") or []
        if len(vecs) != len(batch):
            raise RuntimeError(f"Ollama returned {len(vecs)} vectors for {len(batch)} texts")
        all_vecs.extend(vecs)
    return all_vecs


def _remove_note(conn, rel_path: str):
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE path=?", (rel_path,))]
    if ids:
        conn.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        conn.execute("DELETE FROM chunks WHERE path=?", (rel_path,))


def _index_note(conn, md: Path, vault_path: Path, ollama_url: str, embed_model: str, type_aliases: dict, verbose: bool = False) -> int:
    rel = md.relative_to(vault_path)
    content = md.read_text(encoding="utf-8", errors="ignore")
    meta, body = parse_frontmatter(content)
    mtime = md.stat().st_mtime

    aliases = _norm_list(meta.get("aliases"))
    tags = _norm_list(meta.get("tags"))
    events = _norm_list(meta.get("events"))
    description = str(meta.get("description") or "")
    title = _first_heading(body) or (aliases[0] if aliases else rel.stem)
    note_date = _extract_date(rel, meta, mtime)

    _remove_note(conn, str(rel))

    chunks = _chunk_body(body) or [("", description or title)]
    embed_inputs = []
    for heading, text in chunks:
        head = _header_line(title, aliases, tags, description, events, heading)
        embed_inputs.append(f"{head}\n{text}" if head else text)

    vectors = _embed_texts(embed_inputs, ollama_url, embed_model)
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
        (str(rel), _file_hash(md), mtime, title, description,
         " | ".join(aliases), " | ".join(tags), _derive_type(rel, type_aliases), note_date),
    )
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('model', ?)", (embed_model,))
    conn.commit()
    if verbose:
        print(f"  + {rel} ({len(chunks)} chunks)", flush=True)
    return len(chunks)


def _pending_files(conn, vault_path: Path):
    indexed = dict(conn.execute("SELECT path, hash FROM notes"))
    changed, missing = [], set(indexed)
    for md in _list_md_files(vault_path):
        rel = str(md.relative_to(vault_path))
        missing.discard(rel)
        try:
            if _file_hash(md) != indexed.get(rel):
                changed.append((rel, md))
        except OSError:
            continue
    return changed, missing


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _fts_query(query: str, stopwords: set) -> str:
    toks = []
    seen = set()
    for w in re.findall(r"\w+", _strip_accents(query.lower())):
        if len(w) >= 3 and w not in stopwords and w not in seen:
            seen.add(w)
            toks.append(f'"{w}"*')
    return " OR ".join(toks[:12])


def _cosine(a: list[float], b: bytes | list[float]) -> float:
    if isinstance(b, bytes):
        b = array("f", b).tolist()
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


def _load_allowed(conn, ntype: str | None, tag: str | None, since: str | None, until: str | None, type_aliases: dict):
    sql, params = "SELECT path, title, type, tags, date FROM notes", []
    where = []
    resolved_type = None
    if ntype:
        resolved_type = type_aliases.get(ntype.lower(), ntype.lower())
        where.append("type = ?")
        params.append(resolved_type)
    rows = conn.execute(sql + (" WHERE " + " AND ".join(where) if where else ""), params).fetchall()
    allowed = {}
    for path, title, t, tags, ddate in rows:
        if tag:
            tag_l = tag.lower()
            parts = [p.strip().lower() for p in (tags or "").split("|")]
            if not any(p == tag_l or p.startswith(tag_l + "/") or tag_l in p for p in parts):
                continue
        if since and ddate and ddate < since:
            continue
        if until and ddate and ddate > until:
            continue
        allowed[path] = {"title": title, "type": t, "tags": tags, "date": ddate}
    return allowed


def _find_snippet(text: str, query: str, width: int = 160) -> str:
    toks = [w for w in re.findall(r"\w+", _strip_accents(query.lower())) if len(w) >= 3]
    plain = re.sub(r"[#>*`\n]+", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    for line_only in text.splitlines():
        l = _strip_accents(line_only.lower())
        for w in toks:
            if w in l:
                s = re.sub(r"[#>*`]+", "", line_only).strip()
                return (s[:width] + "…") if len(s) > width else s
    return (plain[:width] + "…") if len(plain) > width else plain


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_index(vault_path: Path, db_path: Path, ollama_url: str, embed_model: str, full_rebuild: bool, verbose: bool, type_aliases: dict) -> dict:
    """Build or rebuild the index. Returns summary dict."""
    conn = _db_connect(db_path)
    if full_rebuild:
        conn.executescript("DELETE FROM chunks_fts; DELETE FROM chunks; DELETE FROM notes; DELETE FROM meta;")

    changed, missing = _pending_files(conn, vault_path)
    for rel in missing:
        _remove_note(conn, rel)
        conn.execute("DELETE FROM notes WHERE path=?", (rel,))
    conn.commit()

    if full_rebuild:
        todo = [(str(md.relative_to(vault_path)), md) for md in _list_md_files(vault_path)]
    else:
        todo = changed

    if not todo and not missing:
        conn.close()
        return {"indexed": 0, "chunks": 0, "time": 0.0, "message": "Index up to date."}

    t0 = datetime.now()
    total_chunks = 0
    for i, (rel, md) in enumerate(todo, 1):
        total_chunks += _index_note(conn, md, vault_path, ollama_url, embed_model, type_aliases, verbose)
        if not verbose and (i % 20 == 0 or i == len(todo)):
            pass  # caller handles progress if needed
    dt = (datetime.now() - t0).total_seconds()
    conn.close()
    return {"indexed": len(todo), "chunks": total_chunks, "time": round(dt, 2), "message": f"Indexed {len(todo)} notes ({total_chunks} chunks) in {dt:.1f}s"}


def query_index(vault_path: Path, db_path: Path, ollama_url: str, embed_model: str, query: str, limit: int,
                ntype: str | None, tag: str | None, since: str | None, until: str | None,
                stopwords: set, type_aliases: dict) -> list[dict]:
    """Hybrid semantic + FTS search."""
    conn = _db_connect(db_path)
    db_model = conn.execute("SELECT value FROM meta WHERE key='model'").fetchone()
    if db_model and db_model[0] != embed_model:
        conn.close()
        raise RuntimeError(f"Model changed ({db_model[0]} -> {embed_model}); run full rebuild")

    # Quick incremental sync
    changed, missing = _pending_files(conn, vault_path)
    if missing or changed:
        for rel in missing:
            _remove_note(conn, rel)
            conn.execute("DELETE FROM notes WHERE path=?", (rel,))
        for _, md in changed:
            _index_note(conn, md, vault_path, ollama_url, embed_model, type_aliases)
        conn.commit()

    allowed = _load_allowed(conn, ntype, tag, since, until, type_aliases)
    if not allowed:
        conn.close()
        return []

    qvec = _embed_texts([query], ollama_url, embed_model)[0]

    vec_scores = {}
    for path, vecblob, dim in conn.execute("SELECT path, vector, dim FROM chunks"):
        if path not in allowed or dim != len(qvec):
            continue
        s = _cosine(qvec, vecblob)
        if s > vec_scores.get(path, (-2,))[0]:
            vec_scores[path] = (s, None)
    vec_ranked = sorted(vec_scores, key=lambda p: -vec_scores[p][0])

    fts_ranked = []
    match = _fts_query(query, stopwords)
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
    top = sorted(fused, key=lambda p: -fused[p])[:limit]

    results = []
    for p in top:
        cos = vec_scores.get(p, (0.0,))[0]
        chunk_row = None
        best = -2.0
        for cid, heading, text, vecblob in conn.execute(
                "SELECT id, heading, text, vector FROM chunks WHERE path=?", (p,)):
            s = _cosine(qvec, vecblob)
            if s > best:
                best, chunk_row = s, (heading, text)
        info = allowed[p]
        results.append({
            "path": p,
            "full_path": str(vault_path / p),
            "title": info["title"],
            "type": info["type"],
            "date": info["date"],
            "tags": info["tags"],
            "score": round(cos, 4),
            "fused": round(fused[p], 5),
            "heading": chunk_row[0] if chunk_row else "",
            "snippet": _find_snippet(chunk_row[1] if chunk_row else "", query),
        })

    conn.close()
    return results


def get_index_status(vault_path: Path, db_path: Path) -> dict:
    """Return current index status."""
    if not db_path.exists():
        return {"db_path": str(db_path), "exists": False, "notes": 0, "chunks": 0, "model": None, "pending_changed": 0, "pending_missing": 0}
    conn = _db_connect(db_path)
    n_notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    model = conn.execute("SELECT value FROM meta WHERE key='model'").fetchone()
    changed, missing = _pending_files(conn, vault_path)
    conn.close()
    return {
        "db_path": str(db_path),
        "exists": True,
        "notes": n_notes,
        "chunks": n_chunks,
        "model": model[0] if model else None,
        "pending_changed": len(changed),
        "pending_missing": len(missing),
    }
