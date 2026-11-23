# Handoff — Fase 3: Adaptador Pi RPC y Pi falso con tool turns

Fecha: 2026-11-21. Rama local: `feat/phase-3-pi-rpc`, desde `ec042a6`. Estado:
**cerrada** por confirmación de la persona usuaria. Sin push.

## Entrega

- `run_plugin()` copia cada `SKILL.md` fijado al directorio privado del run y
  verifica el pin sobre el original, la copia y de nuevo el original, antes de
  iniciar el host. Un pin incorrecto bloquea con `10`, sin subprocesos ni
  recibo. El contrato vigente está en [PLAN.md](../PLAN.md) §5.10.
- `PiHost` implementa `Host` sobre `pi --mode rpc`. Usa una sesión privada por
  run (`--session-dir` y `--session-id`), herramientas de solo lectura,
  descubrimiento y MCP desactivados. En el cierre de la fase, el lanzamiento
  excluía del entorno heredado `GH_TOKEN`, `GITHUB_TOKEN`,
  `GH_ENTERPRISE_TOKEN` y `SSH_AUTH_SOCK`. La corrección posterior 5D añade
  `GITHUB_ENTERPRISE_TOKEN` al mismo filtro. Este filtro por nombre no es un
  mecanismo de aislamiento de credenciales. El adaptador verifica el
  registro de las skills con `get_commands`.
- Cierre de turno estricto: respuesta `started`, `agent_settled` sin aborto,
  último mensaje del asistente con `stop` y pertenencia del turno a la cadena
  `parentId` desde `leafId` hasta el cursor previo. El prompt se escribe una
  sola vez y todo fallo recoge al hijo.
- `history()` ofrece consulta de solo lectura. `reconcile()` del motor no
  cambia y conserva la aprobación explícita.
- [tests/fake_pi.py](../tests/fake_pi.py) emite turnos con herramientas,
  ramas abandonadas, eventos intercalados y los fallos de transporte.

## Verificación y revisión

| Comprobación | Resultado |
| --- | --- |
| RED independiente | 66 fallos esperados, 208 aprobadas sobre `ec042a6`, reproducido por la orquestación |
| Suite final | 280 pruebas aprobadas, todas con Pi falso como subproceso |
| Calidad | `make lint` y `git diff --check` aprobados |
| Caídas reales | `SIGKILL` del supervisor en `prepared` y `accepted`: el relanzamiento devolvió `10` sin prompts nuevos |
| Verificación independiente | T4 y dos revalidaciones acotadas. Hallazgos corregidos: ACL del directorio de sesión, JSONL inválido al cerrar, drenaje sin límite ante un descendiente que escribe |
| Revisión nativa | Gentle AI, cuatro lentes con Codex. Cuatro BLOCKER con una sola causa (registro truncado al EOF), corrección de 32 líneas, validación aprobada y acuse confirmado |

Ejecución desde la raíz del repositorio:

```sh
uv run pytest
uv run pytest tests/test_pi_host.py tests/test_skill_pins.py
make lint
```

## Roles y archivos

| Rol | Trabajo | Tokens |
| --- | --- | --- |
| Orquestación | Opus 5.5 / medio. Contrato C1–C6, integración, tres correcciones acotadas y cierre | no medido |
| WORKER | Codex `gpt-6.2-sol` `high`. Copias fijadas, `PiHost` y transporte | no medido |
| TESTER | Codex `gpt-6.2-sol` `xhigh`. Pi falso y pruebas antes de la implementación, T4 y revalidaciones | no medido |
| Revisión nativa | Gentle AI con Codex `gpt-6.2-sol` `xhigh`. Cuatro lentes y validación dirigida | no medido |

Producción en [src/skillrun.py](../src/skillrun.py). Pruebas en
[test_pi_host.py](../tests/test_pi_host.py) y
[test_skill_pins.py](../tests/test_skill_pins.py). Fixtures en
`tests/fixtures/engine/`. `RunFiles` en
[fake_host.py](../tests/fake_host.py) ahora materializa `SKILL.md` reales con
sus pins. Decisiones y evidencia por tarea en el
[registro de Fase 3](../odd/tasks/phase-3-pi-rpc.md).

## Límites conocidos

- Ninguna prueba usa Pi real. El protocolo se tomó de la documentación de
  `@earendil-works/pi-coding-agent` 1.6.0 instalada. La Fase 6 lo contrasta.
- Evidencia de ejecución solo en macOS, con primitivas POSIX.
- Si el supervisor muere por `SIGKILL`, un Pi que tarde en salir queda
  huérfano. El relanzamiento igual bloquea sin reenviar.
- `read_skill_bytes()` rechaza un `SKILL.md` que sea symlink. Es más estricto
  que el contrato. Revisarlo si la skill de grilling real es un enlace.
- La identificación del mensaje `user` en la rama compara su contenido con el
  `message_end` del turno, sin asumir el formato de expansión de `/skill:`.
- Un run nuevo no persiste estado hasta que las copias pasan la verificación.
- El módulo único tiene 1580 líneas.
- Desvío de proceso: la primera ronda de la revisión nativa usó subagentes
  Claude. Gentle AI rechazó su captura y se repitió con Codex. Regla vigente:
  todo subagente es Codex.

## Dónde empieza la Fase 4

Implementar las rondas de grilling en consola y los pasos posteriores
(PLAN.md §§5.3, 5.4) sobre `run_plugin()` y `Host`, con `PiHost` y el Pi falso.
Incluye el snapshot del checkout antes y después de cada paso. Leer
[PLAN.md](../PLAN.md) §§5.3–5.4, 5.9–5.10 y este handoff. Modelo indicado en el
plan: Sonnet 5.5 / medio.
