# CLAUDE.md

@AGENTS.md

## Notas para Claude Code

- Para iniciar la siguiente fase, usa la línea `START HERE` del handoff activo
  indicado en `AGENTS.md`.
- Orquestador: Opus 5.5 / esfuerzo medio. Planifica, delega, integra y decide;
  no escribe el grueso del código. Ver `prompts/02-orquestador.md`.
- WORKER: Codex `gpt-6.2-sol`, esfuerzo `high`. Tareas mecánicas con
  especificación cerrada.
- TESTER: Codex `gpt-6.2-sol`, esfuerzo `xhigh`. Escribe los tests desde
  `PLAN.md` y la especificación, **sin ver la implementación**; luego ejecuta la
  suite.
