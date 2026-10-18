#!/usr/bin/env python3
"""
CLI y biblioteca auxiliar para identificar, resolver, gestionar y crear notas en ~/Notas.
Se adhiere estrictamente a la arquitectura y reglas del vault definidas en AGENTS.md.
Acepta consultas en español; la taxonomía del vault (carpetas, tags,
cabeceras de sección) está en español según AGENTS.md.
"""

import sys
import os
import re
import json
import time
import argparse
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

VAULT_PATH = Path(os.getenv("NOTES_VAULT_PATH", os.getenv("NOTES_BASE_DIR", os.path.expanduser("~/Notas")))).resolve()

MONTHS = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4, "mayo": 5, "junio": 6, "jun": 6, "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8, "septiembre": 9, "setiembre": 9, "sep": 9, "octubre": 10,
    "oct": 10, "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12
}

WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
    "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6
}

# Las cabeceras de sección de la nota diaria son parte de la taxonomía del vault.
# Los alias amigables se mapean a las cabeceras canónicas del vault.
CATEGORY_ALIASES = {
    "casa / personal": "Casa / Personal",
    "hogar / personal": "Casa / Personal",
    "casa": "Casa / Personal",
    "hogar": "Casa / Personal",
    "personal": "Casa / Personal",
    "trabajo": "Trabajo",
    "empleo": "Trabajo",
    "social": "Social",
}


def normalize_category(category: str) -> str:
    """Mapea alias de categoría a las cabeceras de sección canónicas del vault."""
    key = (category or "").strip().lower()
    return CATEGORY_ALIASES.get(key, (category or "").strip() or "Casa / Personal")


def find_month(text: str):
    """Devuelve el número de mes (1-12) mencionado en el texto, o None."""
    for name, num in MONTHS.items():
        if re.search(rf"\b{re.escape(name)}\b", text):
            return num
    return None


def parse_frontmatter(content: str):
    """Extrae el frontmatter YAML y el cuerpo markdown del contenido de una nota."""
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", content, re.DOTALL)
    if not match:
        return {}, content
    yaml_text = match.group(1)
    body = match.group(2)
    meta = {}
    if yaml:
        try:
            meta = yaml.safe_load(yaml_text) or {}
        except Exception:
            pass
    if not meta:
        # Parser simple de respaldo
        for line in yaml_text.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip().strip('"\'')
    return meta, body


def dump_frontmatter(meta: dict, body: str) -> str:
    """Combina metadatos y cuerpo en el formato frontmatter estándar."""
    if yaml:
        yaml_text = yaml.dump(meta, sort_keys=False, allow_unicode=True).strip()
    else:
        lines = []
        for k, v in meta.items():
            if isinstance(v, list):
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {json.dumps(item) if isinstance(item, str) else item}")
            else:
                lines.append(f"{k}: {json.dumps(v) if isinstance(v, str) else v}")
        yaml_text = "\n".join(lines)
    return f"---\n{yaml_text}\n---\n\n{body.lstrip()}"


def resolve_date_expression(expr: str, base_date: date = None) -> date:
    """Parsea expresiones de fecha relativas o absolutas en español."""
    if base_date is None:
        base_date = date.today()

    norm = expr.strip().lower()

    # Fecha ISO exacta: YYYY-MM-DD
    iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", norm)
    if iso_match:
        y, m, d = map(int, iso_match.groups())
        return date(y, m, d)

    # Fecha europea: DD/MM/YYYY o DD-MM-YYYY
    eu_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", norm)
    if eu_match:
        d, m, y = map(int, eu_match.groups())
        return date(y, m, d)

    # Días relativos (verificar las frases más largas primero)
    if norm in ["hoy", "ahora", "actual", "nota de hoy", "nota diaria",
                "diario", "bitácora", "bitacora", "journal"]:
        return base_date
    if norm in ["anteayer", "antes de ayer", "antier"]:
        return base_date - timedelta(days=2)
    if norm in ["ayer", "nota de ayer"]:
        return base_date - timedelta(days=1)
    if norm in ["pasado mañana", "pasado manana"]:
        return base_date + timedelta(days=2)
    if norm in ["mañana", "manana", "nota de mañana", "nota de manana"]:
        return base_date + timedelta(days=1)

    # Patrones como "hace X días"
    days_ago = re.search(r"hace\s+(\d+)\s+d[ií]as?", norm)
    if days_ago:
        return base_date - timedelta(days=int(days_ago.group(1)))

    # Patrones como "en X días"
    days_in = re.search(r"en\s+(\d+)\s+d[ií]as?", norm)
    if days_in:
        return base_date + timedelta(days=int(days_in.group(1)))

    # Días de la semana (p. ej. "lunes", "lunes pasado", "viernes que viene")
    for name, wd in WEEKDAYS.items():
        if re.search(rf"\b{re.escape(name)}\b", norm):
            current_wd = base_date.weekday()
            if re.search(r"\b(pasado|pasada|anterior)\b", norm):
                diff = (current_wd - wd) % 7
                if diff == 0:
                    diff = 7
                return base_date - timedelta(days=diff)
            elif re.search(r"\b(que viene|próximo|proximo)\b", norm):
                diff = (wd - current_wd) % 7
                if diff == 0:
                    diff = 7
                return base_date + timedelta(days=diff)
            else:
                # Por defecto, el más reciente pasado o hoy
                diff = (current_wd - wd) % 7
                return base_date - timedelta(days=diff)

    # Fecha con nombre de mes: "14 de septiembre", "1 de octubre de 2026"
    es_month = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+(?:de\s+)?(\d{4}))?", norm)
    if es_month and es_month.group(2) in MONTHS:
        d = int(es_month.group(1))
        m = MONTHS[es_month.group(2)]
        y = int(es_month.group(3)) if es_month.group(3) else base_date.year
        return date(y, m, d)

    return base_date


def resolve_entity(query: str) -> dict:
    """
    Identifica de forma inteligente a qué nota o recurso del vault se refiere una consulta.
    Devuelve el tipo de entidad, la ruta del archivo candidato, si existe y metadatos.
    """
    q = query.strip().lower()

    # 1. NOTAS DIARIAS (Journal / Diario)
    daily_keywords = ["nota diaria", "diaria", "diario", "journal", "bitacora",
                      "bitácora", "hoy", "ayer", "mañana", "manana"]
    is_daily = any(k in q for k in daily_keywords) \
        or any(re.search(rf"\b{re.escape(d)}\b", q) for d in WEEKDAYS) \
        or re.search(r"\b\d{4}-\d{2}-\d{2}\b", q)

    # Detectar indicadores de finanzas que puedan entrar en conflicto
    finance_keywords = ["finanzas", "cuenta", "cuentas", "balance",
                        "gasto", "gastos", "ingreso", "ingresos", "presupuesto",
                        "recibo", "recibos", "ticket", "tickets",
                        "factura", "facturas", "resumen anual"]
    is_finance = any(k in q for k in finance_keywords)

    if is_finance:
        year_match = re.search(r"\b(20\d\d)\b", q)
        year = int(year_match.group(1)) if year_match else date.today().year

        # Comprobar recibos (gastos)
        if any(k in q for k in ["recibo", "recibos", "recivo", "recivos",
                                "ticket", "tickets", "justificante"]):
            path = VAULT_PATH / "finanzas" / str(year) / "recibos"
            return {
                "type": "finance_recibos",
                "name": f"Recibos {year}",
                "path": str(path),
                "exists": path.is_dir(),
                "year": year
            }

        # Comprobar facturas (emitidas)
        if any(k in q for k in ["factura", "facturas"]):
            path = VAULT_PATH / "finanzas" / str(year) / "facturas"
            return {
                "type": "finance_facturas",
                "name": f"Facturas {year}",
                "path": str(path),
                "exists": path.is_dir(),
                "year": year
            }

        # Comprobar resumen anual
        if "resumen anual" in q or "anual" in q:
            path = VAULT_PATH / "finanzas" / f"resumen-anual-{year}.md"
            return {
                "type": "finance_annual",
                "name": f"Resumen Anual {year}",
                "path": str(path),
                "exists": path.is_file(),
                "year": year
            }

        # Finanzas mensuales
        month_match = re.search(r"\b(20\d\d)-(\d{2})\b", q)
        if month_match:
            year, month = int(month_match.group(1)), int(month_match.group(2))
        else:
            found_month = find_month(q)
            month = found_month if found_month else date.today().month

        # En este vault, las cuentas se organizan en finanzas/YYYY/cuentas/YYYY-MM.md
        path_accounts = VAULT_PATH / "finanzas" / str(year) / "cuentas" / f"{year}-{month:02d}.md"
        path_legacy = VAULT_PATH / "finanzas" / str(year) / "Cuentas" / f"{year}-{month:02d}.md"
        path_direct = VAULT_PATH / "finanzas" / str(year) / f"{year}-{month:02d}.md"
        path = path_accounts if path_accounts.is_file() else (path_legacy if path_legacy.is_file() else (path_direct if path_direct.is_file() else path_accounts))

        return {
            "type": "finance_monthly",
            "name": f"Cuentas {year}-{month:02d}",
            "path": str(path),
            "exists": path.is_file(),
            "year": year,
            "month": month
        }

    if is_daily:
        target_date = resolve_date_expression(q)
        date_str = target_date.strftime("%Y-%m-%d")
        path = VAULT_PATH / "journal" / f"{date_str}.md"
        result = {
            "type": "daily_note",
            "name": f"Nota Diaria {date_str}",
            "date": date_str,
            "path": str(path),
            "exists": path.is_file()
        }
        if path.is_file():
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            result["metadata"] = meta
            # Extraer eventos
            events = meta.get("events", [])
            if isinstance(events, str):
                events = [events] if events else []
            result["events"] = events
            # Extraer tareas
            tasks = extract_tasks_from_markdown(body)
            result["tasks_summary"] = {
                "total": len(tasks),
                "pending": sum(1 for t in tasks if not t["completed"]),
                "completed": sum(1 for t in tasks if t["completed"])
            }
        return result

    # 2. PROYECTOS
    if "proyecto" in q:
        projects_dir = VAULT_PATH / "projects"
        if projects_dir.is_dir():
            for p in projects_dir.iterdir():
                if p.is_dir() and not p.name.startswith("."):
                    if p.name.lower() in q or any(word in p.name.lower() for word in q.split() if len(word) > 3):
                        readme = p / "README.md"
                        return {
                            "type": "project",
                            "name": p.name,
                            "path": str(p),
                            "readme": str(readme) if readme.is_file() else None,
                            "exists": True
                        }

    # 3. ZETTELKASTEN / BÚSQUEDA GENERAL
    zettel_dir = VAULT_PATH / "zettelkasten"
    if zettel_dir.is_dir():
        # Coincidencia por nombre de archivo
        clean_q = re.sub(r"[^\w\s-]", "", q).strip()
        candidates = []
        for f in zettel_dir.glob("*.md"):
            name = f.stem.lower()
            if clean_q in name:
                candidates.append(f)
            else:
                # Comprobar aliases en el frontmatter
                try:
                    meta, _ = parse_frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
                    aliases = [str(a).lower() for a in meta.get("aliases", [])]
                    if any(clean_q in a for a in aliases):
                        candidates.append(f)
                except Exception:
                    pass

        if candidates:
            best = candidates[0]
            meta, _ = parse_frontmatter(best.read_text(encoding="utf-8", errors="ignore"))
            return {
                "type": "zettelkasten",
                "name": best.stem,
                "path": str(best),
                "exists": True,
                "metadata": meta
            }

    # Respaldo por defecto: comprobar si es una fecha o tratar como consulta zettelkasten
    target_date = resolve_date_expression(q)
    date_str = target_date.strftime("%Y-%m-%d")
    daily_path = VAULT_PATH / "journal" / f"{date_str}.md"
    if daily_path.is_file():
        return {
            "type": "daily_note",
            "name": f"Nota Diaria {date_str}",
            "date": date_str,
            "path": str(daily_path),
            "exists": True
        }

    return {
        "type": "unknown",
        "query": query,
        "vault_path": str(VAULT_PATH),
        "exists": False
    }


def extract_tasks_from_markdown(content: str) -> list:
    """Extrae tareas checkbox de markdown con sus cabeceras de sección."""
    tasks = []
    current_section = "General"
    for line in content.splitlines():
        line_clean = line.strip()
        header_match = re.match(r"^(#{1,4})\s+(.+)$", line_clean)
        if header_match:
            current_section = header_match.group(2).strip()
            continue

        task_match = re.match(r"^-\s*\[([ xX])\]\s*(.*)$", line_clean)
        if task_match:
            is_done = task_match.group(1).lower() == "x"
            task_text = task_match.group(2).strip()
            if task_text:
                tasks.append({
                    "task": task_text,
                    "completed": is_done,
                    "section": current_section,
                    "raw": line
                })
    return tasks


def get_or_create_daily_note(date_val: date) -> tuple[Path, bool]:
    """
    Asegura que la nota diaria existe para date_val.
    Si no, la crea desde templates/plantilla-diaria.md.
    Devuelve (ruta, creada).
    """
    date_str = date_val.strftime("%Y-%m-%d")
    journal_dir = VAULT_PATH / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    note_path = journal_dir / f"{date_str}.md"

    if note_path.is_file():
        return note_path, False

    # Crear desde plantilla
    template_path = VAULT_PATH / "templates" / "plantilla-diaria.md"
    if template_path.is_file():
        template_text = template_path.read_text(encoding="utf-8")
        content = template_text.replace("{{date}}", date_str)
    else:
        # Estructura diaria estándar de respaldo conforme a AGENTS.md
        content = f"""---
id: {date_str}
description: ""
events: []
aliases:
  - "{date_str}"
tags:
  - daily-notes
---

# {date_str}

## TODO

### Trabajo

- [ ]

### Casa / Personal

- [ ]
"""
    note_path.write_text(content, encoding="utf-8")
    return note_path, True


def add_task_to_daily_note(date_val: date, task_text: str, category: str = "Casa / Personal") -> bool:
    """
    Añade un checkbox '- [ ] <task_text>' bajo la categoría indicada en la nota diaria.
    Crea la nota o la sección si no existe.
    """
    category = normalize_category(category)
    note_path, _ = get_or_create_daily_note(date_val)
    content = note_path.read_text(encoding="utf-8")

    category_header = f"### {category}"
    task_line = f"- [ ] {task_text}"

    # Comprobar si existe la cabecera de categoría
    if category_header in content:
        # Insertar justo debajo de la cabecera de categoría
        pattern = re.compile(rf"({re.escape(category_header)}\r?\n)")
        new_content = pattern.sub(rf"\1\n{task_line}\n", content, count=1)
    elif "## TODO" in content:
        # La categoría no existe, añadir categoría y tarea bajo ## TODO
        pattern = re.compile(r"(## TODO\r?\n)")
        new_content = pattern.sub(rf"\1\n{category_header}\n\n{task_line}\n", content, count=1)
    else:
        # Añadir ## TODO, categoría y tarea
        new_content = content.rstrip() + f"\n\n## TODO\n\n{category_header}\n\n{task_line}\n"

    # Limpiar líneas vacías dobles
    new_content = re.sub(r"\n{3,}", "\n\n", new_content)
    note_path.write_text(new_content, encoding="utf-8")
    return True


def add_event_to_daily_note(date_val: date, event_text: str) -> bool:
    """Añade un evento a la lista events del frontmatter YAML de la nota diaria."""
    note_path, _ = get_or_create_daily_note(date_val)
    content = note_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(content)

    events = meta.get("events", [])
    if isinstance(events, str):
        events = [events] if events else []
    elif events is None:
        events = []

    if event_text not in events:
        events.append(event_text)
    meta["events"] = events

    new_content = dump_frontmatter(meta, body)
    note_path.write_text(new_content, encoding="utf-8")
    return True


def classify_note_topic(topic: str) -> dict:
    """
    Clasifica qué tipo de nota se debe crear y dónde, según las reglas de AGENTS.md.
    """
    t = topic.lower().strip()
    timestamp = str(int(time.time()))

    if any(k in t for k in ["diario", "diaria", "journal", "bitacora",
                            "bitácora", "hoy", "ayer", "mañana", "manana"]):
        today_str = date.today().strftime("%Y-%m-%d")
        return {
            "type": "daily_note",
            "directory": "journal/",
            "filename": f"{today_str}.md",
            "template": "templates/plantilla-diaria.md",
            "tags": ["daily-notes"],
            "rule": "Registro diario en journal/YYYY-MM-DD.md"
        }

    if any(k in t for k in ["factura", "facturas", "facturación"]):
        today = date.today()
        return {
            "type": "finance_facturas",
            "directory": f"finanzas/{today.year}/facturas/",
            "filename": f"factura-{timestamp}.pdf",
            "tags": ["finanzas", "finanzas/facturas"],
            "rule": "Facturas emitidas organizadas en finanzas/YYYY/facturas/"
        }

    if any(k in t for k in ["recibo", "recibos", "recivo", "recivos",
                            "ticket", "tickets", "justificante"]):
        today = date.today()
        return {
            "type": "finance_recibos",
            "directory": f"finanzas/{today.year}/recibos/",
            "filename": f"recibo-{timestamp}.pdf",
            "tags": ["finanzas", "finanzas/recibos"],
            "rule": "Recibos y justificantes de gastos organizados en finanzas/YYYY/recibos/"
        }

    if any(k in t for k in ["finanzas", "gasto", "gastos",
                            "cuenta", "cuentas", "presupuesto", "ingreso",
                            "ingresos", "impuestos"]):
        today = date.today()
        target_month = find_month(t) or today.month
        return {
            "type": "finanzas",
            "directory": f"finanzas/{today.year}/cuentas/",
            "filename": f"{today.year}-{target_month:02d}.md",
            "template": "templates/plantilla-cuentas-mes.md",
            "tags": ["finanzas", "finanzas/mensual"],
            "rule": "Gestión financiera organizada en finanzas/YYYY/cuentas/YYYY-MM.md"
        }

    if any(k in t for k in ["proyecto", "desarrollo", "sistema"]):
        # Extraer slug
        slug = re.sub(r"[^\w\s-]", "", t).replace(" ", "-").strip("-")
        return {
            "type": "project",
            "directory": f"projects/{slug}/docs/",
            "filename": f"{slug}.md",
            "tags": ["project", slug],
            "rule": "Proyectos en projects/<project-name>/ con docs/, fases/, backups/"
        }

    # Por defecto: nota atómica zettelkasten
    slug = re.sub(r"[^\w\s-]", "", t).replace(" ", "-").strip("-")
    acronym = "".join([w[0].upper() for w in re.findall(r"\w+", t)[:4]])
    if not acronym or len(acronym) < 2:
        acronym = "NOTE"
    filename = f"{timestamp}-{slug[:30]}.md" if slug else f"{timestamp}-{acronym}.md"

    return {
        "type": "zettelkasten",
        "directory": "zettelkasten/",
        "filename": filename,
        "template": "templates/plantilla-nota.md",
        "tags": ["knowledge", "atomic"],
        "rule": "Notas genéricas y conocimiento atómico en zettelkasten/<TIMESTAMP>-<SLUG/ACRONYM>.md"
    }


def semantic_search(term: str, limit: int = 20) -> list:
    """Delega en el índice de embeddings (notas_index.py) para búsqueda semántica híbrida."""
    script = Path(__file__).resolve().parent / "notas_index.py"
    if not script.is_file():
        return []
    try:
        out = subprocess.run(
            [sys.executable, str(script), "find", term, "-k", str(limit), "--json"],
            capture_output=True, text=True, timeout=180,
        )
        if out.returncode != 0:
            return []
        items = json.loads(out.stdout)
        return [
            {
                "relative_path": it["path"],
                "path": it["full_path"],
                "filename": Path(it["path"]).name,
                "score": it.get("score"),
                "match": "semantic",
            }
            for it in items
        ]
    except Exception:
        return []


def _json_default(o):
    """Serializa objetos date/datetime a ISO en las salidas JSON."""
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)


def main():
    parser = argparse.ArgumentParser(description="Auxiliar del vault de notas y resolutor de entidades (~/Notas)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Comando resolve
    res_parser = subparsers.add_parser("resolve", help="Resuelve una frase en lenguaje natural como 'nota diaria' a una entidad del vault")
    res_parser.add_argument("query", help="Frase a resolver, p. ej. 'nota diaria', 'ayer', 'cuentas de septiembre'")
    res_parser.add_argument("--json", action="store_true", help="Imprimir salida estructurada en JSON")

    # 2. Subcomandos de nota diaria
    daily_parser = subparsers.add_parser("daily", help="Gestiona las notas diarias")
    daily_sub = daily_parser.add_subparsers(dest="daily_command", required=True)

    # daily get
    d_get = daily_sub.add_parser("get", help="Obtiene los detalles de la nota diaria")
    d_get.add_argument("--date", default="hoy", help="Fecha: 'hoy', 'ayer', 'mañana', 'YYYY-MM-DD'")
    d_get.add_argument("--json", action="store_true")

    # daily create
    d_create = daily_sub.add_parser("create", help="Crea la nota diaria si falta")
    d_create.add_argument("--date", default="hoy", help="Fecha: 'hoy', 'ayer', 'mañana', 'YYYY-MM-DD'")

    # daily add-task
    d_task = daily_sub.add_parser("add-task", help="Añade una tarea a la nota diaria")
    d_task.add_argument("task", help="Descripción de la tarea")
    d_task.add_argument("--category", default="Casa / Personal",
                        help="Categoría: 'Casa / Personal' (alias: 'Personal', 'Casa'), 'Trabajo' (alias: 'Empleo'), 'Social'")
    d_task.add_argument("--date", default="hoy", help="Expresión de fecha")

    # daily add-event
    d_event = daily_sub.add_parser("add-event", help="Añade un evento al frontmatter de la nota diaria")
    d_event.add_argument("event", help="Descripción del evento")
    d_event.add_argument("--date", default="hoy", help="Expresión de fecha")

    # 3. Comando classify
    class_parser = subparsers.add_parser("classify", help="Determina la categoría y ruta destino de una nota")
    class_parser.add_argument("topic", help="Tema o título de la nota")
    class_parser.add_argument("--json", action="store_true")

    # 4. Comando search
    search_parser = subparsers.add_parser("search", help="Busca notas en el vault")
    search_parser.add_argument("term", help="Término de búsqueda")
    search_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.command == "resolve":
        res = resolve_entity(args.query)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False, default=_json_default))
        else:
            print(f"Tipo: {res.get('type')}")
            print(f"Nombre: {res.get('name')}")
            print(f"Ruta: {res.get('path')}")
            print(f"Existe: {'Sí' if res.get('exists') else 'No'}")
            if "events" in res and res["events"]:
                print(f"Eventos: {', '.join(res['events'])}")
            if "tasks_summary" in res:
                ts = res["tasks_summary"]
                print(f"Tareas: {ts['total']} (Pendientes: {ts['pending']}, Completadas: {ts['completed']})")

    elif args.command == "daily":
        d_val = resolve_date_expression(args.date)
        if args.daily_command == "get":
            date_str = d_val.strftime("%Y-%m-%d")
            path = VAULT_PATH / "journal" / f"{date_str}.md"
            if not path.is_file():
                res = {"exists": False, "date": date_str, "path": str(path)}
            else:
                meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                tasks = extract_tasks_from_markdown(body)
                res = {
                    "exists": True,
                    "date": date_str,
                    "path": str(path),
                    "metadata": meta,
                    "events": meta.get("events", []),
                    "tasks": tasks
                }
            if args.json:
                print(json.dumps(res, indent=2, ensure_ascii=False, default=_json_default))
            else:
                if not res["exists"]:
                    print(f"La nota diaria {date_str} NO existe en {path}")
                else:
                    print(f"📅 Nota Diaria: {date_str}")
                    print(f"📂 Ruta: {path}")
                    if res.get("events"):
                        print(f"📌 Eventos:")
                        for ev in res["events"]:
                            print(f"   - {ev}")
                    print(f"✅ Tareas ({len(res['tasks'])}):")
                    for t in res["tasks"]:
                        status = "[x]" if t["completed"] else "[ ]"
                        print(f"   {status} ({t['section']}) {t['task']}")

        elif args.daily_command == "create":
            path, created = get_or_create_daily_note(d_val)
            print(f"{'Creada' if created else 'Ya existía'}: {path}")

        elif args.daily_command == "add-task":
            add_task_to_daily_note(d_val, args.task, args.category)
            date_str = d_val.strftime("%Y-%m-%d")
            print(f"Tarea añadida a la nota diaria {date_str} [{normalize_category(args.category)}]: {args.task}")

        elif args.daily_command == "add-event":
            add_event_to_daily_note(d_val, args.event)
            date_str = d_val.strftime("%Y-%m-%d")
            print(f"Evento añadido a la nota diaria {date_str}: {args.event}")

    elif args.command == "classify":
        res = classify_note_topic(args.topic)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False, default=_json_default))
        else:
            print(f"Categoría: {res['type']}")
            print(f"Directorio: {res['directory']}")
            print(f"Archivo sugerido: {res['filename']}")
            print(f"Regla: {res['rule']}")

    elif args.command == "search":
        term = args.term.lower()
        results = []
        for md_file in VAULT_PATH.glob("**/*.md"):
            if ".trash" in md_file.parts or ".obsidian" in md_file.parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                if term in md_file.name.lower() or term in content.lower():
                    rel = md_file.relative_to(VAULT_PATH)
                    results.append({
                        "relative_path": str(rel),
                        "path": str(md_file),
                        "filename": md_file.name
                    })
            except Exception:
                pass

        if len(results) < 3:
            seen = {r["relative_path"] for r in results}
            for r in results:
                r["match"] = "lexical"
            for sem in semantic_search(args.term):
                if sem["relative_path"] not in seen:
                    seen.add(sem["relative_path"])
                    results.append(sem)

        if args.json:
            print(json.dumps(results[:20], indent=2, ensure_ascii=False))
        else:
            print(f"Encontradas {len(results)} notas (mostrando hasta 20):")
            for r in results[:20]:
                tag = " [sem]" if r.get("match") == "semantic" else ""
                print(f" - {r['relative_path']}{tag}")


if __name__ == "__main__":
    main()
