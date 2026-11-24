# Handoff — Fase 4: Grilling en consola y pasos posteriores

Fecha: 2026-11-21. Rama local: `feat/phase-4-grilling`, sobre `3366281`.
Estado: **cerrada** por confirmación de la persona usuaria. Cambios locales
sin commit ni push.

## Entrega

- `run_plugin()` abre el grilling, muestra las respuestas del agente, recibe
  las de la persona y, con `:listo`, solicita una síntesis JSON. Solo avanza
  a los pasos siguientes tras una confirmación positiva. Usa la misma sesión
  del host para todos los pasos. El contrato vigente está en
  [PLAN.md](../PLAN.md) §§5.3–5.4 y §5.11.
- `TerminalConsole` lee de stdin y envía el texto del agente, los avisos y
  las preguntas a stderr. La Fase 4 no agrega subcomandos.
- Los recibos y las trazas identifican cada turno. Al relanzar en
  `awaiting`, el motor verifica y vuelve a mostrar la última respuesta;
  no reenvía el turno. Los recibos guardan el SHA de las respuestas humanas.
  Una traza privada puede contener una cita de la persona si el agente la
  incluyó en su texto (D10). Se conservan las trazas del último paso para
  el resultado final de la Fase 5 (D11).
- El snapshot SHA-256 incluye el árbol del workspace, incluido `.git`, sin
  seguir symlinks. Se compara antes y después de cada turno y al recuperar
  uno en vuelo. Si cambió o no se puede calcular, el bloqueo es definitivo:
  no se ofrece reintento mediante `reconcile()`.

## Verificación y revisión

| Comprobación | Resultado |
| --- | --- |
| RED independiente sobre la base de Fase 3 | 335 casos: 221 pasaron y 114 fallaron como se esperaba; 55 casos eran nuevos |
| Criterio de Fase 4 | El flujo grilling → confirmación → pasos posteriores pasó en una sesión con `PiHost` y Pi falso, sin salida a stdout |
| T6 | Siete sondas reproducidas: cinco defectos corregidos y dos casos resueltos por las decisiones D10/D11 |
| Revisión de cuatro lentes | Corregido el reintento tras una caída con cambios en el workspace. Dos regresiones fijan la diferencia entre workspace modificado e intacto. La sospecha de TOCTOU no se reprodujo |
| Suite final | 342 pruebas aprobadas; ninguna usa Pi real |
| Calidad | `make lint` y `git diff --check HEAD` con código `0`; el lint se ejecutó en copia aislada porque el hook de Markdown puede editar archivos |

Desde la raíz del repositorio:

```sh
uv run pytest
uv run pytest tests/test_grilling.py tests/test_workspace.py tests/test_terminal_console.py tests/test_phase4_review.py tests/test_pi_host.py
make lint
git diff --check HEAD
```

La corrida completa es la evidencia del cierre. El comando de pruebas
específicas sirve para revalidar el alcance de la fase.

## Roles y archivos

| Rol | Trabajo | Tokens |
| --- | --- | --- |
| Orquestación | Opus 5.5 / medio: contrato, integración y correcciones de T6 y de la revisión | no medido |
| WORKER | Codex `gpt-6.2-sol` / `high`: motor, snapshots y consola | no medido |
| TESTER y revisión | Codex `gpt-6.2-sol` / `xhigh`: RED, T6 y revisión de cuatro lentes | no medido |
| Cierre documental | Codex `gpt-6.2-sol` / `xhigh`: contrastó los chats, completó los documentos y revalidó el candidato | no medido |

Implementación: [src/skillrun.py](../src/skillrun.py). Pruebas de
[grilling](../tests/test_grilling.py), [workspace](../tests/test_workspace.py),
[consola](../tests/test_terminal_console.py) y
[regresiones](../tests/test_phase4_review.py). La prueba de sesión compartida
está en [tests/test_pi_host.py](../tests/test_pi_host.py). Decisiones y
correcciones: [registro de Fase 4](../odd/tasks/phase-4-grilling.md).

## Límites conocidos

- Los recibos anteriores a la Fase 4 son incompatibles con el formato nuevo.
  El motor los bloquea al cargar; no los migra.
- Una edición humana entre la caída de un turno y el relanzamiento también
  cambia el digest y bloquea el reintento. El snapshot detecta diferencias,
  no atribuye su autoría.
- La revisión señaló dos brechas de cobertura: poda de trazas al cambiar de
  paso y exclusión de la espera humana del timeout del agente. No se
  revalidaron en el cierre documental.
- Tres `SKILL.md` fijados en fixtures ya causaban `MD041` en la base. Se
  excluyó `tests/fixtures/**` de Markdownlint sin modificar sus pins.
- El módulo tiene 1919 líneas. La evidencia de ejecución es de macOS con
  hosts falsos; Pi real se verifica en la Fase 6.
- Los dos intentos de cierre delegado no editaron archivos porque el ancla
  vigente solo autorizaba la implementación. El cierre se hizo en el hilo
  principal tras autorizar el alcance documental.

## Dónde empieza la Fase 5

Leer [PLAN.md](../PLAN.md) §§5.7 y 5.11, luego conectar `run`, `status` y
`reconcile` al motor, y documentar el contrato de la CLI y su skill de entrada.
`run` debe pasar el mismo workspace al supervisor y a `PiHost`; la salida
JSON final debe quedar separada de la consola. La Fase 5 continúa con
OpenAI Codex; el modelo y el esfuerzo están en [PLAN.md §6](../PLAN.md#6-fases).
Esta fase no se inició.

Para un nuevo hilo, usar la ruta absoluta de este archivo en lugar de la
ruta relativa del ejemplo:

```text
skillrun — Phase 5 of 6: CLI (run/status/reconcile), skill de entrada, README — START HERE handoffs/HANDOFF-2026-11-21-PHASE-4.md
```
