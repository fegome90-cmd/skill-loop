# skillrun — PLAN.md

Ejecución determinista de N skills en orden, con `grilling` (Matt Pocock) como fase obligatoria de discovery.
Unifica lo mejor de **Skill Flow v0.2**, **JIT Gateway v0.1.2** y **GitHub Gateway Loop v0.3** en una sola app ligera.

---

## 1. Objetivo

Una CLI en Python estándar que **lanza y controla al agente** (Pi primero) y lo obliga a ejecutar las skills de un plugin **en orden, una a una, invocándolas de verdad** (no leyendo solo el frontmatter). La app es la máquina de estados: no hay motor externo ni protocolo IPC.

**No es:** un sandbox de SO, un verificador de calidad semántica, ni una herramienta que escriba en GitHub.

## 2. Decisiones cerradas

| Tema | Decisión |
|---|---|
| Arquitectura | Una app; la máquina de estados vive dentro del loop supervisor |
| Repo | `skill-loop` (base, historia y calidad); producto/CLI/módulo `skillrun` (merge 2026-11-20) |
| Tamaño | 1 archivo principal `src/skillrun.py` (~500 líneas, estimado) + tests |
| Stack | Runtime solo stdlib, Python >=3.12; dev con uv · pytest · ruff · mypy strict · bandit; gates `make lint` + `uv run pytest` |
| Hosts | Pi RPC primero; Claude Code y Codex CLI después, tras la misma interfaz `Host` |
| Discovery | `grilling` directo (no `grill-me` ni `grill-with-docs`), siempre paso 1 |
| Fin de grilling | Regla de la propia skill: todas las ramas resueltas **y** el usuario confirma entendimiento compartido |
| Respuestas humanas | Consola del supervisor (única fuente de respuestas humanas) |
| Sesión | **Una sola sesión Pi por run**; los pasos posteriores continúan en la sesión de grilling |
| Permisos | Solo lectura (`--tools read,grep,find,ls`) + snapshot del checkout antes/después |
| Contexto entre pasos | Cada paso devuelve JSON tipado; sirve como **gate** de avance (el contexto ya va en la sesión) |
| Incertidumbre | Nunca reenviar automáticamente; bloquear + `skillrun reconcile` con aprobación explícita |
| Timeout | Por turno del agente; **no** cuenta el tiempo de respuesta humana |
| Entrada | CLI `skillrun run <plugin.json>` + skill de entrada en `.agents/skills/` que solo pide al usuario lanzar la CLI |
| Límite de pasos | `MAX_STEPS = 16`, tope duro en el módulo |

## 3. Qué se toma de cada prototipo

- **Skill Flow v0.2 (`flow.py`):** plugin JSON declarativo con pasos ordenados; JIT (una instrucción a la vez); `digest` del plugin que invalida el run si cambia; `revision` optimista.
- **JIT Gateway v0.1.2:** skills fijadas por SHA-256; contrato de resultado tipado por paso; interfaz `HostAdapter`; snapshot del workspace; tope de tamaño de contexto.
- **Loop v0.3:** supervisor dueño del proceso Pi; cierre de turno estricto (`message_end` assistant `stop` → `agent_settled(aborted=false)` → coincide con la rama activa de `get_entries`); recibos `prepared/accepted/settled`; no reenviar prompts inciertos; `flock` + `O_NOFOLLOW` + `fsync` + permisos 0600/0700; limpieza de `GH_TOKEN`/`GITHUB_TOKEN`/`GH_ENTERPRISE_TOKEN`/`SSH_AUTH_SOCK`; verificación de skill vía `get_commands` + blob fijado; `--no-context-files`, `--no-extensions`, `--no-mcp`, `--no-skills --skill`.

## 4. Errores ya encontrados que NO deben repetirse

1. `event_refs` ilimitados → run inutilizable (Skill Flow). Guardar solo lo del paso activo.
2. Nombres de traza/resultado por índice → evidencia sobrescrita y **resultados de otro run aceptados** (JIT Gateway, Codex). Todo archivo de evidencia lleva `run_id` + `step_id`; borrar salidas antes de cada ejecución.
3. Exit code 0 sobre un run bloqueado (JIT Gateway). Códigos: `0` DONE, `3` NOT_READY, `10` BLOCKED, `130` CANCELLED.
4. `receipt_id` que se reinicia por proceso (JIT Gateway). Derivarlo de `run_id` + `step_id` + intento.
5. Deadline global que incluye el tiempo humano (Loop v0.3). Solo timeout por turno.
6. Timeout de un turno = run muerto sin salida (Loop v0.3). Existe `reconcile`.
7. TOCTOU sobre la skill (Loop v0.3, JIT Gateway). Copiar cada `SKILL.md` fijado al directorio privado del run, verificar la copia y pasar **esa copia** a Pi.
8. Sin `--no-skills`, Pi carga skills personales (Loop v0.3). Siempre `--no-skills` + `--skill` explícitos.
9. stdout mezcla texto humano y JSON (Loop v0.3). Texto del agente → stderr/consola; JSON final → stdout.
10. Pi falso sin turnos con herramientas (Loop v0.3). El fake debe emitir `tool_execution_*` y entradas `toolResult`.
11. Errores de programación (`KeyError`) que salen como mensajes crípticos (Skill Flow). Validar fase antes de leer campos; separar `INTERNAL` de `BLOCKED`.

## 5. Diseño

### 5.1 Plugin (`plugin.json`)

```json
{
  "schema": "skillrun/v1",
  "id": "github-gateway",
  "description": "Discovery con grilling y luego conocimiento GitHub",
  "skills": {
    "grilling": {"path": "skills/grilling/SKILL.md", "git_blob": "d2f09a18e6a6c65c55f1271ba08dfeaf06f0bed3"},
    "github-project": {"path": "skills/github-project/SKILL.md", "sha256": "<64 hex>"}
  },
  "steps": [
    {"id": "discovery", "skill": "grilling", "kind": "grilling",
     "result": {"summary": "string", "decisions": "array", "open_questions": "array"}},
    {"id": "github-knowledge", "skill": "github-project", "kind": "skill",
     "instruction": "Usa las decisiones confirmadas para diagnosticar el repo. Solo lectura.",
     "result": {"diagnosis": "string", "evidence": "array"}}
  ],
  "on_done": {"directive": "Presenta el diagnóstico. No modifiques GitHub."}
}
```

- `kind: grilling` solo puede ir en `steps[0]` y es obligatorio.
- Tipos de resultado: `string`, `array`, `object`, `integer`, `boolean` (comparación de tipo exacta).
- Cada skill fijada por `sha256` o `git_blob` (para poder fijar upstream de GitHub).

### 5.2 Máquina de estados (interna)

Por paso: `ready → prepared → accepted → settled → done`; además `blocked` y `complete`.

Desde la Fase 4, grilling puede volver a `awaiting` entre turnos. Ver §5.11
para el contrato vigente por turno y sus reglas de recuperación.

- **prepared:** recibo persistido *antes* de enviar el prompt (guarda cursor `leafId`, SHA del prompt).
- **accepted:** Pi respondió `disposition=started`.
- **settled:** se observó `stop` + `agent_settled(aborted=false)` + coincidencia con la rama activa; guarda SHA de la respuesta.
- **done:** el resultado JSON cumple el contrato (y, en grilling, el usuario confirmó).
- Fallo en cualquier punto → `blocked` con motivo. Nunca reintento automático.

### 5.3 Fase grilling

1. Enviar `/skill:grilling <goal>`.
2. Mostrar cada respuesta del agente en consola; el usuario responde; repetir (rondas libres, Matt es dueño del árbol).
3. El usuario escribe `:listo` → la app pide a la skill su síntesis de entendimiento compartido en un bloque ```json que cumpla el contrato del paso.
4. La app muestra la síntesis y pregunta `¿Confirmas? [s/n]`. `n` → vuelve a rondas. `s` → recibo `done` con el ID del evento de confirmación de consola.
5. El recibo guarda solo el SHA de la respuesta humana; el texto enviado
   queda en el historial de Pi. Para citas del agente y retención de trazas,
   ver el contrato aprobado de la Fase 4 (§5.11).

### 5.4 Pasos posteriores

- Misma sesión: `/skill:<nombre> <instruction + contrato de resultado>`.
- El resultado es el **último bloque ```json** del mensaje final del asistente; debe cumplir el contrato.
- Snapshot del checkout antes/después: cualquier cambio → `blocked`.

### 5.5 Interfaz `Host`

```python
class Host(Protocol):
    def start(self, skills: dict[str, Path]) -> None: ...  # lanza sesión con skills fijadas
    def verify_skills(self, expected: dict[str, str]) -> None: ...
    def prompt(
        self, text: str, on_prepared, on_accepted
    ) -> str: ...  # devuelve texto final verificado
    def reconcile(self, cursor: str | None) -> str: ...  # lee historial, nunca reenvía
    def close(self) -> None: ...
```

### 5.6 Archivos del run (fuera del workspace, 0700)

```
~/.local/state/skillrun/<run_id>/
  state.json   lock   skills/<copias fijadas>   pi-session/   traces/<step_id>-<intento>-<turn>.json
```

### 5.7 CLI

La Fase 5 conecta estos subcomandos al motor. Para los campos de salida,
los códigos y la recuperación, ver el [contrato de la CLI](README.md#cli).

- `skillrun run <plugin.json> --goal "..." --cwd <repo> --run-id <id>`
- `skillrun status --run-id <id>`
- `skillrun reconcile --run-id <id>` → muestra evidencia del paso incierto y pide `reintentar / abandonar` explícito.
- `skillrun validate <plugin.json>`

### 5.8 Decisiones de la Fase 1 (grilling 2026-11-20)

- `validate` revisa solo esquema + formato de pins; no abre `SKILL.md` (eso es run/Fase 3).
- Rechaza claves desconocidas en todo nivel, claves JSON duplicadas y skills declaradas sin usar. Sin tope de tamaño.
- Obligatorios: `schema`, `id`, `skills`, `steps`; por paso `id`, `skill`, `kind`, `result`. `instruction` obligatoria en `kind: skill`, opcional en `grilling`. `description` y `on_done` opcionales (`on_done.directive` no vacío).
- Pin: exactamente uno de `sha256` (64 hex minúscula) o `git_blob` (40 hex minúscula). `steps[0].skill` debe ser `grilling` (§5.3 invoca `/skill:grilling`). `path` sin NUL. `path` relativo al directorio del plugin; se rechazan absolutos, `..`, vacíos y `\`.
- Errores: todos, en orden determinista, con ruta JSON (`steps[1].skill: …`).
- Exit: `0` válido · `10` inválido (BLOCKED) · `70` INTERNAL · `2` uso. stdout solo JSON `{ok, plugin_id, digest}` / `{ok: false, errors}`; texto humano a stderr.
- `plugin_digest()`: SHA-256 del JSON canónico. `check_result()`: claves exactas y tipo exacto (`bool` ≠ `integer`).
- Pin de `grilling` (`d2f09a18…` aquí vs `8ca78c6d…` vendorizado v1.3): resuelto en la Fase 6, se fija el original.

### 5.9 Contrato aprobado de la Fase 2

- `run_plugin(plugin, *, goal, run_id, host, console, state_root=None)` devuelve
  `RunOutcome(status, exit_code, step_id, reason)`. Códigos: `0` complete,
  `3` lock ocupado, `10` blocked, `70` INTERNAL, `130` abandonado o Ctrl-C.
- `Host` expone `start(skills)`, `verify_skills(expected)`,
  `prompt(text, on_prepared, on_accepted) -> Turn(text, leaf_id)` y `close()`.
  `on_prepared(cursor)` persiste el recibo antes del envío. `on_accepted()`
  registra su aceptación. El host comunica fallos mediante `HostError`.
- `Console.confirm(step_id, result) -> (bool, event_id)`. Grilling requiere
  confirmación positiva y registra `event_id` en `done`. En esta fase el
  rechazo bloquea el paso. El resultado es el último bloque JSON y se valida
  con `check_result()` antes de avanzar.
- `state_root` usa `$XDG_STATE_HOME/skillrun` o `~/.local/state/skillrun` salvo
  que se inyecte otra raíz. Cada run vive en `<state_root>/<run_id>/`, con
  directorios `0700`, archivos `0600` y `flock` exclusivo no bloqueante.
  Se resuelven alias por encima de `state_root`. La raíz y las rutas internas
  del run se abren sin seguir symlinks.
  `state.json` se valida antes de usar sus campos. Se guarda con un temporal
  exclusivo `O_EXCL|O_NOFOLLOW`, `fsync`, reemplazo atómico y `fsync` del
  directorio. La revisión sube en cada escritura.
- El recibo se identifica como `<run_id>/<step_id>/<intento>`. `prepared`
  guarda cursor y SHA del prompt. La traza del intento se limpia antes de
  iniciarlo. `traces/<step_id>-<intento>.json` guarda `run_id`, `step_id`,
  `receipt_id`, texto de respuesta y su SHA. `settled` guarda la referencia
  y el SHA de la respuesta. Las referencias de eventos se limitan al paso activo.
- Al relanzar, un digest del plugin o un SHA del objetivo distinto bloquea el
  run sin modificar su estado. `complete` retorna `0` sin iniciar el host y
  `blocked` retorna `10`. `prepared` y `accepted` interrumpidos se bloquean
  como inciertos sin reenviar. `settled` permite terminar el paso desde su
  traza, validando identidad, intento y SHA, sin invocar al host para ese turno.
- `reconcile(run_dir, step_id, decision, approver)` exige una aprobación
  explícita con `approver`. Sobre un paso bloqueado incierto, `retry` suma un
  intento y deja el paso `ready`. `abandon` deja el run `cancelled`. La
  reconciliación del motor no envía prompts.
- El host falso vive en `tests/`. Pi RPC y la copia de skills fijadas son de
  la Fase 3. Las rondas de grilling y el snapshot del checkout son de la
  Fase 4. Los comandos `run`, `status` y `reconcile` son de la Fase 5.

### 5.10 Contrato aprobado de la Fase 3

- `run_plugin()` posee los pins y el directorio privado. Bajo el lock del run y
  antes de `Host.start()`, lee cada `SKILL.md` original con
  `read_skill_bytes()` (sin seguir symlinks), verifica el pin (`sha256` o
  `git_blob`), escribe la copia en `<run_dir>/skills/<nombre>/SKILL.md`
  (`0700`/`0600`, atómica, `fsync`), la relee y vuelve a verificar el
  original. Un fallo devuelve `blocked` (`10`) sin llamar al host, sin
  subprocesos y sin cambiar el estado persistido. `Host.start()` recibe las
  copias. La firma de `Host` no cambia.
- `PiHost(cwd, session_dir, session_id, command, turn_timeout,
  command_timeout)` implementa `Host` sobre `pi --mode rpc` con
  `--session-dir`/`--session-id` (nunca la última sesión), `--tools
  read,grep,find,ls`, `--no-context-files --no-extensions --no-mcp
  --no-skills --no-prompt-templates` y un `--skill` por copia. Quita
  `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN`
  y `SSH_AUTH_SOCK` del entorno. El directorio de sesión debe ser propio,
  `0700` y sin ACL extendida.
- `verify_skills()` relee las copias y exige por `get_commands` exactamente
  `skill:<nombre>` con `sourceInfo.path` igual a la copia.
- Transporte JSONL estricto: separación solo por LF, UTF-8 y objeto JSON.
  Respuesta sin id pendiente, `extension_ui_request`, bytes truncados al EOF o
  stdout abierto tras la salida de Pi son errores fatales.
- Turno: cursor `leafId` → `on_prepared` → `prompt` (una sola vez) →
  `on_accepted` solo con `disposition=started` → `agent_settled(aborted=false)`
  y último `message_end` del asistente con `stop` → la cadena `parentId` desde
  `leafId` llega al cursor con un único mensaje `user` y el mismo contenido.
  Timeout por turno. Todo fallo recoge al hijo y deja la instancia inutilizable.
- `history(cursor)` solo envía `get_entries` y no acredita un `agent_settled`.
  `close()` escala stdin → SIGTERM → SIGKILL y falla si hubo salida forzada,
  código distinto de cero o un error de protocolo registrado.
- Detalle y evidencia: [registro de Fase 3](odd/tasks/phase-3-pi-rpc.md).

### 5.11 Contrato aprobado de la Fase 4 (grilling 2026-11-21)

- `run_plugin()` recibe `workspace: Path` (obligatorio). `Console` suma
  `show`, `notice` y `ask`; `confirm` no cambia. Ctrl-C o EOF de consola →
  `130` sin tocar el estado si no hay turno en vuelo. Un `EOFError` fuera
  de la consola es un error interno (`70`).
- Cada turno del agente tiene número `turn`. Recibo
  `<run_id>/<step_id>/<intento>/<turn>` y traza
  `traces/<step_id>-<intento>-<turn>.json` en todos los pasos. Se conservan
  hasta dos trazas: el último turno mostrado y el actual. Al completar
  el run se retienen las del último paso para la salida de la Fase 5.
  La traza privada guarda el texto del agente, incluidas posibles citas
  de la respuesta humana.
- Grilling: `/skill:grilling <goal>` → mostrar → estado `awaiting` → la
  respuesta humana se envía literal (vacía se vuelve a pedir). El recibo guarda
  solo su SHA-256; el texto del mensaje humano queda en el historial privado
  de la sesión de Pi (véase §5.3.5). `:listo` pide la síntesis JSON con el
  contrato del paso. Síntesis inválida o `n` → vuelve a rondas. `s` → `done`
  con `event_id`. Rondas libres.
- Relanzar en `awaiting` re-muestra la última respuesta verificada y pregunta.
  Si la rama activa de Pi no alcanza ese turno, el motor bloquea el envío
  y conserva el recibo en `awaiting`.
  `reconcile retry` de una ronda o síntesis incierta vuelve a `awaiting`.
- Snapshot SHA-256 del contenido de todo el árbol (incluido `.git`, sin
  exclusiones, symlinks por `readlink`) antes y después de **cada turno**.
  Una raíz symlink se rechaza antes de iniciar el host; un archivo especial
  o ilegible bloquea antes del envío. Si falla un turno en vuelo o el
  relanzamiento encuentra un recibo `prepared` o `accepted`, se compara el
  workspace con el digest guardado. Un cambio o error de snapshot bloquea
  sin reconciliación; un digest igual conserva la recuperación por incertidumbre.
- `TerminalConsole` (stdlib): texto a stderr, entrada por stdin.
- Detalle: [registro de Fase 4](odd/tasks/phase-4-grilling.md).

## 6. Fases

Formato: una fase por hilo. Tokens = rango aproximado estimado por tamaño de código a escribir/leer (≈ 10–15 k tokens por cada 100 líneas de código+tests, más lectura de referencias).

| # | Fase | Listo cuando | Tokens est. | Real | Modelo / esfuerzo | Estado |
|---|---|---|---|---|---|---|
| 1 | Repo + esquema de plugin | `skillrun validate` acepta/rechaza plugins de ejemplo; tests verdes | 30–50 k | no medido (orquestador, worker y tester) | Opus 5.5 orq. + Codex gpt-6.2-sol (worker high, tester xhigh) | hecho (2026-11-20) |
| 2 | Máquina de estados + recibos + lock | Run completo con host falso; tests de crash en cada etapa | 50–80 k | no medido por rol | Opus 5.5 / medio (arranque), Codex `gpt-6.2-sol` / `xhigh` (orquestación), `high` (WORKER), `xhigh` (TESTER) | hecho (2026-11-20) |
| 3 | Adaptador Pi RPC + Pi falso con tool turns | Tests de cierre de turno, rama activa, TOCTOU, multi-skill | 60–90 k | no medido por rol | Opus 5.5 / medio (orquestación), Codex `gpt-6.2-sol` / `high` (WORKER), `xhigh` (TESTER y revisión nativa) | hecho (2026-11-21) |
| 4 | Fase grilling en consola + pasos posteriores | Flujo grilling→confirmación→paso 2 con fakes | 40–60 k | no medido por rol | Opus 5.5 / medio (orquestación), Codex `gpt-6.2-sol` / `high` (WORKER), `xhigh` (TESTER, verificación y cierre documental) | hecho (2026-11-21) |
| 5 | CLI (`run/status/reconcile`), skill de entrada, README | Comandos documentados y probados | 25–40 k | no medido por rol | OpenAI Codex `gpt-6.2-sol` / `xhigh` (implementación), `gpt-6.1-sol` / `medium` (verificación independiente) | hecho (2026-11-21) |
| 6 | Prueba real con Pi + grilling original | Un run real `discovery → github-knowledge` con evidencia guardada | 20–40 k | no medido | Sonnet 5.5 / medio (preparación y primeras pruebas); corrida aislada ejecutada por la persona usuaria | hecho (2026-11-21) |
| 7 | (Después) Adaptador Claude Code | Por definir | — | — | — | futuro |
| 8 | (Después) Adaptador Codex CLI | Por definir | — | — | — | futuro |

Dependencias: cada fase usa lo construido en las anteriores; la 6 requiere Pi 1.4+ instalado y el `SKILL.md` de grilling fijado.

Último cierre confirmado: [Fase 6](handoffs/HANDOFF-2026-11-21-PHASE-6.md).

## 7. Estructura del repo

```
skill-loop/
  PLAN.md  README.md  CLAUDE.md  AGENTS.md  pyproject.toml  Makefile
  src/skillrun.py                   # app completa
  .agents/skills/skillrun/SKILL.md  # skill de entrada
  .agents/skills/<matt>/            # skills vendorizadas + .agents/skills-lock.json
  plugins/github-gateway/plugin.json
  tests/  fake_pi.py  test_*.py
  reference/REVIEWS.md              # versionado; zips y flow.py ignorados
  handoffs/  prompts/  docs/  tools/
```

## 8. Fuera de alcance (por ahora)

- Aislamiento de SO; el agente aún podría leer credenciales en archivos.
- Pasos con escritura (si llegan: `allowed_writes` + snapshot, como en JIT Gateway).
- Verificar que el agente *siguió* la skill; solo se verifica invocación, cierre de turno y forma del resultado.
- Tipo de paso `reference` (una referencia externa se modela como skill normal).

---

## 9. Prompt para la sesión nueva

Pegar al inicio del primer hilo, en la raíz del repo, con los tres zips en `reference/`:

```text
Proyecto: skillrun. Lee PLAN.md completo antes de nada. No construyas todavía.

Reglas de trabajo:
- Responde en español, breve y directo.
- Trabaja UNA fase por hilo. Si una fase no cabe en un hilo, divídela y actualiza PLAN.md.
- Si algo del plan no está claro o contradice el código de referencia, pregúntame antes de seguir.
- Lee solo los archivos necesarios. En reference/ lee únicamente las partes que la fase requiera
  (sección 3 y 4 de PLAN.md dicen qué buscar); pregunta antes de leer todo.
- Python >=3.12, runtime solo stdlib (dev: uv, pytest, ruff, mypy). Fail-closed. TDD: test primero, luego código.
- Sin subagentes ni trabajo en paralelo salvo que yo lo apruebe explicando el costo.
- Si el mismo arreglo falla dos veces, detente y explica causa e intentos.
- Distingue lo que verificaste de lo que supones.

Al terminar la fase:
1. Muestra el chequeo "Listo cuando" y espera mi confirmación.
2. Registra en PLAN.md los tokens reales ("no medido" si no puedes, sin adivinar) y el estado.
3. Escribe handoffs/HANDOFF-<AAAA-MM-DD>-PHASE-<n>.md: qué se construyó, decisiones,
   archivos tocados, cómo ejecutarlo, fallas conocidas, dónde parte la siguiente fase.
4. Actualiza CLAUDE.md / AGENTS.md si cambió algo relevante.
5. DETENTE sin empezar la siguiente fase. Indica a qué modelo cambiar y dame, en su propio bloque:
   skillrun — Phase <n+1> of 6: <nombre> — START HERE <ruta completa al handoff>

Empieza: confirma que entendiste el plan, lista tus dudas (si hay) y propone el detalle de la Fase 1.
```

Para hilos siguientes basta la línea `skillrun — Phase <n> of 6: … — START HERE <handoff>`; el hilo lee solo PLAN.md, ese handoff y los archivos que nombre.

---

## 10. Prompt del orquestador

La Fase 5 se ejecutó con Codex; ver el [handoff de Fase 5](handoffs/HANDOFF-2026-11-21-PHASE-5.md).

Para los hilos que usen **Opus 5.5 / esfuerzo medio** como orquestador. Este prompt **autoriza** el esquema de subagentes descrito abajo (reemplaza la regla "sin subagentes" del prompt de la sección 9 solo para estos roles).

```text
Eres el ORQUESTADOR de skillrun (Opus 5.5, esfuerzo medio). Fase actual: <n> — <nombre>.
Lee PLAN.md y, si existe, el handoff indicado. No leas reference/ completo.

Tu rol: planificar la fase, delegar, integrar y decidir. No escribas tú el grueso del código.

Roles autorizados:
- WORKER (Codex gpt-6.2-sol, esfuerzo high): tareas mecánicas y acotadas: escribir un módulo o función con
  especificación cerrada, buscar algo concreto en reference/, fixtures, docs.
  Entrégale: objetivo en una línea, archivos que puede tocar, firma/contrato exacto,
  criterio de aceptación. Nada de decisiones de diseño.
- TESTER (Codex gpt-6.2-sol, esfuerzo xhigh): independiente. Escribe los tests de la fase A PARTIR DE PLAN.md
  y de tu especificación, SIN ver la implementación. Luego ejecuta la suite y evalúa.
  Debe incluir casos negativos y los errores de la sección 4 que apliquen a la fase.
- No delegues lo que puedes resolver en pocos pasos.

Flujo por fase:
1. Descompón la fase en tareas (máx. 6). Para cada una: rol, entrada, salida, criterio.
   Muéstramelo y espera mi OK.
2. TESTER escribe los tests primero (deben fallar: RED).
3. WORKER implementa tarea por tarea. Tú revisas cada entrega contra la especificación
   antes de integrar.
4. TESTER ejecuta la suite completa y reporta (GREEN o fallos con causa).
5. Si una tarea falla dos veces con el mismo enfoque, detente y explícame causa e intentos.
6. Tú validas: código coherente con PLAN.md, sin repetir errores de la sección 4,
   archivo principal sin crecer innecesariamente.

Reglas:
- Español, breve y directo. Distingue lo verificado de lo supuesto.
- Decisiones de rutina las tomas tú; consúltame solo si interpretaciones distintas
  llevan a resultados muy diferentes o si algo contradice PLAN.md.
- Fail-closed, runtime stdlib, Python >=3.12. Nada que escriba en GitHub.
- Registra en PLAN.md los tokens reales por rol si puedes ("no medido" si no).

Cierre de fase (igual que la sección 9): chequeo "Listo cuando" → espera confirmación →
PLAN.md actualizado → handoffs/HANDOFF-<AAAA-MM-DD>-PHASE-<n>.md (incluye qué hizo cada
rol) → CLAUDE.md/AGENTS.md → DETENTE y dame la línea START HERE de la siguiente fase.
```
