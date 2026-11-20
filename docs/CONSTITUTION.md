# Constitución operativa de `skill-loop`

## Procedencia

Este repositorio **no es la fuente de verdad** de la Constitución de Código
Agéntico. La fuente canónica es
[`fegome90-cmd/constitucion-ai`](https://github.com/fegome90-cmd/constitucion-ai).

`skill-loop` mantiene un snapshot local únicamente para que la verificación sea
determinista y offline:

| Dato | Valor |
|---|---|
| Versión | v1.1 |
| Commit de origen | `13df6421f8b42bdd602aa45bdf3e024ed7ccadf8` |
| Archivo de origen | `constitution/AGENTIC-CONSTITUTION.md` |
| Snapshot local | `docs/constitution/AGENTIC-CONSTITUTION.md` |
| SHA-256 | `ff201d735c94cb5007651d8f3dcbd8403b1fe0a257dff63fa142c40ff3a65834` |
| Lock | `docs/constitution/SOURCE.lock` |

**Regla de precedencia:** si el snapshot local y el upstream difieren, prevalece
el upstream. El gate `constitution.integrity` está declarado para fallar cerrado
cuando el snapshot no coincide con el lock.

Para actualizar el snapshot:

1. Actualizar el checkout canónico.
2. Copiar el archivo sin modificarlo.
3. Recalcular el SHA-256.
4. Actualizar `SOURCE.lock` y este documento en el mismo commit.

## Qué implementa el kit

El kit queda configurado para hacer operativo el **Anexo I (CLOOP)** y parte del
**Anexo II (enforcement)**. No reemplaza la Constitución: la implementa en el
plano determinista. En `v0.1.0` el mapeo está declarado; su ejecución
corresponde al runner futuro.

```text
Clarify → Layout → Operate → Observe → Reflect → Reconcile → Handoff
```

| Fase | Leyes principales | Gates | Evidencia |
|---|---|---|---|
| Clarify | I.1, I.2, II.1, II.5, VI.1, XII.2, XIII.5 | `constitution.integrity` | `clarification` |
| Layout | I.2, I.3, I.5, III.7, X.1–X.3, XII.4 | `plan.frozen` | `layout` |
| Operate | I.1, I.6, III.1, III.5, IV.2, IV.3, IV.5, VIII.1, VIII.3, VIII.9, X.4 | `scope.compliance` | `operation` |
| Observe | V.1–V.4, V.6, V.8, XI.2, XI.3 | `quality.commands` | `observation` |
| Reflect | III.3, III.5, V.7, XI.6 | — | `reflection` |
| Reconcile | VI.1, VI.3–VI.6, X.5, XI.8 | `docs.reconciled` | `reconciliation` |
| Handoff | IV.4, IV.6, IV.7, X.6, XI.8, XII.5 | `git.clean`, `evidence.chain` | `handoff` |

## Enforcement determinista

| Categoría del Anexo II | Mecanismo configurado |
|---|---|
| Validación automática | `quality.commands`, `scope.compliance`, `git.clean`, `evidence.chain` |
| Revisión humana | `waive --approver`, revisión del diff y del veredicto |
| Evidencia documental | `plan.json`, `state.json`, `evidence.jsonl`, contextos JIT |
| Auditoría posterior | `skill-loop verify` y cadena SHA-256 |

Los gates están declarados en `config/gates.yaml`. El runner todavía no existe:
la tabla describe el contrato, no una funcionalidad disponible.

## Límites explícitos

- El kit **no** aprueba acciones sensibles por sí solo (Ley VIII, Art. 14).
- El kit **no** reemplaza code review ni juicio humano.
- El kit **no** invoca modelos: la selección de skills es determinista.
- El kit **no** escribe fuera del repositorio objetivo.
- Un `waive` registra una excepción; no autentica la identidad del aprobador.
- La mera existencia de un gate no constituye enforcement: recién cuenta cuando
  el runner lo ejecuta y deja evidencia.
