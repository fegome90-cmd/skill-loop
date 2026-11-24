# Phase 3 Pi RPC adapter

Branch `feat/phase-3-pi-rpc` from `ec042a6`. Verification uses `uv run pytest` and `make lint`.
Delivery is local. Protocol reference: `@earendil-works/pi-coding-agent` 1.6.0 (`docs/rpc.md`,
`rpc-commands.md`, `json.md`, `session-format.md`, `message-types.md`, `cli.md`), verified in the
installed package manifest. No real model calls and no GitHub writes in this phase.

## Specs

- S1. “Tests de cierre de turno, rama activa, TOCTOU, multi-skill” per PLAN.md §6, with the
  errors in PLAN.md §4 items 7–10.
- S2. “TESTER escribe los tests primero (deben fallar: RED)” and then runs the full suite per PLAN.md §10.
- S3. Phase 2 contracts in PLAN.md §5.9 remain valid unless this contract changes them explicitly.

## Approved edge contract

### C1. Pinned private copies (engine, before any subprocess)

- `run_plugin()` owns pins and the private directory. Under the run lock and before `host.start()`,
  for each plugin skill in declaration order, it:
  1. reads the original bytes through module-level `skillrun.read_skill_bytes(path: Path) -> bytes`;
  2. checks them against the pin (`sha256` = SHA-256 of bytes; `git_blob` = SHA-1 of
     `b"blob <len>\0" + bytes`);
  3. writes them to `<run_dir>/skills/<name>/SKILL.md` (directories `0700`, file `0600`, no symlink
     following, atomic replace, `fsync`), then reads the copy back and checks the pin again;
  4. reads the original again through `read_skill_bytes` and checks the pin again (detects a change
     after copying).
- `read_skill_bytes` is called exactly twice per skill per launch (before and after the copy).
- Any mismatch or read failure returns `RunOutcome("blocked", 10, <active step>, reason)` with a
  reason starting `Skill pin mismatch` (or `Skill copy failed` for I/O). The persisted state is not
  changed, and the host receives **no** call (`start`, `verify_skills`, `prompt`, `close`), so zero
  subprocesses are spawned.
- `host.start()` receives `{name: <absolute copy path>}` in plugin declaration order. Then
  `host.verify_skills({name: pin})`. The `Host` protocol signature is unchanged.

### C2. `PiHost` construction and launch

```text
class PiHost:  # implements skillrun.Host
    def __init__(self, *, cwd: Path, session_dir: Path, session_id: str,
                 command: Sequence[str] = ("pi",), turn_timeout: float = 600.0,
                 command_timeout: float = 30.0) -> None: ...
    def start(self, skills: Mapping[str, Path]) -> None: ...
    def verify_skills(self, expected: Mapping[str, str]) -> None: ...
    def prompt(self, text, on_prepared, on_accepted) -> Turn: ...
    def history(self, cursor: str | None) -> PiHistory: ...   # read-only
    def close(self) -> None: ...

@dataclass(frozen=True)
class PiHistory:
    entries: tuple[Mapping[str, object], ...]
    leaf_id: str | None
```

- All expected failures raise `HostError`. After any failure the child is reaped and the instance is
  dead: later `start`/`verify_skills`/`prompt`/`history` raise `HostError` without spawning or
  writing. Calling `prompt`/`verify_skills`/`history` before `start`, or `start` twice, raises
  `HostError` without spawning.
- `session_id` must match `[a-z0-9][a-z0-9-]{0,63}`. `session_dir` is created `0700` if missing;
  an existing one must be a real directory (not a symlink) with no group/other permissions.
- argv = `command` + `--mode rpc --session-dir <session_dir> --session-id <session_id>
  --tools read,grep,find,ls --no-context-files --no-extensions --no-mcp --no-skills
  --no-prompt-templates` + `--skill <copy path>` per skill in mapping order. Never `--no-session`,
  `--session`, `--continue`, `--resume` or `--fork`.
- `cwd` = constructor `cwd`. stdin and stdout are pipes; stdout carries RPC only; stderr is
  inherited and never parsed.
- Environment = parent environment minus `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`,
  `SSH_AUTH_SOCK`. No credential is copied into run storage.
- After spawning, `start` sends `get_state` and requires `success`, `sessionId == session_id`,
  `sessionFile` resolving inside the resolved `session_dir`, and `isStreaming == false`.
  Reopening after a restart uses the same `session_dir` and `session_id`; the adapter never selects
  a “last” session.

### C3. Skill registration (`verify_skills`)

- Re-reads each copy given to `start` and checks it against `expected[name]`.
- Sends `get_commands`. Commands with `source == "skill"` must be exactly `skill:<name>` for each
  expected name, once each, with `sourceInfo.path` resolving to the copy path given to `start`.
  Missing, duplicated, extra, or differently located skill commands raise `HostError`.

### C4. JSONL transport

- Commands are one JSON object plus LF, each with a unique string `id`. Stdout is split on LF only
  (an optional preceding CR is stripped); U+2028/U+2029 inside strings are data.
- Each record must be valid UTF-8 JSON object with a string `type`. Invalid UTF-8, invalid JSON, a
  non-object, a `response` without a known pending `id`, or an `extension_ui_request` is a fatal
  protocol error. Unknown event types are ignored.
- A reader runs from spawn, so events arriving before or interleaved with a command response are kept.

### C5. Turn (`prompt`)

1. `get_entries` (no `since`) → cursor = `leafId` (may be `null`).
2. `on_prepared(cursor)`; then write the `prompt` command (`message` = `text`).
3. `on_accepted()` only after the correlated response has `success: true` and
   `data.disposition == "started"`. Any other response raises `HostError`.
4. Wait, within `turn_timeout` measured from the send, for both that response and
   `agent_settled`, in any order. Require `aborted == false`, and require the last assistant
   `message_end` of the turn to have `stopReason == "stop"`. Intermediate `toolUse` assistant
   messages, `tool_execution_*` events and `toolResult` messages are valid.
5. `get_entries` with `since = cursor` (or none when cursor is `null`). Walk `parentId` from
   `leafId` back to the cursor (or to a root when cursor is `null`); it must arrive there.
   Ignoring non-`message` entries and `system` messages, the chain segment must contain exactly one
   `user` message, first; its `content` equals the turn's user `message_end` content. The last
   message must be `assistant` with `stopReason == "stop"` and `content` equal to the final
   `message_end` content. Allowed roles: `system`, `user`, `assistant`, `toolResult`.
6. Return `Turn(text, leafId)`; `text` joins the final message's `text` blocks with `"\n"`.

- EOF, protocol error, timeout, abort, rejected disposition, or verification failure reaps the
  child (stdin close, wait `command_timeout`, SIGTERM, wait, SIGKILL, wait) and raises `HostError`.
  No `prompt` is ever re-sent; the engine records `prepared`/`accepted` failures as uncertain.

### C6. History and close

- `history(cursor)` sends only `get_entries` (with `since` when given) and returns its entries and
  `leafId`. It never prompts and is not evidence of settlement; engine `reconcile()` is unchanged.
- `close()` closes stdin, waits `command_timeout`, then escalates SIGTERM → SIGKILL. A forced kill
  or a non-zero exit raises `HostError` after reaping. A second `close()` is a no-op.

## Tasks

- [x] T1 · S1–S2 · delegated tester (Codex `gpt-6.2-sol` `xhigh`) · `tests/fake_pi.py`, Phase 3 tests
  and fixtures from this contract only · RED observed on `ec042a6`.
- [x] T2 · S1, S3 · delegated worker (Codex `gpt-6.2-sol` `high`) · C1–C3 in `src/skillrun.py`.
- [x] T3 · S1, S3 · delegated worker · C4–C6 in `src/skillrun.py`.
- [x] T4 · S1–S2 · independent tester · full positive/negative suite through the fake subprocess.
- [x] T5 · S1–S3 · orchestration · full suite, `make lint`, diffs, review, “Listo cuando” check.
  Phase closure and handoff wait for separate confirmation. Phase 4 is not started.

## Log

- L1. “Sí, apruebo el plan ajustado. Abrí el hilo de la Fase 3 y arrancá con el tester.”
- Base verified at `ec042a65201ee16d9e3ee5a6cd679151ca71bbfb`, clean worktree. Local ignored
  `ANCHOR.yaml` copied from the original checkout with the same scope. Edge contract C1–C6 fixed
  before any production write.
- T1 dispatched to the independent TESTER (Codex `gpt-6.2-sol`, `xhigh`, shared checkout) with
  contract C1–C6, the `tdd` skill path, the Pi 1.6.0 docs path, and the test-only edit surface.
  No production write is allowed until RED is observed and reproduced by the parent.
- T1 reported 66 failed / 208 passed on `ec042a6` (62 missing `PiHost`, 2 missing
  `read_skill_bytes`, 2 C1 cases completing instead of blocking). Parent reproduced
  `uv run --no-sync pytest -p no:cacheprovider --tb=no` → exit 1, 66 failed, 208 passed, with an
  empty `src/` diff. The only Phase 2 test edit is `RunFiles` in `tests/fake_host.py`, which now
  materializes real `SKILL.md` files and pins in a temporary plugin directory (required by C1).
- T2 and T3 dispatched as one sequential WORKER brief (both edit `src/skillrun.py`): C1 first with
  `tests/test_skill_pins.py` green, then C2–C6. Parent reviews the full diff before integration.
- T2/T3 WORKER reported 274 passed and `make lint` failing only on the Python fence in this
  logbook (Ruff formats Markdown code). Parent changed that fence to `text` (a signature sketch),
  then observed `make lint` exit 0, `uv run pytest` 274 passed, `git diff --check` clean, no leaked
  `fake_pi.py` process. `src/skillrun.py` is 1547 lines (+536/−23).
- Parent diff review: C1 staging runs before the first save of a fresh run, so a pin failure leaves
  no receipt; a recovered `settled` step re-stages pins before confirmation. `read_skill_bytes`
  refuses a symlinked `SKILL.md` (stricter than C1, fail-closed). Turn events are collected from
  before the `prompt` write; prompt is written once; every failure path reaps the child.
- T4 dispatched to an independent TESTER for adversarial verification.
- T4 returned NO-GO with two RED tests (src untouched) plus one green C1 probe: (1) C4 — invalid
  JSON emitted after the verified history was reaped by the reader, yet `close()` saw a clean exit
  and the run stored `complete`/0; (2) C2 — a `0700` session dir with a macOS `everyone allow
  add_file` ACL launched Pi. Also verified: SIGKILL of the supervisor in `prepared` and `accepted`
  relaunches to exit 10 with zero new prompts; 1 MiB lines, 12,000 events and a blocked stdin stay
  within timeouts; no reader threads or registered PIDs leak. Assumed/known: a fake that delays its
  exit after the supervisor is SIGKILLed is left orphaned (PPID 1); the adapter cannot reap after
  its own death.
- Parent fixed both inline (small, scoped): the session directory is opened `O_NOFOLLOW` and checked
  with the existing `_check_open_private` (owner, exact `0700`, no extended ACL); `close()` marks
  closing so only stdout EOF is benign, and any recorded fatal RPC failure raises `HostError`.
  Observed: `uv run pytest` 277 passed, `tests/test_pi_host.py` green in three repeated runs,
  `make lint` exit 0, `git diff --check` clean, no leaked `fake_pi.py`. Module: 1568 lines.
- L4. «Seguí con T5 en el hilo de la Fase 3 y mostrame el chequeo “Listo cuando” antes de cerrarla.»
  Scoped independent recheck of the two T4 findings dispatched (Codex `gpt-6.2-sol` `xhigh`).
  Closure and handoff remain unauthorized.
- Scoped recheck: GO for C2 (real macOS ACL, symlink, group/other bits, regular file, simulated
  owner mismatch → `HostError`, zero spawns; fresh dirs under umask 022/077 start at `0700`).
  NO-GO for C4/C6: the reader loop exited on `_stop_reader` before draining stdout, so a malformed
  record flushed at stdin EOF while the reader was busy was never parsed and the run stored
  `complete`/0 (100/100 with the reader parked). Reproducer added:
  `test_run_plugin_blocks_invalid_rpc_on_stdin_eof_with_reader_busy`.
- Parent fix (different cause from the first fix): the reader now drains stdout until EOF and
  honours `_stop_reader` only when stdout is idle after reaping. Observed: `tests/test_pi_host.py`
  green 10/10 runs, `uv run pytest` 278 passed, `make lint` exit 0, `git diff --check` clean, no
  leaked `fake_pi.py`. Second scoped recheck dispatched.
- Second scoped recheck: C4 GO (400/400 malformed-record runs blocked/10 across five record types
  and four schedules; 80/80 clean controls complete/0). C6 NO-GO: a descendant that keeps streaming
  valid JSONL to the inherited stdout delayed `close()` until the writer stopped (5/5 at ~3.0 s with
  `command_timeout=0.30`), because the drain had no bound and the join has no timeout.
- L5. «Sí, autorizo la revisión nativa con Gentle AI»
- Parent fix: `_reap()` sets a drain deadline of `command_timeout`; past it the reader records
  `HostError("Pi RPC stdout stayed open after exit")`, so `close()` is bounded and fails closed.
  Regression `test_close_is_bounded_when_a_descendant_keeps_streaming_stdout` with fake scenario
  `stream-descendant-on-eof`: RED without the fix (did not raise), green with it. Observed:
  `tests/test_pi_host.py` green 5/5, `uv run pytest` 279 passed, `make lint` exit 0,
  `git diff --check` clean, no leaked `fake_pi.py`.
- Native review (consent granted for target `sha256:6306…253e`, lineage
  `review-153372881c601389`, four lenses, budget 200). Claude lens reviewers were run first by
  mistake; Gentle AI refused their capture (preflight, nothing mutated) and the user ruled that
  subagents are Codex only, so those results were discarded unread by the provider. A Codex
  `xhigh` delegate captured all four lenses: four BLOCKER findings (R1-001, R2-001, R3-001,
  R4-001), all deterministic/introduced, one cause — a final record without LF before a clean
  exit left bytes buffered at EOF, `close()` was clean and the run stored `complete`/0.
- L6. «sí, aplicá la corrección». Correction plan captured (60 lines). Fix: EOF with buffered bytes
  raises `HostError("Pi RPC stdout ended inside a record")`, never the benign close EOF.
  Regression `test_run_plugin_blocks_a_truncated_record_at_stdin_eof` with fake scenario
  `truncated-record-on-stdin-eof`: RED 3/3 without the fix, green with it. Observed:
  `tests/test_pi_host.py` green 5/5, `uv run pytest` 280 passed, `make lint` exit 0,
  `git diff --check` clean, no leaked `fake_pi.py`. Targeted validation delegated to Codex.
- Targeted validation (Codex `xhigh`) captured `approved`: delta 32 of 60 planned lines; with the
  old reader, valid-JSON-without-LF, partial JSON and lone CR reproduced `complete`/0 (3/3 each);
  with the fix, 60/60 truncated runs blocked/10 and 60/60 clean controls complete/0, prompt sent
  once, child reaped. R4-002 refuted as non-blocking. Parent ran `review acknowledge-approved`
  (exit 0, `acknowledged`, authority burned); `review status` is clean.
- L7. «sí, cerrá la Fase 3 y generá el handoff». The user confirmed closure on 2026-11-21.
  PLAN.md (§5.10, §6), the handoff, AGENTS.md, README.md and the affected agent docs were updated.
