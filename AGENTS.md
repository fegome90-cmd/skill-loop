# AGENTS.md — skill-loop

## Misión

Kit determinista para ejecutar el **CLOOP** de la Constitución de Código Agéntico
y aplicar skills **just-in-time** por fase: solo las que corresponden, en orden
reproducible, con gates y evidencia auditable.

## Estado actual

`v0.1.0 — configuración inicial.` No existe runner ni CLI. Este repositorio
define el contrato; la implementación viene después.

**No afirmes que `skill-loop plan`, `start`, `advance` o `verify` existen.** Por
ahora solo existen los manifiestos de `config/` y los comandos de `make`.

## Jerarquía de fuentes de verdad

1. Constitución upstream: [`fegome90-cmd/constitucion-ai`](https://github.com/fegome90-cmd/constitucion-ai).
2. Snapshot local + lock: `docs/constitution/AGENTIC-CONSTITUTION.md` y
   `docs/constitution/SOURCE.lock`.
3. Contrato del kit: `config/loop.yaml`, `config/gates.yaml`, `config/skills.yaml`.
4. Documentación: `README.md`, `docs/CONSTITUTION.md`, este archivo.

Si hay conflicto, gana el upstream. El snapshot y el lock se actualizan en el
mismo commit; nunca se edita el snapshot a mano.

## Stack

- Python `>=3.12`, gestionado con `uv`.
- Ruff (lint + format), mypy estricto, pytest.
- Única dependencia de runtime: `PyYAML`.
- **Sin red y sin LLM en el loop.** La selección de skills es determinista.

## Reglas duras

1. **Leer antes de escribir** (Ley II). Revisar configuración, docs y skills
   vecinas antes de crear artefactos nuevos.
2. **No duplicar** fuentes de verdad, helpers, gates ni skills.
3. **No trabajar directo sobre `main`.** Rama identificable y commit
   convencional. Nunca agregar `Co-Authored-By` ni atribución de IA.
4. **Fallo cerrado** (Ley VIII, Art. 3). Un gate bloqueado detiene el loop; no
   se saltea con `--force` ni con una bandera equivalente.
5. **Determinismo** (Ley V, Art. 6). Ordenar entradas, serializar con JSON
   canónico, hashear con SHA-256. Nada de `set` sin ordenar ni timestamps dentro
   del hash del plan.
6. **JIT real.** Cargar solo las skills seleccionadas para la fase. Prohibido
   inyectar el catálogo completo "por las dudas".
7. **Evidencia antes que relato** (Ley XI). Cada fase deja un registro con
   intención, validación y resultado.
8. **No auto-aprobación** (Ley XII, Art. 5). Las excepciones requieren
   `--approver` explícito y quedan registradas.
9. **Sin secretos** en prompts, config, docs, logs ni commits (Ley VIII, Art. 6).
10. **Higiene** (Ley IV, Art. 7). Sin temporales, logs, dumps ni untracked sin
    propósito al cierre.
11. **Documentación mínima** (Ley VI, Art. 6). Si cambia un contrato, comando,
    gate o configuración, se actualiza su referencia en el mismo commit.
12. **Sin sobreingeniería** (Ley III). No agregar dependencias, capas ni
    abstracciones que no paguen su costo.

## Contrato JIT (a implementar)

Señales declaradas por cada skill en `config/skills.yaml`:

| Señal | Puntaje | Regla |
|---|---|---|
| `tag` explícito | +40 | match exacto, casefold |
| `path` | +20 | glob contra los paths declarados por la tarea |
| `keyword` | +15 | palabra completa en la tarea, casefold |
| `default` | +1 | skill base de la fase |

- Selección: `score >= min_score`, orden `(-score, -priority, id)`.
- Recorte: `max_skills` de la fase, con `dropped` registrado.
- Filtro: `phase in skill.phases` y `requires` satisfechos.
- El hash del plan incluye: tarea normalizada, tags, paths, scope, fase,
  configuración semántica, contenido de cada skill y SHA-256 de la Constitución.
- El contexto de cada fase se renderiza una sola vez y se congela con el plan.

## Fases y gates

| Fase | Gates de entrada | Gates de salida | Evidencia |
|---|---|---|---|
| Clarify | `constitution.integrity` | — | `clarification` |
| Layout | `plan.frozen` | — | `layout` |
| Operate | — | `scope.compliance` | `operation` |
| Observe | — | `quality.commands` | `observation` |
| Reflect | — | — | `reflection` |
| Reconcile | — | `docs.reconciled` | `reconciliation` |
| Handoff | — | `git.clean`, `evidence.chain` | `handoff` |

## Layout

```text
config/          contrato declarativo (fases, gates, skills)
docs/            procedencia constitucional y mapeo
skills/          skills de ejemplo consumidas por el registro
src/skill_loop/  paquete Python (scaffold, sin lógica todavía)
```

## Comandos reales

```bash
make install   # uv sync
make lint      # ruff + mypy + bandit + codespell + markdownlint + yamllint
make format    # ruff format + ruff check --fix + markdownlint --fix
make hooks     # pre-commit install + run --all-files
make check     # alias de lint
```

El stack de calidad replica el de `constitucion-ai`: Ruff, mypy, pytest,
Bandit, codespell, yamllint, markdownlint-cli2, shellcheck y pre-commit. Los
gates no se silencian con `|| true`: un fallo debe fallar.

## Definición de done (cuando se implemente el runner)

- Selector determinista con tests que repitan el mismo plan y hash.
- Máquina de estados que impida saltear fases.
- Cadena de evidencia con detección de tamper.
- Gates que fallen cerrado y dejen rastro.
- Contextos JIT por fase, sin cargar skills fuera de la fase.
- `README.md`, `docs/CONSTITUTION.md` y `AGENTS.md` alineados con el código.
- `make lint` y `uv run pytest` en verde.
