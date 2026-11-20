# Arquitectura

Composición e invariantes de `skillrun`. El diseño completo está en
[PLAN.md](../../PLAN.md) §5. El mapa de ubicaciones está en
[CODEMAP.md](CODEMAP.md); los comandos, en [RUNTIME.md](RUNTIME.md).

## Composición

| Capa | Rutas | Responsabilidad |
| --- | --- | --- |
| Procedencia | `docs/constitution/AGENTIC-CONSTITUTION.md`, `docs/constitution/SOURCE.lock` | Texto canónico de referencia y su identidad verificable |
| Mapeo | `docs/CONSTITUTION.md` | Precedencia, estado y procedimiento de actualización del snapshot |
| Código | `src/skillrun.py` | App completa en un módulo (esquema, máquina de estados, host, CLI según fase) |
| Tests | `tests/` | pytest, fixtures de plugins y host falso (`fake_host.py`) |
| Plugins | `plugins/*/plugin.json` | Plugins de ejemplo `skillrun/v1` |
| Skills vendorizadas | `.agents/skills/`, `.agents/skills-lock.json` | Copias fijadas por git blob; no se editan ni lintean |
| Plan y cierres | `PLAN.md`, `handoffs/`, `prompts/`, `reference/REVIEWS.md` | Decisiones, fases y errores conocidos |
| Empaquetado | `pyproject.toml`, `uv.lock` | Python mínimo, build con hatchling, configuración de herramientas |
| Calidad | `Makefile`, `.pre-commit-config.yaml`, `.yamllint.yaml`, `.markdownlint-cli2.jsonc`, `.codespellrc`, `.shellcheckrc` | Objetivos y configuración de lint |
| Documentación para agentes | `AGENTS.md`, `docs/agent/*` | Entrada, contexto, arquitectura, mapa y operación |

El motor supervisa un `Host` inyectado. La Fase 3 añade el adaptador Pi RPC.
El estado de runs vive fuera del repositorio en la raíz privada definida por
el contrato de [PLAN.md](../../PLAN.md) §5.9.

## Responsabilidades

- `pyproject.toml` posee la configuración de Ruff, mypy, pytest y Bandit, el
  grupo `dev` de herramientas y el mínimo de Python.
- `Makefile` posee los objetivos reales (`install`, `lint`, `format`, `hooks`,
  `check`) y su orden. Un objetivo no debe añadirse sin actualizar
  [RUNTIME.md](RUNTIME.md).
- `docs/CONSTITUTION.md` posee la procedencia, la precedencia y el procedimiento
  de actualización del snapshot.
- `AGENTS.md` posee las reglas operativas del repositorio.
- `docs/agent/*` son documentos derivados: enrutan y explican, no crean
  autoridad.

## Dependencias

- Runtime: solo stdlib (`dependencies = []`). Host externo: Pi 1.4+ (Fase 3+).
- Desarrollo: `pytest`, `ruff`, `mypy`, `pre-commit`, `bandit`, `codespell` y
  `yamllint` en el grupo `dev`.
- Externas y opcionales, sólo para documentación: el guion `agent-docs-kit` y
  `graphify` 0.9.26. No son dependencias del proyecto.

## Invariantes

1. **Precedencia del upstream.** Ante conflicto con la Constitución canónica,
   gana upstream. Fuente: `docs/CONSTITUTION.md`, `AGENTS.md` (Fuente de verdad).
2. **Snapshot íntegro.** El snapshot se copia sin modificarlo; `SOURCE.lock` y
   `docs/CONSTITUTION.md` se actualizan en el mismo commit.
3. **Calidad fail-closed.** `make lint` no silencia fallos: no hay `|| true`.
   Fuente: `Makefile`, `README.md`.
4. **Alcance de la persona usuaria.** No se agregan features no pedidas.
   Fuente: `AGENTS.md` regla 4.
5. **Evidencia antes que relato.** No se declara un cierre sin validación
   observable. Fuente: `AGENTS.md` regla 6.
6. **Documentación mínima.** Si cambia un contrato, se actualiza su referencia
   en el mismo commit. Fuente: `AGENTS.md` regla 9.

## Estado de implementación

- Fase 2 cerrada. `run_plugin()` coordina el host, el lock, los recibos y la
  validación de resultados. `reconcile()` registra la decisión explícita
  sobre un turno incierto. `skillrun validate` es el subcomando disponible.
- La integración del adaptador empieza en el
  [handoff de Fase 2](../../handoffs/HANDOFF-2026-11-20-PHASE-2.md).

## Evidencia y pendientes

- Fuentes: lectura de `pyproject.toml`, `Makefile`, `README.md`,
  `docs/CONSTITUTION.md`, `docs/constitution/SOURCE.lock`,
  `src/skillrun.py`, `PLAN.md`.
