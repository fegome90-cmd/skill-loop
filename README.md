# skillrun

Ejecución determinista de N skills en orden, con `grilling` (Matt Pocock) como
discovery obligatorio. Una CLI en Python estándar lanza y controla al agente
(Pi RPC primero) y lo obliga a invocar las skills de un plugin una a una.

**Estado: v0.1.0 — Fase 1 en curso** (esquema de plugin y `skillrun validate`).
Plan, decisiones y fases en [`PLAN.md`](PLAN.md); estado real en el último
handoff de `handoffs/`.

Repositorio: `skill-loop`. Producto, CLI y módulo: `skillrun`.

## Qué existe

- Proyecto Python `>=3.12` gestionado con `uv`; runtime solo stdlib.
- Módulo único `src/skillrun.py` (scaffold) y console script `skillrun`.
- Plugin de ejemplo `plugins/github-gateway/plugin.json` (pins pendientes:
  `validate` lo rechaza hasta la Fase 6).
- 37 skills de Matt Pocock vendorizadas en `.agents/skills/`, fijadas por git
  blob en `.agents/skills-lock.json`.
- Stack de calidad replicado de `constitucion-ai` y snapshot de la Constitución
  v1.1 con lock de procedencia.

## Cómo trabajar por fases

1. Cada fase en su propio hilo. Primer hilo: `prompts/01-inicio.md`.
2. Hilo de orquestación: `prompts/02-orquestador.md` (cambiar `<n> — <nombre>`)
   o la línea `START HERE` del handoff anterior.

## Antes de la Fase 6 (prueba real)

- Pi 1.4+ instalado.
- `SKILL.md` original de `grilling`:
  `mattpocock/skills@5863806dd4e15c63174bee4e7515a4256792ecfa`,
  `skills/productivity/grilling/SKILL.md`, git blob
  `d2f09a18e6a6c65c55f1271ba08dfeaf06f0bed3` (verificar con `git hash-object`).
  La copia vendorizada (v1.3) tiene otro blob (`8ca78c6d…`): decidir en Fase 6.
- La skill de GitHub elegida y su hash para `plugins/github-gateway/plugin.json`.

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
- Verificación local: usá los comandos de [Calidad](#calidad) cuando el proyecto
  Python esté incorporado en `main`.
- Seguridad: `./scripts/check-secrets.sh staged` (requiere
  [Gitleaks 8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1))
  o activá el hook con `git config core.hooksPath .githooks`. El hook corre el
  escaneo y, si está instalado, `pre-commit`.
- Reportes de seguridad: ver [`SECURITY.md`](SECURITY.md); no abras issues públicos.

## Licencia

[MIT](LICENSE).
