# 📆 Flujos de Trabajo con la Nota Diaria

---

## 1. Comprobación y Creación

Ruta: `journal/YYYY-MM-DD.md`

Si no existe, crear desde `templates/plantilla-diaria.md` reemplazando `{{date}}`.

---

## 2. Inserción de Tareas por Categoría

Cabeceras de nivel 3 bajo `## TODO`:

- `### Casa / Personal`
- `### Trabajo`
- `### Social`

### Helper
```bash
python scripts/resolve_note.py daily add-task "Comprar pan" --category "Casa / Personal"
python scripts/resolve_note.py daily add-task "Revisar PRs" --category "Trabajo"
```

### Inserción directa
```markdown
### Casa / Personal

- [ ] Tarea nueva
- [ ] Tarea existente
```

---

## 3. Registro de Eventos en Frontmatter

```yaml
---
id: 2025-06-10
events:
  - "Cita con el dentista"
---
```

```bash
python scripts/resolve_note.py daily add-event "Reunión de equipo"
```

---

## 4. Marcado de Tareas Completadas

```markdown
- [ ] Pagar alquiler
```
↓
```markdown
- [x] Pagar alquiler
```
