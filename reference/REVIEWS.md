# Revisiones de los prototipos (2026-11-19/20)

Resumen de hallazgos de la revisión previa. **[R]** = reproducido; **[L]** = deducido de lectura.
Usar como lista de comprobación; el detalle está en PLAN.md §4.

## flow.py (Skill Flow v0.2 — idéntico dentro de skill-flow-product-v0.2.zip)
- [R] `event_refs` crece sin límite: con rondas de 128 preguntas el run se bloquea en la 4.ª ronda (`host event references limit reached`), sin recuperación.
- [R] `round` en paso `reference` → `KeyError: 'interaction'` (se lee el campo antes de validar fase).
- [R] Exit 3 significa a la vez "no listo" y "BLOCKED".
- [L] `read_state` no valida coherencia interna (`ui` null tras probe, `batch ⊆ pending`).
- [L] Estado sin integridad propia; `reference_map` fuera del digest; lock huérfano tras SIGKILL; sin fsync de directorio.
- [L] Arquitectura: SKILL.md lo lee el mismo agente que ejecuta flow.py → puede fabricar eventos. No hay frontera de confianza real.
- [L] `source.ref` no validado; `grilling` sin pin en plugin.json.

## jit-gateway-v0.1.2
- [R] **Grave:** adaptador Codex reutiliza `01-result.txt` de otro run (nombres por índice, no se borra antes) → run B `COMPLETE` con resultados de run A.
- [R] Exit 0 al relanzar sobre un run ya `BLOCKED` (status anidado en `state`).
- [L] Trazas Pi/Codex se sobrescriben entre runs con el mismo `--host-dir`.
- [L] `receipt_id` `pi-rpc-step-{n}` se reinicia por proceso → no reanudable.
- [L] `grilling.workflow.json` nunca completa con adaptadores reales (nadie emite `confirmation_event_id`).
- [L] Prompt Pi afirma "synthetic read-only repository" siempre.
- [L] TOCTOU hash vs lectura de Pi; frontmatter exige `name:` en la primera línea; stderr sin tope; `verify_receipts` cuenta mal.
- Bueno: el controlador lanza al agente → frontera de confianza real; cierre de turno Pi estricto.

## github-gateway-loop-v0.3
- [L] Falta el motor de estados: las garantías críticas (no `done` sin confirmación) dependen de él; el loop solo exige `skill_invoked`.
- [L] Timeout de un turno Pi (120 s) → `RECONCILE_UNATTESTED` permanente, sin comando de reconciliación.
- [L] `--deadline` global incluye el tiempo humano.
- [L] Pi falso nunca emite tool calls / `toolResult`; la reconciliación exige exactamente 1 mensaje `user`.
- [L] TOCTOU del blob (verificado una vez, cacheado); sin `--matt-skill-path` Pi carga skills personales.
- [L] stdout mezcla texto de Matt y JSON final; blob de grilling fijado en el código.
- Bueno: cierre de turno + rama activa, recibos y no-reenvío, flock/O_NOFOLLOW/fsync, códigos de salida distintos. 47/47 tests verdes.
