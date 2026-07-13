# Kureha — Documentación SDD

Kureha es la plataforma operativa para clínicas y consultorios en Perú:
agenda multi-tenant, autoservicio del paciente (web + chat embebido),
sincronización con Google Calendar, gestión operativa de personal y un
copiloto interno para el staff, todo sobre un núcleo de gobernanza (RLS,
consentimiento versionado, auditoría append-only, HITL, validador de scope
clínico). Este folder es donde vive el ciclo completo de Spec-Driven
Development (SDD) para llevarla a implementación con agentes de IA.

Esta carpeta sigue la convención estándar SDD (`config.yaml`, `specs/`,
`changes/`).

## Estructura

```
openspec/
├── config.yaml       <- Stack, convenciones y reglas por fase (ver contenido)
├── specs/            <- Specs fuente de verdad (se llenan al archivar cambios)
└── changes/
    ├── archive/       <- Cambios completados (auditoría histórica)
    └── {change-name}/ <- Cambio activo en curso
        ├── state.yaml
        ├── proposal.md
        ├── specs/
        ├── design.md
        ├── tasks.md
        └── verify-report.md
```

## Estado

- **Modo de artefactos**: carpeta propia en el repo (archivos versionables), sin motor de persistencia externo.
- **Modo de ejecución**: interactivo — cada fase se muestra y se confirma antes de avanzar.
- **Estrategia de PRs**: preguntar si hay riesgo de PR grande antes de aplicar tasks.
- **Estado del cambio `kureha-mvp`**: proposal, specs y design completos. Ver `openspec/changes/kureha-mvp/state.yaml` para el detalle de fases.
