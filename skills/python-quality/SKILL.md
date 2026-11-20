---

name: python-quality
description: Use while operating or observing Python changes that need Ruff, mypy, and pytest gates proportional to their risk.
license: MIT
metadata:
  author: felipe gonzalez
  version: "1.0.0"
---

# Python Quality

## Purpose

Aplicar los gates mínimos de la Ley V sin convertir la validación en teatro.

## Sequence

1. `uv run ruff format .`
2. `uv run ruff check .`
3. `uv run mypy src`
4. `uv run pytest -q`

Si el proyecto usa `uv`, no inventes un entorno paralelo: el lockfile es parte
del contrato.

## Rules

- Un test que no puede fallar no es evidencia.
- No silenciar errores de tipos con `# type: ignore` sin justificación acotada.
- No agregar dependencias para evitar un chequeo que el stack ya resuelve.
- Los tests nuevos deben cubrir el comportamiento observable, no la implementación.
- Si el cambio toca contratos, agregar validación de integración o smoke.

## Output

Reportar comando, código de salida y resultado relevante. Si un gate no puede
ejecutarse, declararlo como excepción con control compensatorio, no omitirlo.
