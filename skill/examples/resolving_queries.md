# 🔍 Ejemplos de Resolución de Consultas

---

### Ejemplo 1: "Añade la tarea de comprar fruta"

1. **Resolución:** "nota diaria" → `journal/2025-06-10.md`
2. **Acción:** recado doméstico → `### Casa / Personal`
3. **Comando:**
   ```bash
   python scripts/resolve_note.py daily add-task "Comprar fruta" --category "Casa / Personal"
   ```

---

### Ejemplo 2: "¿Qué tareas tengo pendientes hoy?"

1. **Resolución:** `journal/2025-06-10.md`
2. **Acción:** extraer `- [ ]` agrupadas por sección.

---

### Ejemplo 3: "¿Qué anoté ayer?"

1. **Resolución:** ayer → `journal/2025-06-09.md`
2. **Acción:**
   ```bash
   python scripts/resolve_note.py daily get --date ayer
   ```

---

### Ejemplo 4: "Revisa mis gastos de este mes"

1. **Resolución:** `finanzas/2025/cuentas/2025-06.md`
2. **Acción:** leer tablas de suscripciones y balance.

---

### Ejemplo 5: "Crea una nota sobre Traefik con Docker"

1. **Resolución:** zettelkasten
2. **Destino:** `zettelkasten/<TIMESTAMP>-traefik-docker.md`
3. **Acción:** crear con frontmatter completo.
