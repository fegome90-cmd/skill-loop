"""Phase 4 T6 review probes; no real Pi or provider."""

import json
from io import StringIO
from pathlib import Path
from typing import NoReturn

import pytest

import skillrun
from fake_host import DISCOVERY, OPENING, FakeConsole, FakeHost, ProcessCrash, RunFiles


def test_workspace_change_during_timeout_cannot_be_reconciled(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)
    modified = run.workspace / "modified.txt"

    def timeout_after_write(checkpoint: str, _prompt: str) -> None:
        if checkpoint == "accepted":
            modified.write_text("changed", encoding="utf-8")
            raise skillrun.HostError("Turn timed out")

    first = run.invoke(FakeHost(OPENING, observe=timeout_after_write))
    assert first.exit_code == 10
    assert modified.read_text(encoding="utf-8") == "changed"
    retry = skillrun.reconcile(run.directory, "discovery", "retry", "tester")
    after_retry = run.invoke(FakeHost(OPENING, DISCOVERY)) if retry.exit_code == 3 else None
    assert (retry.exit_code, retry.reason) == (10, "No matching uncertain step"), (
        first,
        retry,
        after_retry,
    )


def test_non_console_eof_is_internal_not_operator_cancel(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)

    def host_bug(checkpoint: str, _prompt: str) -> None:
        if checkpoint == "accepted":
            raise EOFError("Unexpected EOF in the host implementation")

    outcome = run.invoke(FakeHost(OPENING, observe=host_bug))
    assert (outcome.status, outcome.exit_code) == ("internal", 70)


def test_cancelled_state_rejects_settled_turn_evidence(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)

    def interrupt_confirmation() -> NoReturn:
        raise EOFError

    outcome = run.invoke(
        FakeHost(OPENING, DISCOVERY), FakeConsole(on_confirm=interrupt_confirmation)
    )
    assert outcome.exit_code == 130
    state = run.state()
    assert state["status"] == "settled" and state["response_sha256"]
    state.update(status="cancelled", reason="Run abandoned")
    run.state_path.write_text(json.dumps(state), encoding="utf-8")
    before = run.state_path.read_bytes()
    host = FakeHost()
    outcome = run.invoke(host)
    assert host.events == [] and run.state_path.read_bytes() == before
    assert outcome.exit_code == 10


def test_ask_removes_crlf_without_trimming_the_answer() -> None:
    console = skillrun.TerminalConsole(stdin=StringIO("  answer\t \r\n"), stderr=StringIO())
    assert console.ask("discovery") == "  answer\t "


def test_unsupported_workspace_root_is_rejected_before_host_start(tmp_path: Path) -> None:
    target = tmp_path / "actual"
    target.mkdir()
    workspace = tmp_path / "alias"
    workspace.symlink_to(target, target_is_directory=True)
    run = RunFiles(tmp_path, workspace=workspace)
    host = FakeHost()
    outcome = run.invoke(host)
    assert outcome.exit_code == 10
    assert host.events == []


def test_workspace_change_before_a_crash_cannot_be_reconciled(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)
    modified = run.workspace / "modified.txt"

    def crash_after_write(checkpoint: str, _prompt: str) -> None:
        if checkpoint == "accepted":
            modified.write_text("changed", encoding="utf-8")
            raise ProcessCrash

    with pytest.raises(ProcessCrash):
        run.invoke(FakeHost(OPENING, observe=crash_after_write))
    assert run.state()["status"] == "accepted"
    host = FakeHost()
    relaunch = run.invoke(host)
    assert (relaunch.exit_code, relaunch.reason) == (10, "Workspace changed during agent turn")
    assert host.sent == []
    retry = skillrun.reconcile(run.directory, "discovery", "retry", "tester")
    assert (retry.exit_code, retry.reason) == (10, "No matching uncertain step")


def test_unchanged_workspace_after_a_crash_stays_reconcilable(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)

    def crash(checkpoint: str, _prompt: str) -> None:
        if checkpoint == "accepted":
            raise ProcessCrash

    with pytest.raises(ProcessCrash):
        run.invoke(FakeHost(OPENING, observe=crash))
    relaunch = run.invoke(FakeHost())
    assert (relaunch.exit_code, relaunch.reason) == (10, "Prompt delivery is uncertain")
    retry = skillrun.reconcile(run.directory, "discovery", "retry", "tester")
    assert retry.exit_code == 3
