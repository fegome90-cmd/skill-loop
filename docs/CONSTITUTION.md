# Constitución de referencia

## Procedencia

Este repositorio **no es la fuente de verdad** de la Constitución de Código
Agéntico. La fuente canónica es
[`fegome90-cmd/constitucion-ai`](https://github.com/fegome90-cmd/constitucion-ai).

El snapshot local existe únicamente para referencia determinista y offline:

| Dato | Valor |
|---|---|
| Versión | v1.1 |
| Commit de origen | `13df6421f8b42bdd602aa45bdf3e024ed7ccadf8` |
| Archivo de origen | `constitution/AGENTIC-CONSTITUTION.md` |
| Snapshot local | `docs/constitution/AGENTIC-CONSTITUTION.md` |
| SHA-256 | `ff201d735c94cb5007651d8f3dcbd8403b1fe0a257dff63fa142c40ff3a65834` |
| Lock | `docs/constitution/SOURCE.lock` |

**Precedencia:** si el snapshot local y el upstream difieren, prevalece el
upstream.

## Estado

El snapshot se conserva como referencia. En `v0.1.0` no hay mapeo de fases,
gates, registro de skills ni enforcement implementado.

## Actualización

1. Actualizar el checkout canónico.
2. Copiar el archivo sin modificarlo.
3. Recalcular el SHA-256.
4. Actualizar `SOURCE.lock` y este documento en el mismo commit.
