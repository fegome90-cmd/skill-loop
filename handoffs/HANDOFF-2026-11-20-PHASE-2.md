# Handoff — Fase 2: Máquina de estados, recibos y lock

Fecha: 2026-11-20. Rama local: `feat/phase-2-state-machine`. Estado: **cerrada**
por confirmación de la persona usuaria. Implementación `d96cf81`, corrección y
candidato aprobado `f7895b1`.

## Entrega

- `run_plugin()` supervisa un `Host` y una `Console` inyectados. Persiste los
  recibos de cada turno y exige un resultado válido antes de avanzar. El paso
  de `grilling` exige confirmación explícita.
- `reconcile()` registra `retry` o `abandon` para un turno incierto, con
  aprobación explícita. El reenvío requiere una ejecución posterior separada.
- El almacenamiento usa lock exclusivo no bloqueante, escrituras atómicas y
  trazas vinculadas a run, paso, intento y hash de respuesta. El contrato
  vigente está en [PLAN.md](../PLAN.md) §5.9.
- La CLI expone `skillrun validate`. El motor de esta fase se ejercitó con un
  host falso en [tests/fake_host.py](../tests/fake_host.py).

## Verificación y revisión

| Comprobación | Resultado |
| --- | --- |
| RED independiente | 39 fallos esperados antes de editar producción |
| Suite final | 208 pruebas aprobadas sobre `f7895b1` |
| Calidad | `make lint` y `git diff --check` aprobados |
| Caídas reales con host falso | En `prepared` y `accepted`, el relanzamiento devolvió `10` con cero llamadas al host o a la consola |
| Exclusión entre procesos | Contención devolvió `3`. Una prueba real con `/tmp` confirmó que `run` y `reconcile` usan el mismo lock físico |
| Revisión nativa | Cuatro lentes, una corrección de 54 líneas, validación dirigida aprobada y acuse de cierre confirmado por Gentle AI |

Ejecución desde la raíz del repositorio:

```sh
uv run pytest
uv run pytest tests/test_state.py tests/test_engine.py
make lint
uv run skillrun validate tests/fixtures/plugins/complete.json
```

La corrección nativa admite alias por encima de la raíz de estado privada.
Los descriptores de la raíz y de las entradas del run conservan la apertura
sin seguir enlaces. La auditoría previa también verificó los bloqueos por ACL
extendidas en macOS, trazas inseguras e interrupciones durante `host.close()`.

## Roles y archivos

| Rol | Trabajo | Tokens |
| --- | --- | --- |
| Orquestación | Opus 5.5 al inicio. Codex `gpt-6.2-sol` `xhigh` continuó, integró, corrigió hallazgos, verificó y documentó el cierre | no medido |
| WORKER | Codex `gpt-6.2-sol` `high`. Implementó almacenamiento, lock y trazas, luego el motor y la reconciliación | no medido |
| TESTER | Codex `gpt-6.2-sol` `xhigh`. Preparó las pruebas antes de la implementación, auditó el candidato y revalidó los hallazgos | no medido |
| Revisión nativa | Gentle AI. Revisó el candidato desde cuatro lentes y validó la corrección dirigida | no medido |

Implementación en [src/skillrun.py](../src/skillrun.py), pruebas en
[test_state.py](../tests/test_state.py), [test_engine.py](../tests/test_engine.py)
y [test_cli_validate.py](../tests/test_cli_validate.py). Decisiones y evidencia
por tarea en el [registro de Fase 2](../odd/tasks/phase-2-state-machine.md).

## Límites conocidos

- La evidencia de ejecución corresponde a macOS. Las pruebas del motor usan
  primitivas POSIX, incluido `fcntl` en la recolección de `test_state.py`.
  `validate` se verificó en una simulación sin esas primitivas. Queda pendiente
  la ejecución nativa en plataformas sin `fcntl`.
- El módulo único tiene 1034 líneas al cierre, por encima de la estimación
  inicial. El motor, la persistencia y el esquema se ubican en el mismo módulo.

## Dónde empieza la Fase 3

Implementar el adaptador Pi RPC detrás de `Host` y un Pi falso que emita turnos
con herramientas. Leer [PLAN.md](../PLAN.md) §§4, 5.5, 5.6 y 6 junto con este
handoff. Los puntos de entrada son `Host`, `Turn`, `HostError` y `run_plugin()`
en [src/skillrun.py](../src/skillrun.py). Verificar cierre de turno, rama activa,
copia privada de skills fijadas y ejecución de varias skills. Modelo indicado
en el plan para la orquestación: Opus 5.5, esfuerzo medio.
