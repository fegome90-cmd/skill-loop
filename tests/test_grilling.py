"""Console rounds and crash recovery through run_plugin and reconcile."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from stat import S_ISDIR
from typing import TYPE_CHECKING, cast

import pytest

import skillrun
from fake_host import (
    CONFIRMATION_ID,
    DISCOVERY,
    GOAL,
    OPENING,
    RUN_ID,
    SYNTHESIS_PREFIX,
    FakeConsole,
    FakeHost,
    ProcessCrash,
    RunFiles,
    read_json,
)

if TYPE_CHECKING:
    from pathlib import Path

STEP = "discovery"
OPEN_PROMPT = f"/skill:grilling {GOAL}"
SYNTHESIS_PROMPT = SYNTHESIS_PREFIX + '{"summary": "string"}'
ROUND_ANSWER = "  Confirm the original scope.\t "
ROUND_REPLY = "Which boundary should we keep?"


def assert_trace(run: RunFiles, *, attempt: int, turn: int, reply: str) -> None:
    assert read_json(run.trace_path(attempt=attempt, turn=turn)) == {
        "run_id": RUN_ID,
        "step_id": STEP,
        "receipt_id": f"{RUN_ID}/{STEP}/{attempt}/{turn}",
        "text": reply,
        "sha256": sha256(reply.encode()).hexdigest(),
    }


def test_rounds_send_verbatim_answers_and_only_confirm_the_synthesis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = RunFiles(tmp_path)
    events: list[str] = []
    first = "  private-answer-one café\t "
    second = "   private-answer-two déjà vu  "
    opening = DISCOVERY.replace("Agreed scope", "Unconfirmed open result")
    synthesis = f"{DISCOVERY.replace('Agreed scope', 'Draft')}\nFinal synthesis.\n{DISCOVERY}"
    replies = (opening, ROUND_REPLY, "Any remaining questions?", synthesis)
    prepared: list[tuple[int, str, str | None]] = []
    awaiting_turns: list[int] = []

    def assert_no_plaintext() -> None:
        evidence = [run.state_path, *run.trace_path().parent.glob("*.json")]
        for path in evidence:
            persisted = path.read_text(encoding="utf-8")
            assert "private-answer-one" not in persisted
            assert "private-answer-two" not in persisted

    def observe(stage: str, _prompt: str) -> None:
        if stage != "prepared":
            return
        state = run.state()
        turn = state["turn"]
        assert state["attempt"] == 1
        prepared.append((turn, state["turn_kind"], state["answer_sha256"]))
        expected_traces = {run.trace_path(turn=turn - 1)} if turn > 1 else set()
        assert set(run.trace_path().parent.glob("*.json")) == expected_traces
        if turn == 1:
            assert state["previous"] is None
        else:
            assert (state["previous"]["attempt"], state["previous"]["turn"]) == (1, turn - 1)
        assert_no_plaintext()

    def check_awaiting() -> None:
        state = run.state()
        turn = len(host.sent)
        assert state["status"] == "awaiting"
        assert state["previous"] == {
            "attempt": 1,
            "turn": turn,
            "leaf_id": f"leaf-{turn}",
            "response_sha256": sha256(replies[turn - 1].encode()).hexdigest(),
        }
        assert_trace(run, attempt=1, turn=turn, reply=replies[turn - 1])
        assert set(run.trace_path().parent.glob("*.json")) <= {
            run.trace_path(turn=number) for number in range(max(1, turn - 1), turn + 1)
        }
        assert console.shown[-1] == (STEP, replies[turn - 1])
        assert_no_plaintext()
        awaiting_turns.append(turn)

    def check_before_confirm() -> None:
        assert run.state()["status"] == "settled"
        assert console.shown[-1] == (STEP, synthesis)
        assert_trace(run, attempt=1, turn=4, reply=synthesis)
        assert set(run.trace_path().parent.glob("*.json")) <= {
            run.trace_path(turn=3),
            run.trace_path(turn=4),
        }
        assert_no_plaintext()

    host = FakeHost(*replies, observe=observe, events=events)
    console = FakeConsole(
        answers=("", " \t ", first, second, "  :listo\t"),
        on_ask=check_awaiting,
        on_confirm=check_before_confirm,
        events=events,
    )

    outcome = run.invoke(host, console)

    assert (outcome.status, outcome.exit_code) == ("complete", 0)
    assert run.state()["status"] == "complete"
    assert host.sent == [OPEN_PROMPT, first, second, SYNTHESIS_PROMPT]
    assert console.shown == [(STEP, reply) for reply in replies]
    assert console.confirmations == [(STEP, {"summary": "Agreed scope"})]
    assert console.notices == []
    assert awaiting_turns == [1, 1, 1, 2, 3]
    assert prepared == [
        (1, "open", None),
        (2, "round", sha256(first.encode()).hexdigest()),
        (3, "round", sha256(second.encode()).hexdigest()),
        (4, "synthesis", None),
    ]
    assert events == [
        "start",
        "verify_skills",
        "prompt",
        "show",
        "ask",
        "ask",
        "ask",
        "prompt",
        "show",
        "ask",
        "prompt",
        "show",
        "ask",
        "prompt",
        "show",
        "confirm",
        "close",
    ]
    assert_no_plaintext()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("event_id", ["", 42], ids=["missing-id", "non-string-id"])
def test_positive_confirmation_requires_a_nonempty_string_id(
    tmp_path: Path, event_id: object
) -> None:
    run = RunFiles(tmp_path)
    host = FakeHost(OPENING, DISCOVERY)
    console = FakeConsole(decisions=((True, cast("str", event_id)),))

    outcome = run.invoke(host, console)

    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, STEP)
    assert run.state()["status"] == "blocked"
    assert console.confirmations == [(STEP, {"summary": "Agreed scope"})]
    assert host.sent == [OPEN_PROMPT, SYNTHESIS_PROMPT]


@pytest.mark.parametrize("turn_kind", ["round", "synthesis"])
@pytest.mark.parametrize("checkpoint", ["prepared", "sent", "accepted"])
def test_interrupted_in_flight_turn_requires_retry_and_reuses_turn_number(
    tmp_path: Path, turn_kind: str, checkpoint: str
) -> None:
    run = RunFiles(tmp_path)
    answer = ROUND_ANSWER if turn_kind == "round" else ":listo"
    prompt = ROUND_ANSWER if turn_kind == "round" else SYNTHESIS_PROMPT

    def crash_at_boundary(stage: str, prompt_text: str) -> None:
        if stage == checkpoint and prompt_text == prompt:
            raise ProcessCrash

    interrupted = FakeHost(OPENING, DISCOVERY, observe=crash_at_boundary)
    with pytest.raises(ProcessCrash):
        run.invoke(interrupted, FakeConsole(answers=(answer,)))
    receipt = run.state()
    assert (receipt["status"], receipt["attempt"], receipt["turn_kind"], receipt["turn"]) == (
        "accepted" if checkpoint == "accepted" else "prepared",
        1,
        turn_kind,
        2,
    )
    assert interrupted.sent == (
        [OPEN_PROMPT] if checkpoint == "prepared" else [OPEN_PROMPT, prompt]
    )
    assert_trace(run, attempt=1, turn=1, reply=OPENING)

    idle, blocked_console = FakeHost(), FakeConsole(answers=())
    blocked = run.invoke(idle, blocked_console)
    assert (blocked.status, blocked.exit_code, blocked.step_id) == ("blocked", 10, STEP)
    assert run.state()["status"] == "blocked"
    assert idle.events == blocked_console.events == []

    skillrun.reconcile(run.directory, STEP, "retry", "tester")
    retry = run.state()
    assert (retry["status"], retry["attempt"], retry["turn"]) == ("awaiting", 2, 2)
    assert retry["previous"] == receipt["previous"]
    assert idle.events == blocked_console.events == []

    events: list[str] = []
    retry_input: tuple[str | BaseException, ...]
    if turn_kind == "round":
        retry_answer = "  A different answer after explicit retry. "
        reply = ROUND_REPLY
        retry_input = (retry_answer, EOFError())
        expected_exit = 130
    else:
        retry_answer = SYNTHESIS_PROMPT
        reply = DISCOVERY
        retry_input = (":listo",)
        expected_exit = 0

    def check_retry_trace() -> None:
        if host.sent:
            assert_trace(run, attempt=2, turn=2, reply=reply)

    host = FakeHost(reply, events=events)
    console = FakeConsole(
        answers=retry_input, on_ask=check_retry_trace, on_confirm=check_retry_trace, events=events
    )
    assert run.invoke(host, console).exit_code == expected_exit
    assert host.sent == [retry_answer]
    assert events.index("show") < events.index("ask") < events.index("prompt")
    assert console.shown == [(STEP, OPENING), (STEP, reply)]


@pytest.mark.parametrize("turn_kind", ["open", "round", "synthesis"])
def test_settled_turn_is_recovered_from_its_verified_trace_without_resending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, turn_kind: str
) -> None:
    run = RunFiles(tmp_path)
    real_fsync = os.fsync

    def crash_after_settlement(fd: int) -> None:
        real_fsync(fd)
        synced = os.fstat(fd)
        if (
            S_ISDIR(synced.st_mode)
            and run.state_path.exists()
            and os.path.samestat(synced, run.directory.stat())
        ):
            state = run.state()
            if state["status"] == "settled" and state["turn_kind"] == turn_kind:
                raise ProcessCrash

    answer = ":listo" if turn_kind == "synthesis" else ROUND_ANSWER
    reply = DISCOVERY if turn_kind == "synthesis" else ROUND_REPLY
    interrupted = FakeHost(OPENING, reply)
    console = FakeConsole(answers=(answer,))
    with monkeypatch.context() as patch, pytest.raises(ProcessCrash):
        patch.setattr(os, "fsync", crash_after_settlement)
        run.invoke(interrupted, console)

    expected_prompt = {"round": ROUND_ANSWER, "synthesis": SYNTHESIS_PROMPT}.get(turn_kind)
    assert interrupted.sent == (
        [OPEN_PROMPT, expected_prompt] if expected_prompt else [OPEN_PROMPT]
    )
    assert console.confirmations == []
    assert run.state()["status"] == "settled"

    idle = FakeHost()
    resumed = FakeConsole(answers=(EOFError(),))
    outcome = run.invoke(idle, resumed)

    assert "prompt" not in idle.events and idle.sent == []
    assert resumed.shown == [(STEP, OPENING if turn_kind == "open" else reply)]
    if turn_kind == "synthesis":
        assert (outcome.status, outcome.exit_code) == ("complete", 0)
        assert resumed.asked == []
        assert resumed.confirmations == [(STEP, {"summary": "Agreed scope"})]
    else:
        assert (outcome.status, outcome.exit_code) == ("cancelled", 130)
        assert run.state()["status"] == "awaiting"
        assert resumed.asked == [STEP]
        assert resumed.confirmations == []


@pytest.mark.parametrize(
    ("answer", "last_reply"),
    [(ROUND_ANSWER, ROUND_REPLY), (":listo", "No JSON synthesis")],
    ids=["round", "invalid-synthesis"],
)
def test_crash_while_awaiting_reshows_only_the_last_turn_and_asks_again(
    tmp_path: Path, answer: str, last_reply: str
) -> None:
    run = RunFiles(tmp_path)
    host = FakeHost(OPENING, last_reply)

    def crash_before_read() -> None:
        if len(host.sent) == 2:
            assert run.state()["status"] == "awaiting"
            raise ProcessCrash

    with pytest.raises(ProcessCrash):
        run.invoke(host, FakeConsole(answers=(answer,), on_ask=crash_before_read))
    state = run.state_path.read_bytes()
    previous = run.state()["previous"]
    assert (previous["attempt"], previous["turn"]) == (1, 2)
    assert_trace(run, attempt=1, turn=2, reply=last_reply)

    idle = FakeHost()
    console = FakeConsole(answers=(EOFError(),))
    outcome = run.invoke(idle, console)

    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("cancelled", 130, STEP)
    assert console.events == ["show", "ask"]
    assert console.shown == [(STEP, last_reply)]
    assert run.state_path.read_bytes() == state
    assert "prompt" not in idle.events and idle.sent == []


@pytest.mark.parametrize("defect", ["missing", "wrong-receipt", "changed-text-with-new-hash"])
def test_awaiting_recovery_blocks_unverified_previous_trace(tmp_path: Path, defect: str) -> None:
    run = RunFiles(tmp_path)
    assert run.invoke(FakeHost(OPENING), FakeConsole(answers=(EOFError(),))).exit_code == 130
    path = run.trace_path()
    trace = read_json(path)
    if defect == "missing":
        path.unlink()
    else:
        if defect == "wrong-receipt":
            trace["receipt_id"] = f"{RUN_ID}/{STEP}/2/1"
        else:
            text = "Different text"
            trace.update(text=text, sha256=sha256(text.encode()).hexdigest())
        path.write_text(json.dumps(trace), encoding="utf-8")

    idle, console = FakeHost(), FakeConsole(answers=())
    outcome = run.invoke(idle, console)

    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, STEP)
    assert outcome.reason and outcome.reason.startswith("Invalid settled trace")
    assert run.state()["status"] == "blocked"
    assert "prompt" not in idle.events and idle.sent == []
    assert console.events == []


@pytest.mark.parametrize("operation", ["ask", "confirm"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, EOFError])
def test_console_interruption_preserves_the_committed_checkpoint(
    tmp_path: Path, operation: str, interruption: type[BaseException]
) -> None:
    run = RunFiles(tmp_path)
    snapshots: list[bytes] = []

    def interrupt() -> None:
        assert run.state()["status"] == ("awaiting" if operation == "ask" else "settled")
        snapshots.append(run.state_path.read_bytes())
        raise interruption

    host = FakeHost(OPENING, DISCOVERY)
    console = (
        FakeConsole(answers=(), on_ask=interrupt)
        if operation == "ask"
        else FakeConsole(on_confirm=interrupt)
    )

    assert run.invoke(host, console) == skillrun.RunOutcome(
        "cancelled", 130, STEP, "Run interrupted"
    )
    assert snapshots == [run.state_path.read_bytes()]
    assert host.sent == ([OPEN_PROMPT] if operation == "ask" else [OPEN_PROMPT, SYNTHESIS_PROMPT])

    idle = FakeHost(DISCOVERY)
    resumed = FakeConsole(decisions=((True, CONFIRMATION_ID),))
    assert run.invoke(idle, resumed).exit_code == 0
    assert idle.sent == ([SYNTHESIS_PROMPT] if operation == "ask" else [])
    assert resumed.confirmations == [(STEP, {"summary": "Agreed scope"})]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("turn", False),
        ("turn", 0),
        ("turn_kind", "unexpected"),
        ("answer_sha256", "not-a-hash"),
        ("workspace_sha256", "not-a-hash"),
        ("previous", "not-a-previous-turn"),
        ("previous", {"attempt": 1, "turn": 1, "leaf_id": "leaf-1", "response_sha256": "bad"}),
    ],
)
def test_invalid_turn_state_blocks_before_showing_or_sending(
    tmp_path: Path, field: str, value: object
) -> None:
    run = RunFiles(tmp_path)
    assert run.invoke(FakeHost(OPENING), FakeConsole(answers=(EOFError(),))).exit_code == 130
    state = run.state()
    state[field] = value
    run.state_path.write_text(json.dumps(state), encoding="utf-8")
    before = run.state_path.read_bytes()

    idle, console = FakeHost(), FakeConsole(answers=())
    assert run.invoke(idle, console).exit_code == 10

    assert idle.events == console.events == []
    assert run.state_path.read_bytes() == before
