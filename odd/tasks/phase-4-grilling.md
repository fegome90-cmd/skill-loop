# Phase 4 console grilling and later steps

Branch `feat/phase-4-grilling` from `3366281`. Verification uses `uv run pytest` and `make lint`.
Delivery is local. No real Pi, no real model calls and no GitHub writes in this phase.

## Specs

- S1. "Flujo grilling→confirmación→paso 2 con fakes" per PLAN.md §6, implementing PLAN.md §§5.3–5.4.
- S2. "TESTER escribe los tests primero (deben fallar: RED)" and then runs the full suite.
- S3. Phase 2 and Phase 3 contracts (PLAN.md §§5.9–5.10) stay valid unless changed here explicitly.
- S4. Applicable PLAN.md §4 errors: 1 (only active evidence), 2 (`run_id` + `step_id` in every
  evidence file, cleared before use), 3 (exit codes), 4 (receipt identity), 5 (human time is not
  a timeout), 6 (uncertain → reconcile), 9 (agent text never on stdout), 11 (`INTERNAL` vs
  `BLOCKED`).

## Decisions (grilling with the user, 2026-11-21)

- D1. Workspace snapshot: SHA-256 over the content of the whole tree, `.git` included, no
  exclusions, symlinks recorded by `readlink` and never followed.
- D2. Snapshot before and after **each agent turn** (not each step). Human edits between turns
  are not blamed on the agent.
- D3. Special files (FIFO, socket, device) or unreadable entries block **before** the prompt.
- D4. A changed workspace is a definitive block. `reconcile` refuses it.
- D5. Invalid synthesis (no JSON block or contract mismatch) → notice and back to rounds.
- D6. Tokens stay `:listo` and `[s/n]`. Ctrl-C and console EOF → `130`.
- D7. Relaunch while waiting for the human: show the last agent text again from its verified
  trace and ask again. Nothing is resent.
- D8. `reconcile retry` on an uncertain round or synthesis turn → back to waiting for human input;
  the human types again. Human text is never stored (only its SHA-256).
- D9. Each human answer is sent verbatim. Empty or whitespace-only input is asked again without
  sending anything.

## Approved edge contract

### C1. `run_plugin` and `Console`

```text
def run_plugin(plugin, *, goal, run_id, host, console, workspace: Path, state_root=None) -> RunOutcome

class Console(Protocol):
    def show(self, step_id: str, text: str) -> None: ...      # agent text, verbatim
    def notice(self, step_id: str, text: str) -> None: ...    # app message
    def ask(self, step_id: str) -> str: ...                   # one human input line
    def confirm(self, step_id: str, result: Mapping[str, object]) -> tuple[bool, str]: ...
```

- `workspace` is required. It must be an existing directory; otherwise `blocked` (`10`) before the
  host is touched. The caller passes the same path as the host `cwd` (Phase 5 wires it).
- `ask` and `confirm` may raise `KeyboardInterrupt` or `EOFError`. Both return
  `RunOutcome("cancelled", 130, step_id, "Run interrupted")`. If no turn is in flight the
  persisted state is not changed (the run can be resumed). In-flight turns are recorded as
  uncertain, as today.

### C2. Turns, receipts and traces

- Every agent turn in a step has a turn number `turn` (int ≥ 1). The receipt id becomes
  `<run_id>/<step_id>/<attempt>/<turn>` for **all** steps (skill steps always use `turn = 1`).
- Trace file: `traces/<step_id>-<attempt>-<turn>.json` with keys
  `run_id, step_id, receipt_id, text, sha256` (unchanged shape). It is cleared before the turn.
- New state fields: `turn` (int ≥ 1), `turn_kind` (`"skill" | "open" | "round" | "synthesis"`),
  `answer_sha256` (SHA-256 of the human text, only for `round`; `null` otherwise),
  `workspace_sha256` (snapshot taken before the turn, stored in `prepared`), and `previous`:
  `null` or `{attempt, turn, leaf_id, response_sha256}` = the last settled agent turn shown to
  the human. All fields are validated on load.
- New status `awaiting` (grilling only): an agent turn settled and was shown; the human has not
  answered yet. Not in flight.
- Trace retention: only the trace of `previous` and of the current turn exist. When a turn
  settles, the trace of the older `previous` is deleted.

### C3. Grilling step flow

1. `ready`, `turn = 1`, `turn_kind = "open"`: send `/skill:grilling <goal>`. A JSON block in this
   turn is ignored.
2. After any `open` or `round` turn settles: `console.show(step_id, text)`, then save `awaiting`
   with `previous` = that turn.
3. `awaiting`: `console.ask()` until the input is non-empty after `strip()`.
   - Input whose `strip()` equals `:listo` → next turn `turn_kind = "synthesis"` with prompt:
     `The user ended the grilling rounds. Return your shared-understanding synthesis in a fenced JSON block with exactly these fields and types:\n<contract>`
     where `<contract>` = `json.dumps(dict(step.result), sort_keys=True)`.
   - Any other input → next turn `turn_kind = "round"`, prompt = the input **verbatim** (not
     stripped), `answer_sha256` = its SHA-256.
4. `synthesis` settles: `console.show(text)`. The result is the last fenced JSON block checked with
   `check_result()`.
   - Invalid → `console.notice(...)`, save `awaiting` with `previous` = this turn.
   - Valid → `console.confirm(step_id, result)`. `(True, event_id)` with non-empty `event_id` →
     `done` with `confirmation_event_id`. `(False, _)` → `awaiting` with `previous` = this turn.
     `(True, "")` or a non-string id → `blocked` (unchanged Phase 2 rule).
5. Rounds are unlimited. Turn numbers increase by one per turn.

### C4. Recovery

- `awaiting` on relaunch: read and verify the trace of `previous`, `console.show()` it again, then
  continue at C3.3. A missing or invalid trace → `blocked` ("Invalid settled trace").
- `settled` on relaunch: continue from the trace as in Phase 2 (show for open/round, parse and
  confirm for synthesis, contract check for skill steps). No prompt is resent.
- `prepared`/`accepted` on relaunch: `blocked` uncertain, as today.
- `reconcile retry` on an uncertain turn:
  - `turn_kind` `open` or `skill`: unchanged Phase 2 behaviour (`attempt + 1`, `ready`, `turn = 1`).
  - `round` or `synthesis`: `attempt + 1`, status `awaiting`, `previous` kept, `turn` unchanged
    (the next turn reuses this number under the new attempt).
- Workspace blocks (C5) are not uncertain: `reconcile` returns `blocked` "No matching uncertain
  step" for them.

### C5. Workspace snapshot

```text
def workspace_digest(root: Path) -> str  # module level, 64 lowercase hex
```

- Walk `root` with `os.scandir`, never following symlinks. Entries are processed in sorted order of
  their relative path bytes (`os.fsencode`). Each entry contributes its relative path, its type
  (`d`, `f`, `l`), `stat.S_IMODE` of its mode, and: for files the SHA-256 of the content (opened
  with `O_NOFOLLOW`), for symlinks `os.readlink`. `mtime`, `atime`, owner and inode are ignored.
  The encoding must be unambiguous (length-prefixed or NUL-separated fields).
- Any special file or `OSError` raises a dedicated error (not `HostError`).
- Every turn (all kinds, all steps): snapshot **before** `on_prepared`; on error → `blocked`
  "Workspace snapshot failed" with no prompt sent and no `prepared` receipt. The digest is stored
  in the `prepared` receipt. After the host returns the turn and **before** `settled` is saved:
  snapshot again; on error → `blocked` "Workspace snapshot failed"; on mismatch → `blocked`
  "Workspace changed during agent turn". Neither is reconcilable.

### C6. Later steps (§5.4)

- Same session, prompt `/skill:<name> <instruction>` + contract (unchanged text). Result = last
  fenced JSON block of the final assistant message; mismatch → `blocked` (unchanged). Snapshot per
  C5.

### C7. `TerminalConsole`

```text
class TerminalConsole:
    def __init__(self, *, stdin: TextIO, stderr: TextIO, new_id: Callable[[], str] = <uuid4 hex>) -> None
```

- Implements `Console`. Writes **only** to `stderr` (never stdout). `show` writes the text and a
  trailing newline; `notice` writes it prefixed `skillrun:`. `ask` writes the prompt `>` and
  reads one line; `""` (EOF) raises `EOFError`; the trailing newline is removed.
- `confirm` writes the result as `json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)`
  and `¿Confirmas? [s/n]`; accepts `s`/`n` after `strip().lower()`; asks again otherwise; EOF
  raises `EOFError`. Returns `(answer == "s", "console:" + new_id())`.
- Stdlib only.

## T6 review deltas (approved by the orchestrator, 2026-11-21)

Independent T6 probes found five defects, reproduced in `tests/test_phase4_review.py` (RED, then
fixed in `src/skillrun.py`):

- C1/C5. `workspace` must be a real directory checked with `lstat`; a symlink root is `blocked`
  before the host is touched.
- C4/C5. When an in-flight turn fails (`HostError`, Ctrl-C or internal error) after the host is
  stopped, the workspace is compared with the `prepared` digest. A change or snapshot failure is the
  definitive C5 block; only an unchanged workspace stays uncertain and reconcilable.
- C1. Only `EOFError` raised by `Console.ask`/`confirm` maps to `130`. Any other `EOFError` is
  `INTERNAL` (`70`).
- C2. State decoding rejects `cancelled` with settled turn evidence.
- C7. `TerminalConsole.ask` removes a full `\r\n` terminator; inner whitespace is kept.

Rejected T6 probes, confirmed by the user (2026-11-21):

- D10. Traces store the agent text verbatim (needed to show it again and to check its SHA). If the
  agent quotes the human answer, that copy lives in the private trace (`0600` under a `0700` run
  dir). PLAN.md §5.3.5 ("only the SHA") applies to receipts, not to agent text.
- D11. Run completion keeps the traces of the last step: they are the evidence of the final result
  that Phase 5 needs (final JSON and `on_done`). Intermediate steps are still pruned (C2).

## Native review delta (2026-11-21)

Codex `gpt-6.2-sol` `xhigh`, four lenses. 340 tests and `make lint` green before the fix. One
confirmed defect: after a process crash (`SIGKILL`) during a turn that changed the workspace, the
relaunch blocked as uncertain and `reconcile retry` was accepted. Fix: a relaunch that finds a
`prepared`/`accepted` receipt compares the workspace with its `prepared` digest, like the in-process
failures above. A change or snapshot failure is the definitive C5 block. Trade-off: a human edit
made between the crash and the relaunch also blocks definitively (fail-closed). Reproduced by
`test_workspace_change_before_a_crash_cannot_be_reconciled`. Suspected TOCTOU in
`workspace_digest` was not reproduced.
