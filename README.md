# skill-loop

> Loop determinista + carga just-in-time de skills, gobernado por la
> [Constitución de Código Agéntico](docs/constitution/AGENTIC-CONSTITUTION.md).

**Estado: v0.1.0 — configuración inicial.** Este repositorio define el contrato:
fases, gates, registro de skills y procedencia constitucional. Todavía **no**
incluye runner ni CLI. La implementación se agrega en la siguiente etapa sin
cambiar este contrato.

## El problema

Un agente con cuarenta skills cargadas gasta contexto, diluye la atención y elige
mal. Cargar todo "por las dudas" no es determinismo: es ruido.

## El modelo

**LOOP** es el [CLOOP del Anexo I](docs/constitution/AGENTIC-CONSTITUTION.md)
de la Constitución:

```text
Clarify → Layout → Operate → Observe → Reflect → Reconcile → Handoff
```

**JIT** (just-in-time) significa que cada fase carga solo las skills que
matchean con la tarea, por señales declarativas y con un orden reproducible. No
se carga el catálogo completo.

Cada fase declara:

- leyes constitucionales aplicables;
- gates de entrada y de salida;
- un tipo de evidencia;
- un cupo máximo de skills.

## Garantías del contrato

1. **Determinismo:** misma tarea + mismos tags/paths + misma configuración +
   mismo snapshot constitucional ⇒ mismo plan y mismo hash.
2. **Fallo cerrado:** un gate bloqueado detiene el loop. No hay `--force`.
3. **Evidencia antes que relato:** plan congelado, gates ejecutados y cadena de
   evidencia SHA-256.
4. **Neutralidad de modelo:** el loop no invoca modelos ni proveedores.
5. **Mínimo privilegio:** las skills declaran capacidades (`read`, `write`,
   `execute`) y el kit no escribe fuera del repositorio objetivo.
6. **No auto-aprobación:** las excepciones requieren un aprobador explícito y
   quedan registradas.

## Estructura

```text
.
├── AGENTS.md                  # reglas para agentes que trabajen en este repo
├── config/
│   ├── loop.yaml              # fases CLOOP, leyes, gates y comandos de calidad
│   ├── gates.yaml             # catálogo de gates y su severidad
│   └── skills.yaml            # registro declarativo de skills (JIT)
├── docs/
│   ├── CONSTITUTION.md        # procedencia, mapeo y límites
│   └── constitution/
│       ├── AGENTIC-CONSTITUTION.md  # snapshot v1.1
│       └── SOURCE.lock        # commit, ruta y SHA-256 de origen
├── skills/
│   ├── evidence-first/SKILL.md
│   ├── git-hygiene/SKILL.md
│   └── python-quality/SKILL.md
├── src/skill_loop/            # paquete Python (scaffold)
└── pyproject.toml
```

## Configuración

### `config/loop.yaml`

Define las siete fases, sus leyes, sus gates y la validación de calidad:

```yaml
phases:
  - id: operate
    title: Operate
    purpose: Ejecutar de forma aislada, con mínimo privilegio y sin expandir alcance.
    laws: [I.1, I.6, III.1, III.5, IV.2, IV.3, IV.5, VIII.1, VIII.3, VIII.9, X.4]
    entry_gates: []
    exit_gates: [scope.compliance]
    evidence_kind: operation
    max_skills: 5
```

### `config/skills.yaml`

Cada skill declara dónde se aplica y qué señales la activan:

```yaml
- id: python-quality
  path: skills/python-quality/SKILL.md
  description: Gates mínimos de Python antes de observar o cerrar.
  phases: [operate, observe]
  tags: [python, quality]
  keywords: [python, pytest, ruff, mypy, lint, test, tipado]
  paths: ["**/*.py", "pyproject.toml"]
  priority: 80
  risk: low
  capabilities: [read, write, execute]
  requires: [python]
  default: false
```

Contrato de selección previsto:

| Señal | Puntaje |
|---|---|
| `tag` explícito | +40 |
| `path` que matchea | +20 |
| `keyword` en la tarea | +15 |
| `default` | +1 |

Se seleccionan las skills con `score >= min_score`, ordenadas por
`(-score, -priority, id)` y recortadas por `max_skills` de la fase.

### `config/gates.yaml`

Catálogo de verificaciones deterministas. La severidad `block` detiene el loop;
`warn` deja rastro pero permite continuar.

| Gate | Verifica | Leyes |
|---|---|---|
| `constitution.integrity` | snapshot == lock SHA-256 | VI.1, XI.2 |
| `plan.frozen` | plan == configuración + snapshot actuales | I.2, I.6 |
| `scope.compliance` | archivos mutados ⊆ alcance declarado | I.1, I.6, IV.7 |
| `quality.commands` | Ruff, mypy y pytest en verde | V.1, V.3, V.4 |
| `git.clean` | árbol limpio al handoff | IV.7, XI.8 |
| `docs.reconciled` | documentación actualizada o ausencia justificada | VI.4, VI.6 |
| `evidence.chain` | cadena de evidencia íntegra | XI.4, XI.5 |

## Constitución

La fuente de verdad es
[`fegome90-cmd/constitucion-ai`](https://github.com/fegome90-cmd/constitucion-ai).
Este repo mantiene un snapshot v1.1 para verificación offline y determinista.

| Dato | Valor |
|---|---|
| Commit | `13df6421f8b42bdd602aa45bdf3e024ed7ccadf8` |
| SHA-256 | `ff201d735c94cb5007651d8f3dcbd8403b1fe0a257dff63fa142c40ff3a65834` |
| Lock | [`docs/constitution/SOURCE.lock`](docs/constitution/SOURCE.lock) |

Actualizar el snapshot exige actualizar el lock y la documentación en el mismo
commit. Ver [`docs/CONSTITUTION.md`](docs/CONSTITUTION.md).

## CLI objetivo (no implementado)

| Comando | Responsabilidad |
|---|---|
| `skill-loop doctor` | validar configuración, snapshot y git |
| `skill-loop plan` | seleccionar skills JIT y calcular `plan_hash` |
| `skill-loop start` | congelar plan y renderizar contextos por fase |
| `skill-loop advance` | cerrar una fase con evidencia y correr gates |
| `skill-loop verify` | auditar plan, cadena, gates y veredicto |
| `skill-loop waive` | registrar excepción con aprobador explícito |

## Roadmap

1. Selector determinista y `plan_hash` canónico.
2. Máquina de estados de 7 fases + evidencia encadenada.
3. Gates de alcance, calidad, git y documentación.
4. CLI `skill-loop` y contextos JIT renderizados.
5. Tests de determinismo, fail-closed y tamper detection.

## Non-goals

- No reemplaza code review ni aprobación humana.
- No ejecuta modelos ni decide semántica por LLM.
- No aprueba acciones sensibles de la Ley VIII, Art. 14.
- No es un gestor de skills: consume un registro declarativo.

## Desarrollo

El stack de calidad se replica de `constitucion-ai`:

| Herramienta | Rol | Configuración |
|---|---|---|
| Ruff | lint + format Python | `pyproject.toml` |
| mypy | typecheck estricto | `pyproject.toml` |
| pytest | tests | `pyproject.toml` |
| Bandit | seguridad | `pyproject.toml` |
| codespell | ortografía | `.codespellrc` |
| yamllint | YAML | `.yamllint.yaml` |
| markdownlint-cli2 | Markdown | `.markdownlint-cli2.jsonc` |
| shellcheck | shell | `.shellcheckrc` |
| pre-commit | orquestación de hooks | `.pre-commit-config.yaml` |

```bash
make install   # uv sync
make lint      # Python + Markdown + YAML, fail-closed
make format    # Ruff + markdownlint con fix
make hooks     # pre-commit install + run --all-files
make check     # alias de lint
```

`make lint` no usa `|| true`: si una herramienta falla, el comando falla.

## Licencia

MIT.
