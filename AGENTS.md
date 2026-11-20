# AGENTS.md — skill-loop

## Estado

`v0.1.0 — scaffold mínimo.` No hay loop, gates, registro de skills, runner ni
CLI. No inventes comandos `skill-loop ...`.

## Fuente de verdad

1. Constitución upstream: [`fegome90-cmd/constitucion-ai`](https://github.com/fegome90-cmd/constitucion-ai).
2. Snapshot local + lock: `docs/constitution/AGENTIC-CONSTITUTION.md` y
   `docs/constitution/SOURCE.lock`.
3. Documentación del repositorio: `README.md`, `docs/CONSTITUTION.md`, este
   archivo.

Si hay conflicto, gana el upstream. El snapshot y el lock se actualizan en el
mismo commit; nunca se edita el snapshot a mano.

## Stack

- Python `>=3.12`, gestionado con `uv`.
- Ruff, mypy, pytest, Bandit, codespell, yamllint, markdownlint-cli2,
  shellcheck y pre-commit.
- Sin red y sin LLM en el runtime.

## Reglas duras

1. **Leer antes de escribir** (Ley II). Revisar lo existente antes de crear.
2. **No duplicar** fuentes de verdad.
3. **No trabajar directo sobre `main`** a partir del baseline. Rama
   identificable y commit convencional. Nunca agregar `Co-Authored-By` ni
   atribución de IA.
4. **No agregar features no pedidas** (Ley III). El alcance lo define la persona
   usuaria, no el agente.
5. **Fallo cerrado** (Ley VIII, Art. 3) y **determinismo** (Ley V, Art. 6)
   cuando se implemente lógica.
6. **Evidencia antes que relato** (Ley XI). No declarar un cierre sin
   validación observable.
7. **Sin secretos** en config, docs, logs ni commits (Ley VIII, Art. 6).
8. **Higiene** (Ley IV, Art. 7). Sin temporales ni untracked sin propósito.
9. **Documentación mínima** (Ley VI, Art. 6). Si cambia un contrato, se
   actualiza su referencia en el mismo commit.

## Layout

```text
docs/            procedencia constitucional
src/skill_loop/  paquete scaffold, sin lógica
```

## Comandos reales

```bash
make install   # uv sync
make lint      # ruff + mypy + bandit + codespell + markdownlint + yamllint
make format    # ruff format + ruff check --fix + markdownlint --fix
make hooks     # pre-commit install + run --all-files
make check     # alias de lint
```
