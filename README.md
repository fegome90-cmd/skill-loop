# skill-loop

Scaffold mínimo en Python para un futuro kit de aplicación determinista de
skills.

**Estado: v0.1.0 — configuración inicial.** Todavía no hay loop, gates,
registro de skills, runner ni CLI. Este repositorio solo deja preparado el
proyecto: empaquetado, calidad y referencia constitucional.

## Qué existe

- Proyecto Python `>=3.12` gestionado con `uv`.
- Stack de calidad replicado de `constitucion-ai`.
- Snapshot de la Constitución v1.1 con lock de procedencia.
- Paquete `skill_loop` vacío (solo `__version__`).

## Qué no existe todavía

No hay loop, gates, registro de skills, runner ni CLI. Eso se define cuando se
pida explícitamente.

## Estructura

```text
.
├── AGENTS.md                  # reglas para agentes
├── docs/
│   ├── CONSTITUTION.md        # procedencia y actualización del snapshot
│   └── constitution/
│       ├── AGENTIC-CONSTITUTION.md
│       └── SOURCE.lock
├── src/skill_loop/            # paquete scaffold
├── pyproject.toml
├── Makefile
└── uv.lock
```

## Calidad

| Herramienta | Rol | Configuración |
|---|---|---|
| Ruff | lint + format Python | `pyproject.toml` |
| mypy | typecheck estricto | `pyproject.toml` |
| pytest | tests (sin suite todavía) | `pyproject.toml` |
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

## Licencia

MIT.
