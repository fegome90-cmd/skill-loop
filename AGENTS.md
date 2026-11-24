# AGENTS.md — skillrun

## Estado

`v0.1.0 — Fase 6 cerrada`. El repositorio `skill-loop` contiene el módulo y
la CLI `skillrun`, con los subcomandos `validate`, `run`, `status` y
`reconcile`. El contrato de uso está en el [README](README.md#cli).

La prueba con Pi real completó el flujo `discovery → github-knowledge`.
El [handoff de Fase 6](handoffs/HANDOFF-2026-11-21-PHASE-6.md) distingue
las corridas y sus límites de verificación.

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
- El motor delega las operaciones del agente a la interfaz `Host`. `PiHost`
  inicia y controla Pi 1.6 en modo RPC (PLAN.md §5.10).

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
   actualiza su referencia en el mismo commit. Al ejecutarse, el guard comprueba el acoplamiento
   por rutas: los cambios preparados en las cinco superficies enumeradas en
   `CONTRACT_SURFACES` (incluido `SOURCE.lock`) requieren también un cambio
   preparado en `AGENTS.md` o `docs/agent/`. No valida el contenido de la actualización.
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
tests/                pytest + fixtures + fake_host.py + fake_pi.py
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

[La skill de entrada](.agents/skills/skillrun/SKILL.md) dirige a la persona
usuaria a la CLI. Las otras skills de `.agents/skills/` son vendorizadas y
no se editan a mano. El directorio se excluye de los hooks de lint.

## Comandos reales

```bash
make install   # uv sync
make lint      # ruff + mypy + bandit + codespell + markdownlint + agent-docs + yamllint
make format    # ruff format + ruff check --fix + markdownlint --fix
make hooks     # pre-commit install + run --all-files
make check     # alias de lint
uv run pytest  # suite de tests
uv run skillrun validate <plugin.json>  # 0 válido · 10 inválido · 70 interno · 2 uso
```

## Evidencia y pendientes

Fuentes de este archivo: `PLAN.md`, `README.md`, `docs/CONSTITUTION.md`,
`pyproject.toml` y `Makefile`.

- La estructura de estos documentos la comprueba `tools/check_agent_docs.py`;
  no certifica semántica ni vigencia de comandos.
