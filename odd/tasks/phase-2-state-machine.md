# Phase 2 state machine

Branch `feat/phase-2-state-machine` from `e636858`. Verification uses `uv run pytest` and `make lint`.
Delivery is local. The approved product contract is in [PLAN.md §5.9](../../PLAN.md#59-contrato-aprobado-de-la-fase-2).

## Specs

- S1. “Run completo con host falso; tests de crash en cada etapa” per PLAN.md §6. The accepted interfaces and recovery rules are in §5.9.
- S2. “TESTER escribe los tests primero (deben fallar: RED)” and then runs the full suite per PLAN.md §10.
- S3. “Nada que escriba en GitHub” and “chequeo «Listo cuando» → espera confirmación” per PLAN.md §§9–10.

## Tasks

- [x] T1 · S1–S2 · delegated tester · `tests/fake_host.py`, `tests/test_state.py`, and `tests/test_engine.py` · 39 expected failures reproduced on the unchanged implementation at `e636858`.
- [x] T2 · S1 · delegated worker · persistence, locking, trace checks, and state validation in `src/skillrun.py` · isolated storage probe passed; parent confirmed Ruff and strict mypy for source.
- [x] T3 · S1 · delegated worker and inline integration · engine, receipts, result extraction, and reconciliation · 40 focused tests passed after two scoped repairs.
- [x] T4 · S1–S2 · delegated tester · real process crash probes passed; all four findings closed by an independent recheck (9 tests and native ACL probe).
- [x] T5 · S1–S3 · inline integration and phase closure · `d96cf81` implementation and `f7895b1` scoped correction verified and natively reviewed. Phase closure is recorded in [the Phase 2 handoff](../../handoffs/HANDOFF-2026-11-20-PHASE-2.md).

## Log

- L1. “fase 2”
- L2. “continua el trabajo del agente anterior”
- The prior thread records “OK, arrancá” on the exact contract and five tasks. The worktree was clean at `e636858` before the contract and log were written. T1 is first.
- T1 dispatched to the independent TESTER with Codex `gpt-6.2-sol` at `xhigh`. The tester has only the test edit surface and must demonstrate RED before any production write.
- T1 reported 39 expected failures. Parent reproduced all 39 with `PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -o addopts='' -q -p no:cacheprovider tests/test_state.py tests/test_engine.py --tb=no` (exit 1) and verified a clean source diff. T2 uses a persistence-only probe before T3 connects the engine to the public test seam.
- T2 reported an external-storage smoke covering lock contention, revision, modes, trace binding, symlinks, and pre-replace `fsync` failure. Parent read the scoped diff and reproduced passing Ruff and strict mypy. The full Phase 2 tests await the T3 entry points. Risk items 2 and 4 apply to storage and locking.
- T3 reported 39 focused tests passing; parent reproduced all 39. Two integration gaps were then pinned with 8 failing cases: invalid settled evidence left the run settled, and a host close failure reported blocked after storing complete. The engine now persists both failures as blocked and closes the host before storing complete. Parent observed 40 focused tests, Ruff lint and format, strict mypy, and `git diff --check` passing on the integrated code.
- T4 was dispatched to the independent TESTER. Parent ran the full suite (200 passed), `make lint` (passed), and compared five `validate` invocations against `e636858` (matching stdout, stderr, and exit codes). The module is 985 lines. The native read-only assessment requested a declared untracked inventory; native review waits for the final candidate and independent verification.
- T4 independently observed 200 passing tests and clean lint. Process probes proved nonblocking contention and no host or console activity after abrupt exit in `prepared` and `accepted`. T4 blocked closure on unsafe `traces/` directories returning an ephemeral block, interrupted teardown leaving a replayable `done`, and inherited macOS ACLs granting access beyond mode bits. It also reproduced the `fcntl` import failure for `validate` under simulated non-POSIX conditions.
- Parent reproduced five failing cases, then moved trace directory checks to the evidence boundary, closed the live host before the final `done`, rejected extended macOS ACLs through open descriptors before writing, and made POSIX storage primitives lazy. All five cases passed, followed by 205 total tests, `make lint`, `git diff --check`, and reruns of both process-level probes. The module is 1026 lines. T4 recheck is limited to the reported findings.
- Independent T4 recheck passed all 9 cases and the macOS descriptor ACL probe. Parent reran the full suite (205 passed), `make lint`, and `git diff --check`. Functional closure criteria are met, with phase closure and handoff awaiting user confirmation. Changes form one local work unit because the external behavior and tests require the persistence and engine pieces together.
- The user granted native review of `d96cf81`. Four lenses identified one cause: the traversal rejected aliases above the managed state root, including standard macOS paths. `f7895b1` resolves those ancestors before the descriptor walk and still refuses symlinks at the managed root and below. Two failing tests became green; 208 tests, `make lint`, and an actual `/tmp` probe passed. `run` and `reconcile` used the same physical lock through the alias.
- The scoped correction changed 54 lines within the 200-line forecast. The native targeted validation approved the corrected candidate, and Gentle AI confirmed consumption of the approval. The advisory about `fcntl` at POSIX test collection remains open for later work. The production `validate` entry point passed the no-`fcntl` simulation.
- L3. “Sí, cerrá la Fase 2 y generá el handoff.” The user confirmed closure on 2026-11-20. PLAN.md, the handoff, and the affected agent documentation were updated.
