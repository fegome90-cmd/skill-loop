"""skillrun: ejecución determinista de skills en orden (ver PLAN.md)."""

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import asdict, dataclass, replace
from functools import cache
from os import PathLike
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Protocol, TypeGuard
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


class Console(Protocol):
    def confirm(self, step_id: str, result: Mapping[str, object]) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class RunOutcome:
    status: str
    exit_code: int
    step_id: str | None = None
    reason: str | None = None


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
_TURN_FIELDS = ("cursor", "prompt_sha256", "leaf_id", "response_sha256", "confirmation_event_id")


class _StateError(Exception):
    """The run or its persisted evidence is missing, unsafe, or invalid."""


class _RunBusy(Exception):  # noqa: N818 - the engine handles contention as a separate outcome.
    """Another supervisor owns the run lock."""


@dataclass(frozen=True)
class _RunState:
    run_id: str
    plugin_digest: str
    goal_sha256: str
    step_id: str
    status: str = "ready"
    revision: int = 0
    attempt: int = 1
    cursor: str | None = None
    prompt_sha256: str | None = None
    leaf_id: str | None = None
    response_sha256: str | None = None
    confirmation_event_id: str | None = None
    reason: str | None = None

    @property
    def receipt_id(self) -> str:
        return f"{self.run_id}/{self.step_id}/{self.attempt}"


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
    revision, attempt = data["revision"], data["attempt"]
    if type(revision) is not int or revision < 1 or type(attempt) is not int or attempt < 1:
        raise _StateError("Invalid state revision or attempt")

    status = data["status"]
    if not isinstance(status, str) or status not in {
        "ready",
        "prepared",
        "accepted",
        "settled",
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
        for field in ("prompt_sha256", "response_sha256")
        if field in details
    ):
        raise _StateError("Invalid prompt or response digest")
    terminal = status in {"blocked", "cancelled"}
    if terminal != ("reason" in details):
        raise _StateError("Invalid state reason")
    turn = details.keys() - {"reason"}
    if status in {"ready", "complete"} and turn:
        raise _StateError("Unexpected turn evidence")
    if (
        turn or status in {"prepared", "accepted", "settled", "done"}
    ) and "prompt_sha256" not in turn:
        raise _StateError("Missing prompt digest")
    settled = {"leaf_id", "response_sha256"}
    final_evidence = turn & settled
    if final_evidence and (final_evidence != settled or status in {"prepared", "accepted"}):
        raise _StateError("Unexpected or incomplete settled evidence")
    if status in {"settled", "done"} and not final_evidence:
        raise _StateError("Missing settled evidence")
    if "confirmation_event_id" in turn and (not final_evidence or status == "settled"):
        raise _StateError("Unexpected confirmation evidence")
    return _RunState(
        run_id, plugin_digest, goal_sha256, step_id, status, revision, attempt, **details
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


def _write_run_json(parent_fd: int, name: str, data: dict[str, object]) -> None:
    _check_entry(parent_fd, name)
    temporary = f".{name}.{uuid4().hex}.tmp"
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _file_flags(), 0o600, dir_fd=parent_fd
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            _check_open_private(stream.fileno(), temporary)
            json.dump(data, stream, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_fd)


class _RunStore:
    def __init__(self, run_fd: int, run_id: str) -> None:
        self._fd = run_fd
        self._run_id = run_id

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
            data = {key: value for key, value in asdict(saved).items() if value is not None}
            data["schema"] = _STATE_SCHEMA
            _decode_state(data, self._run_id)
            _write_run_json(self._fd, "state.json", data)
            return saved

    def _trace_name(self, state: _RunState) -> str:
        if (
            state.run_id != self._run_id
            or not isinstance(state.step_id, str)
            or not re.fullmatch(_ID_PATTERN, state.step_id)
            or type(state.attempt) is not int
            or state.attempt < 1
        ):
            raise _StateError("Invalid trace identity")
        return f"{state.step_id}-{state.attempt}.json"

    @contextmanager
    def _traces(self, *, create: bool) -> Iterator[int]:
        fd = _open_directory(self._fd, "traces", create=create)
        try:
            _check_open_private(fd, "traces", directory=True)
            yield fd
        finally:
            os.close(fd)

    def clear_trace(self, state: _RunState) -> None:
        with _storage_errors():
            name = self._trace_name(state)
            if _check_entry(self._fd, "traces", directory=True):
                with self._traces(create=False) as fd:
                    if _check_entry(fd, name):
                        os.unlink(name, dir_fd=fd)
                        os.fsync(fd)

    def write_trace(self, state: _RunState, text: str) -> str:
        with _storage_errors():
            name = self._trace_name(state)
            digest = _sha256_text(text)
            with self._traces(create=True) as fd:
                _write_run_json(
                    fd,
                    name,
                    {
                        "run_id": state.run_id,
                        "step_id": state.step_id,
                        "receipt_id": state.receipt_id,
                        "text": text,
                        "sha256": digest,
                    },
                )
        return digest

    def read_trace(self, state: _RunState) -> str:
        with _storage_errors(), self._traces(create=False) as fd:
            data = _read_run_json(fd, self._trace_name(state))
            if data is None or data.keys() != {"run_id", "step_id", "receipt_id", "text", "sha256"}:
                raise _StateError("Missing or invalid trace")
            text, digest = data["text"], data["sha256"]
            if (
                data["run_id"] != state.run_id
                or data["step_id"] != state.step_id
                or data["receipt_id"] != state.receipt_id
                or not isinstance(text, str)
                or digest != state.response_sha256
                or digest != _sha256_text(text)
            ):
                raise _StateError("Trace does not match the run receipt")
            return text


@contextmanager
def _locked_run(run_dir: Path, *, create: bool) -> Iterator[_RunStore]:
    try:
        import fcntl
    except ImportError as exc:
        raise _StateError("Run storage requires POSIX file locking") from exc
    if not re.fullmatch(_ID_PATTERN, run_dir.name) or ".." in run_dir.parts:
        raise _StateError("Invalid run path")
    with ExitStack() as opened:
        with _storage_errors():
            absolute = run_dir.absolute()
            root, *parents = absolute.parent.parts
            parent_fd = _open_directory(None, root, create=False)
            opened.callback(os.close, parent_fd)
            for part in parents:
                parent_fd = _open_directory(parent_fd, part, create=create)
                opened.callback(os.close, parent_fd)
            _check_open_private(parent_fd, "state root", directory=True)
            run_fd = _open_directory(parent_fd, absolute.name, create=create)
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
        store = _RunStore(run_fd, run_dir.name)
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
    except (ValueError, RecursionError):
        return None
    if isinstance(result, dict) and not check_result(step.result, result):
        return result
    return None


def _prompt_text(step: Step, goal: str) -> str:
    if step.kind == "grilling":
        return f"/skill:grilling {goal}"
    contract = json.dumps(dict(step.result), sort_keys=True)
    return (
        f"/skill:{step.skill} {step.instruction}\n\n"
        f"Return the result in a fenced JSON block with exactly these fields and types:\n{contract}"
    )


@contextmanager
def _started_host(host: Host, plugin: Plugin) -> Iterator[None]:
    paths = {name: plugin.source.parent / skill.path for name, skill in plugin.skills.items()}
    pins: dict[str, str] = {}
    for name, skill in plugin.skills.items():
        pin = skill.sha256 if skill.sha256 is not None else skill.git_blob
        if pin is None:
            raise _StateError("Missing skill pin")
        pins[name] = pin
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


def _send_turn(store: _RunStore, state: _RunState, host: Host, text: str) -> _RunState:
    prompt_sha256 = _sha256_text(text)
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
            replace(state, status="prepared", cursor=cursor, prompt_sha256=prompt_sha256)
        )

    def on_accepted() -> None:
        nonlocal state
        require_phase("prepared")
        state = store.save(replace(state, status="accepted"))

    try:
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
    response_sha256 = store.write_trace(state, turn.text)
    return store.save(
        replace(state, status="settled", leaf_id=turn.leaf_id, response_sha256=response_sha256)
    )


def _block_step(store: _RunStore, state: _RunState, reason: str) -> RunOutcome:
    blocked = store.save(replace(state, status="blocked", reason=reason))
    return RunOutcome(blocked.status, EXIT_BLOCKED, blocked.step_id, blocked.reason)


def _fresh_step(state: _RunState, step_id: str, *, attempt: int = 1) -> _RunState:
    return _RunState(
        state.run_id,
        state.plugin_digest,
        state.goal_sha256,
        step_id,
        revision=state.revision,
        attempt=attempt,
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
        confirmed = state.confirmation_event_id is not None
        if state.status == "done" and confirmed != (step.kind == "grilling"):
            break
        if confirmed and (step.kind != "grilling" or state.status not in {"done", "blocked"}):
            break
        if state.reason == _UNCERTAIN and not _is_uncertain(state):
            break
        return index
    raise _StateError("State does not match an active plugin step")


def _record_interruption(store: _RunStore) -> None:
    # A write may already have installed a newer receipt when it raised.
    with suppress(_StateError):
        state = store.load()
        if state is not None and state.status in _IN_FLIGHT:
            _block_step(store, state, _UNCERTAIN)


def _advance_run(
    store: _RunStore,
    state: _RunState,
    plugin: Plugin,
    goal: str,
    host: Host,
    console: Console,
) -> RunOutcome:
    first_index = _active_index(plugin, state)
    if state.status == "complete":
        return RunOutcome("complete", EXIT_DONE)
    if state.status in {"blocked", "cancelled"}:
        code = EXIT_BLOCKED if state.status == "blocked" else EXIT_CANCELLED
        return RunOutcome(state.status, code, state.step_id, state.reason)
    if state.status in _IN_FLIGHT:
        return _block_step(store, state, _UNCERTAIN)

    step = plugin.steps[first_index]
    try:
        with ExitStack() as session:
            started = False
            for index in range(first_index, len(plugin.steps)):
                step = plugin.steps[index]
                if state.status == "ready":
                    store.clear_trace(state)
                    if not started:
                        session.enter_context(_started_host(host, plugin))
                        started = True
                    state = _send_turn(store, state, host, _prompt_text(step, goal))
                if state.status == "settled":
                    try:
                        text = store.read_trace(state)
                    except _StateError:
                        return _block_step(store, state, "Invalid settled trace")
                    result = _step_result(step, text)
                    if result is None:
                        return _block_step(store, state, "Result does not match the step contract")
                    event_id = None
                    if step.kind == "grilling":
                        confirmed, event_id = console.confirm(step.id, result)
                        if confirmed is not True or not _has_text(event_id):
                            return _block_step(
                                store, state, "Grilling confirmation was not recorded"
                            )
                    if index + 1 == len(plugin.steps):
                        try:
                            session.close()
                        except (Exception, KeyboardInterrupt):
                            _block_step(store, state, "Host shutdown failed")
                            raise
                    state = store.save(
                        replace(state, status="done", confirmation_event_id=event_id)
                    )
                if index + 1 < len(plugin.steps):
                    state = store.save(_fresh_step(state, plugin.steps[index + 1].id))
        state = store.save(
            replace(_fresh_step(state, state.step_id, attempt=state.attempt), status="complete")
        )
        return RunOutcome(state.status, EXIT_DONE)
    except (HostError, _InvalidTurnError) as exc:
        current = store.load()
        reason = (
            "Invalid host turn" if isinstance(exc, _InvalidTurnError) else "Host operation failed"
        )
        if current is not None:
            if current.status == "blocked":
                return RunOutcome(current.status, EXIT_BLOCKED, current.step_id, current.reason)
            if isinstance(exc, HostError) and current.status in _IN_FLIGHT:
                reason = _UNCERTAIN
            return _block_step(store, current, reason)
        return RunOutcome("blocked", EXIT_BLOCKED, step.id, reason)
    except _StateError:
        return RunOutcome("blocked", EXIT_BLOCKED, step.id, "Invalid run storage or evidence")
    except KeyboardInterrupt:
        _record_interruption(store)
        return RunOutcome("cancelled", EXIT_CANCELLED, step.id, "Run interrupted")
    except Exception:
        _record_interruption(store)
        return RunOutcome("internal", EXIT_INTERNAL, step.id, "Internal run error")


def run_plugin(
    plugin: Plugin,
    *,
    goal: str,
    run_id: str,
    host: Host,
    console: Console,
    state_root: Path | None = None,
) -> RunOutcome:
    """Run or recover a plugin while holding its exclusive run lock."""
    try:
        goal_sha256 = _sha256_text(goal)
        with _locked_run(_run_directory(state_root, run_id), create=True) as store:
            state = store.load()
            if state is None:
                state = store.save(
                    _RunState(run_id, plugin.digest, goal_sha256, plugin.steps[0].id)
                )
            elif (state.plugin_digest, state.goal_sha256) != (plugin.digest, goal_sha256):
                return RunOutcome("blocked", EXIT_BLOCKED, reason="Plugin or goal changed")
            return _advance_run(store, state, plugin, goal, host, console)
    except _RunBusy:
        return RunOutcome("not_ready", EXIT_NOT_READY, reason="Run lock is held")
    except (_StateError, UnicodeEncodeError):
        return RunOutcome("blocked", EXIT_BLOCKED, reason="Invalid run input or storage")
    except KeyboardInterrupt:
        return RunOutcome("cancelled", EXIT_CANCELLED, reason="Run interrupted")
    except Exception:
        return RunOutcome("internal", EXIT_INTERNAL, reason="Internal run error")


def reconcile(run_dir: Path, step_id: str, decision: str, approver: str) -> RunOutcome:
    """Record an explicit decision about an uncertain prompt without sending it."""
    if decision not in ("retry", "abandon") or not _has_text(approver):
        return RunOutcome("blocked", EXIT_BLOCKED, reason="Invalid reconciliation approval")
    try:
        with _locked_run(run_dir, create=False) as store:
            state = store.load()
            if state is None or state.step_id != step_id or not _is_uncertain(state):
                return RunOutcome("blocked", EXIT_BLOCKED, reason="No matching uncertain step")
            if decision == "retry":
                state = store.save(_fresh_step(state, state.step_id, attempt=state.attempt + 1))
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
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
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
