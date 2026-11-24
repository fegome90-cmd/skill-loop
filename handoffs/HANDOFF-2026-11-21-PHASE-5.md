# Handoff — Fase 5: CLI y skill de entrada

Fecha: 2026-11-21. Rama local: `feat/phase-4-grilling`, sobre `3366281`.
Estado: **cerrada** por confirmación de la persona usuaria. Los cambios
locales de Fases 4 y 5 siguen sin commit ni publicación.

## Entrega

- `run` conecta `TerminalConsole` y `PiHost` al motor. Usa el mismo
  `--cwd` para Pi y el snapshot. La consola lee de stdin y escribe en
  stderr; stdout recibe una única línea JSON. Al completar, el motor
  conserva el recibo final, verifica la identidad y el SHA-256 de la traza
  y valida el bloque JSON antes de devolver `result`. Un segundo `run`
  puede devolver ese resultado sin reiniciar Pi.
- `status` consulta el estado persistido sin modificarlo ni iniciar Pi.
  Informa el checkpoint, no verifica la traza final.
- `reconcile` muestra la evidencia de un turno incierto y pide una decisión
  explícita. Comprueba bajo lock que la revisión no haya cambiado.
  `reintentar` habilita otro intento y `abandonar` cancela; ninguna decisión
  envía un turno.
- La [skill de entrada](../.agents/skills/skillrun/SKILL.md) indica a la
  persona que ejecute la CLI. La [referencia de la CLI](../README.md#cli)
  documenta los comandos, sus códigos y la recuperación.

Implementación en [src/skillrun.py](../src/skillrun.py); cobertura de
subcomandos en [tests/test_cli_runs.py](../tests/test_cli_runs.py).

## Verificación de implementación

| Comprobación | Resultado |
| --- | --- |
| Suite completa | 354 pruebas aprobadas, incluidas 12 nuevas de CLI; se usó Pi falso, no Pi real |
| `make lint` | Código `0` en copia aislada: el hook de Markdown puede editar archivos |
| `git diff --check HEAD` | Código `0` |
| Compatibilidad de `validate` | En los casos probados, mismos códigos y salida que en Fase 4, salvo la lista ampliada de subcomandos en un error de uso global |
| Verificación independiente | Rechazo de trazas alteradas y de aprobaciones basadas en una revisión anterior; `status` sin escrituras |
| Revisión nativa | No iniciada: la evaluación abarcaba también cambios locales de la Fase 4 |

Para repetir las comprobaciones desde la raíz del repositorio:

```sh
uv run pytest tests/test_cli_runs.py
uv run pytest
make lint
git diff --check HEAD
```

Usar una copia aislada para `make lint` si se requiere conservar el
worktree sin cambios. Tokens por rol: no medidos. Implementación:
Codex `gpt-6.2-sol` / `xhigh`; verificación independiente:
Codex `gpt-6.1-sol` / `medium`.

## Límites y punto de entrada de Fase 6

- Un checkpoint completo anterior sin evidencia verificable permite
  consultar `status`, pero `run` bloquea la entrega de un resultado.
- El plugin de ejemplo conserva los pins pendientes. No se modificó el
  `SKILL.md` fijado ni se probó con Pi real.
- **Fase 6 no iniciada.** Para retomarla en otro hilo, leer
  [PLAN.md §6](../PLAN.md#6-fases) y
  [Prueba real (Fase 6)](../README.md#prueba-real-fase-6).
  Modelo previsto: Sonnet 5.5 / medio. La persona usuaria ejecuta Pi.

```text
skillrun — Phase 6 of 6: Prueba real con Pi + grilling original — START HERE handoffs/HANDOFF-2026-11-21-PHASE-5.md
```
