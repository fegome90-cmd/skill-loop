# Handoff — Fase 6: prueba real con Pi + grilling original

Fecha: 2026-11-21. Rama local: `feat/phase-4-grilling`. Estado: **cerrada**
por confirmación de la persona usuaria. Este cierre es documental y no
crea commits.

## Entrega

- `plugins/github-gateway/skills/grilling/SKILL.md`: original upstream
  (`mattpocock/skills@5863806d…`), `git hash-object` = `d2f09a18…`, igual al pin.
  La copia vendorizada v1.3 (`8ca78c6d…`) queda intacta.
- `plugins/github-gateway/skills/github-project/SKILL.md`: escrita para este
  proyecto, sha256 `9a602e0d…` fijado en `plugin.json`.
- `plugin.json`: instrucción del paso 2 ajustada a "checkout local".
- Test `test_validate_main_accepts_pinned_github_gateway` reemplaza al que
  exigía el pin pendiente.

## Hallazgo

Pi corre con `--tools read,grep,find,ls` (sin herramientas de shell ni de red). El primer intento
(`fase6-real-1`, skill basada en `gh`) completó con exit 0 pero con
`evidence: []`: la skill pedía una herramienta que Pi no tiene. Se reescribió
para leer un checkout local.

## Evidencia

| Run | Resultado |
| --- | --- |
| `fase6-real-1` | `complete`, exit 0, `evidence` vacía (skill con `gh`) |
| `fase6-real-2` | `complete`, exit 0, 8 entradas de `evidence` con rutas |
| `fase6-real-3` | `blocked`, exit 10, `Workspace changed during agent turn`, `reconcilable: false` (estado informado por la persona usuaria) |
| `fase6-copia-20261121-142500` | `complete`, exit 0, paso `github-knowledge`, 2 referencias en `result.evidence` (JSON aportado por la persona usuaria) |

`fase6-real-2` (Pi 1.6.0, `--cwd` = clon superficial de
`fegome90-cmd/skill-loop`) dejó en `~/.local/state/skillrun/fase6-real-2/`:
`state.json` (revisión 19), `traces/github-knowledge-1-1.json`, sesión de Pi y
copias de las skills. `status` informa `complete`, `reconcilable: false`.
Suite completa verde.

En `fase6-real-3` se usó el worktree compartido. El bloqueo no identifica
qué archivo cambió ni quién lo modificó. La siguiente corrida usó un ID
nuevo, una copia local aislada y el estado y la salida JSON fuera de ella.
Se validó el JSON compartido contra el contrato de `github-knowledge` y
se comprobaron ambas referencias en el checkout actual:
[uso de la CLI](../README.md#cli) y [fases](../PLAN.md#6-fases).
El archivo temporal original y su recibo no se pudieron leer desde el
entorno de verificación.

## Límites

- En `fase6-real-2`, el grilling se respondió con stdin guionado (una
  respuesta, `:listo`, `s`) y el objetivo fue un clon del estado remoto
  (Fase 1), no este worktree.
- No se verificó que el agente *siguió* la skill (fuera de alcance, PLAN §8).
- Tokens: no medidos. En el cierre documental, `make lint` se detuvo por
  `MD041` en las dos skills fijadas del plugin. El mismo fallo se reprodujo
  en `HEAD`; no se modificaron las skills ni sus pins.
- La skill `github-project` es de autoría propia y debe revisarla la persona
  usuaria.
