# AGENTS.md — skillrun

## Estado

`v0.1.0 — Fase 1 en curso.` Repositorio `skill-loop`; producto, CLI y módulo
`skillrun`. CLI que lanza y controla un agente (Pi RPC primero) para ejecutar las
skills de un plugin **en orden**, con `grilling` como paso 1 obligatorio. Plan,
decisiones y fases: [PLAN.md](PLAN.md).

Solo existe lo que la fase cerrada más reciente declara en su handoff
(`handoffs/`). No afirmes que `skillrun run`, `status` o `reconcile` existen
antes de su fase.

## Lectura por intención

Documentos derivados para agentes. Enrutan y explican; **no** crean autoridad ni
reemplazan las fuentes de la sección siguiente.

| Para… | Leer |
| --- | --- |
| Plan, decisiones cerradas y fases | [PLAN.md](PLAN.md) |
| Entender propósito, actores y conceptos | [docs/agent/CONTEXT.md](docs/agent/CONTEXT.md) |
| Revisar composición, responsabilidades e invariantes | [docs/agent/ARCHITECTURE.md](docs/agent/ARCHITECTURE.md) |
| Elegir por dónde empezar y qué tocar | [docs/agent/CODEMAP.md](docs/agent/CODEMAP.md) |
| Preparar entorno, ejecutar o verificar | [docs/agent/RUNTIME.md](docs/agent/RUNTIME.md) |
| Errores de los prototipos que no se repiten | [reference/REVIEWS.md](reference/REVIEWS.md) y PLAN.md §4 |

## Fuente de verdad

1. Constitución upstream: [`fegome90-cmd/constitucion-ai`](https://github.com/fegome90-cmd/constitucion-ai).
2. Snapshot local + lock: `docs/constitution/AGENTIC-CONSTITUTION.md` y
   `docs/constitution/SOURCE.lock`.
3. `PLAN.md` (decisiones del producto) y el handoff activo en `handoffs/`.
4. Documentación del repositorio: `README.md`, `docs/CONSTITUTION.md`, este
   archivo.

Si hay conflicto, gana el upstream. El snapshot y el lock se actualizan en el
mismo commit; nunca se edita el snapshot a mano.

## Stack

- Python `>=3.12`, gestionado con `uv`.
- **Runtime solo stdlib**: `dependencies = []`. Un único módulo
  `src/skillrun.py`; console script `skillrun = "skillrun:main"`.
- Dev: Ruff, mypy estricto, pytest, Bandit, codespell, yamllint,
  markdownlint-cli2, shellcheck y pre-commit.
- skillrun no llama a red ni a LLMs por sí mismo; lanza al host agente (Pi)
  como subproceso y lo controla.

## Reglas duras

1. **Leer antes de escribir** (Ley II). Revisar lo existente antes de crear.
   Leer `PLAN.md` y el handoff activo antes de actuar. Una fase por hilo.
2. **No duplicar** fuentes de verdad.
3. **No trabajar directo sobre `main`.** Rama identificable y commit
   convencional. Nunca agregar `Co-Authored-By` ni atribución de IA.
4. **No agregar features no pedidas** (Ley III). El alcance lo define la persona
   usuaria, no el agente.
5. **Fallo cerrado** (Ley VIII, Art. 3) y **determinismo** (Ley V, Art. 6).
   TDD: test primero, luego código.
6. **Evidencia antes que relato** (Ley XI). No declarar un cierre sin
   validación observable. Distinguir lo verificado de lo supuesto.
7. **Sin secretos** en config, docs, logs ni commits (Ley VIII, Art. 6).
8. **Higiene** (Ley IV, Art. 7). Sin temporales ni untracked sin propósito.
9. **Documentación mínima** (Ley VI, Art. 6). Si cambia un contrato, se
   actualiza su referencia en el mismo commit. El hook `agent-docs` de
   pre-commit (`tools/check_agent_docs.py`) lo verifica: bloquea el commit si
   cambia `pyproject.toml`, `Makefile`, `.pre-commit-config.yaml` o el snapshot
   constitucional sin tocar `AGENTS.md` o `docs/agent/`.
10. **Nada escribe en GitHub.** Los pasos del agente controlado son solo
    lectura.
11. **Estado de runs fuera del repo** (`~/.local/state/skillrun/`), permisos
    0700/0600.
12. **`reference/` es solo lectura.** Solo `REVIEWS.md` se versiona; zips y
    `flow.py` quedan en disco (ignorados). Para leer un zip, extraerlo en un
    directorio temporal nuevo y no ejecutar su código salvo que la fase lo
    requiera.
13. Si un arreglo falla dos veces con el mismo enfoque, detenerse y explicar
    causa e intentos.

## Layout

```text
src/skillrun.py       app completa (módulo único)
tests/                pytest + fixtures (+ fake_pi.py desde Fase 3)
plugins/              plugins de ejemplo (plugin.json)
.agents/skills/       skill de entrada (Fase 5) + skills de Matt Pocock
                      vendorizadas, fijadas en .agents/skills-lock.json
prompts/              prompts de inicio y orquestador
handoffs/             HANDOFF-<AAAA-MM-DD>-PHASE-<n>.md
reference/            REVIEWS.md (versionado) + prototipos (ignorados)
docs/                 procedencia constitucional
docs/agent/           documentos derivados para agentes
tools/                guard de documentación de agentes
```

`.agents/skills/` es contenido vendorizado: no se edita a mano ni se lintea
(excluido en pre-commit, codespell y markdownlint).

## Comandos reales

```bash
make install   # uv sync
make lint      # ruff + mypy + bandit + codespell + markdownlint + agent-docs + yamllint
make format    # ruff format + ruff check --fix + markdownlint --fix
make hooks     # pre-commit install + run --all-files
make check     # alias de lint
uv run pytest  # suite de tests
```

## Evidencia y pendientes

Fuentes de este archivo: `PLAN.md`, `README.md`, `docs/CONSTITUTION.md`,
`pyproject.toml` y `Makefile`.

- La estructura de estos documentos la comprueba `tools/check_agent_docs.py`;
  no certifica semántica ni vigencia de comandos.
