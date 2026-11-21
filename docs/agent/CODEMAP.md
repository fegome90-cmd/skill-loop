# Dónde empezar

Mapa superficial para elegir por dónde leer. No es un inventario. Los comandos y
su estado de verificación viven en [RUNTIME.md](RUNTIME.md); las
responsabilidades e invariantes, en [ARCHITECTURE.md](ARCHITECTURE.md).

## Entradas y áreas

| Ruta o símbolo | Para qué leerlo |
| --- | --- |
| `AGENTS.md` | Reglas operativas, fuente de verdad y alcance |
| `PLAN.md` | Decisiones cerradas, diseño (§5), errores a evitar (§4) y fases (§6) |
| `handoffs/` | Estado real al cierre de cada fase |
| `README.md` | Qué existe, qué no existe y stack de calidad |
| `docs/CONSTITUTION.md` | Procedencia, precedencia y actualización del snapshot |
| `docs/constitution/SOURCE.lock` | Commit, ruta y SHA-256 del origen canónico |
| `docs/constitution/AGENTIC-CONSTITUTION.md` | Texto normativo de referencia (no se edita a mano) |
| `src/skillrun.py` | App completa (módulo único) |
| `run_plugin()`, `reconcile()` en `src/skillrun.py` | Supervisor, recuperación y decisiones sobre turnos inciertos |
| `workspace_digest()`, `Console`, `TerminalConsole` en `src/skillrun.py` | Snapshot por turno y entrada/salida humana |
| `Host`, `Turn`, `HostError` en `src/skillrun.py` | Interfaz del host para el adaptador Pi RPC |
| `PiHost`, `PiHistory`, `read_skill_bytes()` en `src/skillrun.py` | Adaptador Pi RPC y lectura de skills fijadas |
| `tests/fake_pi.py` | Pi falso como subproceso, con turnos de herramientas y escenarios de fallo |
| `tests/test_grilling.py`, `tests/test_workspace.py`, `tests/test_terminal_console.py`, `tests/test_phase4_review.py` | Rondas, snapshots, terminal y regresiones de Fase 4 |
| `tests/` | Suite pytest y fixtures |
| `plugins/github-gateway/plugin.json` | Plugin de ejemplo `skillrun/v1` |
| `.agents/skills-lock.json` | Pins (git blob) de las skills vendorizadas |
| `pyproject.toml` | Python mínimo, empaquetado y configuración de Ruff, mypy, pytest y Bandit |
| `Makefile` | Objetivos reales de instalación, lint, formato y hooks |
| `.pre-commit-config.yaml` | Revisores y versiones que fijan la calidad |

## Superficies de cambio

| Si cambia… | Empezar por… | Revisar también… | Verificación pertinente |
| --- | --- | --- | --- |
| El esquema de plugin o la CLI | `src/skillrun.py` | `PLAN.md` §5, `README.md`, `plugins/` | `uv run pytest` |
| Una herramienta de calidad o su configuración | `pyproject.toml` o el archivo de configuración correspondiente | `Makefile`, `.pre-commit-config.yaml`, `README.md` | lint de [RUNTIME.md](RUNTIME.md) |
| Un objetivo del `Makefile` | `Makefile` | [RUNTIME.md](RUNTIME.md), `README.md` | ejecutar el objetivo y registrar el resultado |
| El snapshot constitucional | `docs/constitution/AGENTIC-CONSTITUTION.md` y `SOURCE.lock` en el mismo commit | `docs/CONSTITUTION.md`, `README.md` | comparar SHA-256 con el lock |
| El Python mínimo o el empaquetado | `pyproject.toml` | `uv.lock`, `Makefile` | lint y tipos de [RUNTIME.md](RUNTIME.md) |
| Las reglas para agentes | `AGENTS.md` | `docs/agent/*` | markdownlint |
| La documentación de agentes | `docs/agent/*` | `AGENTS.md` (tabla de lectura por intención) | `agent_docs_kit.py check` y markdownlint |

## Recorrido de lectura

1. `AGENTS.md` — qué está prohibido antes de tocar nada.
2. `PLAN.md` y el último handoff — qué se decidió y dónde estamos.
3. `README.md` — qué existe y qué no.
4. `pyproject.toml` — herramientas, versiones y configuración.
5. `Makefile` — qué se ejecuta y en qué orden.
6. `docs/CONSTITUTION.md` — procedencia y precedencia.
7. [ARCHITECTURE.md](ARCHITECTURE.md) — invariantes.

Para propósito y términos, [CONTEXT.md](CONTEXT.md).

## Evidencia y pendientes

- Grafo regenerado con graphify 0.9.26 sobre `src/skillrun.py` en el commit de
  cierre de Fase 1 (`ddced5f`), excluyendo `.agents/**` y `reference/**`:
  **84 nodos y 173 aristas**. Nodos de interés: `src_skillrun`,
  `src_skillrun_plugin`, `src_skillrun_skill`, `src_skillrun_step`,
  `src_skillrun_pluginerror`. Es evidencia derivada y no se versiona.
- El grafo anterior describía el scaffold `skill_loop`, retirado en el merge, y
  ya no aplica.
- El grafo citado arriba corresponde a la Fase 1. Para el motor actual, el
  [handoff de Fase 4](../../handoffs/HANDOFF-2026-11-21-PHASE-4.md) registra
  las pruebas específicas y el alcance verificado; no se regeneró el grafo.
