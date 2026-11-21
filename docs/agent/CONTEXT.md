# Contexto del producto

`skillrun` es una CLI en Python estándar que lanza y controla un agente (Pi RPC
primero) y lo obliga a ejecutar las skills de un plugin **en orden, una a una,
invocándolas de verdad**, con `grilling` como paso 1 obligatorio. Vive en el
repositorio `skill-loop`. Fuentes: [PLAN.md](../../PLAN.md),
[README.md](../../README.md), [AGENTS.md](../../AGENTS.md).

## Propósito

Unificar lo mejor de tres prototipos (Skill Flow v0.2, JIT Gateway v0.1.2 y
GitHub Gateway Loop v0.3) en una sola app ligera cuya máquina de estados vive
dentro del loop supervisor. Ver PLAN.md §1–§3.

**No es** un sandbox de SO, ni un verificador de calidad semántica, ni una
herramienta que escriba en GitHub.

## Actores

| Actor | Rol | Fuente |
| --- | --- | --- |
| Persona usuaria | Define el alcance, responde el grilling en consola y autoriza commits | [AGENTS.md](../../AGENTS.md) reglas 3 y 4 |
| Supervisor `skillrun` | Máquina de estados; dueño del proceso del agente | [PLAN.md](../../PLAN.md) §5 |
| Host agente (Pi) | Ejecuta cada skill fijada, solo lectura | [PLAN.md](../../PLAN.md) §5.5 |
| Constitución upstream | Autoridad normativa; el snapshot local solo la refleja | [docs/CONSTITUTION.md](../CONSTITUTION.md) |

## Conceptos

- **Plugin**: `plugin.json` (`schema: skillrun/v1`) con skills fijadas por
  `sha256` o `git_blob` y pasos ordenados con contrato de resultado tipado.
- **Paso `grilling`**: discovery obligatorio en `steps[0]`; termina cuando la
  persona confirma el entendimiento compartido.
- **Contrato de resultado**: claves exactas y tipo exacto (`string`, `array`,
  `object`, `integer`, `boolean`); es el gate de avance.
- **Digest**: SHA-256 del JSON canónico del plugin; invalida un run si cambia.
- **Recibos**: identifican cada turno por run, paso, intento y número. En
  grilling, `awaiting` significa que se espera a la persona, no al agente.
  Un turno incierto nunca se reenvía automáticamente.

## Alcance

Lo verificado está en el [handoff de Fase 4](../../handoffs/HANDOFF-2026-11-21-PHASE-4.md).
El motor ya admite más de un paso en una misma sesión, pero la CLI solo expone
`validate`. Las fases siguientes están en PLAN.md §6.

## Límites

- No inventes comandos `skillrun ...` que la fase actual no haya construido.
- No agregues features no pedidas (regla 4).
- El snapshot constitucional no se edita a mano.

## Evidencia y pendientes

- Fuentes: `PLAN.md`, `README.md`, `AGENTS.md`, `docs/CONSTITUTION.md`.
- Decidido en la Fase 6: el plugin fija el `grilling` original (`d2f09a18…`);
  la copia vendorizada (`8ca78c6d…`) no se modifica.
