# 🏛️ Arquitectura y Reglas del Vault de Notas

Este documento complementa `AGENTS.md` y especifica la organización técnica del vault.

---

## 📁 1. Estructura de Directorios

```
vault/
├── journal/           # Notas diarias: YYYY-MM-DD.md
├── finanzas/          # Gestión financiera anual
│   └── YYYY/
│       ├── cuentas/   # Balances mensuales: YYYY-MM.md
│       ├── recibos/   # Justificantes de gastos
│       └── facturas/  # Facturas emitidas
├── todo/              # Tareas fechadas detalladas
├── zettelkasten/      # Notas atómicas: TIMESTAMP-SLUG.md
├── projects/          # Proyectos con README.md, docs/, fases/, backups/
├── templates/         # Plantillas oficiales
├── prompts/           # Instrucciones para agentes
├── assets/            # Recursos binarios
│   └── pdf/
└── archived/          # Material congelado
    └── projects/
```

---

## 🚫 2. Reglas Invariantes para Agentes

1. **Sin archivos sueltos en raíz.**
2. **Frontmatter YAML obligatorio** en toda nota nueva:
   ```yaml
   ---
   id: <ID-UNICO>
   description: "Descripción breve"
   aliases:
     - "Nombre Principal"
   tags:
     - tag1
   ---
   ```
3. **Taxonomía fija:**
   - Journal → `journal/` (tag `daily-notes`).
   - Finanzas mensuales → tags `finanzas` + `finanzas/mensual`.
4. **Binarios** a `projects/<proyecto>/backups/` o `assets/`.

---

## 🔒 3. Backup y Sincronización

- **Git:** repositorio privado con `obsidian-git`.
- **Backup cifrado:** script de copia externa periódica.
- **Índice RAG:** fuera del vault en `~/.local/share/notas-rag/index.db`.
