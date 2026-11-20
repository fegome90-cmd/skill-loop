<!-- markdownlint-disable MD041 -->

## Resumen

<!-- Qué cambia, por qué y qué queda fuera del alcance. -->

## Verificación

Marcá lo que corriste y anotá el resultado, no solo el tilde. Si un comando no
existe en la base de este PR, indicá qué verificación hiciste en su lugar.

- [ ] `./scripts/check-secrets.sh staged` (si Gitleaks 8.30.1 está disponible)
- [ ] Si el PR ya incluye el proyecto Python: `uv sync`
- [ ] Si el PR ya incluye el proyecto Python: `make lint`
- [ ] Si el PR ya incluye el proyecto Python: `uv run pytest`
- [ ] Si el PR ya incluye el proyecto Python y toca el validador: `uv run skillrun validate tests/fixtures/plugins/complete.json`
- [ ] Si toca `.github/workflows/**` o `scripts/check-*`: revisión explícita del cambio de seguridad

## Procedencia

- [ ] Sin secretos, credenciales ni rutas absolutas de la máquina local.
- [ ] Skills vendorizadas nuevas: commit/tag o git blob, SHA-256 cuando aplique, y licencia.
- [ ] Si cambia una superficie de contrato, se actualizó su documentación.

## Límites

<!-- Qué no se pudo verificar y por qué. -->
