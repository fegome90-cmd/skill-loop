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
- Variables de entorno: `XDG_STATE_HOME` absoluto es opcional para el motor.
  Las pruebas de Fase 2 usan un host falso y un directorio temporal privado.
- Herramientas externas de documentación, no declaradas como dependencias:
  el guion `agent-docs-kit` (PEP 723) y `graphify` 0.9.26.

## Comandos

Todos se ejecutan desde la raíz del repositorio.

| Acción | Comando | Fuente | Estado de verificación |
| --- | --- | --- | --- |
| Sincronizar entorno | `uv sync` | `Makefile` (`install`) | Solo leído |
| Lint completo | `make lint` | `Makefile` | Ejecutado al cierre de Fase 2: código 0 |
| Ruff lint | `uv run ruff check .` | `Makefile` (`lint-python`) | Ejecutado: código 0, "All checks passed!" |
| Formato | `uv run ruff format --check .` | `Makefile` (`lint-python`) | Ejecutado como parte de `make lint` en Fase 2: código 0 |
| Tipos | `uv run mypy src tests` | `Makefile` (`lint-python`) | Strict sobre código y tests, ejecutado en Fase 2: código 0 |
| Seguridad | `uv run bandit -c pyproject.toml -r src` | `Makefile` (`lint-python`) | Ejecutado: código 0, 0 hallazgos |
| Ortografía | `uv run codespell` | `Makefile` (`lint-python`) | Ejecutado: código 0, sin salida |
| Pruebas | `uv run pytest` | `pyproject.toml` (`testpaths`) | Ejecutado al cierre de Fase 2: código 0, 208 aprobadas |
| Validar un plugin | `uv run skillrun validate <plugin.json>` | `src/skillrun.py` (`main`) | Comparación de Fase 2 contra `e636858`: coincidieron stdout, stderr y códigos 0, 2 y 10 en los casos ejecutados |
| Markdown | `uv run pre-commit run markdownlint-cli2 --all-files` | `Makefile` (`lint-docs`) | Ejecutado como parte de `make lint` en Fase 2: código 0 |
| YAML | `uv run yamllint -c .yamllint.yaml .pre-commit-config.yaml .yamllint.yaml docs/constitution/SOURCE.lock` | `Makefile` (`lint-yaml`) | Ejecutado como parte de `make lint` en Fase 2: código 0 |
| Hooks de Git | `uv run pre-commit install` | `Makefile` (`hooks`) | **No ejecutado**: al cierre de Fase 1 el hook `agent-docs` seguía sin instalar, así que sólo actuó cuando se corrió a mano |
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
- Resultado sobre `src/skillrun.py` en `ddced5f`, excluyendo `.agents/**` y
  `reference/**`: **84 nodos y 173 aristas**. La evidencia está registrada en
  [CODEMAP.md](CODEMAP.md).
- El grafo no se versiona: es evidencia derivada, no autoridad documental.

## Procesos y diagnóstico

- No hay servicios, puertos ni procesos de larga duración.
- `pytest` devuelve 5 cuando no recolecta tests. Ejecuta pytest y `make lint`
  como comprobaciones separadas.
- `make lint` propaga fallos: no hay `|| true`. Un componente fallido provoca
  el fallo del objetivo y debe tratarse, no silenciarse.
- `agent_docs_kit.py check` valida presencia de los cinco documentos, UTF-8 con
  LF, ausencia de marcador de borrador y enlaces locales simples. No valida
  semántica, vigencia de comandos ni anclas.

## Evidencia y pendientes

- El [handoff de Fase 2](../../handoffs/HANDOFF-2026-11-20-PHASE-2.md) enlaza
  el candidato verificado y registra las pruebas de caída de proceso, permisos
  y compatibilidad. La suite del motor usa primitivas POSIX.
- Pendiente: decidir si conviene un objetivo `make codemap`; hoy el comando del
  grafo vive sólo en este documento.
