import fcntl
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

import skillrun
from fake_host import DISCOVERY, GOAL, MULTI_STEP_DISCOVERY, OPENING, RUN_ID, RunFiles

STATE_ARGS = ["--run-id", RUN_ID]


class CLI:
    def __init__(self, root: Path, run: RunFiles) -> None:
        self.root = root
        self.run = run
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "pi.log"
        self.env = {
            **os.environ,
            "PATH": str(self.bin),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "XDG_STATE_HOME": str(root / "xdg"),
        }
        self.directory = root / "xdg" / "skillrun" / RUN_ID

    def fake_pi(self, *args: str) -> None:
        executable = self.bin / "pi"
        fake = Path(__file__).with_name("fake_pi.py").resolve()
        prefix = ["--log", str(self.log), *args]
        executable.write_text(
            f"#!{sys.executable}\n"
            "import runpy, sys\n"
            f"sys.argv[1:1] = {prefix!r}\n"
            f"runpy.run_path({str(fake)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)

    def call(self, *args: str, answer: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", "-m", "skillrun", *args],
            cwd=self.root,
            env=self.env,
            input=answer,
            capture_output=True,
            encoding="utf-8",
            check=False,
            timeout=15,
        )

    def run_plugin(self, *, answer: str = "") -> subprocess.CompletedProcess[str]:
        return self.call(
            "run",
            str(self.run.plugin_path.relative_to(self.root)),
            "--goal",
            GOAL,
            "--cwd",
            str(self.run.workspace.relative_to(self.root)),
            *STATE_ARGS,
            answer=answer,
        )


def response(result: subprocess.CompletedProcess[str], code: int) -> dict[str, Any]:
    assert result.returncode == code, result.stderr
    assert len(result.stdout.splitlines()) == 1, result.stdout
    data = json.loads(result.stdout)
    assert isinstance(data, dict)
    assert data["run_id"] == RUN_ID
    assert data["exit_code"] == code
    return data


def test_run_prints_only_final_validated_json_and_replays_without_pi(tmp_path: Path) -> None:
    cli = CLI(tmp_path, RunFiles(tmp_path, "complete"))
    cli.fake_pi(
        "--reply",
        OPENING,
        "--reply",
        MULTI_STEP_DISCOVERY,
        "--reply",
        '```json\n{"evidence":{},"count":2}\n```',
        "--reply",
        'Private commentary\n```json\n{"verified":false}\n```\n```json\n{"verified":true}\n```',
    )

    completed = cli.run_plugin(answer=":listo\ns\n")
    data = response(completed, 0)
    assert (data["status"], data["step_id"], data["result"]) == (
        "complete",
        "summarize",
        {"verified": True},
    )
    assert OPENING in completed.stderr
    assert "¿Confirmas? [s/n]" in completed.stderr
    assert "Private commentary" not in completed.stdout

    log = cli.log.read_bytes()
    (spawn,) = [
        record for line in log.splitlines() if (record := json.loads(line))["event"] == "spawn"
    ]
    assert Path(spawn["cwd"]) == cli.run.workspace.resolve()
    flags = spawn["argv"]
    assert Path(flags[flags.index("--session-dir") + 1]) == cli.directory / "pi-session"
    assert flags[flags.index("--session-id") + 1] == RUN_ID

    (cli.bin / "pi").unlink()
    assert response(cli.run_plugin(), 0) == data
    assert cli.log.read_bytes() == log


def test_legacy_transcript_mode_reports_manual_recovery_and_preserves_resume(
    tmp_path: Path,
) -> None:
    cli = CLI(tmp_path, RunFiles(tmp_path))
    cli.fake_pi("--reply", OPENING)
    assert response(cli.run_plugin(), 130)["status"] == "cancelled"
    transcript = cli.directory / "pi-session" / f"{RUN_ID}.jsonl"
    transcript.chmod(0o644)  # Simulate a transcript created by an older release.
    receipt = cli.directory / "state.json"
    before = (receipt.read_bytes(), transcript.read_bytes(), cli.log.read_bytes())

    blocked = cli.run_plugin(answer="answer\n")
    reason = response(blocked, 10)["reason"]
    assert str(transcript) in reason
    assert "0644" in reason and "0600" in reason and "manually" in reason
    assert reason in blocked.stderr
    assert transcript.stat().st_mode & 0o777 == 0o644
    assert (receipt.read_bytes(), transcript.read_bytes(), cli.log.read_bytes()) == before

    transcript.chmod(0o600)  # The operator, not skillrun, performs the repair.
    cli.fake_pi("--reply", DISCOVERY)
    assert response(cli.run_plugin(answer=":listo\ns\n"), 0)["status"] == "complete"


def test_status_reads_the_saved_checkpoint_without_touching_pi_or_state(tmp_path: Path) -> None:
    cli = CLI(tmp_path, RunFiles(tmp_path))
    cli.fake_pi("--reply", OPENING)
    assert response(cli.run_plugin(), 130)["status"] == "cancelled"
    state_path = cli.directory / "state.json"
    state = state_path.read_bytes()
    log = cli.log.read_bytes()
    (cli.bin / "pi").unlink()

    with (cli.directory / "lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        busy = response(cli.call("status", *STATE_ARGS), 3)
        assert (busy["status"], busy["reason"]) == ("not_ready", "Run lock is held")

    current = cli.call("status", *STATE_ARGS)
    data = response(current, 3)
    assert (data["status"], data["step_id"], data["revision"]) == (
        "awaiting",
        "discovery",
        json.loads(state)["revision"],
    )
    assert state_path.read_bytes() == state
    assert cli.log.read_bytes() == log


def test_status_missing_run_does_not_create_storage(tmp_path: Path) -> None:
    cli = CLI(tmp_path, RunFiles(tmp_path))
    assert response(cli.call("status", *STATE_ARGS), 10)["status"] == "blocked"
    assert not (tmp_path / "xdg").exists()


def uncertain_run(tmp_path: Path) -> CLI:
    cli = CLI(tmp_path, RunFiles(tmp_path))
    cli.fake_pi("--scenario", "eof-before-response")
    assert response(cli.run_plugin(), 10)["status"] == "blocked"
    (cli.bin / "pi").unlink()
    return cli


@pytest.mark.parametrize(
    ("answer", "code", "status", "attempt"),
    [("reintentar", 3, "ready", 2), ("abandonar", 130, "cancelled", 1)],
)
def test_reconcile_inspects_one_receipt_then_records_explicit_decision_without_pi(
    tmp_path: Path, answer: str, code: int, status: str, attempt: int
) -> None:
    cli = uncertain_run(tmp_path)
    state = json.loads((cli.directory / "state.json").read_bytes())
    log = cli.log.read_bytes()
    assert response(cli.call("status", *STATE_ARGS), 10)["reconcilable"] is True

    reconciled = cli.call("reconcile", *STATE_ARGS, answer=answer + "\n")
    data = response(reconciled, code)
    assert (data["status"], data["step_id"]) == (status, "discovery")
    assert f"{RUN_ID}/discovery/1/1" in reconciled.stderr
    assert state["prompt_sha256"] in reconciled.stderr
    assert "reintentar / abandonar" in reconciled.stderr
    assert state["prompt_sha256"] not in reconciled.stdout
    saved = response(cli.call("status", *STATE_ARGS), code)
    assert (saved["status"], saved["attempt"], saved["revision"], saved["reconcilable"]) == (
        status,
        attempt,
        state["revision"] + 1,
        False,
    )
    assert cli.log.read_bytes() == log


def test_reconcile_never_applies_an_empty_or_unrecognized_answer(tmp_path: Path) -> None:
    cli = uncertain_run(tmp_path)
    state_path = cli.directory / "state.json"
    before = state_path.read_bytes()
    log = cli.log.read_bytes()

    data = response(cli.call("reconcile", *STATE_ARGS, answer="s\n\n"), 130)
    assert data["status"] == "cancelled"
    assert state_path.read_bytes() == before
    assert cli.log.read_bytes() == log


def test_reconcile_does_not_prompt_for_a_non_uncertain_checkpoint(tmp_path: Path) -> None:
    cli = CLI(tmp_path, RunFiles(tmp_path))
    cli.fake_pi("--reply", OPENING)
    assert response(cli.run_plugin(), 130)["status"] == "cancelled"
    before = (cli.directory / "state.json").read_bytes()

    result = cli.call("reconcile", *STATE_ARGS, answer="reintentar\n")
    assert response(result, 10)["status"] == "blocked"
    assert "reintentar / abandonar" not in result.stderr
    assert (cli.directory / "state.json").read_bytes() == before


@pytest.mark.parametrize("tamper", ["response", "receipt_id"])
def test_run_never_returns_a_result_from_an_unbound_trace(tmp_path: Path, tamper: str) -> None:
    cli = CLI(tmp_path, RunFiles(tmp_path))
    cli.fake_pi("--reply", OPENING, "--reply", DISCOVERY)
    assert response(cli.run_plugin(answer=":listo\ns\n"), 0)["result"] == {
        "summary": "Agreed scope"
    }
    trace_path = cli.directory / "traces" / "discovery-1-2.json"
    trace = json.loads(trace_path.read_bytes())
    if tamper == "response":
        trace["text"] = DISCOVERY.replace("Agreed scope", "Wrong result")
        trace["sha256"] = sha256(trace["text"].encode()).hexdigest()
    else:
        trace["receipt_id"] = f"{RUN_ID}/discovery/1/3"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    before = (cli.directory / "state.json").read_bytes()
    (cli.bin / "pi").unlink()

    data = response(cli.run_plugin(), 10)
    assert data["status"] == "blocked"
    assert "result" not in data
    assert (cli.directory / "state.json").read_bytes() == before


def test_run_with_missing_workspace_preserves_cli_error_without_writing(tmp_path: Path) -> None:
    cli = CLI(tmp_path, RunFiles(tmp_path))
    cli.fake_pi()
    cli.run.workspace.rmdir()

    result = cli.run_plugin()

    assert response(result, 10) == {
        "run_id": RUN_ID,
        "status": "blocked",
        "exit_code": 10,
        "step_id": None,
        "reason": "Unable to use run storage",
    }
    assert result.stderr == "skillrun: Unable to use run storage\n"
    assert not Path(cli.env["XDG_STATE_HOME"]).exists()
    assert not cli.log.exists()


@pytest.mark.parametrize("case_alias", [False, True])
def test_run_rejects_state_storage_inside_the_workspace(tmp_path: Path, case_alias: bool) -> None:
    cli = CLI(tmp_path, RunFiles(tmp_path))
    cli.fake_pi()
    workspace = cli.run.workspace
    if case_alias:
        workspace = workspace.with_name(workspace.name.upper())
        if not workspace.exists():
            pytest.skip("The test filesystem is case-sensitive")
    cli.env["XDG_STATE_HOME"] = str(workspace / "xdg")
    assert response(cli.run_plugin(), 10)["status"] == "blocked"
    assert not cli.log.exists()
    assert list(cli.run.workspace.iterdir()) == []


@pytest.mark.parametrize("inside_checkout", [False, True])
def test_run_from_nested_worktree_keeps_storage_outside_checkout(
    tmp_path: Path, inside_checkout: bool
) -> None:
    checkout = tmp_path / "checkout"
    workspace = checkout / "src"
    workspace.mkdir(parents=True)
    (checkout / ".git").write_text("gitdir: ../metadata\n", encoding="utf-8")
    cli = CLI(tmp_path, RunFiles(tmp_path, workspace=workspace))
    cli.fake_pi("--reply", OPENING, "--reply", DISCOVERY)
    xdg = (checkout if inside_checkout else tmp_path) / "xdg"
    cli.env["XDG_STATE_HOME"] = str(xdg)

    completed = cli.run_plugin(answer=":listo\ns\n")

    if inside_checkout:
        assert response(completed, 10)["status"] == "blocked"
        assert not xdg.exists()
        assert not cli.log.exists()
    else:
        assert response(completed, 0)["status"] == "complete"
        assert (xdg / "skillrun" / RUN_ID / "state.json").is_file()


def test_reconcile_does_not_apply_approval_to_a_new_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = uncertain_run(tmp_path)

    class OperatorInput:
        def readline(self) -> str:
            assert (
                response(cli.call("reconcile", *STATE_ARGS, answer="reintentar\n"), 3)["status"]
                == "ready"
            )
            cli.fake_pi("--scenario", "eof-before-response")
            assert response(cli.run_plugin(), 10)["status"] == "blocked"
            return "abandonar\n"

    monkeypatch.setenv("XDG_STATE_HOME", cli.env["XDG_STATE_HOME"])
    monkeypatch.setattr(sys, "stdin", OperatorInput())
    assert skillrun.main(["reconcile", *STATE_ARGS]) == 10
    data = json.loads(capsys.readouterr().out)
    assert data["reason"] == "Reconciliation evidence changed"
    current = response(cli.call("status", *STATE_ARGS), 10)
    assert (current["status"], current["attempt"], current["reconcilable"]) == ("blocked", 2, True)
