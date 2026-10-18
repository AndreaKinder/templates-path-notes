# 🤖 AGENTS.md — Contrato del Vault de Notas

Documento de reglas invariantes para agentes de IA que operen sobre esta bóveda.

---

## 📁 1. Arquitectura de Directorios

La raíz del vault se mantiene **estrictamente limpia**. Cada nota o recurso pertenece a una de las siguientes carpetas:

| Directorio | Propósito | Nomenclatura |
|------------|-----------|--------------|
| `journal/` | Notas diarias (Daily Notes) | `YYYY-MM-DD.md` |
| `finanzas/` | Gestión financiera por año | `finanzas/YYYY/cuentas/YYYY-MM.md`, `recibos/`, `facturas/`, `resumen-anual-YYYY.md` |
| `todo/` | Tareas fechadas detalladas | `todo/YYYY-MM-DD/<ID>.md` |
| `zettelkasten/` | Notas atómicas de conocimiento | `<TIMESTAMP>-<SLUG>.md` |
| `projects/` | Documentación de proyectos | `projects/<nombre>/{README.md,docs/,fases/,backups/}` |
| `templates/` | Plantillas oficiales | `plantilla-*.md` |
| `prompts/` | Instrucciones para agentes de IA | — |
| `assets/` | Recursos gráficos y binarios | `assets/pdf/`, imágenes, SVG |
| `archived/` | Proyectos y notas congeladas | `archived/projects/` |
| `.obsidian/` | Configuración interna de Obsidian | Solo lectura |

---

## 🚫 2. Reglas Invariantes

1. **Nada de archivos en la raíz.** Cada nota debe vivir dentro de una subcarpeta del sistema.
2. **Journal en `journal/`**. Nunca crear carpetas `daily/`, `diary/` o `dailies/`.
3. **Frontmatter YAML obligatorio** en toda nota nueva:
   ```yaml
   ---
   id: <ID-UNICO>
   description: "Descripción breve de una o dos frases"
   aliases:
     - "Nombre Principal"
   tags:
     - tag1
   ---
   ```
4. **Tag obligatorio:** las notas de journal siempre llevan `daily-notes`.
5. **Archivos no-Markdown** (SQL, scripts pesados) van a `projects/<proyecto>/backups/`, nunca a `zettelkasten/` ni a la raíz.

---

## 🧭 3. Guía de Resolución de Entidades

| Expresión del usuario | Tipo | Ubicación | Plantilla |
|-----------------------|------|-----------|-----------|
| "nota diaria", "hoy" | Nota Diaria | `journal/YYYY-MM-DD.md` | `templates/plantilla-diaria.md` |
| "ayer", "anteayer" | Nota Diaria Pasada | `journal/YYYY-MM-DD.md` (calculada) | `templates/plantilla-diaria.md` |
| "mañana", "el lunes" | Nota Diaria Futura | `journal/YYYY-MM-DD.md` (calculada) | `templates/plantilla-diaria.md` |
| "cuentas del mes" | Finanzas Mensuales | `finanzas/YYYY/cuentas/YYYY-MM.md` | `templates/plantilla-cuentas-mes.md` |
| "recibos", "tickets" | Recibos | `finanzas/YYYY/recibos/` | — |
| "facturas" | Facturas Emitidas | `finanzas/YYYY/facturas/` | — |
| "resumen anual" | Finanzas Anuales | `finanzas/resumen-anual-YYYY.md` | — |
| "zettelkasten", "idea" | Nota Atómica | `zettelkasten/<TIMESTAMP>-<SLUG>.md` | `templates/plantilla-nota.md` |
| "proyecto [nombre]" | Proyecto | `projects/<nombre>/` | — |

---

## 🔒 4. Seguridad y Copias

- **Git:** sincronización automática con `obsidian-git`.
- **Backup externo:** copia cifrada periódica fuera de la máquina.
- **Índice de búsqueda** (`~/.local/share/notas-rag/index.db`) vive **fuera** del vault.

---

*Última actualización: 2025*
