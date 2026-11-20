---

name: evidence-first
description: Use during clarification, reflection, or reconciliation when a task must prove intent, validation, and closure with traceable evidence instead of narrative.
license: MIT
metadata:
  author: felipe gonzalez
  version: "1.0.0"
---

# Evidence First

## Purpose

Convertir una tarea en una cadena verificable: intención → plan → ejecución →
validación → reconciliación. Un cierre sin evidencia es un cierre falso.

## Rules

1. Declarar objetivo, alcance y resultado esperado antes de mutar.
2. Definir la validación antes de ejecutar, no después.
3. Preferir evidencia reproducible: tests, lint, typecheck, diff, hashes.
4. Distinguir "corrió" de "está sano": un exit code 0 no prueba coherencia.
5. Si el alcance cambia, actualizar el plan o declarar excepción.
6. No cerrar con contradicciones vivas entre código, documentación y estado.

## Checklist

- [ ] Intención y alcance explícitos.
- [ ] Validación definida y ejecutada.
- [ ] Diff revisado contra el plan.
- [ ] Documentación mínima actualizada o ausencia justificada.
- [ ] Evidencia enlazada al cierre.

## Output

Devolver: objetivo, validación ejecutada, resultado observable, desviaciones y
evidencia pendiente. Si falta evidencia, el veredicto es `BLOCK`, no `WARN`.
