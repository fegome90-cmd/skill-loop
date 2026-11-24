# skillrun

Ejecución determinista de N skills en orden, con `grilling` (Matt Pocock) como
discovery obligatorio. Una CLI en Python estándar lanza y controla al agente
(Pi RPC primero) y lo obliga a invocar las skills de un plugin una a una.

**Estado: v0.1.0 — CLI de Fase 5.** El flujo se verifica con un host falso
y con Pi falso como subproceso. Un run real con Pi 1.6.0 se registró en la Fase 6.
El alcance está en [PLAN.md](PLAN.md); la entrega del motor está en el
[handoff de Fase 4](handoffs/HANDOFF-2026-11-21-PHASE-4.md).

Repositorio: `skill-loop`. Producto, CLI y módulo: `skillrun`.

## Qué existe

- Proyecto Python `>=3.12` gestionado con `uv`; runtime solo stdlib.
- Módulo único `src/skillrun.py` y console script `skillrun`.
- Plugin de ejemplo `plugins/github-gateway/plugin.json` (pins fijados en la Fase 6;
  `validate` lo acepta).
- 37 skills de Matt Pocock vendorizadas en `.agents/skills/`, fijadas por git
  blob en `.agents/skills-lock.json`.
- [Skill de entrada](.agents/skills/skillrun/SKILL.md) para dirigir a la
  persona usuaria a la CLI; no ejecuta el run por ella.
- Stack de calidad replicado de `constitucion-ai` y snapshot de la Constitución
  v1.1 con lock de procedencia.

## CLI

Después de `make install`, desde la raíz del proyecto:

```bash
uv run skillrun validate <plugin.json>
uv run skillrun run <plugin.json> --goal "<objetivo>" --cwd <repo> --run-id <id>
uv run skillrun status --run-id <id>
uv run skillrun reconcile --run-id <id>
```

- `validate` solo comprueba el esquema y el formato de los pins. No abre
  `SKILL.md` ni inicia Pi. Su JSON incluye `ok` y `plugin_id`/`digest` o
  `errors`.
- `run` comprueba los pins antes de iniciar Pi y usa `--cwd` tanto para Pi
  como para el snapshot. En Pi, la skill de grilling no delega: para
  consultar el checkout dispone de `read`, `grep`, `find` y `ls`.
  El host pasa esta instrucción explícitamente, en lugar de cargar un
  `APPEND_SYSTEM.md` del proyecto o del usuario. Durante el grilling,
  responde por stdin. Si escribes `/skill:grilling ejemplo` como respuesta,
  Pi lo guarda como texto literal: no ejecuta la skill. Escribe `:listo`
  para pedir la síntesis y confirma con `s` para avanzar.
  Al completar, el JSON incluye `result`: el último bloque JSON del paso
  final, validado contra su contrato y el recibo. Al volver a ejecutar un
  run completo con los mismos parámetros, no se inicia Pi; si falta el
  recibo final verificable, no se devuelve un resultado.
- `status` consulta el checkpoint persistido sin ejecutar Pi ni cambiar el
  estado. Incluye `revision`, `attempt`, `turn` y `reconcilable` si hay
  un checkpoint legible. No comprueba la traza del resultado final.
- `reconcile` solo actúa cuando hay un turno bloqueado por entrega
  incierta. Muestra el recibo en stderr y pide `reintentar` o `abandonar`
  en stdin. Si cambia la revisión antes de aplicar la decisión, no la
  registra. `reintentar` habilita el intento, pero no envía nada: vuelve
  a ejecutar `run` con los mismos parámetros. `abandonar` cancela el run.
  Ctrl-C o fin de entrada sin decisión no modifican el checkpoint.
  Si `status` indica `prepared` o `accepted` tras una caída, vuelve a
  ejecutar `run` para que el motor clasifique el turno sin reenviarlo.

Cada ejecución operativa emite una sola línea JSON en stdout. En
`run`, `status` y `reconcile` incluye `run_id`, `status`, `exit_code`,
`step_id` y `reason` (los dos últimos pueden ser `null`). El texto del
grilling, las preguntas y los avisos van a stderr. `--help` muestra ayuda.

| Código | Significado |
| --- | --- |
| `0` | Plugin válido o run completo |
| `2` | Error de uso |
| `3` | Checkpoint pendiente, reintento habilitado o lock ocupado |
| `10` | Plugin inválido, run bloqueado o estado no disponible |
| `70` | Error interno |
| `130` | Interrupción, fin de entrada sin decisión o abandono |

El estado y la sesión de Pi viven fuera de `--cwd`, en
`$XDG_STATE_HOME/skillrun/<id>/` si `XDG_STATE_HOME` es absoluto; si no,
en `~/.local/state/skillrun/<id>/`. El ID debe cumplir
`[a-z0-9][a-z0-9-]{0,63}`. Si termina en guion, Pi usa un identificador interno
estable; el directorio del run y todos los comandos de la CLI conservan el ID original.

## Cómo trabajar por fases

1. Cada fase en su propio hilo. Primer hilo: `prompts/01-inicio.md`.
2. Hilo de orquestación: `prompts/02-orquestador.md` (cambiar `<n> — <nombre>`)
   o la línea `START HERE` del handoff anterior.

## Prueba real (Fase 6)

Pi corre solo con `read,grep,find,ls`: la skill `github-project` diagnostica
un checkout local en `--cwd`, sin `gh` ni red. El `SKILL.md` original de
`grilling` (`mattpocock/skills@5863806d…`, blob `d2f09a18…`) está copiado en
`plugins/github-gateway/skills/grilling/`; la copia vendorizada v1.3 (blob
`8ca78c6d…`) no se toca. Detalles en el
[handoff de Fase 6](handoffs/HANDOFF-2026-11-21-PHASE-6.md).

## Estructura

```text
.
├── AGENTS.md / CLAUDE.md      # reglas para agentes
├── PLAN.md                    # plan, decisiones y fases
├── src/skillrun.py            # app (módulo único)
├── tests/                     # pytest
├── plugins/                   # plugins de ejemplo
├── prompts/                   # prompts de inicio y orquestador
├── handoffs/                  # cierres de fase
├── reference/REVIEWS.md       # errores de prototipos (zips ignorados)
├── .agents/skills/            # skills vendorizadas + skill de entrada
├── docs/                      # Constitución y docs de agente
├── tools/check_agent_docs.py  # guard de documentación
├── pyproject.toml
├── Makefile
└── uv.lock
```

## Calidad

| Herramienta | Rol | Configuración |
|---|---|---|
| Ruff | lint + format Python | `pyproject.toml` |
| mypy | typecheck estricto | `pyproject.toml` |
| pytest | tests | `pyproject.toml` |
| Bandit | seguridad | `pyproject.toml` |
| codespell | ortografía | `.codespellrc` |
| yamllint | YAML | `.yamllint.yaml` |
| markdownlint-cli2 | Markdown | `.markdownlint-cli2.jsonc` |
| shellcheck | shell | `.shellcheckrc` |
| pre-commit | hooks | `.pre-commit-config.yaml` |

```bash
make install   # uv sync
make lint      # fail-closed
make format    # Ruff + markdownlint con fix
make hooks     # pre-commit install + run --all-files
uv run pytest  # tests
```

## Constitución

La fuente de verdad es
[`fegome90-cmd/constitucion-ai`](https://github.com/fegome90-cmd/constitucion-ai).
El snapshot local existe solo para referencia determinista y offline.

| Dato | Valor |
|---|---|
| Versión | v1.1 |
| Commit | `13df6421f8b42bdd602aa45bdf3e024ed7ccadf8` |
| SHA-256 | `ff201d735c94cb5007651d8f3dcbd8403b1fe0a257dff63fa142c40ff3a65834` |

Ver [`docs/CONSTITUTION.md`](docs/CONSTITUTION.md).

## Colaboración

`main` está protegida: todo cambio entra por pull request y requiere el check
`Secrets and private paths`.

- Plantilla de PR: [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).
- Verificación local: usá los comandos de [Calidad](#calidad).
- Seguridad: `./scripts/check-secrets.sh staged` (requiere
  [Gitleaks 8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1))
  o activá el hook con `git config core.hooksPath .githooks`. El hook corre el
  escaneo y, si está instalado, `pre-commit`.
- Reportes de seguridad: ver [`SECURITY.md`](SECURITY.md); no abras issues públicos.

## Licencia

[MIT](LICENSE).
