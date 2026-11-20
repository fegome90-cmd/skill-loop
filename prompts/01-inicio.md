# Prompt de inicio (primer hilo)

Pegar tal cual en el primer hilo, desde la raíz del repo.

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
