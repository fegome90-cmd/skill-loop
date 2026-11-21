"""Workspace evidence at the filesystem and agent-turn boundaries."""

from __future__ import annotations

import os
import re
from stat import S_ISDIR
from typing import TYPE_CHECKING

import pytest

import skillrun
from fake_host import (
    DISCOVERY,
    GOAL,
    INVESTIGATION,
    MULTI_STEP_DISCOVERY,
    OPENING,
    RUN_ID,
    FakeConsole,
    FakeHost,
    RunFiles,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def digest_reader() -> Callable[[Path], str]:
    # Lookup inside the test so the Phase 3 baseline still collects.
    digest: Callable[[Path], str] = getattr(skillrun, "workspace_digest")  # noqa: B009
    return digest


def test_workspace_digest_is_content_based_and_independent_of_creation_order(
    tmp_path: Path,
) -> None:
    digest = digest_reader()
    first, second = tmp_path / "first", tmp_path / "second"
    for root, names in ((first, ("z.txt", "a.txt")), (second, ("a.txt", "z.txt"))):
        root.mkdir()
        nested = root / "nested"
        nested.mkdir()
        for name in names:
            (nested / name).write_text(name, encoding="utf-8")

    before = digest(first)
    assert re.fullmatch("[0-9a-f]{64}", before)
    path = first / "nested" / "z.txt"
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 20_000_000_000))
    assert path.stat().st_mtime_ns != stat.st_mtime_ns
    assert digest(first) == digest(second) == before


@pytest.mark.parametrize("change", ["content", "mode", "new", "deleted", "renamed", "git"])
def test_workspace_digest_changes_with_the_tree(tmp_path: Path, change: str) -> None:
    digest = digest_reader()
    path = tmp_path / "tracked"
    path.write_bytes(b"original")
    (tmp_path / ".git").mkdir()
    head = tmp_path / ".git" / "HEAD"
    head.write_bytes(b"ref: refs/heads/main")
    before = digest(tmp_path)

    if change == "content":
        stat = path.stat()
        path.write_bytes(b"modified")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif change == "mode":
        path.chmod(0o700)
    elif change == "new":
        (tmp_path / "new").write_bytes(b"")
    elif change == "deleted":
        path.unlink()
    elif change == "renamed":
        path.rename(path.with_name("renamed"))
    else:
        head.write_bytes(b"ref: refs/heads/next")

    assert digest(tmp_path) != before


def test_workspace_digest_hashes_the_link_target_without_following_it(tmp_path: Path) -> None:
    digest = digest_reader()
    root = tmp_path / "checkout"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    first = outside / "first"
    second = outside / "second"
    first.write_bytes(b"original")
    link = root / "pointer"
    link.symlink_to(first)
    (root / "directory-link").symlink_to(outside, target_is_directory=True)
    before = digest(root)

    first.write_bytes(b"new content outside the checkout")
    second.write_bytes(first.read_bytes())
    assert digest(root) == before

    link.unlink()
    link.symlink_to(second)
    assert digest(root) != before


@pytest.mark.parametrize("defect", ["fifo", "unreadable"])
def test_workspace_digest_rejects_special_and_unreadable_entries(
    tmp_path: Path, defect: str
) -> None:
    digest = digest_reader()
    path = tmp_path / "unsupported"
    if defect == "fifo":
        os.mkfifo(path)
    else:
        path.write_bytes(b"Unreadable contents")
        path.chmod(0)
        if os.access(path, os.R_OK):
            pytest.skip("This user can read the file despite mode 000")

    with pytest.raises(Exception) as raised:  # noqa: PT011
        digest(tmp_path)

    assert type(raised.value).__module__ == skillrun.__name__
    assert not isinstance(raised.value, skillrun.HostError)


def test_run_requires_a_workspace_argument(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)
    host = FakeHost(OPENING, DISCOVERY)
    run_plugin: Callable[..., skillrun.RunOutcome] = skillrun.run_plugin
    with pytest.raises(TypeError, match="workspace"):
        run_plugin(
            skillrun.load_plugin(run.plugin_path),
            goal=GOAL,
            run_id=RUN_ID,
            host=host,
            console=FakeConsole(),
            state_root=run.root,
        )
    assert host.events == []


@pytest.mark.parametrize("defect", ["missing", "regular-file"])
def test_invalid_workspace_blocks_before_touching_host(tmp_path: Path, defect: str) -> None:
    workspace = tmp_path / "not-a-directory"
    if defect == "regular-file":
        workspace.touch()
    run = RunFiles(tmp_path, workspace=workspace)
    host = FakeHost()

    outcome = run.invoke(host)

    assert (outcome.status, outcome.exit_code) == ("blocked", 10)
    assert host.events == []


def test_special_file_blocks_before_sending_or_preparing_a_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = RunFiles(tmp_path)
    os.mkfifo(run.workspace / "pipe")
    checkpoints: list[str] = []
    durable_states: list[str] = []
    host = FakeHost(OPENING, observe=lambda stage, _: checkpoints.append(stage))
    real_fsync = os.fsync

    def record_durable_state(fd: int) -> None:
        real_fsync(fd)
        synced = os.fstat(fd)
        if (
            S_ISDIR(synced.st_mode)
            and run.state_path.exists()
            and os.path.samestat(synced, run.directory.stat())
        ):
            durable_states.append(run.state()["status"])

    monkeypatch.setattr(os, "fsync", record_durable_state)

    outcome = run.invoke(host)

    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "discovery")
    assert outcome.reason and outcome.reason.startswith("Workspace snapshot failed")
    assert host.sent == []
    assert "prepared" not in checkpoints and "prepared" not in durable_states
    assert list(run.trace_path().parent.glob("*.json")) == []
    if run.state_path.exists():
        assert run.state()["status"] == "blocked"
        assert run.state().get("workspace_sha256") is None


@pytest.mark.parametrize("turn_kind", ["open", "round", "synthesis", "skill"])
def test_agent_workspace_change_definitively_blocks_each_turn_kind(
    tmp_path: Path, turn_kind: str
) -> None:
    run = RunFiles(tmp_path, "complete")
    target = run.workspace / "changed-by-agent"
    answers = ("A human answer",) if turn_kind == "round" else (":listo",)
    changed_at = {"open": 1, "round": 2, "synthesis": 2, "skill": 3}[turn_kind]

    def change_workspace(stage: str, _prompt: str) -> None:
        if stage == "accepted" and len(host.sent) == changed_at:
            assert run.state()["turn_kind"] == turn_kind
            target.write_bytes(b"A change during the agent turn")

    host = FakeHost(OPENING, MULTI_STEP_DISCOVERY, INVESTIGATION, observe=change_workspace)
    console = FakeConsole(answers=answers)

    outcome = run.invoke(host, console)

    step = "investigate" if turn_kind == "skill" else "discovery"
    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, step)
    assert outcome.reason and outcome.reason.startswith("Workspace changed during agent turn")
    assert target.read_bytes() == b"A change during the agent turn"
    assert len(host.sent) == changed_at
    assert len(console.confirmations) == (1 if turn_kind == "skill" else 0)
    assert run.state()["status"] == "blocked"
    blocked = run.state_path.read_bytes()
    attempt = skillrun.reconcile(run.directory, step, "retry", "tester")
    assert (attempt.status, attempt.exit_code) == ("blocked", 10)
    assert attempt.reason and attempt.reason.startswith("No matching uncertain step")
    assert run.state_path.read_bytes() == blocked
    idle = FakeHost()
    assert run.invoke(idle).exit_code == 10
    assert idle.events == []


def test_workspace_snapshot_failure_after_agent_turn_is_not_uncertain(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)

    def make_unsupported_entry(stage: str, _prompt: str) -> None:
        if stage == "accepted":
            os.mkfifo(run.workspace / "pipe")

    host = FakeHost(OPENING, observe=make_unsupported_entry)
    console = FakeConsole()
    outcome = run.invoke(host, console)

    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "discovery")
    assert outcome.reason and outcome.reason.startswith("Workspace snapshot failed")
    assert len(host.sent) == 1
    assert console.shown == []
    blocked = run.state_path.read_bytes()
    retry = skillrun.reconcile(run.directory, "discovery", "retry", "tester")
    assert (retry.status, retry.exit_code) == ("blocked", 10)
    assert retry.reason and retry.reason.startswith("No matching uncertain step")
    assert run.state_path.read_bytes() == blocked


def test_human_workspace_edit_between_turns_gets_a_fresh_prepared_digest(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)
    path = run.workspace / "working-file"
    path.write_bytes(b"Before human edit")
    digests: list[tuple[str, str]] = []

    def edit_between_turns() -> None:
        assert run.state()["status"] == "awaiting"
        path.write_bytes(b"Edited by the human")

    def record_prepared(stage: str, _prompt: str) -> None:
        if stage == "prepared":
            state = run.state()
            assert state["status"] == "prepared"
            digests.append((state["turn_kind"], state["workspace_sha256"]))

    host = FakeHost(OPENING, "Any other changes?", DISCOVERY, observe=record_prepared)
    console = FakeConsole(answers=("I edited the file.", ":listo"), on_ask=edit_between_turns)

    outcome = run.invoke(host, console)

    assert (outcome.status, outcome.exit_code) == ("complete", 0)
    (opening, old_digest), (round_kind, new_digest), (synthesis, final_digest) = digests
    assert (opening, round_kind, synthesis) == ("open", "round", "synthesis")
    assert re.fullmatch("[0-9a-f]{64}", old_digest)
    assert new_digest == final_digest == digest_reader()(run.workspace)
    assert old_digest != new_digest


def test_later_skill_blocks_if_the_last_block_breaks_its_contract(tmp_path: Path) -> None:
    run = RunFiles(tmp_path, "complete")
    invalid_last = INVESTIGATION + '\n```json\n{"count": true, "evidence": {}}\n```'
    host = FakeHost(OPENING, MULTI_STEP_DISCOVERY, invalid_last)
    console = FakeConsole()

    outcome = run.invoke(host, console)

    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "investigate")
    assert run.state()["status"] == "blocked"
    assert len(console.confirmations) == 1
    assert len(host.sent) == 3
    assert host.sent[-1].startswith("/skill:research Collect evidence within the agreed scope.")
