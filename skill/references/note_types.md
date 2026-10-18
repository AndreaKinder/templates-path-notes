# 📝 Catálogo de Tipos de Notas y Esquemas

---

## 📅 1. Nota Diaria (`journal/YYYY-MM-DD.md`)

- **Plantilla:** `templates/plantilla-diaria.md`
- **Tag obligatorio:** `daily-notes`

### Frontmatter
```yaml
---
id: YYYY-MM-DD
description: ""
events: []
aliases:
  - YYYY-MM-DD
tags:
  - daily-notes
---
```

### Secciones estándar
```markdown
# YYYY-MM-DD

## TODO

### Casa / Personal
### Trabajo
### Social
```

---

## 💳 2. Finanzas (`finanzas/`)

- **Mensual:** `finanzas/YYYY/cuentas/YYYY-MM.md` → plantilla `plantilla-cuentas-mes.md`
- **Recibos:** `finanzas/YYYY/recibos/`
- **Facturas:** `finanzas/YYYY/facturas/`
- **Anual:** `finanzas/resumen-anual-YYYY.md`

### Frontmatter mensual
```yaml
---
id: YYYY-MM-finanzas
description: "Cuentas y balance del mes"
aliases:
  - "Cuentas YYYY-MM"
tags:
  - finanzas
  - finanzas/mensual
year: YYYY
month: "MM"
status: en-curso
total_ingresos: 0.00
total_gastos: 0.00
balance_neto: 0.00
---
```

---

## 🧠 3. Zettelkasten (`zettelkasten/`)

- **Plantilla:** `templates/plantilla-nota.md`
- **ID:** timestamp Unix + slug kebab-case o acrónimo

### Frontmatter
```yaml
---
id: <TIMESTAMP-SLUG>
description: "Resumen conciso de 1-2 frases"
aliases:
  - "Título legible"
tags:
  - tema-principal
---
```

---

## 🚀 4. Proyectos (`projects/`)

```
projects/<nombre>/
├── README.md
├── docs/
├── fases/
├── backups/
└── assets/
```

---

## 📋 5. Tareas Detalladas (`todo/`)

- **Formato:** `todo/YYYY-MM-DD/<ID>.md`
- Uso: proyectos con checkboxes extensos que no caben en journal.
