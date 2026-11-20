# Preparación, ejecución y verificación

Distingue lo leído de lo ejecutado. Un comando leído no prueba que se haya
ejecutado ni que pase.

## Requisitos y configuración

- `requires-python = ">=3.12"` en `pyproject.toml`. El entorno local resuelto es
  Python 3.14: satisface el mínimo y no es un requisito del proyecto.
- `uv` gestiona entorno y lock (`uv.lock` versionado). Versión observada: 0.13.8.
- Runtime solo stdlib (`dependencies = []`); console script `skillrun`. Grupo `dev`: `pytest`, `ruff`, `mypy`,
  `pre-commit`, `bandit`, `codespell` y `yamllint`.
- Configuración: `pyproject.toml` (Ruff, mypy, pytest, Bandit),
  `.yamllint.yaml`, `.markdownlint-cli2.jsonc`, `.codespellrc`, `.shellcheckrc`
  y `.pre-commit-config.yaml`.
- Variables de entorno: ninguna requerida. Sin credenciales ni servicios.
- Herramientas externas de documentación, no declaradas como dependencias:
  el guion `agent-docs-kit` (PEP 723) y `graphify` 0.9.26.

## Comandos

Todos se ejecutan desde la raíz del repositorio.

| Acción | Comando | Fuente | Estado de verificación |
| --- | --- | --- | --- |
| Sincronizar entorno | `uv sync` | `Makefile` (`install`) | Solo leído |
| Lint completo | `make lint` o `make check` | `Makefile` | Solo leído; se ejecutaron sus componentes de Python por separado |
| Ruff lint | `uv run ruff check .` | `Makefile` (`lint-python`) | Ejecutado: código 0, "All checks passed!" |
| Formato | `uv run ruff format --check .` | `Makefile` (`lint-python`) | Ejecutado: código 0, 5 archivos ya formateados |
| Tipos | `uv run mypy src` | `Makefile` (`lint-python`) | Ejecutado: código 0, sin hallazgos en 1 archivo |
| Seguridad | `uv run bandit -c pyproject.toml -r src` | `Makefile` (`lint-python`) | Ejecutado: código 0, 0 hallazgos |
| Ortografía | `uv run codespell` | `Makefile` (`lint-python`) | Ejecutado: código 0, sin salida |
| Pruebas | `uv run pytest` | `pyproject.toml` (`testpaths`) | `tests/` existe desde el merge; estado al cierre de cada fase en su handoff |
| Markdown | `uv run pre-commit run markdownlint-cli2 --all-files` | `Makefile` (`lint-docs`) | Solo leído |
| YAML | `uv run yamllint -c .yamllint.yaml .pre-commit-config.yaml .yamllint.yaml` | `Makefile` (`lint-yaml`) | Solo leído |
| Hooks de Git | `uv run pre-commit install` | `Makefile` (`hooks`) | Solo leído (pre-commit 4.7.0 disponible) |
| Verificar documentos de agente | `uv run --script <kit>/agent_docs_kit.py check <raíz>` | Kit documental | Ejecutado sobre este repositorio |
| Verificar documentación de agentes (determinista) | `uv run python tools/check_agent_docs.py` | `tools/check_agent_docs.py`, hook `agent-docs` | Ejecutado: código 0; falla si falta un documento, queda un borrador, un enlace local está roto o el contrato cambia sin tocar `docs/agent/` |
| Regenerar el grafo del mapa | ver "Mapa de código" | Kit documental | Ejecutado con graphify 0.9.26 |

## Mapa de código (CODEMAP)

El comando no añade dependencias al proyecto: usa el guion del kit y el
`graphify` ya instalado. El destino debe ser nuevo, externo a la raíz y sin
componentes simbólicos (en macOS `/tmp` es un enlace y el kit lo rechaza):

```sh
uv run --no-python-downloads --script <ruta-al-kit>/agent_docs_kit.py graph <repo> \
  --output <directorio-nuevo-externo> --apply \
  --exclude '.venv/**' --exclude '__pycache__/**' --exclude '.git/**'
```

- Requiere graphify exactamente 0.9.26; `graphify --version` respondió `0.9.26`.
- Salida: `graphify-out/graph.json`, `graphify.log`, `run.json` y `run.jsonl`.
- Resultado sobre este árbol: 3 nodos y 1 arista. La evidencia está registrada
  en [CODEMAP.md](CODEMAP.md).
- El grafo no se versiona: es evidencia derivada, no autoridad documental.

## Procesos y diagnóstico

- No hay servicios, puertos ni procesos de larga duración.
- `pytest` devuelve 5 si no recolecta tests: ausencia de suite, no fallo de
  aserción. `make lint` no ejecuta pytest; córrelo aparte.
- `make lint` propaga fallos: no hay `|| true`. Un componente fallido provoca
  el fallo del objetivo y debe tratarse, no silenciarse.
- `agent_docs_kit.py check` valida presencia de los cinco documentos, UTF-8 con
  LF, ausencia de marcador de borrador y enlaces locales simples. No valida
  semántica, vigencia de comandos ni anclas.

## Evidencia y pendientes

- Comprobado por ejecución (antes del merge): `ruff check`, `ruff format --check`,
  `mypy`, `bandit`, `codespell` y el grafo del mapa.
- Ejecutado también: `tools/check_agent_docs.py` (estructura y acoplamiento).
- Sólo leído: `uv sync`, `make lint` completo, `pre-commit`/markdownlint y
  `yamllint`. Registrarlos como pendientes, no como verdes.
- Pendiente: decidir si conviene un objetivo `make codemap`; hoy el comando del
  grafo vive sólo en este documento.
