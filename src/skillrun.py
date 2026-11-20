"""skillrun: ejecución determinista de skills en orden (ver PLAN.md)."""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import TypeGuard

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
        or "\\" in path
        or "\x00" in path
        or ".." in path.split("/")
    ):
        errors.append(f"{at}.path: expected a relative path without NUL, backslashes or '..'")
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
