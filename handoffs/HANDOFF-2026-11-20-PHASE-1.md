# Handoff — Fase 1: Repo + esquema de plugin

Fecha: 2026-11-20. Rama: `feat/phase-1-plugin-schema` (desde
`chore/merge-skillrun`). Estado: **cerrada** con la confirmación de la persona
usuaria.

## Qué se construyó

- **Merge previo:** el repo `skill-loop` absorbió skillrun en
  `chore/merge-skillrun`. Producto, CLI y módulo: `skillrun`. Runtime solo
  stdlib, Python >=3.12, tooling de calidad de skill-loop. Las 37 skills de Matt
  Pocock están vendorizadas en `.agents/skills/` y fijadas en
  `.agents/skills-lock.json`. Se integró el guard `tools/check_agent_docs.py` y
  `docs/agent/*`, que había dejado otra sesión.
- **`src/skillrun.py`** (304 líneas):
  - Constantes `SCHEMA`, `MAX_STEPS = 16`, `RESULT_TYPES` y `EXIT_*`
    (0, 2, 3, 10, 70, 130).
  - `PluginError(errors)` y las dataclasses frozen `Skill`, `Step` y `Plugin`,
    con mappings inmutables.
  - `validate_plugin_data(data) -> list[str]`: pura, todos los errores
    ordenados con ruta.
  - `load_plugin(path) -> Plugin`: UTF-8 estricto y claves duplicadas
    rechazadas.
  - `plugin_digest(data)`: SHA-256 del JSON canónico.
  - `check_result(contract, value)`: claves exactas, tipo exacto con
    `type(v) is X`.
  - `main(argv)` con el subcomando `validate`.
- **Tests** (158, pytest):
  - `tests/test_schema.py` y `tests/test_cli_validate.py`.
  - Fixtures `tests/fixtures/plugins/{minimal,complete}.json`.

## Decisiones

Todas están en PLAN.md §5.8 y salen del grilling. Durante la fase se agregaron
estas:

- `steps[0].skill` debe ser `grilling`, porque §5.3 envía `/skill:grilling`.
- `path` rechaza NUL y valores hechos solo de espacios. Lo mismo vale para
  `instruction` y `on_done.directive`.
- La respuesta INTERNAL es `{"ok": false, "internal": true, "errors": ["$: internal error (<Tipo>)"]}`.
- Los errores Unicode del digest (surrogates) se reportan junto con los errores
  de esquema.

## Qué hizo cada rol

| Rol | Modelo | Trabajo |
| --- | --- | --- |
| Orquestador | Opus 5.5 / medio | Grilling (Q1–Q18), merge, specs, revisión, tarea 3 (CLI, ~35 líneas) y fixes post-auditoría con tests de regresión |
| TESTER | Codex gpt-6.2-sol / xhigh | Escribió 151 tests sin ver la implementación (RED verificado); luego auditó la fase y encontró NUL, grilling-alias, surrogate, INTERNAL sin `errors` y MD041 |
| WORKER | Codex gpt-6.2-sol / high | Tarea 2: modelo + validación (142 tests de esquema en verde a la primera entrega) |

Tokens por rol: no medido.

Desvío: el plan asignaba la tarea 3 al WORKER. La hizo el orquestador porque
eran unas 35 líneas y delegarlas costaba más que escribirlas.

## Archivos tocados (Fase 1)

`src/skillrun.py`, `tests/**`, `PLAN.md`, `AGENTS.md`, `CLAUDE.md`,
`README.md`, `docs/agent/ARCHITECTURE.md`, `docs/agent/RUNTIME.md` y este
handoff.

## Cómo ejecutarlo

```bash
make install
uv run pytest                                            # 158 passed
make lint                                                # exit 0
uv run skillrun validate tests/fixtures/plugins/complete.json   # exit 0
uv run skillrun validate plugins/github-gateway/plugin.json     # exit 10 (pin PENDIENTE)
```

## Fallas conocidas (aceptadas)

- Una clave JSON duplicada o un límite del parser (enteros de más de 4300
  dígitos, anidamiento extremo) producen un único error `$`. El resultado sigue
  siendo fail-closed, pero no se reportan los demás errores de esquema. El umbral
  de recursión varía entre Python 3.12 y 3.14.
- Una clave raíz desconocida que contiene puntos (p. ej.
  `"skills.research.sha256"`) produce una ruta idéntica a la de un campo
  anidado.
- El pin de `grilling` en `plugins/github-gateway/plugin.json` es `d2f09a18…`,
  y la copia vendorizada v1.3 tiene `8ca78c6d…`. La skill de GitHub sigue con
  `PENDIENTE_64_HEX`. Se decide en la Fase 6.
- Un hook del entorno Codex crea `ANCHOR.yaml` en la raíz al cerrar cada
  subagente. Hay que borrarlo tras cada delegación.
- El hook de pre-commit no está instalado (`make hooks`). Antes de cada commit,
  el chequeo de acoplamiento se corrió a mano.

## Dónde parte la Fase 2

La Fase 2 construye la máquina de estados, los recibos y el lock (PLAN.md §5.2 y
§5.6). Se apoya en:

- `load_plugin()` y `Plugin.digest`, para invalidar un run si el plugin cambia.
- `check_result()`, como gate de `done`.
- `EXIT_*`, que ya están definidos.

Aplican los errores 1, 2, 4, 5 y 6 de PLAN.md §4: `run_id` + `step_id` en toda
la evidencia, `receipt_id` derivado y timeout solo por turno. El host falso
vive en `tests/`. No hay adaptador Pi todavía.
