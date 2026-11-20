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
  los tres métodos de merge habilitados;
- la protección clásica de `main` conserva el pull request obligatorio, el
  bloqueo de force-push y borrado, y se actualiza para exigir el check
  `Secrets and private paths` con `strict` y aplicar `enforce_admins`;
- `delete_branch_on_merge` habilitado;
- un workflow `.github/workflows/security.yml` con Gitleaks fijado por versión y
  verificado por SHA-256, más `scripts/check-secrets.sh` y
  `scripts/check-sensitive-paths.py`; la política se carga desde la rama base
  para que un pull request no pueda sustituirla;
- `SECURITY.md` con reporte privado y alcance;
- plantilla de pull request, sección de colaboración en `README.md` y la licencia
  MIT existente.

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

## Consequences

- El push directo a `main` deja de ser posible: todo cambio entra por pull
  request.
- Los threads de revisión, incluidos los de bots, bloquean el merge hasta
  resolverse.
- El primer pull request usa una política de seguridad fijada por blob y
  SHA-256; los pull requests posteriores usan la política de la rama base.
- La licencia MIT cubre el contenido propio; las skills vendorizadas conservan
  su licencia.
- Reversión: leer el ruleset con `GET`, cambiar `enforcement` a `disabled` y
  enviar el objeto completo con `PUT`; `PATCH` del repositorio con
  `{"delete_branch_on_merge": false}`; restaurar la protección clásica con el
  payload previo, que también requiere `PUT` completo; y revertir los archivos
  por pull request.
