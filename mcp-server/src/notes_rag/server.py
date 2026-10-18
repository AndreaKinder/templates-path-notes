"""MCP stdio server entry point for notes-rag."""

import asyncio
import json
import os
import sys
from pathlib import Path

from .tools import ServerConfig, get_tool_schemas, handle_tool


def _default_vault_path(lang: str) -> str:
    return str(Path.home() / ("Notes" if lang == "en" else "Notas"))


def _default_db_path(lang: str) -> str:
    return str(Path.home() / ".local" / "share" / ("notes-rag" if lang == "en" else "notas-rag") / "index.db")


def _load_locale(lang: str) -> dict:
    pkg = Path(__file__).resolve().parent
    locale_path = pkg / "locales" / f"{lang}.json"
    if not locale_path.is_file():
        raise FileNotFoundError(f"Locale not found: {locale_path}")
    with locale_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _build_config(lang: str) -> ServerConfig:
    locale = _load_locale(lang)
    vault_path = Path(os.getenv("NOTES_VAULT_PATH", _default_vault_path(lang))).expanduser()
    db_path = Path(os.getenv("NOTES_INDEX_DB", _default_db_path(lang))).expanduser()
    ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    embed_model = os.getenv("NOTES_EMBED_MODEL", "snowflake-arctic-embed2")
    return ServerConfig(
        lang=lang,
        vault_path=vault_path,
        db_path=db_path,
        ollama_url=ollama_url,
        embed_model=embed_model,
        locale=locale,
    )


async def _run_server(config: ServerConfig):
    try:
        from mcp.server import Server  # type: ignore
        from mcp.server.stdio import stdio_server  # type: ignore
    except ImportError as e:
        print(f"ERROR: MCP SDK not installed: {e}", file=sys.stderr)
        sys.exit(1)

    server = Server("notes-rag")

    @server.list_tools()  # type: ignore
    async def list_tools():
        return get_tool_schemas(config)

    @server.call_tool()  # type: ignore
    async def call_tool(name: str, arguments: dict):
        return await handle_tool(name, arguments, config)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main_en():
    config = _build_config("en")
    asyncio.run(_run_server(config))


def main_es():
    config = _build_config("es")
    asyncio.run(_run_server(config))


if __name__ == "__main__":
    # Fallback for direct execution without entry-point script
    lang = os.getenv("NOTES_LANG", "en")
    if lang not in ("en", "es"):
        lang = "en"
    config = _build_config(lang)
    asyncio.run(_run_server(config))
