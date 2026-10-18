# Templates Path Notes

Plantilla de bóveda de Obsidian + Neovim con servidor MCP, skill de agente y scripts auxiliares.

Basado en [`mcp-rag-notes`](https://github.com/AndreaKinder/mcp-rag-notes) y [`skills-notes`](https://github.com/AndreaKinder/skills-notes).

## Estructura

```
templates-path-notes/
├── vault/              # Plantilla de bóveda para copiar a ~/Notas (o ~/Notes)
│   ├── AGENTS.md       # Contrato del vault para agentes de IA
│   ├── journal/
│   ├── finanzas/
│   ├── zettelkasten/
│   ├── projects/
│   ├── todo/
│   ├── templates/      # Plantillas oficiales
│   ├── prompts/
│   ├── assets/
│   └── archived/
├── skill/              # Skill para agentes + scripts CLI
│   ├── SKILL.md
│   ├── references/
│   ├── examples/
│   └── scripts/
│       ├── resolve_note.py
│       └── vault_index.py
└── mcp-server/         # Servidor MCP (RAG semántico + herramientas)
    ├── pyproject.toml
    ├── .pi/mcp.json
    └── src/notes_rag/
```

## Uso rápido

### 1. Desplegar la bóveda

```bash
cp -r vault ~/Notas
# o para inglés:
cp -r vault ~/Notes
```

### 2. Instalar el servidor MCP

```bash
cd mcp-server
uv pip install -e .
```

### 3. Configurar en Pi / Claude Code

```bash
pi mcp add notes-rag-es --env OLLAMA_HOST='http://localhost:11434' -- uv run --project ~/Projects/templates-path-notes/mcp-server mcp-server-notes-es
```

### 4. Scripts auxiliares

```bash
# Resolver entidades
python skill/scripts/resolve_note.py resolve "hoy"

# Buscar semánticamente
python skill/scripts/vault_index.py find "configurar docker"
```

## Variables de entorno

| Variable | Default (ES) | Default (EN) | Descripción |
|----------|--------------|--------------|-------------|
| `NOTES_VAULT_PATH` | `~/Notas` | `~/Notes` | Ruta a la bóveda |
| `NOTES_INDEX_DB` | `~/.local/share/notas-rag/index.db` | `~/.local/share/notes-rag/index.db` | Índice SQLite |
| `OLLAMA_HOST` | `http://localhost:11434` | igual | Endpoint Ollama |
| `NOTES_EMBED_MODEL` | `snowflake-arctic-embed2` | igual | Modelo embeddings |

## Licencia

MIT
