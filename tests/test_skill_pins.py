"""C1 exercised at the run_plugin and Host boundaries."""

from __future__ import annotations

import json
from stat import S_IMODE
from typing import TYPE_CHECKING

import pytest

import skillrun
from fake_host import (
    DISCOVERY,
    INVESTIGATION,
    MULTI_STEP_DISCOVERY,
    SUMMARY,
    FakeHost,
    ProcessCrash,
    RunFiles,
    read_json,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


def test_run_passes_verified_private_copies_in_declaration_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = RunFiles(tmp_path, "complete")
    document = read_json(run.plugin_path)
    document["skills"] = dict(reversed(list(document["skills"].items())))
    run.plugin_path.write_text(json.dumps(document), encoding="utf-8")
    sources = {
        name: (run.plugin_path.parent / skill["path"]).resolve()
        for name, skill in document["skills"].items()
    }
    pins = {
        name: skill["git_blob"] if "git_blob" in skill else skill["sha256"]
        for name, skill in document["skills"].items()
    }
    originals = {path: path.read_bytes() for path in sources.values()}
    staged = {name: run.directory.resolve() / "skills" / name / "SKILL.md" for name in sources}
    names = {path: name for name, path in sources.items()}
    reads: list[Path] = []
    observed_skills: list[tuple[str, Path]] = []
    observed_pins: dict[str, str] = {}
    # Resolve at test time so RED also type-checks against the Phase 2 module.
    read_skill: Callable[[Path], bytes] = getattr(skillrun, "read_skill_bytes")  # noqa: B009

    def observe_read(path: Path) -> bytes:
        source = path.resolve()
        if source in reads:
            private = staged[names[source]]
            assert private.read_bytes() == originals[source]
        reads.append(source)
        return read_skill(path)

    class ObserveCopies(FakeHost):
        def start(self, skills: Mapping[str, Path]) -> None:
            observed_skills.extend(skills.items())
            assert reads == [source for source in sources.values() for _ in range(2)]
            for name, path in skills.items():
                assert path.is_absolute()
                assert not path.is_symlink()
                assert path.read_bytes() == originals[sources[name]]
                assert S_IMODE(path.stat().st_mode) == 0o600
                assert S_IMODE(path.parent.stat().st_mode) == 0o700
                assert S_IMODE(path.parent.parent.stat().st_mode) == 0o700
            super().start(skills)

        def verify_skills(self, expected: Mapping[str, str]) -> None:
            observed_pins.update(expected)
            super().verify_skills(expected)

    monkeypatch.setattr(skillrun, "read_skill_bytes", observe_read)
    outcome = run.invoke(ObserveCopies(MULTI_STEP_DISCOVERY, INVESTIGATION, SUMMARY))
    assert (outcome.status, outcome.exit_code) == ("complete", 0)
    assert reads == [source for source in sources.values() for _ in range(2)]
    assert observed_skills == list(staged.items())
    assert observed_pins == pins


def stop_at_ready(checkpoint: str, _prompt: str) -> None:
    if checkpoint == "ready":
        raise ProcessCrash


@pytest.mark.parametrize("failure", ["mismatch", "missing-source", "changed-after-read"])
def test_pin_failure_preserves_ready_state_and_prevents_all_host_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    run = RunFiles(tmp_path)
    with pytest.raises(ProcessCrash):
        run.invoke(FakeHost(DISCOVERY, observe=stop_at_ready))
    assert run.state()["status"] == "ready"
    before = run.state_path.read_bytes()
    relative = read_json(run.plugin_path)["skills"]["grilling"]["path"]
    source = (run.plugin_path.parent / relative).resolve()
    reads: list[Path] = []
    original = source.read_bytes()

    if failure == "mismatch":
        source.write_bytes(b"Wrong pin")
    elif failure == "missing-source":
        source.unlink()
    else:
        read_skill: Callable[[Path], bytes] = getattr(skillrun, "read_skill_bytes")  # noqa: B009

        def replace_after_read(path: Path) -> bytes:
            content = read_skill(path)
            if path.resolve() == source:
                reads.append(path.resolve())
                if len(reads) == 1:
                    path.write_bytes(b"Changed after the initial read")
            return content

        monkeypatch.setattr(skillrun, "read_skill_bytes", replace_after_read)

    host = FakeHost(DISCOVERY)
    outcome = run.invoke(host)
    assert (outcome.status, outcome.exit_code, outcome.step_id) == ("blocked", 10, "discovery")
    prefix = "Skill copy failed" if failure == "missing-source" else "Skill pin mismatch"
    assert outcome.reason and outcome.reason.startswith(prefix)
    assert host.events == []
    assert run.state_path.read_bytes() == before
    if failure == "changed-after-read":
        assert reads == [source, source]
        assert source.read_bytes() != original
