---

name: git-hygiene
description: Use while operating, reconciling, or handing off work that must stay traceable, isolated, and free of workspace residue.
license: MIT
metadata:
  author: felipe gonzalez
  version: "1.0.0"
---

# Git Hygiene

## Purpose

Mantener trazabilidad y aislamiento: una tarea, una rama, un commit acotado,
un árbol limpio.

## Rules

1. No trabajar directo sobre `main`.
2. Rama identificable por tarea; worktree aislado si el riesgo lo exige.
3. Commits convencionales y acotados al alcance declarado.
4. No mezclar tareas ni dejar cambios ajenos en el mismo árbol.
5. Eliminar temporales, logs, dumps y artefactos de debug antes del cierre.
6. Revisar `git status` y `git diff --stat` antes de declarar handoff.

## Checklist

- [ ] Rama correcta y sin trabajo ajeno.
- [ ] Diff coherente con el plan.
- [ ] Sin archivos temporales ni untracked sin propósito.
- [ ] Commit trazable con mensaje convencional.
- [ ] Estado listo para revisión o integración.

## Output

Reportar rama, HEAD, archivos tocados y estado del árbol. Si el árbol no está
limpio, el handoff no está completo.
