from __future__ import annotations

import json
import os
import time
from hashlib import sha256
from stat import S_ISDIR
from typing import TYPE_CHECKING

import pytest

import skillrun
from fake_host import (
    CONFIRMATION_ID,
    DISCOVERY,
    GOAL,
    INVESTIGATION,
    MULTI_STEP_DISCOVERY,
    RUN_ID,
    SUMMARY,
    FakeConsole,
    FakeHost,
    ProcessCrash,
    RunFiles,
    read_json,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_full_run_keeps_one_host_and_uses_the_last_json_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = RunFiles(tmp_path, "complete")
    events: list[str] = []
    revisions: list[int] = []
    clock = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: clock)

    def wait_for_operator() -> None:
        nonlocal clock
        assert run.state()["status"] == "settled"
        clock += 86_400

    def observe(checkpoint: str, prompt: str) -> None:
        if checkpoint == "sent":
            return
        state = run.state()
        assert state["status"] == checkpoint
        revisions.append(state["revision"])
        if checkpoint == "prepared":
            persisted = json.dumps(state)
            assert f"cursor-{len(host.sent) + 1}" in persisted
            assert sha256(prompt.encode()).hexdigest() in persisted
            if host.sent:
                assert CONFIRMATION_ID not in persisted

    response = f'```json\n{{"draft":true}}\n```\nFinal scope.\n{MULTI_STEP_DISCOVERY}'
    host = FakeHost(response, INVESTIGATION, SUMMARY, observe=observe, events=events)
    console = FakeConsole(on_confirm=wait_for_operator, events=events)

    outcome = run.invoke(host, console)

    assert (outcome.status, outcome.exit_code) == ("complete", 0)
    assert console.confirmations == [("discovery", {"summary": "Agreed scope", "decisions": []})]
    assert events == ["start", "verify_skills", "prompt", "confirm", "prompt", "prompt", "close"]
    assert host.skill_names == host.verified_names == {"grilling", "research", "summary"}
    assert [prompt.split()[0] for prompt in host.sent] == [
        "/skill:grilling",
        "/skill:research",
        "/skill:summary",
    ]
    assert GOAL in host.sent[0]
    assert "Collect evidence within the agreed scope." in host.sent[1]
    state = run.state()
    assert state["status"] == "complete"
    revisions.append(state["revision"])
    assert revisions == sorted(set(revisions))

    for step, text in zip(
        ("discovery", "investigate", "summarize"), (response, INVESTIGATION, SUMMARY), strict=True
    ):
        trace = read_json(run.trace_path(step))
        assert trace["run_id"] == RUN_ID
        assert trace["step_id"] == step
        assert trace["receipt_id"] == f"{RUN_ID}/{step}/1"
        assert trace["text"] == text
        assert trace["sha256"] == sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("checkpoint", ["ready", "prepared", "accepted"])
def test_crash_at_the_send_boundary_only_replays_a_ready_step(
    tmp_path: Path, checkpoint: str
) -> None:
    run = RunFiles(tmp_path)

    def crash_at_checkpoint(stage: str, _prompt: str) -> None:
        # A prepared receipt can survive a send whose acceptance was never recorded.
        if stage == ("sent" if checkpoint == "prepared" else checkpoint):
            raise ProcessCrash

    interrupted = FakeHost(DISCOVERY, observe=crash_at_checkpoint)
    with pytest.raises(ProcessCrash):
        run.invoke(interrupted)
    assert len(interrupted.sent) == (0 if checkpoint == "ready" else 1)
    assert run.state()["status"] == checkpoint

    resumed = FakeHost(DISCOVERY)
    outcome = run.invoke(resumed)
    if checkpoint == "ready":
        assert outcome.exit_code == 0
        assert len(resumed.sent) == 1
        assert read_json(run.trace_path())["receipt_id"] == f"{RUN_ID}/discovery/1"
    else:
        assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "discovery")
        assert run.state()["status"] == "blocked"
        assert resumed.events == []


@pytest.mark.parametrize("checkpoint", ["settled", "done", "complete"])
def test_crash_after_a_durable_checkpoint_does_not_repeat_completed_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint: str
) -> None:
    run = RunFiles(tmp_path, "complete")
    real_fsync = os.fsync

    def crash_after_sync(fd: int) -> None:
        real_fsync(fd)
        synced = os.fstat(fd)
        if (
            S_ISDIR(synced.st_mode)
            and run.state_path.exists()
            and os.path.samestat(synced, run.directory.stat())
            and run.state()["status"] == checkpoint
        ):
            raise ProcessCrash

    interrupted = FakeHost(MULTI_STEP_DISCOVERY, INVESTIGATION, SUMMARY)
    console = FakeConsole()
    with monkeypatch.context() as patch, pytest.raises(ProcessCrash):
        patch.setattr(os, "fsync", crash_after_sync)
        run.invoke(interrupted, console)
    checkpoint_state = run.state_path.read_bytes()
    assert run.state()["status"] == checkpoint
    assert len(interrupted.sent) == (3 if checkpoint == "complete" else 1)
    assert len(console.confirmations) == (0 if checkpoint == "settled" else 1)
    if checkpoint == "done":
        assert CONFIRMATION_ID.encode() in checkpoint_state

    resumed = FakeHost(INVESTIGATION, SUMMARY)
    resumed_console = FakeConsole()
    assert run.invoke(resumed, resumed_console).exit_code == 0
    assert len(resumed_console.confirmations) == (1 if checkpoint == "settled" else 0)
    if checkpoint == "complete":
        assert resumed.events == []
        assert run.state_path.read_bytes() == checkpoint_state
    else:
        assert [prompt.split()[0] for prompt in resumed.sent] == [
            "/skill:research",
            "/skill:summary",
        ]
        assert CONFIRMATION_ID.encode() not in run.state_path.read_bytes()


@pytest.mark.parametrize(
    "response",
    [
        pytest.param("Human-readable text only", id="no-json-block"),
        pytest.param(f"{DISCOVERY}\n```json\n{{\n```", id="malformed-final-block"),
        pytest.param('```json\n{"summary":true}\n```', id="wrong-type"),
        pytest.param('```json\n{"summary":"OK","extra":true}\n```', id="extra-key"),
    ],
)
def test_invalid_result_blocks_before_confirmation(tmp_path: Path, response: str) -> None:
    run = RunFiles(tmp_path)
    console = FakeConsole()
    outcome = run.invoke(FakeHost(response), console)

    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "discovery")
    assert console.confirmations == []
    assert run.state()["status"] == "blocked"


def test_declined_confirmation_stops_grilling_and_cannot_be_retried_as_uncertain(
    tmp_path: Path,
) -> None:
    run = RunFiles(tmp_path, "complete")
    host = FakeHost(MULTI_STEP_DISCOVERY)
    console = FakeConsole(confirmed=False)
    assert run.invoke(host, console).exit_code == 10
    assert len(console.confirmations) == len(host.sent) == 1
    assert run.state()["status"] == "blocked"
    blocked = run.state_path.read_bytes()

    assert skillrun.reconcile(run.directory, "discovery", "retry", "tester").exit_code == 10
    resumed = FakeHost()
    assert run.invoke(resumed).exit_code == 10
    assert resumed.events == []
    assert run.state_path.read_bytes() == blocked


def test_host_close_failure_persists_a_blocked_run(tmp_path: Path) -> None:
    class HostWithBrokenClose(FakeHost):
        def close(self) -> None:
            raise skillrun.HostError("Host did not shut down")

    run = RunFiles(tmp_path)
    first = run.invoke(HostWithBrokenClose(DISCOVERY))
    assert (first.status, first.exit_code) == ("blocked", 10)
    assert run.state()["status"] == "blocked"

    host = FakeHost()
    assert run.invoke(host) == first
    assert host.events == []


def test_interrupt_during_host_close_blocks_replay(tmp_path: Path) -> None:
    class InterruptedClose(FakeHost):
        def close(self) -> None:
            raise KeyboardInterrupt

    run = RunFiles(tmp_path)
    assert run.invoke(InterruptedClose(DISCOVERY)).exit_code == 130
    assert run.state()["status"] == "blocked"

    host = FakeHost()
    assert run.invoke(host).exit_code == 10
    assert host.events == []


def timeout_after_acceptance(stage: str, _prompt: str) -> None:
    if stage == "accepted":
        raise skillrun.HostError("Turn timed out after acceptance")


@pytest.mark.parametrize("decision", ["retry", "abandon"])
def test_uncertain_timeout_requires_an_explicit_reconciliation(
    tmp_path: Path, decision: str
) -> None:
    run = RunFiles(tmp_path)
    host = FakeHost(DISCOVERY, observe=timeout_after_acceptance)
    assert run.invoke(host).exit_code == 10
    assert len(host.sent) == 1
    blocked = run.state_path.read_bytes()
    assert run.state()["status"] == "blocked"
    idle_host = FakeHost()
    assert run.invoke(idle_host).exit_code == 10

    outcome = skillrun.reconcile(run.directory, "discovery", decision, "tester")

    assert idle_host.events == []
    assert run.state()["revision"] > json.loads(blocked)["revision"]
    if decision == "abandon":
        assert (outcome.status, outcome.exit_code) == ("cancelled", 130)
        assert run.state()["status"] == "cancelled"
        assert run.invoke(idle_host).exit_code == 130
        assert idle_host.events == []
        return

    assert run.state()["status"] == "ready"
    stale_path = run.trace_path(attempt=2)
    stale_path.parent.mkdir(mode=0o700, exist_ok=True)
    stale_path.touch(mode=0o600)
    stale_path.write_text('{"text":"left over from an old execution"}', encoding="utf-8")

    def check_stale_trace_removed(stage: str, _prompt: str) -> None:
        if stage == "prepared":
            assert not stale_path.exists()

    resumed = FakeHost(DISCOVERY, observe=check_stale_trace_removed)
    assert run.invoke(resumed).exit_code == 0
    assert len(resumed.sent) == 1
    assert read_json(stale_path)["receipt_id"] == f"{RUN_ID}/discovery/2"


@pytest.mark.parametrize(
    ("step_id", "decision", "approver"),
    [
        pytest.param("wrong-step", "retry", "tester", id="wrong-step"),
        pytest.param("discovery", "resume", "tester", id="unknown-decision"),
        pytest.param("discovery", "retry", " \t", id="blank-approver"),
    ],
)
def test_reconcile_rejects_invalid_approval_without_changing_state(
    tmp_path: Path, step_id: str, decision: str, approver: str
) -> None:
    run = RunFiles(tmp_path)
    assert run.invoke(FakeHost(DISCOVERY, observe=timeout_after_acceptance)).exit_code == 10
    blocked = run.state_path.read_bytes()

    assert skillrun.reconcile(run.directory, step_id, decision, approver).exit_code == 10
    assert run.state_path.read_bytes() == blocked


@pytest.mark.parametrize("exit_code", [70, 130], ids=["programming-error", "interrupt"])
def test_programming_errors_and_interrupts_have_distinct_outcomes(
    tmp_path: Path, exit_code: int
) -> None:
    run = RunFiles(tmp_path)

    def fail(stage: str, _prompt: str) -> None:
        if stage == "accepted":
            if exit_code == 130:
                raise KeyboardInterrupt
            raise KeyError("unexpected host implementation bug")

    host, console = FakeHost(DISCOVERY, observe=fail), FakeConsole()
    assert run.invoke(host, console).exit_code == exit_code
    assert len(host.sent) == 1
    assert console.confirmations == []
