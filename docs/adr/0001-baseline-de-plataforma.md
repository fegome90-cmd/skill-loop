# Baseline de plataforma

## Status

accepted

## Contexto

`skill-loop` nace con un único mantenedor y `main` como rama por defecto. La
protección clásica de `main` ya exige pull request, bloquea force-push y borrado,
pero no aplica las restricciones a administradores, no exige resolución de
conversaciones y no tiene un check de seguridad propio. Esas decisiones vivían
fuera del repositorio.

## Decisión

Se adopta un baseline de plataforma compuesto por:

- un ruleset `pr-gate` sobre la rama por defecto, con la regla `pull_request`:
  pull request obligatorio, 0 aprobaciones, resolución de threads obligatoria y
  los tres métodos de merge habilitados. GitHub agrega
  `require_extra_approval_for_unattributed_changes: true`; con 0 aprobaciones no
  tiene efecto;
- la protección clásica de `main` conserva el pull request obligatorio, el
  bloqueo de force-push y borrado, y se actualiza para exigir el check
  `Secrets and private paths` con `strict` y aplicar `enforce_admins`;
- `delete_branch_on_merge` habilitado;
- un workflow `.github/workflows/security.yml` con Gitleaks fijado por versión y
  verificado por SHA-256, más `scripts/check-secrets.sh` y
  `scripts/check-sensitive-paths.py`; los archivos de política se cargan desde
  la rama base, mientras el workflow que los invoca corre desde el head del PR
  (riesgo residual documentado abajo);
- `SECURITY.md` con reporte privado habilitado y alcance;
- plantilla de pull request, sección de colaboración en `README.md` y la licencia
  MIT del árbol del proyecto.

La protección clásica no se reemplaza: el ruleset aísla la regla de pull request
y conversaciones; la protección clásica conserva el check y `enforce_admins`.

## Considered Options

- **Mutar solo la protección clásica**: se descartó porque la API de rama no
  separa "requerir pull request" de revisiones y un `PUT` completo puede borrar
  el check requerido o `enforce_admins`. El ruleset aísla la regla sin reemplazar
  la protección existente.
- **Ruleset con `deletion` y `non_fast_forward`**: se descartó porque la
  protección clásica ya cubre esos bloqueos y duplicarlos agrega superficie.
- **CODEOWNERS con revisión obligatoria de code owners**: se descartó porque, con
  un solo mantenedor y `enforce_admins`, la rama quedaría inmergeable por pull
  request.
- **Merge queue, Dependabot, auto-merge**: fuera de alcance por Anti-Ferrari; no
  hay una necesidad demostrada.
- **Vendorizar la skill de Netresearch**: se descartó porque es una skill de
  operaciones de plataforma; se usó como referencia técnica, no como dependencia.

## Estado previo

La protección clásica previa a este cambio:

```json
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": false,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": false,
  "lock_branch": false,
  "allow_fork_syncing": false
}
```

## Consequences

- El push directo a `main` deja de ser posible: todo cambio entra por pull
  request.
- Los threads de revisión, incluidos los de bots, bloquean el merge hasta
  resolverse.
- El primer pull request usa una política de seguridad fijada por blob y
  SHA-256; los pull requests posteriores usan la política de la rama base. El
  paso queda inerte cuando la base ya contiene la política y se puede eliminar
  en un PR de limpieza.
- **Riesgo residual:** el workflow `security.yml` corre desde el head del PR, así
  que un pull request podría reemplazar el job por un no-op conservando el nombre
  `Secrets and private paths`. La política de archivos está protegida, pero el
  workflow que la invoca no. Mitigación aceptada: revisión explícita del diff de
  `.github/workflows/**` y `scripts/check-*`. Una alternativa futura es mover el
  check a un workflow reutilizable en un repositorio protegido.
- GitHub secret scanning y push protection están activos. El scan propio usa las
  reglas default de Gitleaks y agrega historial, nombres sensibles y hook local;
  se mantiene por el historial y las rutas, que el scanning nativo no recorre,
  no solo por duplicar proveedores.
- El reporte privado de vulnerabilidades está habilitado en la configuración del
  repositorio y verificado por API.
- La licencia MIT del árbol del proyecto cubre el contenido propio; las skills
  vendorizadas conservan su licencia.

## Reversión

1. Quitar el check `Secrets and private paths` de la protección clásica o
   restaurar el payload previo con `PUT /branches/main/protection`, para que el PR
   de reversión no quede bloqueado.
2. `DELETE /repos/fegome90-cmd/skill-loop/rulesets/27720395` para volver al estado
   sin ruleset. Si se prefiere conservar el artefacto, `PUT` con
   `enforcement: disabled`.
3. `PATCH /repos/fegome90-cmd/skill-loop` con
   `{"delete_branch_on_merge": false}`.
4. Revertir los archivos por pull request.
