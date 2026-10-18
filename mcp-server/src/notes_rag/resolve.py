"""Entity resolution helper — converts natural-language queries to vault paths."""

import os
import re
from datetime import date, timedelta
from pathlib import Path


SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

SPANISH_WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
    "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6,
}

ENGLISH_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

ENGLISH_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def resolve_date_expression(expr: str, base_date: date | None = None, lang: str = "es") -> date:
    """Parse relative or absolute date expressions in Spanish/English."""
    if base_date is None:
        base_date = date.today()

    norm = expr.strip().lower()

    # ISO date: YYYY-MM-DD
    iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", norm)
    if iso_match:
        y, m, d = map(int, iso_match.groups())
        return date(y, m, d)

    # European date: DD/MM/YYYY or DD-MM-YYYY
    eu_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", norm)
    if eu_match:
        d, m, y = map(int, eu_match.groups())
        return date(y, m, d)

    # Relative days (cross-language)
    daily_keywords = {
        "hoy", "today", "ahora", "current", "nota de hoy", "nota diaria",
        "diario", "diaria", "journal", "bitacora", "bitácora",
    }
    if any(kw in norm for kw in daily_keywords):
        return base_date

    if norm in {"ayer", "yesterday", "nota de ayer"}:
        return base_date - timedelta(days=1)
    if norm in {"anteayer", "antes de ayer", "antier", "day before yesterday"}:
        return base_date - timedelta(days=2)
    if norm in {"mañana", "manana", "tomorrow", "nota de mañana", "nota de manana"}:
        return base_date + timedelta(days=1)
    if norm in {"pasado mañana", "pasado manana", "day after tomorrow"}:
        return base_date + timedelta(days=2)

    # Days ago / in N days
    days_ago = re.search(r"hace\s+(\d+)\s+d[ií]as?", norm)
    if days_ago:
        return base_date - timedelta(days=int(days_ago.group(1)))
    days_in = re.search(r"en\s+(\d+)\s+d[ií]as?", norm)
    if days_in:
        return base_date + timedelta(days=int(days_in.group(1)))

    en_days_ago = re.search(r"(\d+)\s+days?\s+ago", norm)
    if en_days_ago:
        return base_date - timedelta(days=int(en_days_ago.group(1)))
    en_days_in = re.search(r"in\s+(\d+)\s+days?", norm)
    if en_days_in:
        return base_date + timedelta(days=int(en_days_in.group(1)))

    # Weekdays
    weekdays = {**SPANISH_WEEKDAYS, **ENGLISH_WEEKDAYS}
    for name, wd in weekdays.items():
        if name in norm:
            current_wd = base_date.weekday()
            if "pasado" in norm or "anterior" in norm or "last" in norm:
                diff = (current_wd - wd) % 7
                if diff == 0:
                    diff = 7
                return base_date - timedelta(days=diff)
            elif "que viene" in norm or "proximo" in norm or "próximo" in norm or "next" in norm:
                diff = (wd - current_wd) % 7
                if diff == 0:
                    diff = 7
                return base_date + timedelta(days=diff)
            else:
                diff = (current_wd - wd) % 7
                return base_date - timedelta(days=diff)

    # Date with month name: "14 de septiembre" / "September 14"
    month_match_es = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+(?:de\s+)?(\d{4}))?", norm)
    if month_match_es:
        d = int(month_match_es.group(1))
        m_str = month_match_es.group(2)
        y = int(month_match_es.group(3)) if month_match_es.group(3) else base_date.year
        if m_str in SPANISH_MONTHS:
            return date(y, SPANISH_MONTHS[m_str], d)

    month_match_en = re.search(r"([a-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?", norm)
    if month_match_en:
        m_str = month_match_en.group(1)
        d = int(month_match_en.group(2))
        y = int(month_match_en.group(3)) if month_match_en.group(3) else base_date.year
        if m_str in ENGLISH_MONTHS:
            return date(y, ENGLISH_MONTHS[m_str], d)

    return base_date


def resolve_entity(query: str, vault_path: Path) -> dict:
    """
    Resolve a natural-language query to a vault entity.
    Returns dict with type, path, exists, and metadata.
    """
    q = query.strip().lower()

    # Finance indicators
    finance_keywords = {
        "finanzas", "cuentas", "gastos", "gasto", "balance", "resumen anual",
        "recibo", "recibos", "recivo", "recivos", "ticket", "tickets",
        "factura", "facturas", "justificante",
        "finance", "accounts", "expenses", "expense", "receipt", "receipts",
        "invoice", "invoices",
    }
    if any(k in q for k in finance_keywords):
        year_match = re.search(r"\b(20\d\d)\b", q)
        year = int(year_match.group(1)) if year_match else date.today().year

        if any(k in q for k in {"recibo", "recibos", "recivo", "recivos", "ticket", "tickets", "receipt", "receipts"}):
            path = vault_path / "finanzas" / str(year) / "recibos"
            return {"type": "finance_recibos", "name": f"Recibos {year}", "path": str(path), "exists": path.is_dir(), "year": year}

        if any(k in q for k in {"factura", "facturas", "invoice", "invoices"}):
            path = vault_path / "finanzas" / str(year) / "facturas"
            return {"type": "finance_facturas", "name": f"Facturas {year}", "path": str(path), "exists": path.is_dir(), "year": year}

        if "resumen anual" in q or "annual summary" in q or "anual" in q:
            path = vault_path / "finanzas" / f"resumen-anual-{year}.md"
            return {"type": "finance_annual", "name": f"Resumen Anual {year}", "path": str(path), "exists": path.is_file(), "year": year}

        # Monthly finance
        target_date = date.today()
        month_match = re.search(r"\b(20\d\d)-(\d{2})\b", q)
        if month_match:
            year, month = int(month_match.group(1)), int(month_match.group(2))
        else:
            found_month = None
            for m_name, m_num in {**SPANISH_MONTHS, **ENGLISH_MONTHS}.items():
                if m_name in q:
                    found_month = m_num
                    break
            month = found_month if found_month else date.today().month

        path_cuentas = vault_path / "finanzas" / str(year) / "cuentas" / f"{year}-{month:02d}.md"
        path_legacy = vault_path / "finanzas" / str(year) / "Cuentas" / f"{year}-{month:02d}.md"
        path_direct = vault_path / "finanzas" / str(year) / f"{year}-{month:02d}.md"
        path = path_cuentas if path_cuentas.is_file() else (path_legacy if path_legacy.is_file() else (path_direct if path_direct.is_file() else path_cuentas))
        return {"type": "finance_monthly", "name": f"Cuentas {year}-{month:02d}", "path": str(path), "exists": path.is_file(), "year": year, "month": month}

    # Daily notes
    daily_keywords = {
        "nota diaria", "diaria", "diario", "journal", "bitacora", "bitácora",
        "daily", "daily-note", "daily note",
    }
    is_daily = any(k in q for k in daily_keywords) or any(d in q for d in weekdays) or re.search(r"\b\d{4}-\d{2}-\d{2}\b", q)

    if is_daily:
        target_date = resolve_date_expression(q)
        date_str = target_date.strftime("%Y-%m-%d")
        path = vault_path / "journal" / f"{date_str}.md"
        result = {"type": "daily_note", "name": f"Nota Diaria {date_str}", "date": date_str, "path": str(path), "exists": path.is_file()}
        if path.is_file():
            from .vault import parse_frontmatter, extract_tasks_from_markdown
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            result["metadata"] = meta
            events = meta.get("events", [])
            if isinstance(events, str):
                events = [events] if events else []
            result["events"] = events
            tasks = extract_tasks_from_markdown(body)
            result["tasks_summary"] = {
                "total": len(tasks),
                "pending": sum(1 for t in tasks if not t["completed"]),
                "completed": sum(1 for t in tasks if t["completed"]),
            }
        return result

    # Projects
    if "proyecto" in q or "project" in q:
        projects_dir = vault_path / "projects"
        if projects_dir.is_dir():
            for p in projects_dir.iterdir():
                if p.is_dir() and not p.name.startswith("."):
                    if p.name.lower() in q or any(len(w) > 3 and w in p.name.lower() for w in q.split()):
                        readme = p / "README.md"
                        return {"type": "project", "name": p.name, "path": str(p), "readme": str(readme) if readme.is_file() else None, "exists": True}

    # Zettelkasten / general search
    zettel_dir = vault_path / "zettelkasten"
    if zettel_dir.is_dir():
        clean_q = re.sub(r"[^\w\s-]", "", q).strip()
        candidates = []
        for f in zettel_dir.glob("*.md"):
            name = f.stem.lower()
            if clean_q in name:
                candidates.append(f)
            else:
                try:
                    from .vault import parse_frontmatter
                    meta, _ = parse_frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
                    aliases = [str(a).lower() for a in meta.get("aliases", [])]
                    if any(clean_q in a for a in aliases):
                        candidates.append(f)
                except Exception:
                    pass
        if candidates:
            best = candidates[0]
            from .vault import parse_frontmatter
            meta, _ = parse_frontmatter(best.read_text(encoding="utf-8", errors="ignore"))
            return {"type": "zettelkasten", "name": best.stem, "path": str(best), "exists": True, "metadata": meta}

    # Fallback to daily note for date-like queries
    target_date = resolve_date_expression(q)
    date_str = target_date.strftime("%Y-%m-%d")
    daily_path = vault_path / "journal" / f"{date_str}.md"
    if daily_path.is_file():
        return {"type": "daily_note", "name": f"Nota Diaria {date_str}", "date": date_str, "path": str(daily_path), "exists": True}

    return {"type": "unknown", "query": query, "vault_path": str(vault_path), "exists": False}
