---
name: notes
description: >
  Identifica, resuelve, consulta y gestiona notas en el vault personal de Obsidian y Neovim.
  Activa esta skill SIEMPRE que el usuario mencione "nota diaria", "nota de hoy", "diario",
  "bitácora", "nota de ayer", "nota de mañana", "cuentas del mes", "finanzas", "zettelkasten",
  "tareas de hoy", o cualquier petición para buscar, leer, añadir tareas o crear notas.
triggers:
  - nota diaria
  - nota de hoy
  - diario
  - bitácora
  - cuentas del mes
  - finanzas
  - zettelkasten
  - tareas de hoy
  - nota de ayer
  - nota de mañana
---

# 🧠 Skill: Gestor y Resolutor de Notas

Skill para agentes de IA que operan sobre el vault personal. Respeta estrictamente las directrices de `AGENTS.md` y la integración con Neovim / Obsidian.

> **Contrato:** La taxonomía del vault (`journal/`, `finanzas/`, `plantilla-*.md`, tags, cabeceras) es inmutable para el agente.

---

## ⚡ Reglas Invariantes Obligatorias

1. **NADA DE ARCHIVOS EN LA RAÍZ DEL VAULT.**
2. **Notas diarias en `journal/`** — nunca `daily/`, `diary/` ni `dailies/`.
3. **Frontmatter YAML obligatorio** (`id`, `description`, `aliases`, `tags`).
4. **Tag `daily-notes`** obligatorio en journal.
5. **Archivos no-Markdown** a `projects/<nombre>/backups/`.

---

## 🧭 1. Guía de Resolución de Entidades

| Expresión del usuario | Tipo | Ubicación | Plantilla |
|-----------------------|------|-----------|-----------|
| "nota diaria", "hoy", "diario" | Nota Diaria | `journal/YYYY-MM-DD.md` | `templates/plantilla-diaria.md` |
| "ayer", "anteayer" | Nota Diaria Pasada | `journal/YYYY-MM-DD.md` | `templates/plantilla-diaria.md` |
| "mañana", "el lunes" | Nota Diaria Futura | `journal/YYYY-MM-DD.md` | `templates/plantilla-diaria.md` |
| "cuentas del mes", "finanzas" | Finanzas Mensuales | `finanzas/YYYY/cuentas/YYYY-MM.md` | `templates/plantilla-cuentas-mes.md` |
| "recibos", "tickets" | Recibos | `finanzas/YYYY/recibos/` | — |
| "facturas" | Facturas | `finanzas/YYYY/facturas/` | — |
| "resumen anual" | Finanzas Anuales | `finanzas/resumen-anual-YYYY.md` | — |
| "zettelkasten", "idea" | Nota Atómica | `zettelkasten/TIMESTAMP-SLUG.md` | `templates/plantilla-nota.md` |
| "proyecto [nombre]" | Proyecto | `projects/<nombre>/` | — |

---

## 🛠️ 2. Scripts Auxiliares

### `scripts/resolve_note.py`

```bash
# Resolver entidad
python scripts/resolve_note.py resolve "hoy"

# Consultar nota diaria
python scripts/resolve_note.py daily get [--date ayer] [--json]

# Añadir tarea
python scripts/resolve_note.py daily add-task "Revisar logs" --category "Trabajo"

# Registrar evento
python scripts/resolve_note.py daily add-event "Cita médica"
```

### `scripts/vault_index.py`

```bash
# Estado del índice
python scripts/vault_index.py status

# Indexar (incremental)
python scripts/vault_index.py build

# Búsqueda híbrida
python scripts/vault_index.py find "configuración nginx" -k 5

# Con filtros
python scripts/vault_index.py find "impuestos" --type finanzas --since 2025-01
```

---

## 📋 3. Protocolos de Operación

### Caso A: Consultar "nota diaria"
1. Resolver fecha a `journal/YYYY-MM-DD.md`.
2. Leer eventos del frontmatter y tareas bajo `## TODO`.
3. Presentar resumen: pendientes (`[ ]`) vs completadas (`[x]`), agrupadas por categoría.

### Caso B: Añadir tarea a nota diaria
1. Determinar categoría (`Casa / Personal`, `Trabajo`, `Social`).
2. Añadir `- [ ] tarea` bajo la sección correspondiente.
3. Crear nota desde plantilla si no existe.

### Caso C: Marcar tarea como hecha
1. Localizar línea `- [ ] tarea`.
2. Reemplazar por `- [x] tarea`.

### Caso D: Crear nota conceptual
1. Generar ID: `<TIMESTAMP>-<SLUG>`.
2. Crear en `zettelkasten/` con frontmatter completo.

---

## 📚 Referencias

- [Arquitectura del Vault](references/vault_architecture.md)
- [Catálogo de Tipos de Notas](references/note_types.md)
- [Ejemplos de Resolución](examples/resolving_queries.md)
- [Flujos de Nota Diaria](examples/daily_note_workflows.md)
