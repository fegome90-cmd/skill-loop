## Resumen

<!-- Qué cambia, por qué y qué queda fuera del alcance. -->

## Verificación

Marcá lo que corriste y anotá el resultado, no solo el tilde. Si un comando no
existe en la base de este PR, indicá qué verificación hiciste en su lugar.

- [ ] `uv sync`
- [ ] `make lint`
- [ ] `uv run pytest`
- [ ] Si toca el validador: `uv run skillrun validate tests/fixtures/plugins/complete.json`
- [ ] `./scripts/check-secrets.sh staged` (si `gitleaks` está disponible)

## Procedencia

- [ ] Sin secretos, credenciales ni rutas absolutas de la máquina local.
- [ ] Sin skills vendorizadas nuevas sin commit/tag, SHA-256 y licencia.
- [ ] Si cambia una superficie de contrato, se actualizó su documentación.

## Límites

<!-- Qué no se pudo verificar y por qué. -->
