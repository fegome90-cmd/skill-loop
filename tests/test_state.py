from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from stat import S_IMODE
from typing import TYPE_CHECKING

import pytest

import skillrun
from fake_host import (
    DISCOVERY,
    GOAL,
    RUN_ID,
    FakeConsole,
    FakeHost,
    ProcessCrash,
    RunFiles,
    read_json,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_run_paths_are_private_under_a_permissive_umask(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)
    previous_umask = os.umask(0)
    try:
        assert run.invoke(FakeHost(DISCOVERY)).exit_code == 0
    finally:
        os.umask(previous_umask)

    for path in (run.directory, *run.directory.rglob("*")):
        assert not path.is_symlink()
        assert S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600), path


@pytest.mark.parametrize("source", ["injected", "xdg"])
def test_run_accepts_an_alias_above_the_state_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    real_parent = tmp_path / "physical"
    real_parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    fixture = RunFiles(tmp_path)
    if source == "xdg":
        monkeypatch.setenv("XDG_STATE_HOME", str(alias))
    state_dir = "skillrun" if source == "xdg" else "state"
    host = FakeHost(DISCOVERY)

    result = skillrun.run_plugin(
        skillrun.load_plugin(fixture.plugin_path),
        goal=GOAL,
        run_id=RUN_ID,
        host=host,
        console=FakeConsole(),
        state_root=None if source == "xdg" else alias / state_dir,
    )

    assert result.exit_code == 0
    assert len(host.sent) == 1
    state_path = real_parent / state_dir / RUN_ID / "state.json"
    assert read_json(state_path)["status"] == "complete"


@pytest.mark.skipif(sys.platform != "darwin", reason="Checks macOS inherited ACLs")
def test_inherited_acl_blocks_before_creating_evidence(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)
    subprocess.run(
        [
            "/bin/chmod",
            "+a",
            "everyone allow list,search,readattr,file_inherit,directory_inherit",
            str(tmp_path),
        ],
        check=True,
    )
    host = FakeHost(DISCOVERY)
    assert run.invoke(host).exit_code == 10
    assert host.events == []
    assert not run.state_path.exists()


def test_run_returns_not_ready_without_changes_when_lock_is_held(tmp_path: Path) -> None:
    run = RunFiles(tmp_path)
    assert run.invoke(FakeHost(DISCOVERY)).exit_code == 0
    state_before = run.state_path.read_bytes()
    trace_before = run.trace_path().read_bytes()
    host = FakeHost()
    # Release the lock before joining the worker, even if the engine blocks.
    with ThreadPoolExecutor(max_workers=1) as pool, (run.directory / "lock").open("r+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert pool.submit(run.invoke, host).result(timeout=5).exit_code == 3

    assert run.state_path.read_bytes() == state_before
    assert run.trace_path().read_bytes() == trace_before
    assert host.events == []


@pytest.mark.parametrize("changed", ["goal", "plugin"])
def test_replay_preserves_a_run_bound_to_different_input(tmp_path: Path, changed: str) -> None:
    run = RunFiles(tmp_path)
    assert run.invoke(FakeHost(DISCOVERY)).exit_code == 0
    before = run.state_path.read_bytes()
    host = FakeHost()

    if changed == "goal":
        outcome = run.invoke(host, goal="A different goal")
    else:
        plugin = read_json(run.plugin_path)
        plugin["description"] = "Changed plugin with the same id"
        changed_path = tmp_path / "plugin.json"
        changed_path.write_text(json.dumps(plugin), encoding="utf-8")
        outcome = run.invoke(host, plugin_path=changed_path)

    assert outcome.exit_code == 10
    assert run.state_path.read_bytes() == before
    assert host.events == []


@pytest.mark.parametrize(
    "contents",
    [
        pytest.param("{", id="invalid-json"),
        pytest.param("[]", id="non-object"),
        pytest.param("{}", id="missing-stage"),
        pytest.param('{"status":"unknown"}', id="invalid-stage-with-missing-fields"),
        pytest.param('{"status":"settled","revision":1}', id="missing-settled-evidence"),
        pytest.param('{"status":"complete","revision":1}', id="unbound-terminal-state"),
    ],
)
def test_corrupt_state_blocks_before_accessing_phase_fields(tmp_path: Path, contents: str) -> None:
    run = RunFiles(tmp_path)
    assert run.invoke(FakeHost(DISCOVERY)).exit_code == 0
    run.state_path.write_text(contents, encoding="utf-8")
    host = FakeHost()

    assert run.invoke(host).exit_code == 10
    assert host.events == []
    assert run.state_path.read_text(encoding="utf-8") == contents


@pytest.mark.parametrize("entry", ["root", "run", "lock", "state"])
def test_run_rejects_symlinked_state_entries(tmp_path: Path, entry: str) -> None:
    run = RunFiles(tmp_path)
    assert run.invoke(FakeHost(DISCOVERY)).exit_code == 0
    original = {
        "root": run.root,
        "run": run.directory,
        "lock": run.directory / "lock",
        "state": run.state_path,
    }
    path = original[entry]
    target = tmp_path / "outside"
    is_directory = path.is_dir()
    path.rename(target)
    path.symlink_to(target, target_is_directory=is_directory)
    guarded_file = target / run.state_path.relative_to(path) if is_directory else target
    before = guarded_file.read_bytes()
    host = FakeHost()

    assert run.invoke(host).exit_code == 10
    assert host.events == []
    assert path.is_symlink()
    assert guarded_file.read_bytes() == before


@pytest.mark.parametrize(
    "defect",
    [
        "cross-run",
        "cross-step",
        "cross-attempt",
        "wrong-hash",
        "stale-rehashed",
        "missing",
        "symlink",
    ],
)
def test_settled_recovery_rejects_unbound_evidence(tmp_path: Path, defect: str) -> None:
    run = RunFiles(tmp_path)

    def crash_before_confirmation() -> None:
        assert run.state()["status"] == "settled"
        raise ProcessCrash

    with pytest.raises(ProcessCrash):
        run.invoke(FakeHost(DISCOVERY), FakeConsole(on_confirm=crash_before_confirmation))

    path = run.trace_path()
    trace = read_json(path)
    if defect == "missing":
        path.unlink()
    elif defect == "symlink":
        target = tmp_path / "external-trace.json"
        path.rename(target)
        path.symlink_to(target)
    else:
        trace.update(
            {
                "cross-run": {"run_id": "other-run"},
                "cross-step": {"step_id": "other-step"},
                "cross-attempt": {"receipt_id": f"{RUN_ID}/discovery/2"},
                "wrong-hash": {"sha256": "0" * 64},
                "stale-rehashed": {},
            }[defect]
        )
        if defect == "stale-rehashed":
            stale = DISCOVERY.replace("Agreed scope", "Old scope")
            trace.update(text=stale, sha256=sha256(stale.encode()).hexdigest())
        path.write_text(json.dumps(trace), encoding="utf-8")

    host, console = FakeHost(), FakeConsole()
    outcome = run.invoke(host, console)
    assert (outcome.exit_code, outcome.step_id) == (10, "discovery")
    assert run.state()["status"] == "blocked"
    assert host.events == []
    assert console.confirmations == []


@pytest.mark.parametrize("defect", ["symlink", "mode"])
def test_unsafe_trace_directory_persists_blocked_on_a_settled_run(
    tmp_path: Path, defect: str
) -> None:
    run = RunFiles(tmp_path)

    def crash_before_confirmation() -> None:
        raise ProcessCrash

    with pytest.raises(ProcessCrash):
        run.invoke(FakeHost(DISCOVERY), FakeConsole(on_confirm=crash_before_confirmation))

    traces = run.trace_path().parent
    original = tmp_path / "saved-traces"
    if defect == "symlink":
        traces.rename(original)
        traces.symlink_to(original, target_is_directory=True)
    else:
        traces.chmod(0o755)

    host, console = FakeHost(), FakeConsole()
    assert run.invoke(host, console).exit_code == 10
    assert run.state()["status"] == "blocked"
    assert host.events == []
    assert console.confirmations == []

    if defect == "symlink":
        traces.unlink()
        original.rename(traces)
    else:
        traces.chmod(0o700)
    blocked = run.state_path.read_bytes()
    assert run.invoke(host, console).exit_code == 10
    assert run.state_path.read_bytes() == blocked
    assert host.events == []
    assert console.confirmations == []
