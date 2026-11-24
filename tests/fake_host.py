from __future__ import annotations

import json
from hashlib import sha1, sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

import skillrun

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

RUN_ID = "test-run"
GOAL = "Agree on the scope"
CONFIRMATION_ID = "operator-confirmation-001"
OPENING = "Which behavior should we preserve?"
SYNTHESIS_PREFIX = (
    "The user ended the grilling rounds. Return your shared-understanding synthesis in a "
    "fenced JSON block with exactly these fields and types:\n"
)
DISCOVERY_RESULT = '{"summary":"Agreed scope"}'
DISCOVERY = f"```json\n{DISCOVERY_RESULT}\n```"
MULTI_STEP_DISCOVERY = '```json\n{"summary":"Agreed scope","decisions":[]}\n```'
INVESTIGATION = '```json\n{"evidence":{},"count":2}\n```'
SUMMARY = '```json\n{"verified":true}\n```'
FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


class ProcessCrash(BaseException):
    """Simulate losing control before the caller can return an outcome."""


class FakeHost:
    def __init__(
        self,
        *responses: str,
        observe: Callable[[str, str], None] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.responses = iter(responses)
        self.observe = observe
        self.events = [] if events is None else events
        self.sent: list[str] = []
        self.skill_names: set[str] = set()
        self.verified_names: set[str] = set()

    def start(self, skills: Mapping[str, Path]) -> None:
        self.events.append("start")
        self.skill_names = set(skills)

    def verify_skills(self, expected: Mapping[str, str]) -> None:
        self.events.append("verify_skills")
        self.verified_names = set(expected)

    def prompt(
        self,
        text: str,
        on_prepared: Callable[[str | None], None],
        on_accepted: Callable[[], None],
    ) -> skillrun.Turn:
        self.events.append("prompt")
        response = next(self.responses)
        turn_number = len(self.sent) + 1
        self._observe("ready", text)
        on_prepared(f"cursor-{turn_number}")
        self._observe("prepared", text)
        self.sent.append(text)
        self._observe("sent", text)
        on_accepted()
        self._observe("accepted", text)
        return skillrun.Turn(response, f"leaf-{turn_number}")

    def close(self) -> None:
        self.events.append("close")

    def _observe(self, checkpoint: str, prompt: str) -> None:
        if self.observe is not None:
            self.observe(checkpoint, prompt)


class FakeConsole:
    def __init__(
        self,
        *,
        answers: Iterable[str | BaseException] = (":listo",),
        decisions: Iterable[tuple[bool, str]] = ((True, CONFIRMATION_ID),),
        on_ask: Callable[[], None] | None = None,
        on_confirm: Callable[[], None] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.answers = iter(answers)
        self.decisions = iter(decisions)
        self.on_ask = on_ask
        self.on_confirm = on_confirm
        self.events = [] if events is None else events
        self.shown: list[tuple[str, str]] = []
        self.notices: list[tuple[str, str]] = []
        self.asked: list[str] = []
        self.confirmations: list[tuple[str, dict[str, object]]] = []

    def show(self, step_id: str, text: str) -> None:
        self.events.append("show")
        self.shown.append((step_id, text))

    def notice(self, step_id: str, text: str) -> None:
        self.events.append("notice")
        self.notices.append((step_id, text))

    def ask(self, step_id: str) -> str:
        self.events.append("ask")
        self.asked.append(step_id)
        if self.on_ask is not None:
            self.on_ask()
        answer = next(self.answers)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def confirm(self, step_id: str, result: Mapping[str, object]) -> tuple[bool, str]:
        self.events.append("confirm")
        self.confirmations.append((step_id, dict(result)))
        if self.on_confirm is not None:
            self.on_confirm()
        return next(self.decisions)


class RunFiles:
    def __init__(
        self, tmp_path: Path, fixture: str = "minimal", *, workspace: Path | None = None
    ) -> None:
        work = tmp_path / "plugin"
        self.workspace = workspace if workspace is not None else tmp_path / "checkout"
        if workspace is None:
            self.workspace.mkdir()
        data = read_json(FIXTURES / f"{fixture}.json")
        for skill in data["skills"].values():
            source = FIXTURES.parent / "engine" / skill["path"]
            target = work / skill["path"]
            target.parent.mkdir(parents=True)
            content = source.read_bytes()
            target.write_bytes(content)
            if "git_blob" in skill:
                blob = f"blob {len(content)}\0".encode() + content
                skill["git_blob"] = sha1(blob, usedforsecurity=False).hexdigest()
            else:
                skill["sha256"] = sha256(content).hexdigest()
        self.plugin_path = work / f"{fixture}.json"
        self.plugin_path.write_text(json.dumps(data), encoding="utf-8")
        self.root = tmp_path / "state"
        self.directory = self.root / RUN_ID
        self.state_path = self.directory / "state.json"

    def invoke(
        self,
        host: skillrun.Host,
        console: skillrun.Console | None = None,
        *,
        goal: str = GOAL,
        plugin_path: Path | None = None,
    ) -> skillrun.RunOutcome:
        return skillrun.run_plugin(
            skillrun.load_plugin(plugin_path or self.plugin_path),
            goal=goal,
            run_id=RUN_ID,
            host=host,
            console=console if console is not None else FakeConsole(),
            workspace=self.workspace,
            state_root=self.root,
        )

    def trace_path(self, step_id: str = "discovery", attempt: int = 1, turn: int = 1) -> Path:
        return self.directory / "traces" / f"{step_id}-{attempt}-{turn}.json"

    def state(self) -> dict[str, Any]:
        return read_json(self.state_path)


def read_json(path: Path) -> dict[str, Any]:
    data: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data
