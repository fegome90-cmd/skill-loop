"""skillrun: ejecución determinista de skills en orden (ver PLAN.md)."""

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess  # nosec B404
import sys
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import asdict, dataclass, replace
from functools import cache
from os import PathLike
from pathlib import Path, PureWindowsPath
from threading import Condition, Event, Lock, Thread
from time import monotonic
from types import MappingProxyType
from typing import IO, Protocol, TextIO, TypeGuard
from uuid import uuid4

__version__ = "0.1.0"

SCHEMA = "skillrun/v1"
MAX_STEPS = 16
EXIT_DONE = 0
EXIT_USAGE = 2
EXIT_NOT_READY = 3
EXIT_BLOCKED = 10
EXIT_INTERNAL = 70
EXIT_CANCELLED = 130

_RESULT_CLASSES = {"array": list, "boolean": bool, "integer": int, "object": dict, "string": str}
RESULT_TYPES = tuple(_RESULT_CLASSES)
_ID_PATTERN = r"[a-z0-9][a-z0-9-]{0,63}"
_RESULT_FIELD_PATTERN = r"[a-z_][a-z0-9_]{0,63}"
_PIN_LENGTHS = {"sha256": 64, "git_blob": 40}


class PluginError(Exception):
    def __init__(self, errors: Iterable[str]) -> None:
        self.errors: tuple[str, ...] = tuple(sorted(errors))
        if not self.errors:
            raise ValueError("PluginError requires at least one error")
        super().__init__("\n".join(self.errors))


@dataclass(frozen=True)
class Skill:
    name: str
    path: str
    sha256: str | None
    git_blob: str | None


@dataclass(frozen=True)
class Step:
    id: str
    skill: str
    kind: str
    result: Mapping[str, str]
    instruction: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", MappingProxyType(dict(self.result)))


@dataclass(frozen=True)
class Plugin:
    id: str
    description: str | None
    skills: Mapping[str, Skill]
    steps: tuple[Step, ...]
    on_done_directive: str | None
    digest: str
    source: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "skills", MappingProxyType(dict(self.skills)))


class HostError(Exception):
    """An expected failure to start, verify, or operate the host."""


class WorkspaceSnapshotError(Exception):
    """The workspace could not be snapshotted or changed during a turn."""


@dataclass(frozen=True)
class Turn:
    text: str
    leaf_id: str


class Host(Protocol):
    def start(self, skills: Mapping[str, Path]) -> None: ...
    def verify_skills(self, expected: Mapping[str, str]) -> None: ...

    def prompt(
        self,
        text: str,
        on_prepared: Callable[[str | None], None],
        on_accepted: Callable[[], None],
    ) -> Turn: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class PiHistory:
    entries: tuple[Mapping[str, object], ...]
    leaf_id: str | None


class Console(Protocol):
    def show(self, step_id: str, text: str) -> None: ...
    def notice(self, step_id: str, text: str) -> None: ...
    def ask(self, step_id: str) -> str: ...
    def confirm(self, step_id: str, result: Mapping[str, object]) -> tuple[bool, str]: ...


class TerminalConsole:
    def __init__(
        self, *, stdin: TextIO, stderr: TextIO, new_id: Callable[[], str] = lambda: uuid4().hex
    ) -> None:
        self._stdin = stdin
        self._stderr = stderr
        self._new_id = new_id

    def show(self, step_id: str, text: str) -> None:
        print(text, file=self._stderr, flush=True)

    def notice(self, step_id: str, text: str) -> None:
        self.show(step_id, f"skillrun: {text}")

    def _readline(self, prompt: str) -> str:
        print(prompt, end="", file=self._stderr, flush=True)
        line = self._stdin.readline()
        if not line:
            raise EOFError
        return line[:-2] if line.endswith("\r\n") else line.removesuffix("\n")

    def ask(self, step_id: str) -> str:
        return self._readline("> ")

    def confirm(self, step_id: str, result: Mapping[str, object]) -> tuple[bool, str]:
        self.show(step_id, json.dumps(dict(result), indent=2, sort_keys=True, ensure_ascii=False))
        while True:
            answer = self._readline("¿Confirmas? [s/n] ").strip().lower()
            if answer in {"s", "n"}:
                return answer == "s", "console:" + self._new_id()

    def reconciliation_decision(self) -> tuple[str, str]:
        choices = {"reintentar": "retry", "abandonar": "abandon"}
        while True:
            answer = self._readline("Decisión [reintentar / abandonar]: ").strip().lower()
            if answer in choices:
                return choices[answer], "console:" + self._new_id()


@dataclass(frozen=True)
class RunOutcome:
    status: str
    exit_code: int
    step_id: str | None = None
    reason: str | None = None
    result: Mapping[str, object] | None = None


def _has_text(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _unknown_fields(data: Mapping[object, object], allowed: set[str], at: str = "") -> list[str]:
    errors = []
    prefix = f"{at}." if at else ""
    for key in data:
        if not isinstance(key, str):
            errors.append(f"{at or '$'}: unknown non-string key")
        elif key not in allowed:
            errors.append(f"{prefix + key or '$'}: unknown field")
    return errors


def _check_skill(skill: object, at: str) -> list[str]:
    if not isinstance(skill, dict):
        return [f"{at}: expected an object"]
    errors = _unknown_fields(skill, {"path", *_PIN_LENGTHS}, at)
    path = skill.get("path")
    if (
        not _has_text(path)
        or path.startswith("/")
        or PureWindowsPath(path).drive  # C:/x o C:x son absolutos/rooted en Windows
        or "\\" in path
        or "\x00" in path
        or ".." in path.split("/")
    ):
        errors.append(
            f"{at}.path: expected a relative path without drive, NUL, backslashes or '..'"
        )
    if len(skill.keys() & _PIN_LENGTHS.keys()) != 1:
        errors.append(f"{at}: expected exactly one of sha256 or git_blob")
    for pin, length in _PIN_LENGTHS.items():
        if pin in skill:
            value = skill[pin]
            if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
                errors.append(f"{at}.{pin}: expected {length} lowercase hexadecimal characters")
    return errors


def _check_result_contract(result: object, at: str) -> list[str]:
    if not isinstance(result, dict) or not result:
        return [f"{at}: expected a non-empty object"]
    errors = []
    for name, kind in result.items():
        path = f"{at}.{name}" if isinstance(name, str) else f"{at}.<non-string key>"
        if not isinstance(name, str) or not re.fullmatch(_RESULT_FIELD_PATTERN, name):
            errors.append(f"{path}: invalid result field name")
        if not isinstance(kind, str) or kind not in RESULT_TYPES:
            errors.append(f"{path}: expected one of {', '.join(RESULT_TYPES)}")
    return errors


def _check_steps(steps: object, skills: set[str]) -> list[str]:
    if not isinstance(steps, list):
        return ["steps: expected an array"]
    errors = []
    if not 1 <= len(steps) <= MAX_STEPS:
        errors.append(f"steps: expected between 1 and {MAX_STEPS} steps")
    seen_ids: set[str] = set()
    unused_skills = skills.copy()
    for index, step in enumerate(steps):
        at = f"steps[{index}]"
        if not isinstance(step, dict):
            errors.append(f"{at}: expected an object")
            continue
        errors.extend(_unknown_fields(step, {"id", "skill", "kind", "result", "instruction"}, at))
        step_id = step.get("id")
        if not isinstance(step_id, str) or not re.fullmatch(_ID_PATTERN, step_id):
            errors.append(f"{at}.id: invalid step id")
        elif step_id in seen_ids:
            errors.append(f"{at}.id: duplicate step id")
        else:
            seen_ids.add(step_id)
        skill = step.get("skill")
        if not isinstance(skill, str) or skill not in skills:
            errors.append(f"{at}.skill: expected a declared skill name")
        elif index == 0 and skill != "grilling":  # §5.3 invoca /skill:grilling
            errors.append(f"{at}.skill: the first step must use the 'grilling' skill")
        else:
            unused_skills.discard(skill)
        kind = step.get("kind")
        expected_kind = "grilling" if index == 0 else "skill"
        if not isinstance(kind, str) or kind != expected_kind:
            errors.append(f"{at}.kind: expected {expected_kind!r}")
        if ("instruction" in step or isinstance(kind, str) and kind == "skill") and not _has_text(
            step.get("instruction")
        ):
            errors.append(f"{at}.instruction: expected a non-empty string")
        errors.extend(_check_result_contract(step.get("result"), f"{at}.result"))
    errors.extend(f"skills.{name}: unused skill" for name in unused_skills)
    return errors


def validate_plugin_data(data: object) -> list[str]:
    if not isinstance(data, dict):
        return ["$: expected an object"]
    errors = _unknown_fields(data, {"schema", "id", "skills", "steps", "description", "on_done"})
    schema, plugin_id = data.get("schema"), data.get("id")
    if not isinstance(schema, str) or schema != SCHEMA:
        errors.append(f"schema: expected {SCHEMA!r}")
    if not isinstance(plugin_id, str) or not re.fullmatch(_ID_PATTERN, plugin_id):
        errors.append("id: invalid plugin id")
    if "description" in data and not _has_text(data["description"]):
        errors.append("description: expected a non-empty string")
    if "on_done" in data:
        on_done = data["on_done"]
        if not isinstance(on_done, dict):
            errors.append("on_done: expected an object")
        else:
            errors.extend(_unknown_fields(on_done, {"directive"}, "on_done"))
            if not _has_text(on_done.get("directive")):
                errors.append("on_done.directive: expected a non-empty string")

    skills = data.get("skills")
    skill_names: set[str] = set()
    if not isinstance(skills, dict) or not skills:
        errors.append("skills: expected a non-empty object")
    else:
        for name, skill in skills.items():
            if not isinstance(name, str):
                errors.append("skills.<non-string key>: skill names must be strings")
                errors.extend(_check_skill(skill, "skills.<non-string key>"))
                continue
            skill_names.add(name)
            if not re.fullmatch(_ID_PATTERN, name):
                errors.append(f"skills.{name}: invalid skill name")
            errors.extend(_check_skill(skill, f"skills.{name}"))
    errors.extend(_check_steps(data.get("steps"), skill_names))
    return sorted(errors)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def plugin_digest(data: Mapping[str, object]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_plugin(path: str | PathLike[str]) -> Plugin:
    try:
        source = Path(path).resolve()
        data = json.loads(source.read_bytes().decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, ValueError, RuntimeError) as exc:
        raise PluginError([f"$: {exc}"]) from exc
    errors = validate_plugin_data(data)
    try:
        digest = plugin_digest(data)
    except UnicodeEncodeError as exc:
        errors.append(f"$: {exc}")
    if errors:
        raise PluginError(errors)
    return Plugin(
        id=data["id"],
        description=data.get("description"),
        skills={
            name: Skill(name, skill["path"], skill.get("sha256"), skill.get("git_blob"))
            for name, skill in data["skills"].items()
        },
        steps=tuple(
            Step(step["id"], step["skill"], step["kind"], step["result"], step.get("instruction"))
            for step in data["steps"]
        ),
        on_done_directive=data.get("on_done", {}).get("directive"),
        digest=digest,
        source=source,
    )


def check_result(contract: Mapping[str, str], value: object) -> list[str]:
    if type(value) is not dict:
        return ["result: expected an object"]
    errors = []
    for field, kind in contract.items():
        if field not in value:
            errors.append(f"result.{field}: missing field")
        elif type(value[field]) is not _RESULT_CLASSES.get(kind):
            errors.append(f"result.{field}: expected {kind}")
    errors.extend(f"result.{field}: unknown field" for field in value if field not in contract)
    return sorted(errors)


_STATE_SCHEMA = "skillrun/state/v1"
_TURN_FIELDS = (
    "cursor",
    "prompt_sha256",
    "workspace_sha256",
    "answer_sha256",
    "leaf_id",
    "response_sha256",
    "confirmation_event_id",
)


class _StateError(Exception):
    """The run or its persisted evidence is missing, unsafe, or invalid."""


class _RunStorageConflictError(_StateError):
    """Managed run storage would overlap the workspace or its checkout."""


class _ConsoleClosedError(Exception):
    """The human console reached end of input."""


@contextmanager
def _human_input() -> Iterator[None]:
    try:
        yield
    except EOFError as exc:
        raise _ConsoleClosedError from exc


class _RunBusy(Exception):  # noqa: N818 - the engine handles contention as a separate outcome.
    """Another supervisor owns the run lock."""


@dataclass(frozen=True)
class _SettledTurn:
    attempt: int
    turn: int
    leaf_id: str
    response_sha256: str


@dataclass(frozen=True)
class _RunState:
    run_id: str
    plugin_digest: str
    goal_sha256: str
    step_id: str
    status: str = "ready"
    revision: int = 0
    attempt: int = 1
    turn: int = 1
    turn_kind: str = "open"
    cursor: str | None = None
    prompt_sha256: str | None = None
    workspace_sha256: str | None = None
    answer_sha256: str | None = None
    leaf_id: str | None = None
    response_sha256: str | None = None
    confirmation_event_id: str | None = None
    reason: str | None = None
    previous: _SettledTurn | None = None

    def receipt_id(self, attempt: int, turn: int) -> str:
        return f"{self.run_id}/{self.step_id}/{attempt}/{turn}"

    def settled_turn(self) -> _SettledTurn:
        if self.leaf_id is None or self.response_sha256 is None:
            raise _StateError("Missing settled evidence")
        return _SettledTurn(self.attempt, self.turn, self.leaf_id, self.response_sha256)


def _run_directory(state_root: Path | None, run_id: str) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(_ID_PATTERN, run_id):
        raise _StateError("Invalid run id")
    if state_root is None:
        xdg_state = Path(os.environ.get("XDG_STATE_HOME", ""))
        base = xdg_state if xdg_state.is_absolute() else Path.home() / ".local/state"
        state_root = base / "skillrun"
    return state_root / run_id


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _workspace_entries(
    directory_fd: int, prefix: bytes = b""
) -> Iterator[tuple[bytes, bytes, int, bytes]]:
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            path = prefix + os.fsencode(entry.name)
            info = entry.stat(follow_symlinks=False)
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(entry.name, dir_fd=directory_fd)
                yield path, b"l", mode, os.fsencode(target)
                continue
            directory = stat.S_ISDIR(info.st_mode)
            if not directory and not stat.S_ISREG(info.st_mode):
                raise WorkspaceSnapshotError("Workspace snapshot failed")
            flags = os.O_RDONLY | _file_flags()
            if directory:
                flags |= os.O_DIRECTORY
            fd = os.open(entry.name, flags, dir_fd=directory_fd)
            try:
                current = os.fstat(fd)
                if current.st_mode != info.st_mode or not os.path.samestat(info, current):
                    raise WorkspaceSnapshotError("Workspace snapshot failed")
                if directory:
                    yield path, b"d", mode, b""
                    yield from _workspace_entries(fd, path + b"/")
                else:
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        yield path, b"f", mode, hashlib.file_digest(stream, "sha256").digest()
            finally:
                os.close(fd)


def workspace_digest(root: Path) -> str:
    """Hash the workspace paths, modes and contents without traversing symlinks."""
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            entries = sorted(_workspace_entries(fd))
        finally:
            os.close(fd)
    except (OSError, RecursionError) as exc:
        raise WorkspaceSnapshotError("Workspace snapshot failed") from exc
    digest = hashlib.sha256()
    for path, kind, mode, payload in entries:
        for field in (path, kind, mode.to_bytes(2, "big"), payload):
            digest.update(len(field).to_bytes(8, "big"))
            digest.update(field)
    return digest.hexdigest()


def _decode_previous(value: object) -> _SettledTurn | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.keys() != {
        "attempt",
        "turn",
        "leaf_id",
        "response_sha256",
    }:
        raise _StateError("Invalid previous turn")
    attempt, turn, leaf_id, digest = (
        value["attempt"],
        value["turn"],
        value["leaf_id"],
        value["response_sha256"],
    )
    if (
        type(attempt) is not int
        or attempt < 1
        or type(turn) is not int
        or turn < 1
        or not _has_text(leaf_id)
        or not _is_sha256(digest)
    ):
        raise _StateError("Invalid previous turn")
    leaf_id.encode("utf-8")
    return _SettledTurn(attempt, turn, leaf_id, digest)


def _decode_state(data: dict[str, object], run_id: str) -> _RunState:
    required = {
        "schema",
        "run_id",
        "step_id",
        "plugin_digest",
        "goal_sha256",
        "status",
        "revision",
        "attempt",
        "turn",
        "turn_kind",
        "answer_sha256",
        "workspace_sha256",
        "previous",
    }
    if not required <= data.keys() or data.keys() - (required | {*_TURN_FIELDS, "reason"}):
        raise _StateError("Invalid state fields")
    if data["schema"] != _STATE_SCHEMA or data["run_id"] != run_id:
        raise _StateError("State schema or run id mismatch")
    step_id, plugin_digest, goal_sha256 = (
        data["step_id"],
        data["plugin_digest"],
        data["goal_sha256"],
    )
    if not isinstance(step_id, str) or not re.fullmatch(_ID_PATTERN, step_id):
        raise _StateError("Invalid state step id")
    if not _is_sha256(plugin_digest) or not _is_sha256(goal_sha256):
        raise _StateError("Invalid plugin or goal digest")
    revision, attempt, turn = data["revision"], data["attempt"], data["turn"]
    if type(revision) is not int or revision < 1 or type(attempt) is not int or attempt < 1:
        raise _StateError("Invalid state revision or attempt")
    turn_kind = data["turn_kind"]
    if (
        type(turn) is not int
        or turn < 1
        or not isinstance(turn_kind, str)
        or turn_kind not in {"skill", "open", "round", "synthesis"}
        or (turn == 1) != (turn_kind in {"skill", "open"})
    ):
        raise _StateError("Invalid turn identity")

    status = data["status"]
    if not isinstance(status, str) or status not in {
        "ready",
        "prepared",
        "accepted",
        "settled",
        "awaiting",
        "done",
        "blocked",
        "complete",
        "cancelled",
    }:
        raise _StateError("Invalid run status")
    details: dict[str, str] = {}
    for field in (*_TURN_FIELDS, "reason"):
        value = data.get(field)
        if value is not None:
            if not _has_text(value):
                raise _StateError(f"Invalid state field: {field}")
            value.encode("utf-8")
            details[field] = value

    if any(
        not _is_sha256(details[field])
        for field in ("prompt_sha256", "response_sha256", "answer_sha256", "workspace_sha256")
        if field in details
    ):
        raise _StateError("Invalid prompt or response digest")
    terminal = status in {"blocked", "cancelled"}
    if terminal != ("reason" in details):
        raise _StateError("Invalid state reason")
    evidence = details.keys() - {"reason"}
    if (status == "ready" and (evidence or turn != 1)) or (
        status == "complete" and not evidence and turn != 1
    ):
        raise _StateError("Unexpected turn evidence")
    if (
        evidence or status in {"prepared", "accepted", "settled", "done"}
    ) and "prompt_sha256" not in evidence:
        raise _StateError("Missing prompt digest")
    if ("workspace_sha256" in evidence) != ("prompt_sha256" in evidence):
        raise _StateError("Invalid workspace digest")
    if ("answer_sha256" in evidence) != (turn_kind == "round" and "prompt_sha256" in evidence):
        raise _StateError("Invalid answer digest")
    if "answer_sha256" in evidence and details["answer_sha256"] != details["prompt_sha256"]:
        raise _StateError("Answer digest does not match the prompt")
    settled = {"leaf_id", "response_sha256"}
    final_evidence = evidence & settled
    if final_evidence and (final_evidence != settled or status in {"prepared", "accepted"}):
        raise _StateError("Unexpected or incomplete settled evidence")
    if status == "cancelled" and final_evidence:
        raise _StateError("Unexpected settled evidence")
    if (
        status in {"settled", "done"} or (status == "complete" and evidence)
    ) and not final_evidence:
        raise _StateError("Missing settled evidence")
    if "confirmation_event_id" in evidence and (
        not final_evidence
        or turn_kind != "synthesis"
        or status not in {"done", "complete", "blocked"}
    ):
        raise _StateError("Unexpected confirmation evidence")
    previous = _decode_previous(data["previous"])
    if previous is None:
        if turn > 1 or status == "awaiting":
            raise _StateError("Missing previous turn")
    elif turn_kind == "skill" or not (
        (
            previous.attempt == attempt
            and previous.turn == turn
            and status in {"awaiting", "blocked"}
            and final_evidence
            and previous.leaf_id == details["leaf_id"]
            and previous.response_sha256 == details["response_sha256"]
        )
        or (
            previous.attempt <= attempt
            and previous.turn == turn - 1
            and (status != "awaiting" or (previous.attempt < attempt and not evidence))
        )
    ):
        raise _StateError("Invalid previous turn identity")
    return _RunState(
        run_id,
        plugin_digest,
        goal_sha256,
        step_id,
        status,
        revision,
        attempt,
        turn,
        turn_kind,
        previous=previous,
        **details,
    )


def _check_private(info: os.stat_result, name: str, *, directory: bool) -> None:
    if directory:
        correct_type = stat.S_ISDIR(info.st_mode)
    else:
        correct_type = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if (
        not correct_type
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
    ):
        raise _StateError(f"Unsafe run storage entry: {name}")


@cache
def _darwin_acl_api() -> ctypes.CDLL:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.acl_get_fd.argtypes = (ctypes.c_int,)
        libc.acl_get_fd.restype = ctypes.c_void_p
        libc.acl_free.argtypes = (ctypes.c_void_p,)
        libc.acl_free.restype = ctypes.c_int
    except (AttributeError, OSError) as exc:
        raise _StateError("Unable to inspect macOS ACLs") from exc
    return libc


def _check_open_private(fd: int, name: str, *, directory: bool = False) -> None:
    _check_private(os.fstat(fd), name, directory=directory)
    if sys.platform == "darwin":
        libc = _darwin_acl_api()
        ctypes.set_errno(0)
        acl = libc.acl_get_fd(fd)
        if acl is not None:
            libc.acl_free(acl)
            raise _StateError(f"Extended ACL on run storage entry: {name}")
        # Darwin reports ENOENT when the open object has no ACL property.
        if ctypes.get_errno() != errno.ENOENT:
            raise _StateError(f"Unable to inspect ACL on run storage entry: {name}")


def _check_entry(parent_fd: int, name: str, *, directory: bool = False) -> bool:
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    _check_private(info, name, directory=directory)
    return True


def _open_directory(parent_fd: int | None, name: str, *, create: bool) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create or parent_fd is None:
            raise
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    else:
        os.fsync(parent_fd)
    return os.open(name, flags, dir_fd=parent_fd)


def _file_flags() -> int:
    return os.O_NOFOLLOW | os.O_NONBLOCK


def _read_skill_file(name: str, *, parent_fd: int | None = None, private: bool = False) -> bytes:
    fd = os.open(name, os.O_RDONLY | _file_flags(), dir_fd=parent_fd)
    with os.fdopen(fd, "rb") as stream:
        if private:
            _check_open_private(stream.fileno(), name)
        elif not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("Expected a regular skill file")
        return stream.read()


def read_skill_bytes(path: Path) -> bytes:
    """Read the original bytes without following a SKILL.md symlink."""
    return _read_skill_file(os.fspath(path))


def _matches_pin(data: bytes, pin: str) -> bool:
    if len(pin) == _PIN_LENGTHS["sha256"]:
        return hashlib.sha256(data).hexdigest() == pin
    if len(pin) == _PIN_LENGTHS["git_blob"]:
        blob = f"blob {len(data)}\0".encode("ascii") + data
        return hashlib.sha1(blob, usedforsecurity=False).hexdigest() == pin
    return False


class _SkillCopyError(Exception):
    """A failed skill preflight, before changing a run receipt."""


@contextmanager
def _storage_errors() -> Iterator[None]:
    try:
        yield
    except (OSError, ValueError, RecursionError) as exc:
        raise _StateError("Unable to use run storage") from exc


def _read_run_json(parent_fd: int, name: str) -> dict[str, object] | None:
    if not _check_entry(parent_fd, name):
        return None
    fd = os.open(name, os.O_RDONLY | _file_flags(), dir_fd=parent_fd)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        _check_open_private(stream.fileno(), name)
        data = json.load(stream, object_pairs_hook=_unique_object)
    if not isinstance(data, dict):
        raise _StateError(f"Expected a JSON object in {name}")
    return data


def _write_private_file(parent_fd: int, name: str, data: bytes) -> None:
    _check_entry(parent_fd, name)
    temporary = f".{name}.{uuid4().hex}.tmp"
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _file_flags(), 0o600, dir_fd=parent_fd
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            _check_open_private(stream.fileno(), temporary)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_fd)


def _write_run_json(parent_fd: int, name: str, data: dict[str, object]) -> None:
    _write_private_file(parent_fd, name, (json.dumps(data, allow_nan=False) + "\n").encode("utf-8"))


class _RunStore:
    def __init__(self, run_fd: int, run_dir: Path) -> None:
        self._fd = run_fd
        self._run_dir = run_dir
        self._run_id = run_dir.name

    def stage_skills(self, plugin: Plugin) -> tuple[dict[str, Path], dict[str, str]]:
        paths: dict[str, Path] = {}
        pins: dict[str, str] = {}
        with _storage_errors(), ExitStack() as opened:
            skills_fd = _open_directory(self._fd, "skills", create=True)
            opened.callback(os.close, skills_fd)
            _check_open_private(skills_fd, "skills", directory=True)
            for name, skill in plugin.skills.items():
                if not re.fullmatch(_ID_PATTERN, name):
                    raise _StateError("Invalid skill name")
                pin = skill.sha256 if skill.sha256 is not None else skill.git_blob
                source = plugin.source.parent / skill.path
                data = read_skill_bytes(source)
                if pin is None or not _matches_pin(data, pin):
                    raise _SkillCopyError(f"Skill pin mismatch: {name}")
                skill_fd = _open_directory(skills_fd, name, create=True)
                try:
                    _check_open_private(skill_fd, name, directory=True)
                    _write_private_file(skill_fd, "SKILL.md", data)
                    staged = _read_skill_file("SKILL.md", parent_fd=skill_fd, private=True)
                finally:
                    os.close(skill_fd)
                if not _matches_pin(staged, pin) or not _matches_pin(read_skill_bytes(source), pin):
                    raise _SkillCopyError(f"Skill pin mismatch: {name}")
                paths[name] = self._run_dir / "skills" / name / "SKILL.md"
                pins[name] = pin
        return paths, pins

    def load(self) -> _RunState | None:
        with _storage_errors():
            data = _read_run_json(self._fd, "state.json")
            return None if data is None else _decode_state(data, self._run_id)

    def save(self, state: _RunState) -> _RunState:
        with _storage_errors():
            previous = self.load()
            revision = 0 if previous is None else previous.revision
            if type(state.revision) is not int or state.revision != revision:
                raise _StateError("Stale state revision")
            saved = replace(state, revision=revision + 1)
            data = {
                key: value
                for key, value in asdict(saved).items()
                if value is not None or key in {"answer_sha256", "workspace_sha256", "previous"}
            }
            data["schema"] = _STATE_SCHEMA
            _decode_state(data, self._run_id)
            _write_run_json(self._fd, "state.json", data)
            return saved

    def _trace_name(self, state: _RunState, attempt: int, turn: int) -> str:
        if (
            state.run_id != self._run_id
            or not isinstance(state.step_id, str)
            or not re.fullmatch(_ID_PATTERN, state.step_id)
            or type(attempt) is not int
            or attempt < 1
            or type(turn) is not int
            or turn < 1
        ):
            raise _StateError("Invalid trace identity")
        return f"{state.step_id}-{attempt}-{turn}.json"

    @contextmanager
    def _traces(self, *, create: bool) -> Iterator[int]:
        fd = _open_directory(self._fd, "traces", create=create)
        try:
            _check_open_private(fd, "traces", directory=True)
            yield fd
        finally:
            os.close(fd)

    def clear_trace(self, state: _RunState, target: _SettledTurn | None = None) -> None:
        attempt, turn = (
            (state.attempt, state.turn) if target is None else (target.attempt, target.turn)
        )
        with _storage_errors():
            name = self._trace_name(state, attempt, turn)
            if _check_entry(self._fd, "traces", directory=True):
                with self._traces(create=False) as fd:
                    if _check_entry(fd, name):
                        os.unlink(name, dir_fd=fd)
                        os.fsync(fd)

    def write_trace(self, state: _RunState, text: str) -> str:
        with _storage_errors():
            name = self._trace_name(state, state.attempt, state.turn)
            digest = _sha256_text(text)
            with self._traces(create=True) as fd:
                _write_run_json(
                    fd,
                    name,
                    {
                        "run_id": state.run_id,
                        "step_id": state.step_id,
                        "receipt_id": state.receipt_id(state.attempt, state.turn),
                        "text": text,
                        "sha256": digest,
                    },
                )
        return digest

    def read_trace(self, state: _RunState, target: _SettledTurn) -> str:
        with _storage_errors(), self._traces(create=False) as fd:
            data = _read_run_json(fd, self._trace_name(state, target.attempt, target.turn))
            if data is None or data.keys() != {"run_id", "step_id", "receipt_id", "text", "sha256"}:
                raise _StateError("Missing or invalid trace")
            text, digest = data["text"], data["sha256"]
            if (
                data["run_id"] != state.run_id
                or data["step_id"] != state.step_id
                or data["receipt_id"] != state.receipt_id(target.attempt, target.turn)
                or not isinstance(text, str)
                or digest != target.response_sha256
                or digest != _sha256_text(text)
            ):
                raise _StateError("Trace does not match the run receipt")
            return text


def _resolved_run_directory(run_dir: Path) -> Path:
    if not re.fullmatch(_ID_PATTERN, run_dir.name) or ".." in run_dir.parts:
        raise _StateError("Invalid run path")
    with _storage_errors():
        state_root = run_dir.absolute().parent
        if not state_root.name:
            raise _StateError("Invalid state root")
        # Resolve aliases above managed storage without following the state root itself.
        try:
            storage_parent = state_root.parent.resolve()
        except RuntimeError as exc:
            raise _StateError("Unable to resolve the state root parent") from exc
    return storage_parent / state_root.name / run_dir.name


def _require_external_run_storage(run_dir: Path, workspace: Path) -> None:
    try:
        workspace = workspace.resolve(strict=True)
    except RuntimeError as exc:
        raise _StateError("Unable to resolve the workspace") from exc
    storage_ancestors = []
    for directory in (run_dir, *run_dir.parents):
        with suppress(FileNotFoundError):
            storage_ancestors.append(directory.lstat())

    def contains(info: os.stat_result) -> bool:
        # Compare filesystem identity, not spelling on case-insensitive volumes.
        return any(os.path.samestat(info, ancestor) for ancestor in storage_ancestors)

    if contains(workspace.stat()):
        raise _RunStorageConflictError("Run storage must be outside the workspace")
    for parent in workspace.parents:
        if contains(parent.stat()):
            with suppress(FileNotFoundError):
                # A linked worktree or submodule may have a .git file, not a directory.
                (parent / ".git").lstat()
                raise _RunStorageConflictError("Run storage must be outside the enclosing checkout")


@contextmanager
def _locked_run(
    run_dir: Path, *, create: bool, workspace: Path | None = None
) -> Iterator[_RunStore]:
    try:
        import fcntl
    except ImportError as exc:
        raise _StateError("Run storage requires POSIX file locking") from exc
    run_dir = _resolved_run_directory(run_dir)
    with ExitStack() as opened:
        with _storage_errors():
            if workspace is not None:
                _require_external_run_storage(run_dir, workspace)
            root, *parents = run_dir.parent.parts
            parent_fd = _open_directory(None, root, create=False)
            opened.callback(os.close, parent_fd)
            for part in parents:
                parent_fd = _open_directory(parent_fd, part, create=create)
                opened.callback(os.close, parent_fd)
            _check_open_private(parent_fd, "state root", directory=True)
            run_fd = _open_directory(parent_fd, run_dir.name, create=create)
            opened.callback(os.close, run_fd)
            _check_open_private(run_fd, "run directory", directory=True)

            if not _check_entry(run_fd, "lock") and not create:
                raise _StateError("Missing run lock")
            lock_fd = os.open(
                "lock",
                os.O_RDWR | _file_flags() | (os.O_CREAT if create else 0),
                0o600,
                dir_fd=run_fd,
            )
            opened.callback(os.close, lock_fd)
            _check_open_private(lock_fd, "lock")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
                    raise _RunBusy("Run lock is held") from exc
                raise
            _check_entry(run_fd, "state.json")
        store = _RunStore(run_fd, run_dir)
        try:
            yield store
        finally:
            store._fd = -1


_IN_FLIGHT = ("prepared", "accepted")
_UNCERTAIN = "Prompt delivery is uncertain"
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)\r?$", re.MULTILINE)


class _InvalidTurnError(Exception):
    """The host broke the callback or settled-turn contract."""


def _reject_json_constant(_constant: str) -> object:
    raise ValueError("Invalid JSON constant")


def _rpc_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HostError("Expected a Pi RPC object")
    return value


def _active_branch(history: PiHistory, cursor: str | None) -> list[Mapping[str, object]]:
    entries: dict[str, Mapping[str, object]] = {}
    for item in history.entries:
        entry_id = item.get("id")
        if not _has_text(entry_id) or entry_id in entries:
            raise HostError("Invalid Pi history entry id")
        entries[entry_id] = item

    branch: list[Mapping[str, object]] = []
    current = history.leaf_id
    while current != cursor:
        entry = entries.pop(current, None) if current is not None else None
        if entry is None or "parentId" not in entry or not isinstance(entry.get("type"), str):
            raise HostError("Pi active branch does not reach the turn cursor")
        parent = entry["parentId"]
        if parent is not None and not _has_text(parent):
            raise HostError("Invalid Pi history parent id")
        branch.append(entry)
        current = parent
    return branch


def _bound_turn(
    history: PiHistory,
    cursor: str | None,
    user: Mapping[str, object],
    assistant: Mapping[str, object],
    *,
    literal_text: str | None = None,
) -> Turn:
    leaf = history.leaf_id
    if leaf is None or leaf == cursor:
        raise HostError("Pi did not advance the active branch")
    messages: list[dict[str, object]] = []
    for entry in _active_branch(history, cursor):
        if entry["type"] == "message":
            message = _rpc_object(entry.get("message"))
            role = message.get("role")
            if role not in ("system", "user", "assistant", "toolResult"):
                raise HostError("Invalid role on the Pi active branch")
            if role != "system":
                messages.append(message)

    # The walk ran from leaf to cursor, so the final assistant is first here.
    if (
        len(messages) < 2
        or messages[-1].get("role") != "user"
        or any(message.get("role") == "user" for message in messages[:-1])
        or messages[-1].get("content") != user["content"]
        or messages[0].get("role") != "assistant"
        or messages[0].get("stopReason") != "stop"
        or messages[0].get("content") != assistant["content"]
    ):
        raise HostError("Pi active branch does not match the settled turn")
    if literal_text is not None:
        persisted = messages[-1]["content"]
        if persisted not in (literal_text, [{"type": "text", "text": literal_text}]):
            raise HostError("Pi did not preserve the human answer in session history")
    blocks = assistant["content"]
    if not isinstance(blocks, list):
        raise HostError("Invalid final Pi message content")
    text: list[str] = []
    for raw in blocks:
        block = _rpc_object(raw)
        if block.get("type") == "text":
            part = block.get("text")
            if not isinstance(part, str):
                raise HostError("Invalid Pi text block")
            text.append(part)
    return Turn("\n".join(text), leaf)


class _PiStdoutClosedError(HostError):
    """Pi closed stdout, which is only expected during close()."""


class _PiResumeBindingError(HostError):
    """Pi could not prove continuity with a saved turn before sending a prompt."""


class _PiLegacyTranscriptModeError(HostError):
    """A legacy transcript requires manual repair before Pi can start."""


_PI_STDOUT_POLL_SECONDS = 0.1


class PiHost:
    """Drive one Pi RPC child and verify turns against its active session branch."""

    def __init__(
        self,
        *,
        cwd: Path,
        session_dir: Path,
        session_id: str,
        command: Sequence[str] = ("pi",),
        turn_timeout: float = 600.0,
        command_timeout: float = 30.0,
    ) -> None:
        self._cwd = cwd.absolute()
        self._session_dir = self._cwd / session_dir
        self._session_id = session_id
        self._command = tuple(command)
        self._turn_timeout = turn_timeout
        self._command_timeout = command_timeout
        self._skills: dict[str, Path] = {}
        self._skill_pins: dict[str, str] | None = None
        self._session_file: Path | None = None
        self._literal_profile = False
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: Thread | None = None
        self._dead = False
        self._reap_lock = Lock()
        self._clean_exit: bool | None = None
        self._stop_reader = Event()
        self._reader_done = Event()
        self._stdout_eof = False
        self._received = Condition()
        self._pending: str | None = None
        self._failure: str | None = None
        self._response: tuple[float, dict[str, object]] | None = None
        self._events: deque[tuple[float, dict[str, object]]] = deque()
        self._collecting_turn = False
        self._closing = False
        self._drain_deadline = 0.0

    @contextmanager
    def _operation(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            # A receipt callback can fail independently of Pi. Preserve its exception.
            with suppress(Exception):
                self._shutdown()
            raise

    def _resolved_path(self, value: str) -> Path:
        try:
            return (self._cwd / value).resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise HostError("Unable to resolve a Pi path") from exc

    def _prepare_session_storage(self, *, grilling: bool) -> Path | None:
        try:
            session_fd = _open_directory(None, str(self._session_dir), create=False)
            try:
                _check_open_private(session_fd, "Pi session directory", directory=True)
                # Pi selects an existing session from the JSONL files in this directory.
                for name in os.listdir(session_fd):
                    if not name.endswith(".jsonl"):
                        continue
                    info = os.stat(name, dir_fd=session_fd, follow_symlinks=False)
                    if (
                        info.st_mode == stat.S_IFREG | 0o644
                        and info.st_nlink == 1
                        and info.st_uid == os.geteuid()
                    ):
                        path = ascii(str(self._session_dir / name))
                        raise _PiLegacyTranscriptModeError(
                            f"Pi transcript {path} has mode 0644; manually set this file to "
                            "0600, then rerun with the same arguments."
                        )
                    _check_private(info, name, directory=False)
                    fd = os.open(name, os.O_RDONLY | _file_flags(), dir_fd=session_fd)
                    try:
                        _check_open_private(fd, name)
                    finally:
                        os.close(fd)
                if not grilling:
                    return None
                # Pi treats a prompt argument as a filename if it exists in the workspace.
                # Supply a known private file rather than ambiguous inline text.
                name = "grilling-host.txt"
                _write_private_file(
                    session_fd,
                    name,
                    b"When grilling needs a workspace fact, this host cannot delegate to a "
                    b"sub-agent. Inspect the workspace directly with its read-only tools "
                    b"(read, grep, find, ls). State what you could not verify; do not guess.",
                )
                return self._session_dir / name
            finally:
                os.close(session_fd)
        except (OSError, _StateError) as exc:
            raise HostError("Unsafe Pi session storage") from exc

    def start(self, skills: Mapping[str, Path]) -> None:
        with self._operation():
            if self._dead or self._process is not None:
                raise HostError("Pi host cannot be started again")
            if not re.fullmatch(_ID_PATTERN, self._session_id):
                raise HostError("Invalid Pi session id")
            self._skills = dict(skills)
            self._session_file = self._launch(literal_profile=False)

    def _launch(self, *, literal_profile: bool) -> Path:
        try:
            self._session_dir.mkdir(mode=0o700, exist_ok=True)
            guidance = self._prepare_session_storage(grilling="grilling" in self._skills)
            session_root = self._resolved_path(str(self._session_dir.parent))
            session_root /= self._session_dir.name
            if not self._command:
                raise HostError("Missing Pi executable")
            argv = [
                *self._command,
                "--mode",
                "rpc",
                "--session-dir",
                str(self._session_dir),
                "--session-id",
                self._session_id,
                "--tools",
                "read,grep,find,ls",
                "--no-context-files",
                "--no-extensions",
                "--no-mcp",
                "--no-skills",
                "--no-prompt-templates",
            ]
            if guidance is not None:
                argv.extend(("--append-system-prompt", str(guidance)))
            if not literal_profile:
                for path in self._skills.values():
                    argv.extend(("--skill", str(path)))
            env = os.environ.copy()
            for key in (
                "GH_TOKEN",
                "GITHUB_TOKEN",
                "GH_ENTERPRISE_TOKEN",
                "GITHUB_ENTERPRISE_TOKEN",
                "SSH_AUTH_SOCK",
            ):
                env.pop(key, None)
            # Pi runs with an explicit argv and no shell.
            process = subprocess.Popen(  # nosec B603
                argv,
                cwd=self._cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                bufsize=0,
                umask=0o077,
            )
            self._process = process
            assert process.stdin is not None and process.stdout is not None
            os.set_blocking(process.stdin.fileno(), False)
            self._reader = Thread(
                target=self._read_output,
                args=(process, process.stdout),
                name="skillrun-pi-reader",
                daemon=True,
            )
            self._reader.start()
        except (OSError, ValueError, RuntimeError) as exc:
            raise HostError("Unable to launch Pi RPC") from exc

        data = self._request("get_state")
        session_file = data.get("sessionFile")
        if (
            data.get("sessionId") != self._session_id
            or data.get("isStreaming") is not False
            or not _has_text(session_file)
        ):
            raise HostError("Pi reported the wrong session state")
        bound = self._resolved_path(session_file)
        if session_root not in bound.parents:
            raise HostError("Pi session file is outside its private directory")
        return bound

    def verify_skills(self, expected: Mapping[str, str]) -> None:
        with self._operation():
            self._live_process()
            self._verify_registered_skills(self._check_skill_copies(expected))
            self._skill_pins = dict(expected)

    def _check_skill_copies(self, expected: Mapping[str, str]) -> dict[str, Path]:
        if self._skills.keys() != expected.keys():
            raise HostError("Pi skill names do not match the pins")
        remaining: dict[str, Path] = {}
        try:
            for name, path in self._skills.items():
                data = _read_skill_file(str(self._cwd / path), private=True)
                if not _matches_pin(data, expected[name]):
                    raise HostError("Pi skill copy does not match its pin")
                remaining[f"skill:{name}"] = self._resolved_path(str(path))
        except (OSError, _StateError, ValueError) as exc:
            raise HostError("Unable to read a private Pi skill copy") from exc
        return remaining

    def _verify_registered_skills(self, remaining: dict[str, Path]) -> None:
        commands = self._request("get_commands").get("commands")
        if not isinstance(commands, list):
            raise HostError("Invalid Pi command list")
        for raw in commands:
            command = _rpc_object(raw)
            if command.get("source") != "skill":
                continue
            registered_name = command.get("name")
            source = _rpc_object(command.get("sourceInfo")).get("path")
            if (
                not isinstance(registered_name, str)
                or not _has_text(source)
                or remaining.pop(registered_name, None) != self._resolved_path(source)
            ):
                raise HostError("Unexpected Pi skill registration")
        if remaining:
            raise HostError("Missing Pi skill registration")

    def _read_output(self, process: subprocess.Popen[bytes], stream: IO[bytes]) -> None:
        partial = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(stream, selectors.EVENT_READ)
                while True:
                    timeout = _PI_STDOUT_POLL_SECONDS
                    if self._stop_reader.is_set():
                        remaining = self._drain_deadline - monotonic()
                        if remaining <= 0:
                            raise HostError("Pi RPC stdout stayed open after exit")
                        timeout = min(timeout, remaining)
                    if not selector.select(timeout):
                        # An idle pipe may still be open in a descendant; keep looking for EOF.
                        continue
                    chunk = os.read(stream.fileno(), 65536)
                    if not chunk:
                        if partial:
                            # Bytes after the last LF are a truncated record, never a clean EOF.
                            raise HostError("Pi RPC stdout ended inside a record")
                        raise _PiStdoutClosedError("Pi RPC stdout ended")
                    *lines, tail = chunk.split(b"\n")
                    for line in lines:
                        partial.extend(line)
                        record = _rpc_object(
                            json.loads(
                                partial.removesuffix(b"\r").decode("utf-8"),
                                object_pairs_hook=_unique_object,
                                parse_constant=_reject_json_constant,
                            )
                        )
                        partial.clear()
                        self._record_output(record)
                    partial.extend(tail)
        except (OSError, ValueError, RecursionError, HostError) as exc:
            with self._received:
                # Only stdout EOF is expected once close() has asked Pi to exit.
                if self._closing and isinstance(exc, _PiStdoutClosedError):
                    self._stdout_eof = True
                else:
                    self._failure = (
                        str(exc) if isinstance(exc, HostError) else "Invalid Pi RPC stream"
                    )
                self._received.notify_all()
            self._reap(process)
        finally:
            try:
                stream.close()
            finally:
                self._reader_done.set()

    def _record_output(self, record: dict[str, object]) -> None:
        kind = record.get("type")
        if not isinstance(kind, str) or kind == "extension_ui_request":
            raise HostError("Invalid Pi RPC record type")
        received = monotonic(), record
        with self._received:
            if kind == "response":
                if self._pending is None or record.get("id") != self._pending:
                    raise HostError("Unexpected Pi response id")
                self._pending = None
                self._response = received
            elif self._collecting_turn and kind in ("message_end", "agent_settled"):
                self._events.append(received)
            else:
                return
            self._received.notify_all()

    def _live_process(self) -> subprocess.Popen[bytes]:
        if self._failure is not None:
            raise HostError(self._failure)
        if self._dead or self._process is None:
            raise HostError("Pi host is not running")
        return self._process

    def _send(self, stream: IO[bytes], payload: bytes, deadline: float) -> None:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(stream, selectors.EVENT_WRITE)
                remaining = memoryview(payload)
                while remaining:
                    timeout = deadline - monotonic()
                    if timeout <= 0 or not selector.select(timeout):
                        raise HostError("Pi RPC send timed out")
                    with self._received, suppress(BlockingIOError):
                        self._live_process()
                        remaining = remaining[os.write(stream.fileno(), remaining) :]
        except (OSError, ValueError) as exc:
            raise HostError("Unable to write to Pi RPC stdin") from exc

    def _wait_record(self, deadline: float, *, response: bool) -> dict[str, object]:
        with self._received:
            while True:
                self._live_process()
                if response and self._response is not None:
                    received, record = self._response
                    self._response = None
                    break
                if not response and self._events:
                    received, record = self._events.popleft()
                    break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise HostError("Pi RPC timed out")
                self._received.wait(remaining)
        if received > deadline:
            raise HostError("Pi RPC timed out")
        return record

    def _request(
        self, kind: str, *, deadline: float | None = None, **fields: object
    ) -> dict[str, object]:
        if deadline is None:
            deadline = monotonic() + self._command_timeout
        request_id = uuid4().hex
        payload = (json.dumps({"id": request_id, "type": kind, **fields}) + "\n").encode("utf-8")
        with self._received:
            process = self._live_process()
            self._pending = request_id
            if kind == "prompt":
                self._events.clear()
                self._collecting_turn = True
        assert process.stdin is not None
        self._send(process.stdin, payload, deadline)
        response = self._wait_record(deadline, response=True)
        if response.get("success") is not True:
            raise HostError(f"Pi rejected {kind}")
        return _rpc_object(response.get("data"))

    def _history(self, cursor: str | None) -> PiHistory:
        data = (
            self._request("get_entries")
            if cursor is None
            else self._request("get_entries", since=cursor)
        )
        entries, leaf = data.get("entries"), data.get("leafId")
        if (
            not isinstance(entries, list)
            or "leafId" not in data
            or (leaf is not None and not _has_text(leaf))
        ):
            raise HostError("Invalid Pi history response")
        return PiHistory(tuple(_rpc_object(entry) for entry in entries), leaf)

    def history(self, cursor: str | None) -> PiHistory:
        with self._operation():
            return self._history(cursor)

    def prompt(
        self,
        text: str,
        on_prepared: Callable[[str | None], None],
        on_accepted: Callable[[], None],
    ) -> Turn:
        return self._prompt(text, on_prepared, on_accepted)

    def _reopen_for_prompt(self, history: PiHistory, *, literal_profile: bool) -> None:
        try:
            if self._skill_pins is None or self._session_file is None or history.leaf_id is None:
                raise HostError("Missing verified Pi session or skill evidence")
            _active_branch(history, None)
            # Close and join the old reader before reusing any transport state.
            self.close()
            self._process = None
            self._reader = None
            self._clean_exit = None
            self._stop_reader.clear()
            self._reader_done.clear()
            self._stdout_eof = False
            self._pending = None
            self._response = None
            self._events.clear()
            self._collecting_turn = False
            self._closing = False
            self._drain_deadline = 0.0
            self._dead = False

            self._check_skill_copies(self._skill_pins)
            if self._launch(literal_profile=literal_profile) != self._session_file:
                raise HostError("Pi reopened a different session file")
            if not literal_profile:
                self.verify_skills(self._skill_pins)
            elif self._request("get_commands").get("commands") != []:
                raise HostError("Pi literal profile registered a prompt command")
            reopened = self._history(None)
            if reopened.leaf_id != history.leaf_id:
                raise HostError("Pi reopened a different active leaf")
            _active_branch(reopened, None)
            self._literal_profile = literal_profile
        except _PiLegacyTranscriptModeError:
            raise
        except HostError as exc:
            raise _PiResumeBindingError(
                "Pi could not reopen the same verified session for the next turn"
            ) from exc

    def _prompt(
        self,
        text: str,
        on_prepared: Callable[[str | None], None],
        on_accepted: Callable[[], None],
        *,
        resume_leaf: str | None = None,
        literal: bool = False,
    ) -> Turn:
        with self._operation():
            try:
                history = self._history(None)
                if resume_leaf is not None and not any(
                    entry["id"] == resume_leaf for entry in _active_branch(history, None)
                ):
                    raise HostError("Saved turn is not on the active branch")
            except HostError as exc:
                if resume_leaf is None:
                    raise
                raise _PiResumeBindingError(
                    "Pi active branch does not reach the saved verified turn"
                ) from exc
            # Stock Pi matches a registered skill only at the start of the input
            # and uses an ASCII space to separate the skill name from arguments.
            command = text.partition(" ")[0]
            might_expand = command.startswith("/skill:") and (
                command.removeprefix("/skill:") in self._skills
            )
            literal_profile = literal and (self._literal_profile or might_expand)
            if literal_profile != self._literal_profile:
                self._reopen_for_prompt(history, literal_profile=literal_profile)
            cursor = history.leaf_id
            on_prepared(cursor)
            deadline = monotonic() + self._turn_timeout
            data = self._request("prompt", message=text, deadline=deadline)
            if data.get("disposition") != "started":
                raise HostError("Pi did not start the prompt")
            on_accepted()
            user, assistant = self._turn_messages(deadline)
            return _bound_turn(
                self._history(cursor),
                cursor,
                user,
                assistant,
                literal_text=text if literal else None,
            )

    def _turn_messages(self, deadline: float) -> tuple[dict[str, object], dict[str, object]]:
        user = assistant = None
        while True:
            event = self._wait_record(deadline, response=False)
            if event["type"] == "agent_settled":
                with self._received:
                    self._collecting_turn = False
                    self._events.clear()
                if event.get("aborted") is not False:
                    raise HostError("Pi turn was aborted or failed to settle")
                break
            message = _rpc_object(event.get("message"))
            if message.get("role") == "assistant":
                assistant = message
            elif message.get("role") == "user":
                if user is not None:
                    raise HostError("Multiple user messages in the Pi turn")
                user = message
        if (
            user is None
            or not isinstance(user.get("content"), (str, list))
            or assistant is None
            or assistant.get("stopReason") != "stop"
            or not isinstance(assistant.get("content"), list)
        ):
            raise HostError("Pi turn did not end with a final assistant message")
        return user, assistant

    def _reap(self, process: subprocess.Popen[bytes]) -> bool:
        with self._reap_lock:
            if self._clean_exit is not None:
                return self._clean_exit
            try:
                if process.stdin is not None:
                    with suppress(OSError):
                        process.stdin.close()
                killed = False
                try:
                    process.wait(timeout=self._command_timeout)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=self._command_timeout)
                    except subprocess.TimeoutExpired:
                        killed = True
                        process.kill()
                        try:
                            process.wait(timeout=self._command_timeout)
                        except subprocess.TimeoutExpired:
                            return False
                self._clean_exit = not killed and process.returncode == 0
                return self._clean_exit
            finally:
                if not self._stop_reader.is_set():
                    self._drain_deadline = monotonic() + self._command_timeout
                    self._stop_reader.set()

    def _join_reader(self, process: subprocess.Popen[bytes]) -> bool:
        reader = self._reader
        if reader is None or reader.ident is None:
            if process.stdout is not None:
                process.stdout.close()
            return False
        deadline = self._drain_deadline + _PI_STDOUT_POLL_SECONDS
        reader.join(timeout=max(0.0, deadline - monotonic()))
        # On older Python versions, an interrupted join can incorrectly report a dead thread.
        return self._reader_done.wait(max(0.0, deadline - monotonic())) and not reader.is_alive()

    def _shutdown(self, *, closing: bool = False) -> bool:
        process = self._process
        try:
            self._dead = True
            if process is None:
                return True
            if closing:
                with self._received:
                    self._closing = True
            clean_exit = self._reap(process)
            joined = self._join_reader(process)
        except KeyboardInterrupt:
            # The host is already dead to callers. Finish cleanup here, before
            # propagating the interruption, rather than relying on a second close().
            if process is None:
                raise
            with suppress(Exception, KeyboardInterrupt):
                process.kill()
            with suppress(Exception, KeyboardInterrupt):
                self._reap(process)
            with suppress(Exception, KeyboardInterrupt):
                self._join_reader(process)
            raise
        return clean_exit and joined and self._stdout_eof

    def close(self) -> None:
        if self._dead:
            return
        clean_exit = self._shutdown(closing=True)
        # A fatal record seen after the last turn still invalidates the session.
        if not clean_exit or self._failure is not None:
            raise HostError("Pi RPC did not shut down cleanly")


def _step_result(step: Step, text: str) -> Mapping[str, object] | None:
    fence = ""
    json_start = None
    last_block = None
    for match in _FENCE.finditer(text):
        marker, info = match.groups()
        if not fence:
            fence = marker
            if info.strip() == "json":
                json_start = match.end()
                last_block = None  # An unterminated final JSON block is invalid too.
        elif marker.startswith(fence) and not info.strip():
            if json_start is not None:
                last_block = text[json_start : match.start()]
                json_start = None
            fence = ""

    if last_block is None:
        return None
    try:
        result: object = json.loads(
            last_block, object_pairs_hook=_unique_object, parse_constant=_reject_json_constant
        )
        if not isinstance(result, dict) or check_result(step.result, result):
            return None
        # A valid numeric literal can still overflow to infinity during decoding.
        json.dumps(result, allow_nan=False)
    except (ValueError, RecursionError):
        return None
    return result


def _prompt_text(step: Step, goal: str) -> str:
    if step.kind == "grilling":
        return f"/skill:grilling {goal}"
    contract = json.dumps(dict(step.result), sort_keys=True)
    return (
        f"/skill:{step.skill} {step.instruction}\n\n"
        f"Return the result in a fenced JSON block with exactly these fields and types:\n{contract}"
    )


def _grilling_input(state: _RunState, step: Step, console: Console) -> tuple[_RunState, str]:
    if state.previous is None:
        raise _StateError("Missing previous turn")
    with _human_input():
        answer = console.ask(step.id)
        while not answer.strip():
            answer = console.ask(step.id)
    synthesis = answer.strip() == ":listo"
    next_turn = replace(
        state,
        status="ready",
        turn=state.previous.turn + 1,
        turn_kind="synthesis" if synthesis else "round",
        cursor=None,
        prompt_sha256=None,
        workspace_sha256=None,
        leaf_id=None,
        response_sha256=None,
        answer_sha256=None,
    )
    if synthesis:
        contract = json.dumps(dict(step.result), sort_keys=True)
        answer = (
            "The user ended the grilling rounds. Return your shared-understanding synthesis "
            f"in a fenced JSON block with exactly these fields and types:\n{contract}"
        )
    return next_turn, answer


@contextmanager
def _started_host(host: Host, paths: Mapping[str, Path], pins: Mapping[str, str]) -> Iterator[None]:
    try:
        host.start(paths)
        host.verify_skills(pins)
        yield
    except BaseException:
        # Preserve the original failure if cleanup also fails.
        with suppress(Exception, KeyboardInterrupt):
            host.close()
        raise
    else:
        host.close()


def _send_turn(
    store: _RunStore,
    state: _RunState,
    host: Host,
    text: str,
    workspace: Path,
    *,
    resume_leaf: str | None = None,
) -> _RunState:
    prompt_sha256 = _sha256_text(text)
    workspace_sha256 = workspace_digest(workspace)
    active = True
    invalid_callback = False

    def require_phase(phase: str, *, valid: bool = True) -> None:
        nonlocal invalid_callback
        if not active or invalid_callback or state.status != phase or not valid:
            invalid_callback = True
            raise _InvalidTurnError

    def on_prepared(cursor: str | None) -> None:
        nonlocal state
        require_phase("ready", valid=cursor is None or _has_text(cursor))
        state = store.save(
            replace(
                state,
                status="prepared",
                cursor=cursor,
                prompt_sha256=prompt_sha256,
                workspace_sha256=workspace_sha256,
                answer_sha256=prompt_sha256 if state.turn_kind == "round" else None,
            )
        )

    def on_accepted() -> None:
        nonlocal state
        require_phase("prepared")
        state = store.save(replace(state, status="accepted"))

    try:
        if isinstance(host, PiHost):
            turn = host._prompt(
                text,
                on_prepared,
                on_accepted,
                resume_leaf=resume_leaf,
                literal=state.turn_kind == "round",
            )
        else:
            turn = host.prompt(text, on_prepared, on_accepted)
    finally:
        active = False
    if invalid_callback or state.status != "accepted":
        raise _InvalidTurnError
    if not isinstance(turn, Turn) or not isinstance(turn.text, str) or not _has_text(turn.leaf_id):
        raise _InvalidTurnError
    try:
        turn.text.encode("utf-8")
        turn.leaf_id.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _InvalidTurnError from exc
    if workspace_digest(workspace) != workspace_sha256:
        raise WorkspaceSnapshotError("Workspace changed during agent turn")
    response_sha256 = store.write_trace(state, turn.text)
    return store.save(
        replace(state, status="settled", leaf_id=turn.leaf_id, response_sha256=response_sha256)
    )


def _block_step(store: _RunStore, state: _RunState, reason: str) -> RunOutcome:
    blocked = store.save(replace(state, status="blocked", reason=reason))
    return RunOutcome(blocked.status, EXIT_BLOCKED, blocked.step_id, blocked.reason)


def _fresh_step(state: _RunState, step_id: str, turn_kind: str, *, attempt: int = 1) -> _RunState:
    return _RunState(
        state.run_id,
        state.plugin_digest,
        state.goal_sha256,
        step_id,
        revision=state.revision,
        attempt=attempt,
        turn_kind=turn_kind,
    )


def _is_uncertain(state: _RunState) -> bool:
    return (
        state.status == "blocked"
        and state.reason == _UNCERTAIN
        and state.prompt_sha256 is not None
        and state.response_sha256 is None
    )


def _active_index(plugin: Plugin, state: _RunState) -> int:
    for index, step in enumerate(plugin.steps):
        if step.id != state.step_id:
            continue
        if state.status == "complete" and index != len(plugin.steps) - 1:
            break
        if (state.turn_kind == "skill") != (step.kind == "skill"):
            break
        confirmed = state.confirmation_event_id is not None
        finished = state.status == "done" or (
            state.status == "complete" and state.response_sha256 is not None
        )
        if finished and confirmed != (step.kind == "grilling"):
            break
        if confirmed and (
            step.kind != "grilling" or state.status not in {"done", "complete", "blocked"}
        ):
            break
        if state.reason == _UNCERTAIN and not _is_uncertain(state):
            break
        return index
    raise _StateError("State does not match an active plugin step")


def _in_flight_reason(state: _RunState, workspace: Path) -> str:
    """Keep an interrupted turn reconcilable only if the workspace did not change."""
    try:
        changed = workspace_digest(workspace) != state.workspace_sha256
    except WorkspaceSnapshotError:
        return "Workspace snapshot failed"
    return "Workspace changed during agent turn" if changed else _UNCERTAIN


def _record_interruption(store: _RunStore, workspace: Path) -> None:
    # A write may already have installed a newer receipt when it raised.
    with suppress(_StateError):
        state = store.load()
        if state is not None and state.status in _IN_FLIGHT:
            _block_step(store, state, _in_flight_reason(state, workspace))


def _completed_outcome(store: _RunStore, state: _RunState, step: Step) -> RunOutcome:
    # Older complete receipts did not retain the digest of the final trace.
    if state.response_sha256 is None:
        return RunOutcome("complete", EXIT_DONE)
    try:
        text = store.read_trace(state, state.settled_turn())
        result = _step_result(step, text)
        if result is not None:
            return RunOutcome("complete", EXIT_DONE, step.id, result=result)
    except (_StateError, ValueError, RecursionError):
        pass
    return RunOutcome("blocked", EXIT_BLOCKED, step.id, "Invalid final result evidence")


def _advance_run(
    store: _RunStore,
    state: _RunState,
    plugin: Plugin,
    goal: str,
    host: Host,
    console: Console,
    workspace: Path,
) -> RunOutcome:
    first_index = _active_index(plugin, state)
    if state.status == "complete":
        return _completed_outcome(store, state, plugin.steps[first_index])
    if state.status in {"blocked", "cancelled"}:
        code = EXIT_BLOCKED if state.status == "blocked" else EXIT_CANCELLED
        return RunOutcome(state.status, code, state.step_id, state.reason)
    if state.status in _IN_FLIGHT:
        return _block_step(store, state, _in_flight_reason(state, workspace))

    step = plugin.steps[first_index]

    def stage_skills() -> tuple[dict[str, Path], dict[str, str]]:
        try:
            return store.stage_skills(plugin)
        except _StateError as exc:
            raise _SkillCopyError("Skill copy failed") from exc

    try:
        with ExitStack() as session:

            def finish_step(
                state: _RunState, *, last: bool, event_id: str | None = None
            ) -> _RunState:
                if last:
                    try:
                        session.close()
                    except Exception:
                        _block_step(store, state, "Host shutdown failed")
                        raise
                return store.save(replace(state, status="done", confirmation_event_id=event_id))

            staged = None
            started = False
            if state.status == "awaiting":
                if state.previous is None:
                    raise _StateError("Missing previous turn")
                try:
                    text = store.read_trace(state, state.previous)
                except _StateError:
                    return _block_step(store, state, "Invalid settled trace")
                console.show(step.id, text)
            for index in range(first_index, len(plugin.steps)):
                step = plugin.steps[index]
                has_next_step = index + 1 < len(plugin.steps)
                while state.status != "done":
                    if state.status == "awaiting":
                        state, prompt = _grilling_input(state, step, console)
                    elif state.status == "ready":
                        prompt = _prompt_text(step, goal)
                    if state.status == "ready":
                        if staged is None:
                            staged = stage_skills()
                        if state.revision == 0:
                            state = store.save(state)
                        store.clear_trace(state)
                        resume_leaf = None
                        if not started:
                            session.enter_context(_started_host(host, *staged))
                            started = True
                            if state.previous is not None:
                                resume_leaf = state.previous.leaf_id
                        state = _send_turn(
                            store, state, host, prompt, workspace, resume_leaf=resume_leaf
                        )
                    target = state.settled_turn()
                    try:
                        text = store.read_trace(state, target)
                    except _StateError:
                        return _block_step(store, state, "Invalid settled trace")
                    event_id = None
                    if step.kind == "grilling":
                        console.show(step.id, text)
                        if state.turn_kind == "synthesis":
                            result = _step_result(step, text)
                            if result is None:
                                console.notice(
                                    step.id, "Synthesis does not match the step contract"
                                )
                            else:
                                # Check the pins before advancing a recovered step.
                                if has_next_step and staged is None:
                                    staged = stage_skills()
                                with _human_input():
                                    confirmed, event_id = console.confirm(step.id, result)
                                if not isinstance(event_id, str) or (
                                    confirmed is not False
                                    and (confirmed is not True or not _has_text(event_id))
                                ):
                                    return _block_step(
                                        store, state, "Grilling confirmation was not recorded"
                                    )
                                if confirmed:
                                    state = finish_step(
                                        state, last=not has_next_step, event_id=event_id
                                    )
                                    continue
                        # A recovered settled turn needs only its own trace.
                        if state.previous is not None:
                            store.clear_trace(state, state.previous)
                        state = store.save(replace(state, status="awaiting", previous=target))
                        continue
                    if _step_result(step, text) is None:
                        return _block_step(store, state, "Result does not match the step contract")
                    state = finish_step(state, last=not has_next_step)
                if has_next_step:
                    if staged is None:
                        staged = stage_skills()
                    store.clear_trace(state)
                    if state.previous is not None:
                        store.clear_trace(state, state.previous)
                    state = store.save(_fresh_step(state, plugin.steps[index + 1].id, "skill"))
        outcome = _completed_outcome(store, state, step)
        if outcome.exit_code != EXIT_DONE:
            return _block_step(store, state, "Invalid final result evidence")
        store.save(replace(state, status="complete"))
        return outcome
    except _SkillCopyError as exc:
        return RunOutcome("blocked", EXIT_BLOCKED, step.id, str(exc))
    except (_PiResumeBindingError, _PiLegacyTranscriptModeError) as exc:
        # No prompt was prepared; preserve the checkpoint for retry after repair.
        return RunOutcome("blocked", EXIT_BLOCKED, step.id, str(exc))
    except WorkspaceSnapshotError as exc:
        current = store.load()
        if current is not None:
            return _block_step(store, current, str(exc))
        return RunOutcome("blocked", EXIT_BLOCKED, step.id, str(exc))
    except (HostError, _InvalidTurnError) as exc:
        current = store.load()
        reason = (
            "Invalid host turn" if isinstance(exc, _InvalidTurnError) else "Host operation failed"
        )
        if current is not None:
            if current.status == "blocked":
                return RunOutcome(current.status, EXIT_BLOCKED, current.step_id, current.reason)
            if isinstance(exc, HostError) and current.status in _IN_FLIGHT:
                reason = _in_flight_reason(current, workspace)
            return _block_step(store, current, reason)
        return RunOutcome("blocked", EXIT_BLOCKED, step.id, reason)
    except _StateError:
        return RunOutcome("blocked", EXIT_BLOCKED, step.id, "Invalid run storage or evidence")
    except (KeyboardInterrupt, _ConsoleClosedError):
        _record_interruption(store, workspace)
        return RunOutcome("cancelled", EXIT_CANCELLED, step.id, "Run interrupted")
    except Exception:
        _record_interruption(store, workspace)
        return RunOutcome("internal", EXIT_INTERNAL, step.id, "Internal run error")


def run_plugin(
    plugin: Plugin,
    *,
    goal: str,
    run_id: str,
    host: Host,
    console: Console,
    workspace: Path,
    state_root: Path | None = None,
) -> RunOutcome:
    """Run or recover a plugin while holding its exclusive run lock."""
    try:
        workspace_is_dir = False
        with suppress(OSError):
            workspace_is_dir = stat.S_ISDIR(os.lstat(workspace).st_mode)
        if not workspace_is_dir:
            return RunOutcome(
                "blocked", EXIT_BLOCKED, plugin.steps[0].id, "Workspace snapshot failed"
            )
        goal_sha256 = _sha256_text(goal)
        with _locked_run(
            _run_directory(state_root, run_id), create=True, workspace=workspace
        ) as store:
            state = store.load()
            if state is None:
                state = _RunState(run_id, plugin.digest, goal_sha256, plugin.steps[0].id)
            elif (state.plugin_digest, state.goal_sha256) != (plugin.digest, goal_sha256):
                return RunOutcome("blocked", EXIT_BLOCKED, reason="Plugin or goal changed")
            return _advance_run(store, state, plugin, goal, host, console, workspace)
    except _RunBusy:
        return RunOutcome("not_ready", EXIT_NOT_READY, reason="Run lock is held")
    except _RunStorageConflictError as exc:
        return RunOutcome("blocked", EXIT_BLOCKED, reason=str(exc))
    except (_StateError, UnicodeEncodeError):
        return RunOutcome("blocked", EXIT_BLOCKED, reason="Invalid run input or storage")
    except KeyboardInterrupt:
        return RunOutcome("cancelled", EXIT_CANCELLED, reason="Run interrupted")
    except Exception:
        return RunOutcome("internal", EXIT_INTERNAL, reason="Internal run error")


def reconcile(
    run_dir: Path,
    step_id: str,
    decision: str,
    approver: str,
    *,
    expected_revision: int | None = None,
) -> RunOutcome:
    """Record an explicit decision about an uncertain prompt without sending it."""
    if decision not in ("retry", "abandon") or not _has_text(approver):
        return RunOutcome("blocked", EXIT_BLOCKED, reason="Invalid reconciliation approval")
    try:
        with _locked_run(run_dir, create=False) as store:
            state = store.load()
            if state is None or state.step_id != step_id or not _is_uncertain(state):
                return RunOutcome("blocked", EXIT_BLOCKED, reason="No matching uncertain step")
            if expected_revision is not None and state.revision != expected_revision:
                return RunOutcome("blocked", EXIT_BLOCKED, reason="Reconciliation evidence changed")
            if decision == "retry":
                store.clear_trace(state)
                retried = _fresh_step(
                    state, state.step_id, state.turn_kind, attempt=state.attempt + 1
                )
                if state.previous is not None:
                    retried = replace(
                        retried, status="awaiting", turn=state.turn, previous=state.previous
                    )
                state = store.save(retried)
                return RunOutcome(state.status, EXIT_NOT_READY, state.step_id)
            state = store.save(replace(state, status="cancelled", reason="Run abandoned"))
            return RunOutcome(state.status, EXIT_CANCELLED, state.step_id, state.reason)
    except _RunBusy:
        return RunOutcome("not_ready", EXIT_NOT_READY, reason="Run lock is held")
    except _StateError:
        return RunOutcome("blocked", EXIT_BLOCKED, reason="Invalid run storage")
    except KeyboardInterrupt:
        return RunOutcome("cancelled", EXIT_CANCELLED, reason="Reconciliation interrupted")
    except Exception:
        return RunOutcome("internal", EXIT_INTERNAL, reason="Internal reconciliation error")


def _emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")


def _emit_run(run_id: str, outcome: RunOutcome, **details: object) -> int:
    payload = {
        "run_id": run_id,
        "status": outcome.status,
        "exit_code": outcome.exit_code,
        "step_id": outcome.step_id,
        "reason": outcome.reason,
        **details,
    }
    if outcome.result is not None:
        payload["result"] = dict(outcome.result)
    _emit(payload)
    if outcome.reason is not None:
        print(f"skillrun: {outcome.reason}", file=sys.stderr)
    return outcome.exit_code


def _run_cli(args: argparse.Namespace) -> int:
    try:
        plugin = load_plugin(args.plugin)
    except PluginError as exc:
        return _emit_run(
            args.run_id,
            RunOutcome("blocked", EXIT_BLOCKED, reason="Invalid plugin"),
            errors=list(exc.errors),
        )
    workspace = Path(args.cwd).absolute()
    run_dir = _resolved_run_directory(_run_directory(None, args.run_id))
    with _storage_errors():
        # Preserve the CLI error for a workspace that cannot be statted.
        workspace.stat()
    outcome = run_plugin(
        plugin,
        goal=args.goal,
        run_id=args.run_id,
        host=PiHost(
            cwd=workspace,
            session_dir=run_dir / "pi-session",
            # Pi requires an alphanumeric ending. Run directories remain keyed by the public ID.
            session_id=_sha256_text(args.run_id) if args.run_id.endswith("-") else args.run_id,
        ),
        console=TerminalConsole(stdin=sys.stdin, stderr=sys.stderr),
        workspace=workspace,
        state_root=run_dir.parent,
    )
    if outcome.status == "complete" and outcome.result is None:
        outcome = RunOutcome(
            "blocked", EXIT_BLOCKED, reason="No verified final result for this run"
        )
    return _emit_run(args.run_id, outcome)


def _read_run_state(run_dir: Path) -> _RunState:
    with _locked_run(run_dir, create=False) as store:
        state = store.load()
        if state is None:
            raise _StateError("Run state not found")
        return state


def _status_cli(args: argparse.Namespace) -> int:
    state = _read_run_state(_run_directory(None, args.run_id))
    code = {
        "complete": EXIT_DONE,
        "blocked": EXIT_BLOCKED,
        "cancelled": EXIT_CANCELLED,
    }.get(state.status, EXIT_NOT_READY)
    return _emit_run(
        args.run_id,
        RunOutcome(state.status, code, state.step_id, state.reason),
        revision=state.revision,
        attempt=state.attempt,
        turn=state.turn,
        reconcilable=_is_uncertain(state),
    )


def _reconcile_cli(args: argparse.Namespace) -> int:
    run_dir = _run_directory(None, args.run_id)
    state = _read_run_state(run_dir)
    if not _is_uncertain(state):
        raise _StateError("No matching uncertain step; check run status")
    console = TerminalConsole(stdin=sys.stdin, stderr=sys.stderr)
    console.show(
        state.step_id,
        f"Run: {state.run_id} · Paso: {state.step_id} · Revisión: {state.revision}\n"
        f"Recibo: {state.receipt_id(state.attempt, state.turn)} · Motivo: {state.reason}\n"
        f"SHA-256 del prompt: {state.prompt_sha256}",
    )
    with _human_input():
        decision, approver = console.reconciliation_decision()
    outcome = reconcile(
        run_dir, state.step_id, decision, approver, expected_revision=state.revision
    )
    return _emit_run(args.run_id, outcome)


def _validate(path: str) -> int:
    try:
        plugin = load_plugin(path)
    except PluginError as exc:
        _emit({"ok": False, "errors": list(exc.errors)})
        sys.stderr.write("plugin inválido:\n" + "".join(f"  - {e}\n" for e in exc.errors))
        return EXIT_BLOCKED
    _emit({"ok": True, "plugin_id": plugin.id, "digest": plugin.digest})
    sys.stderr.write(f"plugin válido: {plugin.id}\n")
    return EXIT_DONE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skillrun")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="valida un plugin.json (solo esquema)")
    validate.add_argument("plugin", help="ruta al plugin.json")
    run = commands.add_parser("run", help="ejecuta o retoma un plugin en consola")
    run.add_argument("plugin", help="ruta al plugin.json")
    run.add_argument("--goal", required=True, help="objetivo del run")
    run.add_argument("--cwd", required=True, help="directorio de trabajo de Pi y del snapshot")
    run.add_argument("--run-id", required=True, help="identificador del run")
    status = commands.add_parser("status", help="consulta el estado persistido sin cambiarlo")
    status.add_argument("--run-id", required=True, help="identificador del run")
    reconcile_cmd = commands.add_parser(
        "reconcile", help="muestra el recibo incierto y pide reintentar o abandonar"
    )
    reconcile_cmd.add_argument("--run-id", required=True, help="identificador del run")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    if args.command != "validate":
        commands = {"run": _run_cli, "status": _status_cli, "reconcile": _reconcile_cli}
        try:
            return commands[args.command](args)
        except _RunBusy:
            return _emit_run(
                args.run_id, RunOutcome("not_ready", EXIT_NOT_READY, reason="Run lock is held")
            )
        except _StateError as exc:
            return _emit_run(args.run_id, RunOutcome("blocked", EXIT_BLOCKED, reason=str(exc)))
        except (KeyboardInterrupt, _ConsoleClosedError):
            return _emit_run(
                args.run_id, RunOutcome("cancelled", EXIT_CANCELLED, reason="Run interrupted")
            )
        except Exception:
            return _emit_run(
                args.run_id, RunOutcome("internal", EXIT_INTERNAL, reason="Internal CLI error")
            )
    try:
        return _validate(args.plugin)
    except KeyboardInterrupt:
        return EXIT_CANCELLED
    except Exception as exc:  # INTERNAL (§4.11): nunca se reporta como BLOCKED
        _emit(
            {"ok": False, "internal": True, "errors": [f"$: internal error ({type(exc).__name__})"]}
        )
        sys.stderr.write(f"error interno: {type(exc).__name__}: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
