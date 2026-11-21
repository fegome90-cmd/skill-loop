# Handoff — Fase 6: prueba real con Pi + grilling original

Fecha: 2026-11-21. Rama local: `feat/phase-4-grilling`. Estado: **ejecutada,
pendiente de confirmación**. Nada está commiteado.

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

Pi corre con `--tools read,grep,find,ls` (sin bash ni red). El primer intento
(`fase6-real-1`, skill basada en `gh`) completó con exit 0 pero con
`evidence: []`: la skill pedía una herramienta que Pi no tiene. Se reescribió
para leer un checkout local.

## Evidencia

| Run | Resultado |
| --- | --- |
| `fase6-real-1` | `complete`, exit 0, `evidence` vacía (skill con `gh`) |
| `fase6-real-2` | `complete`, exit 0, 8 entradas de `evidence` con rutas |

`fase6-real-2` (Pi 1.6.0, `--cwd` = clon superficial de
`fegome90-cmd/skill-loop`) dejó en `~/.local/state/skillrun/fase6-real-2/`:
`state.json` (revisión 19), `traces/github-knowledge-1-1.json`, sesión de Pi y
copias de las skills. `status` informa `complete`, `reconcilable: false`.
Suite completa verde.

## Límites

- El grilling se respondió con stdin guionado (una respuesta, `:listo`, `s`),
  no con una conversación humana.
- El clon era del estado remoto (Fase 1), no de este worktree.
- No se verificó que el agente *siguió* la skill (fuera de alcance, PLAN §8).
- Tokens: no medidos. `make lint` no se ejecutó tras estos cambios.
- La skill `github-project` es de autoría propia y debe revisarla la persona
  usuaria.
