"""Vault file operations: frontmatter, daily notes, tasks, zettel creation."""

import json
import os
import re
import time
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

from .resolve import resolve_date_expression, SPANISH_MONTHS


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and markdown body."""
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
        for line in yaml_text.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip().strip('"\'')
    return meta, body


def dump_frontmatter(meta: dict, body: str) -> str:
    """Combine metadata and body into standard frontmatter format."""
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


def extract_tasks_from_markdown(content: str) -> list[dict]:
    """Extract markdown checkbox tasks with their section headers."""
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
                tasks.append({"task": task_text, "completed": is_done, "section": current_section, "raw": line})
    return tasks


def get_or_create_daily_note(vault_path: Path, date_val: date, template: str) -> tuple[Path, bool]:
    """
    Ensure the daily note exists for date_val.
    Returns (path, created).
    """
    date_str = date_val.strftime("%Y-%m-%d")
    journal_dir = vault_path / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    note_path = journal_dir / f"{date_str}.md"

    if note_path.is_file():
        return note_path, False

    content = template.replace("{date}", date_str)
    note_path.write_text(content, encoding="utf-8")
    return note_path, True


def add_task_to_daily_note(vault_path: Path, date_val: date, task_text: str, category: str, template: str) -> bool:
    """Add a task checkbox under the specified category in the daily note."""
    note_path, _ = get_or_create_daily_note(vault_path, date_val, template)
    content = note_path.read_text(encoding="utf-8")

    category_header = f"### {category}"
    task_line = f"- [ ] {task_text}"

    if category_header in content:
        pattern = re.compile(rf"({re.escape(category_header)}\r?\n)")
        new_content = pattern.sub(rf"\1\n{task_line}\n", content, count=1)
    elif "## TODO" in content:
        pattern = re.compile(r"(## TODO\r?\n)")
        new_content = pattern.sub(rf"\1\n{category_header}\n\n{task_line}\n", content, count=1)
    else:
        new_content = content.rstrip() + f"\n\n## TODO\n\n{category_header}\n\n{task_line}\n"

    new_content = re.sub(r"\n{3,}", "\n\n", new_content)
    note_path.write_text(new_content, encoding="utf-8")
    return True


def complete_task_in_daily_note(vault_path: Path, date_val: date, task_query: str, template: str) -> bool:
    """Mark a task as completed [x] by matching task text in the daily note."""
    date_str = date_val.strftime("%Y-%m-%d")
    note_path = vault_path / "journal" / f"{date_str}.md"
    if not note_path.is_file():
        return False

    content = note_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(content)

    # Find best matching pending task
    tasks = extract_tasks_from_markdown(body)
    candidates = [t for t in tasks if not t["completed"] and task_query.lower() in t["task"].lower()]
    if not candidates:
        # Try partial word match
        words = [w for w in task_query.lower().split() if len(w) >= 3]
        for t in tasks:
            if t["completed"]:
                continue
            task_lower = t["task"].lower()
            if all(w in task_lower for w in words):
                candidates.append(t)

    if not candidates:
        return False

    target = candidates[0]["raw"]
    # Replace the exact line in the original content, preserving indentation
    replacement = re.sub(r"^(\s*)-\s*\[ \]", r"\1- [x]", target)
    new_content = content.replace(target, replacement, 1)
    note_path.write_text(new_content, encoding="utf-8")
    return True


def get_note(vault_path: Path, rel_path: str) -> str:
    """Read full content of a note by relative vault path."""
    target = vault_path / rel_path
    target = target.resolve()
    # Security: ensure the resolved path stays within vault_path
    if not str(target).startswith(str(vault_path.resolve())):
        raise ValueError("Path escapes vault")
    if not target.is_file():
        raise FileNotFoundError(f"Note not found: {rel_path}")
    return target.read_text(encoding="utf-8")


def list_notes(vault_path: Path, directory: str | None = None, note_type: str | None = None) -> list[dict]:
    """List notes in a directory or of a specific type."""
    if directory:
        target_dir = vault_path / directory
        if not target_dir.is_dir():
            return []
        md_files = list(target_dir.rglob("*.md"))
    else:
        md_files = list(vault_path.rglob("*.md"))

    results = []
    excluded = {".trash", ".obsidian", ".git", ".pi"}
    for md in md_files:
        rel = md.relative_to(vault_path)
        if any(p in excluded for p in rel.parts):
            continue
        # If type filter, derive type from top directory
        if note_type:
            top = rel.parts[0].lower() if rel.parts else ""
            if top != note_type.lower():
                continue
        meta, _ = parse_frontmatter(md.read_text(encoding="utf-8", errors="ignore"))
        results.append({
            "relative_path": str(rel),
            "filename": md.name,
            "title": meta.get("title", md.stem),
            "tags": meta.get("tags", []),
            "date": meta.get("id", meta.get("date", "")),
        })
    return sorted(results, key=lambda x: x["relative_path"])


def create_zettel(vault_path: Path, title: str, tags: list[str] | None = None, body: str = "") -> str:
    """Create a new atomic Zettelkasten note with mandatory frontmatter."""
    zettel_dir = vault_path / "zettelkasten"
    zettel_dir.mkdir(parents=True, exist_ok=True)

    timestamp = str(int(time.time()))
    slug = re.sub(r"[^\w\s-]", "", title).replace(" ", "-").strip("-")
    if not slug or len(slug) < 2:
        acronym = "".join([w[0].upper() for w in re.findall(r"\w+", title)[:4]])
        if not acronym or len(acronym) < 2:
            acronym = "NOTE"
        slug = acronym
    filename = f"{timestamp}-{slug[:30]}.md"
    note_path = zettel_dir / filename

    meta = {
        "id": f"{timestamp}-{slug[:20]}",
        "title": title,
        "date": date.today().isoformat(),
        "tags": tags or ["zettelkasten"],
        "aliases": [title.lower().replace(" ", "-")],
    }
    content = dump_frontmatter(meta, body or f"# {title}\n\n")
    note_path.write_text(content, encoding="utf-8")
    return str(note_path.relative_to(vault_path))


def add_event_to_daily_note(vault_path: Path, date_val: date, event_text: str, template: str) -> bool:
    """Add an event to the events list in YAML frontmatter of the daily note."""
    note_path, _ = get_or_create_daily_note(vault_path, date_val, template)
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
