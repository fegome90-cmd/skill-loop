"""C2-C6 exercised through pipes to the Pi RPC stand-in."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from contextlib import suppress
from hashlib import sha1, sha256
from pathlib import Path
from stat import S_IMODE
from threading import Event
from typing import TYPE_CHECKING, Protocol

import pytest

import skillrun
from fake_host import (
    DISCOVERY,
    INVESTIGATION,
    MULTI_STEP_DISCOVERY,
    SUMMARY,
    FakeConsole,
    RunFiles,
    read_json,
)
from fake_pi import append_record, read_records

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fake_pi import Record

FAKE_PI = Path(__file__).with_name("fake_pi.py").resolve()
SESSION_ID = "test-session-3"
DENIED_ENV = {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "SSH_AUTH_SOCK"}


class History(Protocol):
    @property
    def entries(self) -> tuple[Mapping[str, object], ...]: ...

    @property
    def leaf_id(self) -> str | None: ...


class PiAdapter(skillrun.Host, Protocol):
    def history(self, cursor: str | None) -> History: ...


class PiProcess:
    def __init__(self, root: Path) -> None:
        self.cwd = root / "workspace"
        self.cwd.mkdir()
        self.log = root / "fake-pi.jsonl"
        self.session_dir = root / "sessions"
        self.hosts: list[PiAdapter] = []
        self.skills: dict[str, Path] = {}
        self.pins: dict[str, str] = {}
        for name in ("zeta", "alpha"):
            path = root / "copies" / name / "SKILL.md"
            path.parent.mkdir(parents=True, mode=0o700)
            path.touch(mode=0o600)
            content = f"---\nname: {name}\ndescription: Synthetic fixture\n---\n".encode()
            path.write_bytes(content)
            self.skills[name] = path
            self.pins[name] = (
                sha256(content).hexdigest()
                if name == "zeta"
                else sha1(
                    f"blob {len(content)}\0".encode() + content, usedforsecurity=False
                ).hexdigest()
            )

    def prefix(
        self, scenario: str, fault_turn: int = 1, replies: tuple[str, ...] = ()
    ) -> list[str]:
        command = [
            sys.executable,
            str(FAKE_PI),
            "--scenario",
            scenario,
            "--fault-turn",
            str(fault_turn),
            "--log",
            str(self.log),
        ]
        for reply in replies:
            command.extend(("--reply", reply))
        return command

    def host(
        self,
        scenario: str = "plain",
        *,
        fault_turn: int = 1,
        replies: tuple[str, ...] = (),
        session_id: str = SESSION_ID,
    ) -> PiAdapter:
        # Resolve at test time so RED also type-checks against the Phase 2 module.
        adapter: PiAdapter = getattr(skillrun, "PiHost")(  # noqa: B009
            cwd=self.cwd,
            session_dir=self.session_dir,
            session_id=session_id,
            command=self.prefix(scenario, fault_turn, replies),
            turn_timeout=0.65,
            command_timeout=1.2,
        )
        self.hosts.append(adapter)
        return adapter

    def started(self, scenario: str = "plain", *, fault_turn: int = 1) -> PiAdapter:
        host = self.host(scenario, fault_turn=fault_turn)
        host.start(self.skills)
        host.verify_skills(self.pins)
        return host

    def spawns(self) -> list[Record]:
        return [record for record in read_records(self.log) if record["event"] == "spawn"]

    def commands(self, kind: str | None = None) -> list[Record]:
        return [
            record["command"]
            for record in read_records(self.log)
            if record["event"] == "command" and (kind is None or record["command"]["type"] == kind)
        ]


@pytest.fixture
def pi_process(tmp_path: Path) -> Iterator[PiProcess]:
    process = PiProcess(tmp_path.resolve())
    yield process
    for host in process.hosts:
        with suppress(skillrun.HostError):
            host.close()


def noop() -> None:
    pass


def ignore_cursor(_cursor: str | None) -> None:
    pass


def assert_reaped(process: PiProcess) -> None:
    assert process.spawns()
    for spawn in process.spawns():
        with pytest.raises(ProcessLookupError):
            os.kill(spawn["pid"], 0)


def assert_dead_host(process: PiProcess, host: PiAdapter) -> None:
    assert_reaped(process)
    before = process.log.read_bytes()
    with pytest.raises(skillrun.HostError):
        host.start(process.skills)
    with pytest.raises(skillrun.HostError):
        host.verify_skills(process.pins)
    with pytest.raises(skillrun.HostError):
        host.prompt("Never send this", ignore_cursor, noop)
    with pytest.raises(skillrun.HostError):
        host.history(None)
    assert process.log.read_bytes() == before


def test_launch_passes_exact_rpc_flags_and_sanitizes_environment(
    pi_process: PiProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in DENIED_ENV:
        monkeypatch.setenv(key, "synthetic-test-value")
    monkeypatch.setenv("SKILLRUN_TEST_SENTINEL", "preserve")
    host = pi_process.host()
    previous_umask = os.umask(0)
    try:
        host.start(pi_process.skills)
    finally:
        os.umask(previous_umask)

    (spawn,) = pi_process.spawns()
    assert spawn["spawn_count"] == 1
    assert spawn["cwd"] == str(pi_process.cwd)
    assert DENIED_ENV.isdisjoint(spawn["env_keys"])
    assert "SKILLRUN_TEST_SENTINEL" in spawn["env_keys"]
    assert S_IMODE(pi_process.session_dir.stat().st_mode) == 0o700
    assert spawn["argv"] == [
        *pi_process.prefix("plain")[2:],
        "--mode",
        "rpc",
        "--session-dir",
        str(pi_process.session_dir),
        "--session-id",
        SESSION_ID,
        "--tools",
        "read,grep,find,ls",
        "--no-context-files",
        "--no-extensions",
        "--no-mcp",
        "--no-skills",
        "--no-prompt-templates",
        "--skill",
        str(pi_process.skills["zeta"]),
        "--skill",
        str(pi_process.skills["alpha"]),
    ]
    assert [command["type"] for command in pi_process.commands()] == ["get_state"]


@pytest.mark.parametrize(
    "scenario",
    ["state-rejected", "wrong-session-id", "outside-session-file", "streaming-on-start"],
)
def test_launch_reaps_unbound_session(pi_process: PiProcess, scenario: str) -> None:
    host = pi_process.host(scenario)
    with pytest.raises(skillrun.HostError):
        host.start(pi_process.skills)
    assert [command["type"] for command in pi_process.commands()] == ["get_state"]
    assert_dead_host(pi_process, host)


@pytest.mark.parametrize("session_id", ["", "UPPER", "-start", "a_b", "a" * 65, "../other"])
def test_invalid_session_id_never_spawns(pi_process: PiProcess, session_id: str) -> None:
    with pytest.raises(skillrun.HostError):
        pi_process.host(session_id=session_id).start(pi_process.skills)
    assert pi_process.spawns() == []


@pytest.mark.parametrize("defect", ["symlink", "mode", "file"])
def test_unsafe_session_dir_never_spawns(pi_process: PiProcess, defect: str) -> None:
    directory = pi_process.session_dir
    if defect == "symlink":
        real = directory.with_name("real-sessions")
        real.mkdir(mode=0o700)
        directory.symlink_to(real, target_is_directory=True)
    elif defect == "mode":
        directory.mkdir()
        directory.chmod(0o750)
    else:
        directory.touch()
    with pytest.raises(skillrun.HostError):
        pi_process.host().start(pi_process.skills)
    assert pi_process.spawns() == []


@pytest.mark.skipif(sys.platform != "darwin", reason="Checks macOS extended ACLs")
def test_session_dir_acl_granting_group_write_never_spawns(pi_process: PiProcess) -> None:
    directory = pi_process.session_dir
    directory.mkdir(mode=0o700)
    subprocess.run(
        ["/bin/chmod", "+a", "everyone allow search,add_file", str(directory)],
        check=True,
    )
    assert S_IMODE(directory.stat().st_mode) == 0o700

    with pytest.raises(skillrun.HostError):
        pi_process.host().start(pi_process.skills)
    assert pi_process.spawns() == []


@pytest.mark.parametrize("action", ["verify_skills", "prompt", "history"])
def test_use_before_start_never_spawns(pi_process: PiProcess, action: str) -> None:
    host = pi_process.host()
    with pytest.raises(skillrun.HostError):
        if action == "verify_skills":
            host.verify_skills(pi_process.pins)
        elif action == "prompt":
            host.prompt("Never send this", ignore_cursor, noop)
        else:
            host.history(None)
    assert pi_process.spawns() == []


def test_start_twice_never_spawns_a_second_child(pi_process: PiProcess) -> None:
    host = pi_process.host()
    host.start(pi_process.skills)
    with pytest.raises(skillrun.HostError):
        host.start(pi_process.skills)
    assert [spawn["spawn_count"] for spawn in pi_process.spawns()] == [1]


def test_verify_accepts_only_the_registered_pin_copies(pi_process: PiProcess) -> None:
    pi_process.started()
    assert [command["type"] for command in pi_process.commands()] == [
        "get_state",
        "get_commands",
    ]


def test_verify_detects_copy_tampered_after_start(pi_process: PiProcess) -> None:
    host = pi_process.host()
    host.start(pi_process.skills)
    pi_process.skills["zeta"].write_bytes(b"A tampered copy")
    with pytest.raises(skillrun.HostError):
        host.verify_skills(pi_process.pins)
    assert_dead_host(pi_process, host)


@pytest.mark.parametrize(
    "scenario", ["missing-skill", "extra-skill", "duplicate-skill", "mislocated-skill"]
)
def test_verify_rejects_wrong_skill_registration(pi_process: PiProcess, scenario: str) -> None:
    host = pi_process.host(scenario)
    host.start(pi_process.skills)
    with pytest.raises(skillrun.HostError):
        host.verify_skills(pi_process.pins)
    assert len(pi_process.commands("get_commands")) == 1
    assert_dead_host(pi_process, host)


@pytest.mark.parametrize(
    "scenario",
    ["plain", "interleaved", "crlf", "branch-correct", "separators", "metadata", "expanded-prompt"],
)
def test_prompt_correlates_response_settlement_and_active_leaf(
    pi_process: PiProcess, scenario: str
) -> None:
    host = pi_process.started(scenario)
    prompt = "/skill:zeta test\u2028input\u2029paragraph"

    def prepared(cursor: str | None) -> None:
        assert cursor is None
        assert pi_process.commands("prompt") == []
        append_record(pi_process.log, {"event": "test-prepared"})

    def accepted() -> None:
        assert any(record["event"] == "started-response" for record in read_records(pi_process.log))
        append_record(pi_process.log, {"event": "test-accepted"})

    turn = host.prompt(prompt, prepared, accepted)

    expected_text = (
        "Line\u2028separator\u2029paragraph\nSecond block"
        if scenario == "separators"
        else "Fixture answer"
    )
    expected_leaf = "00000004" if scenario in {"branch-correct", "metadata"} else "00000002"
    assert turn == skillrun.Turn(expected_text, expected_leaf)
    (submitted,) = pi_process.commands("prompt")
    assert submitted["message"] == prompt
    records = [
        record["command"]["type"] if record["event"] == "command" else record["event"]
        for record in read_records(pi_process.log)
    ]
    assert records == [
        "spawn",
        "get_state",
        "get_commands",
        "get_entries",
        "test-prepared",
        "prompt",
        "started-response",
        "test-accepted",
        "get_entries",
    ]
    ids = [command["id"] for command in pi_process.commands()]
    assert all(isinstance(command_id, str) for command_id in ids)
    assert len(ids) == len(set(ids))
    assert all("since" not in command for command in pi_process.commands("get_entries"))


def test_tool_turns_and_two_skills_reuse_one_process_and_cursor(pi_process: PiProcess) -> None:
    host = pi_process.started("tool")
    cursors: list[str | None] = []
    first = host.prompt("/skill:zeta first", cursors.append, noop)
    second = host.prompt("/skill:alpha second", cursors.append, noop)
    assert first == skillrun.Turn("Fixture answer", "00000004")
    assert second == skillrun.Turn("Fixture answer", "00000008")
    assert cursors == [None, first.leaf_id]
    before_first, after_first, before_second, after_second = pi_process.commands("get_entries")
    assert all("since" not in command for command in (before_first, after_first, before_second))
    assert after_second["since"] == first.leaf_id
    before, after = pi_process.commands("prompt")
    assert [before["message"], after["message"]] == ["/skill:zeta first", "/skill:alpha second"]
    assert [spawn["spawn_count"] for spawn in pi_process.spawns()] == [1]
    history = host.history(first.leaf_id)
    roles = []
    for entry in history.entries:
        message = entry["message"]
        assert isinstance(message, Mapping)
        roles.append(message["role"])
    assert roles == [
        "user",
        "assistant",
        "toolResult",
        "assistant",
    ]
    assert history.leaf_id == second.leaf_id


@pytest.mark.parametrize(
    ("scenario", "accepted"),
    [
        ("queued", False),
        ("handled", False),
        ("rejected", False),
        ("eof-before-response", False),
        ("hang-before-response", False),
        ("slow-response", False),
        ("eof-after-response", None),
        ("invalid-json", None),
        ("non-object", None),
        ("non-string-type", None),
        ("invalid-utf8", None),
        ("unknown-id", None),
        ("extension-ui", None),
        ("aborted", True),
        ("error", True),
        ("length", True),
        ("hang", True),
    ],
)
def test_bad_turn_raises_and_is_never_resent(
    pi_process: PiProcess, scenario: str, accepted: bool | None
) -> None:
    host = pi_process.started(scenario)
    checkpoints: list[tuple[str, str | None]] = []
    with pytest.raises(skillrun.HostError):
        host.prompt(
            "Submit only once",
            lambda cursor: checkpoints.append(("prepared", cursor)),
            lambda: checkpoints.append(("accepted", None)),
        )

    assert checkpoints[0] == ("prepared", None)
    if accepted is not None:
        expected = [("prepared", None)]
        if accepted:
            expected.append(("accepted", None))
        assert checkpoints == expected
    assert_dead_host(pi_process, host)
    assert [command["message"] for command in pi_process.commands("prompt")] == ["Submit only once"]


@pytest.mark.parametrize(
    "scenario",
    [
        "branch-diverged",
        "branch-mismatch",
        "branch-user-mismatch",
        "branch-extra-user",
        "branch-wrong-stop",
    ],
)
def test_matching_abandoned_branch_cannot_validate_invalid_active_turn(
    pi_process: PiProcess, scenario: str
) -> None:
    host = pi_process.started(scenario, fault_turn=2)
    first = host.prompt("Establish a cursor", ignore_cursor, noop)
    cursors: list[str | None] = []
    with pytest.raises(skillrun.HostError):
        host.prompt("Branch-sensitive prompt", cursors.append, noop)
    assert cursors == [first.leaf_id]
    assert pi_process.commands("get_entries")[-1]["since"] == first.leaf_id
    assert_dead_host(pi_process, host)
    assert [command["message"] for command in pi_process.commands("prompt")] == [
        "Establish a cursor",
        "Branch-sensitive prompt",
    ]


def test_history_is_read_only_and_reopens_the_same_session(pi_process: PiProcess) -> None:
    first = pi_process.started()
    cursor = first.prompt("Persist first turn", ignore_cursor, noop).leaf_id
    leaf = first.prompt("Persist second turn", ignore_cursor, noop).leaf_id
    history = first.history(None)
    first.close()
    assert_reaped(pi_process)

    reopened = pi_process.started()
    before = len(pi_process.commands())
    all_entries = reopened.history(None)
    tail = reopened.history(cursor)
    assert isinstance(all_entries, getattr(skillrun, "PiHistory"))  # noqa: B009
    assert isinstance(all_entries.entries, tuple)
    assert all_entries == history
    assert all_entries.leaf_id == tail.leaf_id == leaf
    assert [entry["id"] for entry in tail.entries] == ["00000003", "00000004"]
    queries = pi_process.commands()[before:]
    assert "since" not in queries[0]
    assert [(query["type"], query.get("since")) for query in queries] == [
        ("get_entries", None),
        ("get_entries", cursor),
    ]
    first_spawn, second_spawn = pi_process.spawns()
    assert first_spawn["argv"] == second_spawn["argv"]
    assert second_spawn["spawn_count"] == 2
    assert (pi_process.session_dir / f"{SESSION_ID}.jsonl").is_file()


@pytest.mark.parametrize("scenario", ["plain", "close-failure", "close-nonzero"])
def test_close_reaps_child_even_when_exit_is_unsuccessful(
    pi_process: PiProcess, scenario: str
) -> None:
    host = pi_process.started(scenario)
    if scenario == "plain":
        host.close()
    else:
        with pytest.raises(skillrun.HostError):
            host.close()
    assert_reaped(pi_process)
    events = [record["event"] for record in read_records(pi_process.log)]
    assert "eof" in events
    if scenario == "close-failure":
        assert events[-2:] == ["eof", "sigterm"]
    before = pi_process.log.read_bytes()
    host.close()
    assert pi_process.log.read_bytes() == before


def test_run_plugin_finishes_multiple_skills_with_one_pi_session(
    tmp_path: Path, pi_process: PiProcess
) -> None:
    run = RunFiles(tmp_path, "complete")
    console = FakeConsole()
    host = pi_process.host("tool", replies=(MULTI_STEP_DISCOVERY, INVESTIGATION, SUMMARY))

    outcome = run.invoke(host, console)

    assert (outcome.status, outcome.exit_code) == ("complete", 0)
    assert run.state()["status"] == "complete"
    assert len(console.confirmations) == 1
    (spawn,) = pi_process.spawns()
    argv = spawn["argv"]
    assert [argv[index + 1] for index, flag in enumerate(argv) if flag == "--skill"] == [
        str(run.directory.resolve() / "skills" / name / "SKILL.md")
        for name in ("grilling", "research", "summary")
    ]
    assert [command["message"].split()[0] for command in pi_process.commands("prompt")] == [
        "/skill:grilling",
        "/skill:research",
        "/skill:summary",
    ]
    assert_reaped(pi_process)


def test_run_plugin_pin_mismatch_never_spawns_pi(tmp_path: Path, pi_process: PiProcess) -> None:
    run = RunFiles(tmp_path)
    skill = read_json(run.plugin_path)["skills"]["grilling"]
    (run.plugin_path.parent / skill["path"]).write_bytes(b"Changed pinned bytes")
    outcome = run.invoke(pi_process.host())
    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "discovery")
    assert outcome.reason and outcome.reason.startswith("Skill pin mismatch")
    assert pi_process.spawns() == []
    assert pi_process.commands() == []


def test_run_plugin_detects_source_change_after_copy_before_spawning_pi(
    tmp_path: Path, pi_process: PiProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = RunFiles(tmp_path)
    skill = read_json(run.plugin_path)["skills"]["grilling"]
    source = run.plugin_path.parent / skill["path"]
    copy = run.directory / "skills" / "grilling" / "SKILL.md"
    pinned_bytes = source.read_bytes()
    reads = 0
    read_skill = skillrun.read_skill_bytes

    def change_after_copy(path: Path) -> bytes:
        nonlocal reads
        reads += 1
        if reads == 2:
            assert copy.read_bytes() == pinned_bytes
            path.write_bytes(b"Changed after the private copy was written")
        return read_skill(path)

    monkeypatch.setattr(skillrun, "read_skill_bytes", change_after_copy)
    outcome = run.invoke(pi_process.host())

    assert reads == 2
    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "discovery")
    assert outcome.reason and outcome.reason.startswith("Skill pin mismatch")
    assert not run.state_path.exists()
    assert pi_process.spawns() == []


def test_run_plugin_blocks_invalid_rpc_after_verified_history(
    tmp_path: Path, pi_process: PiProcess
) -> None:
    run = RunFiles(tmp_path)
    host = pi_process.host("late-invalid-json", replies=(DISCOVERY,))

    def wait_for_protocol_failure() -> None:
        (spawn,) = pi_process.spawns()
        pi_process.log.with_suffix(".emit-invalid").touch()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                os.kill(spawn["pid"], 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        pytest.fail("Pi was not reaped after emitting malformed JSON during confirmation")

    outcome = run.invoke(host, FakeConsole(on_confirm=wait_for_protocol_failure))

    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "discovery")
    assert run.state()["status"] == "blocked"
    assert len(pi_process.commands("prompt")) == 1
    assert_reaped(pi_process)


def test_run_plugin_blocks_invalid_rpc_on_stdin_eof_with_reader_busy(
    tmp_path: Path, pi_process: PiProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = RunFiles(tmp_path)
    host = pi_process.host("invalid-json-on-stdin-eof", replies=(DISCOVERY,))
    assert isinstance(host, skillrun.PiHost)
    reader_parked = Event()
    reader_can_resume = Event()
    resumed_for_join: list[bool] = []
    record_output = host._record_output

    def park_before_eof(record: dict[str, object]) -> None:
        if record.get("type") == "before_stdin_eof":
            reader_parked.set()
            resumed_for_join.append(reader_can_resume.wait(4))
        record_output(record)

    def hold_reader_until_join() -> None:
        assert reader_parked.wait(4)
        assert host._reader is not None
        join = host._reader.join

        def resume_and_join(timeout: float | None = None) -> None:
            reader_can_resume.set()
            join(timeout)

        monkeypatch.setattr(host._reader, "join", resume_and_join)

    monkeypatch.setattr(host, "_record_output", park_before_eof)
    outcome = run.invoke(host, FakeConsole(on_confirm=hold_reader_until_join))

    assert resumed_for_join == [True]
    assert [record["event"] for record in read_records(pi_process.log)][-2:] == [
        "eof",
        "invalid-json-written",
    ]
    assert_reaped(pi_process)
    assert (outcome.status, outcome.exit_code, run.state()["status"]) == ("blocked", 10, "blocked")


@pytest.mark.parametrize("scenario", ["eof-before-response", "hang"], ids=["prepared", "accepted"])
def test_run_plugin_blocks_uncertain_turn_without_relaunching_or_resending(
    tmp_path: Path, pi_process: PiProcess, scenario: str
) -> None:
    run = RunFiles(tmp_path)
    first = run.invoke(pi_process.host(scenario))
    assert (first.status, first.exit_code, first.step_id) == ("blocked", 10, "discovery")
    assert run.state()["status"] == "blocked"
    assert_reaped(pi_process)
    assert len(pi_process.commands("prompt")) == 1
    before = pi_process.log.read_bytes()

    resumed = run.invoke(pi_process.host())
    assert (resumed.status, resumed.exit_code, resumed.step_id) == ("blocked", 10, "discovery")
    assert pi_process.log.read_bytes() == before

    skillrun.reconcile(run.directory, "discovery", "retry", "tester")
    assert run.state()["status"] == "ready"
    assert pi_process.log.read_bytes() == before


def test_close_is_bounded_when_a_descendant_keeps_streaming_stdout(
    pi_process: PiProcess,
) -> None:
    host = pi_process.started("stream-descendant-on-eof")
    started = time.monotonic()
    with pytest.raises(skillrun.HostError):
        host.close()
    elapsed = time.monotonic() - started
    assert_reaped(pi_process)
    descendants = [
        record["pid"] for record in read_records(pi_process.log) if record["event"] == "descendant"
    ]
    assert len(descendants) == 1
    # Pi exits at once; the drain is bounded by command_timeout (1.2 s), far below the writer's 5 s.
    assert elapsed < 3.0
    with suppress(ProcessLookupError):
        os.kill(descendants[0], signal.SIGKILL)


def test_run_plugin_blocks_a_truncated_record_at_stdin_eof(
    tmp_path: Path, pi_process: PiProcess
) -> None:
    run = RunFiles(tmp_path)
    outcome = run.invoke(pi_process.host("truncated-record-on-stdin-eof", replies=(DISCOVERY,)))

    events = [record["event"] for record in read_records(pi_process.log)]
    assert events[-2:] == ["eof", "truncated-record-written"]
    assert_reaped(pi_process)
    assert (outcome.status, outcome.exit_code, run.state()["status"]) == ("blocked", 10, "blocked")
