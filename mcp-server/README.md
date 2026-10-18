# MCP Server: Notes RAG

Servidor MCP (Model Context Protocol) para búsqueda semántica híbrida (vectorial + FTS5) y gestión de notas sobre bóvedas personales Obsidian/Neovim.

Basado en el repositorio `mcp-rag-notes`.

## Entry points

- `mcp-server-notes-en` — vault en `~/Notes`
- `mcp-server-notes-es` — vault en `~/Notas`

## Variables de entorno

| Variable | Default (ES) | Descripción |
|----------|--------------|-------------|
| `NOTES_VAULT_PATH` | `~/Notas` | Ruta a la bóveda |
| `NOTES_INDEX_DB` | `~/.local/share/notas-rag/index.db` | Índice SQLite |
| `OLLAMA_HOST` | `http://localhost:11434` | Endpoint Ollama |
| `NOTES_EMBED_MODEL` | `snowflake-arctic-embed2` | Modelo de embeddings |

## Instalación

```bash
uv pip install -e .
```

## Configuración en Pi

```bash
pi mcp add notes-rag-es --env OLLAMA_HOST='http://localhost:11434' -- uv run --project ~/Projects/templates-path-notes/mcp-server mcp-server-notes-es
```

## Tools disponibles

- `query_notes` — búsqueda híbrida semántica + full-text
- `get_daily_note` — leer/crear nota diaria
- `add_task` — añadir tarea a nota diaria
- `complete_task` — marcar tarea como hecha
- `get_note` — leer nota por ruta
- `list_notes` — listar notas por directorio o tipo
- `index_vault` — (re)construir índice
- `index_status` — estado del índice
- `create_zettel` — crear nota atómica Zettelkasten
