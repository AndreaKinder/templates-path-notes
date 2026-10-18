"""MCP tool schemas and async handlers."""

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .index import build_index, query_index, get_index_status
from .resolve import resolve_date_expression, resolve_entity
from .vault import (
    add_event_to_daily_note,
    add_task_to_daily_note,
    complete_task_in_daily_note,
    create_zettel,
    extract_tasks_from_markdown,
    get_note,
    get_or_create_daily_note,
    list_notes,
    parse_frontmatter,
)


def _try_import_mcp_types():
    """Best-effort import of MCP types; fall back to plain dicts if unavailable."""
    try:
        from mcp.types import CallToolResult, TextContent  # type: ignore
        return CallToolResult, TextContent
    except Exception:
        return None, None


_CallToolResult, _TextContent = _try_import_mcp_types()


def _result(text: str, is_error: bool = False):
    """Return a CallToolResult if available, otherwise a plain dict list."""
    if _CallToolResult and _TextContent:
        try:
            return _CallToolResult(content=[_TextContent(type="text", text=text)], isError=is_error)  # type: ignore
        except Exception:
            try:
                return _CallToolResult(content=[_TextContent(type="text", text=text)], is_error=is_error)  # type: ignore
            except Exception:
                pass
    return [{"type": "text", "text": text}]


def _ok(text: str):
    return _result(text, is_error=False)


def _err(text: str):
    return _result(text, is_error=True)


@dataclass
class ServerConfig:
    lang: str
    vault_path: Path
    db_path: Path
    ollama_url: str
    embed_model: str
    locale: dict


def _type_aliases(locale: dict) -> dict:
    """Build a merged type alias map from locale + defaults."""
    defaults = {
        "journal": "journal", "daily": "journal", "diaria": "journal", "diario": "journal",
        "zettelkasten": "zettelkasten", "zettel": "zettelkasten", "nota": "zettelkasten",
        "projects": "projects", "proyecto": "projects", "proyectos": "projects",
        "finanzas": "finance", "finance": "finance",
        "todo": "todo", "inbox": "inbox",
        "templates": "templates", "plantillas": "templates",
        "prompts": "prompts",
    }
    # Merge with any locale-defined aliases if present
    locale_aliases = locale.get("type_aliases", {})
    merged = {**defaults, **locale_aliases}
    return merged


def get_tool_schemas(config: ServerConfig) -> list[Any]:
    """Return list of mcp.types.Tool objects with localized descriptions."""
    try:
        from mcp.types import Tool  # type: ignore
        ToolCls = Tool
    except Exception:
        ToolCls = dict

    t = config.locale["tools"]
    schemas = []

    def add(name: str, description: str, schema: dict):
        if ToolCls is dict:
            schemas.append({"name": name, "description": description, "inputSchema": schema})
        else:
            schemas.append(ToolCls(name=name, description=description, inputSchema=schema))

    add("query_notes", t["query_notes"]["description"], {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query text."},
            "limit": {"type": "integer", "default": 6, "description": "Max results to return."},
            "type": {"type": "string", "description": "Filter by note type: journal, zettelkasten, projects, finance, ..."},
            "tag": {"type": "string", "description": "Filter by tag (prefix matching supported)."},
            "since": {"type": "string", "description": "YYYY-MM-DD lower bound."},
            "until": {"type": "string", "description": "YYYY-MM-DD upper bound."},
        },
        "required": ["query"],
    })

    add("get_daily_note", t["get_daily_note"]["description"], {
        "type": "object",
        "properties": {
            "date": {"type": "string", "default": "today" if config.lang == "en" else "hoy",
                      "description": "Date expression: today/hoy, yesterday/ayer, YYYY-MM-DD."},
        },
        "required": [],
    })

    add("add_task", t["add_task"]["description"], {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Task text to add."},
            "date": {"type": "string", "default": "today" if config.lang == "en" else "hoy",
                     "description": "Date expression for the daily note."},
            "category": {"type": "string", "default": "Personal" if config.lang == "en" else "Casa / Personal",
                         "description": "Category / section under which to add the task."},
        },
        "required": ["task"],
    })

    add("complete_task", t["complete_task"]["description"], {
        "type": "object",
        "properties": {
            "task_query": {"type": "string", "description": "Text snippet of the task to complete."},
            "date": {"type": "string", "default": "today" if config.lang == "en" else "hoy",
                     "description": "Date expression for the daily note."},
        },
        "required": ["task_query"],
    })

    add("get_note", t["get_note"]["description"], {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative vault path, e.g. zettelkasten/example.md"},
        },
        "required": ["path"],
    })

    add("list_notes", t["list_notes"]["description"], {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Relative directory to list, e.g. 'journal' or 'projects'."},
            "type": {"type": "string", "description": "Filter by note type (alternative to directory)."},
        },
        "required": [],
    })

    add("index_vault", t["index_vault"]["description"], {
        "type": "object",
        "properties": {
            "full_rebuild": {"type": "boolean", "default": False,
                             "description": "If true, rebuild the entire index from scratch (runs in background)."},
        },
        "required": [],
    })

    add("index_status", t["index_status"]["description"], {
        "type": "object",
        "properties": {},
        "required": [],
    })

    add("create_zettel", t["create_zettel"]["description"], {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Title of the new atomic note."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags to attach."},
            "body": {"type": "string", "default": "", "description": "Optional initial markdown body."},
        },
        "required": ["title"],
    })

    return schemas


# ---------------------------------------------------------------------------
# Background task tracking for long-running full rebuilds
# ---------------------------------------------------------------------------
_background_tasks: set = set()


def _fire_and_forget(coro):
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _tool_query_notes(args: dict, config: ServerConfig):
    try:
        query = args["query"]
        limit = args.get("limit", 6)
        ntype = args.get("type")
        tag = args.get("tag")
        since = args.get("since")
        until = args.get("until")
        stopwords = set(config.locale.get("stopwords", []))
        aliases = _type_aliases(config.locale)

        results = await asyncio.to_thread(
            query_index,
            config.vault_path, config.db_path, config.ollama_url, config.embed_model,
            query, limit, ntype, tag, since, until,
            stopwords, aliases,
        )
        return _ok(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        return _err(config.locale["errors"]["generic"].format(detail=str(e)))


async def _tool_get_daily_note(args: dict, config: ServerConfig):
    try:
        expr = args.get("date", "today" if config.lang == "en" else "hoy")
        d = resolve_date_expression(expr)
        template = config.locale.get("daily_template", "")
        note_path, created = await asyncio.to_thread(
            get_or_create_daily_note, config.vault_path, d, template
        )
        content = await asyncio.to_thread(note_path.read_text, encoding="utf-8")
        meta, body = parse_frontmatter(content)
        tasks = extract_tasks_from_markdown(body)
        result = {
            "path": str(note_path.relative_to(config.vault_path)),
            "full_path": str(note_path),
            "created": created,
            "date": d.isoformat(),
            "metadata": meta,
            "events": meta.get("events", []),
            "tasks": tasks,
            "content_preview": body[:800] if len(body) > 800 else body,
        }
        return _ok(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        return _err(config.locale["errors"]["generic"].format(detail=str(e)))


async def _tool_add_task(args: dict, config: ServerConfig):
    try:
        task_text = args["task"]
        expr = args.get("date", "today" if config.lang == "en" else "hoy")
        category = args.get("category", "Personal" if config.lang == "en" else "Casa / Personal")
        d = resolve_date_expression(expr)
        template = config.locale.get("daily_template", "")
        await asyncio.to_thread(
            add_task_to_daily_note, config.vault_path, d, task_text, category, template
        )
        return _ok(f"Task added to daily note {d.isoformat()} under [{category}]: {task_text}")
    except Exception as e:
        return _err(config.locale["errors"]["generic"].format(detail=str(e)))


async def _tool_complete_task(args: dict, config: ServerConfig):
    try:
        task_query = args["task_query"]
        expr = args.get("date", "today" if config.lang == "en" else "hoy")
        d = resolve_date_expression(expr)
        template = config.locale.get("daily_template", "")
        ok = await asyncio.to_thread(
            complete_task_in_daily_note, config.vault_path, d, task_query, template
        )
        if not ok:
            msg = config.locale["errors"]["task_not_found"].format(query=task_query, date=d.isoformat())
            return _err(msg)
        return _ok(f"Task marked completed in daily note {d.isoformat()} matching: {task_query}")
    except Exception as e:
        return _err(config.locale["errors"]["generic"].format(detail=str(e)))


async def _tool_get_note(args: dict, config: ServerConfig):
    try:
        rel_path = args["path"]
        content = await asyncio.to_thread(get_note, config.vault_path, rel_path)
        return _ok(content)
    except FileNotFoundError as e:
        return _err(config.locale["errors"]["note_not_found"].format(path=str(e)))
    except Exception as e:
        return _err(config.locale["errors"]["generic"].format(detail=str(e)))


async def _tool_list_notes(args: dict, config: ServerConfig):
    try:
        directory = args.get("directory")
        ntype = args.get("type")
        results = await asyncio.to_thread(list_notes, config.vault_path, directory, ntype)
        return _ok(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        return _err(config.locale["errors"]["generic"].format(detail=str(e)))


async def _tool_index_vault(args: dict, config: ServerConfig):
    try:
        full_rebuild = args.get("full_rebuild", False)
        verbose = False
        aliases = _type_aliases(config.locale)

        if full_rebuild:
            # Run in background so we don't block the stdio response
            _fire_and_forget(asyncio.to_thread(
                build_index,
                config.vault_path, config.db_path, config.ollama_url, config.embed_model,
                True, verbose, aliases,
            ))
            return _ok("Full index rebuild started in background. Check index_status for progress.")
        else:
            result = await asyncio.to_thread(
                build_index,
                config.vault_path, config.db_path, config.ollama_url, config.embed_model,
                False, verbose, aliases,
            )
            return _ok(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        return _err(config.locale["errors"]["index_failed"].format(detail=str(e)))


async def _tool_index_status(args: dict, config: ServerConfig):
    try:
        status = await asyncio.to_thread(get_index_status, config.vault_path, config.db_path)
        return _ok(json.dumps(status, indent=2, ensure_ascii=False))
    except Exception as e:
        return _err(config.locale["errors"]["generic"].format(detail=str(e)))


async def _tool_create_zettel(args: dict, config: ServerConfig):
    try:
        title = args["title"]
        tags = args.get("tags")
        body = args.get("body", "")
        rel_path = await asyncio.to_thread(
            create_zettel, config.vault_path, title, tags, body
        )
        return _ok(f"Created zettel: {rel_path}")
    except Exception as e:
        return _err(config.locale["errors"]["generic"].format(detail=str(e)))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_TOOL_MAP = {
    "query_notes": _tool_query_notes,
    "get_daily_note": _tool_get_daily_note,
    "add_task": _tool_add_task,
    "complete_task": _tool_complete_task,
    "get_note": _tool_get_note,
    "list_notes": _tool_list_notes,
    "index_vault": _tool_index_vault,
    "index_status": _tool_index_status,
    "create_zettel": _tool_create_zettel,
}


async def handle_tool(name: str, arguments: dict, config: ServerConfig):
    """Route a tool call to its handler."""
    handler = _TOOL_MAP.get(name)
    if handler is None:
        return _err(f"Unknown tool: {name}")
    return await handler(arguments, config)
