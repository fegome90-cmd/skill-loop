import copy
import json
from collections.abc import Iterable
from dataclasses import FrozenInstanceError, is_dataclass
from enum import IntEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

import skillrun

COMPLETE_DIGEST = "1ce92ddbb70be340df8678330754b697546a466dca842faa06ccd1f9311c3f42"

type FieldTarget = tuple[str, *tuple[str | int, ...]]


class _Severity(IntEnum):
    LOW = 1


def _field_parent(data: Any, target: tuple[str | int, ...]) -> Any:
    for part in target[:-1]:
        data = data[part]
    return data


def _field_path(target: FieldTarget) -> str:
    path = target[0]
    for part in target[1:]:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _error_paths(errors: Iterable[str]) -> set[str]:
    paths = set()
    for error in errors:
        path, separator, message = error.partition(": ")
        assert path and separator and message.strip(), error
        paths.add(path)
    return paths


def _assert_message(errors: Iterable[str], path: str, keyword: str) -> None:
    assert any(
        error_path == path and keyword in message.lower()
        for error_path, _, message in (error.partition(": ") for error in errors)
    ), errors


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SCHEMA", "skillrun/v1"),
        ("MAX_STEPS", 16),
        ("RESULT_TYPES", ("array", "boolean", "integer", "object", "string")),
        ("EXIT_DONE", 0),
        ("EXIT_USAGE", 2),
        ("EXIT_NOT_READY", 3),
        ("EXIT_BLOCKED", 10),
        ("EXIT_INTERNAL", 70),
        ("EXIT_CANCELLED", 130),
    ],
)
def test_public_constants(name: str, value: object) -> None:
    actual = getattr(skillrun, name)
    assert type(actual) is type(value)
    assert actual == value


def test_validate_accepts_valid_examples_without_mutating_them(valid_plugin_file: Path) -> None:
    data = json.loads(valid_plugin_file.read_text(encoding="utf-8"))
    original = copy.deepcopy(data)
    assert skillrun.validate_plugin_data(data) == []
    assert data == original


@pytest.mark.parametrize(
    ("name", "result_field"),
    [("0", "_"), ("0" + "a-" * 31 + "-", "_" + "a0_" * 21)],
    ids=["min-length", "max-length"],
)
def test_validate_accepts_boundary_names_step_count_and_relative_path(
    plugin_data: dict[str, Any], name: str, result_field: str
) -> None:
    plugin_data["id"] = name
    plugin_data["skills"][name] = plugin_data["skills"].pop("research")
    plugin_data["skills"][name]["path"] = ".skills/release..notes/SKILL.md"
    plugin_data["steps"][1].update(
        id=name,
        skill=name,
        result={result_field: "integer"},
    )
    for index in range(13):
        plugin_data["steps"].append(dict(plugin_data["steps"][1], id=f"step-{index}"))

    assert skillrun.validate_plugin_data(plugin_data) == []


@pytest.mark.parametrize("data", [None, [], True, "plugin"])
def test_validate_rejects_non_object_root(data: object) -> None:
    assert _error_paths(skillrun.validate_plugin_data(data)) == {"$"}


@pytest.mark.parametrize(
    "target",
    [
        ("schema",),
        ("id",),
        ("skills",),
        ("steps",),
        ("skills", "research", "path"),
        ("steps", 0, "id"),
        ("steps", 0, "skill"),
        ("steps", 0, "kind"),
        ("steps", 0, "result"),
        ("steps", 1, "instruction"),
        ("on_done", "directive"),
    ],
)
def test_validate_rejects_missing_required_fields(
    plugin_data: dict[str, Any], target: FieldTarget
) -> None:
    del _field_parent(plugin_data, target)[target[-1]]
    assert _field_path(target) in _error_paths(skillrun.validate_plugin_data(plugin_data))


@pytest.mark.parametrize(
    "target",
    [
        ("extra",),
        ("skills", "grilling", "extra"),
        ("steps", 1, "extra"),
        ("on_done", "extra"),
    ],
)
def test_validate_rejects_unknown_keys_at_each_fixed_schema_level(
    plugin_data: dict[str, Any], target: FieldTarget
) -> None:
    _field_parent(plugin_data, target)[target[-1]] = None
    _assert_message(skillrun.validate_plugin_data(plugin_data), _field_path(target), "unknown")


@pytest.mark.parametrize(
    ("target", "value"),
    [
        (("schema",), "skillrun/v2"),
        (("schema",), True),
        (("schema",), " skillrun/v1"),
        (("id",), ""),
        (("id",), True),
        (("id",), "Invalid"),
        (("id",), "-leading"),
        (("id",), "with_underscore"),
        (("id",), "a" * 65),
        (("description",), True),
        (("description",), ""),
        (("description",), " \t\n"),
        (("on_done",), []),
        (("on_done", "directive"), ""),
        (("on_done", "directive"), True),
        (("skills",), {}),
        (("skills",), []),
        (("skills", "research"), True),
        (("skills", "research", "path"), True),
        (("skills", "research", "path"), ""),
        (("skills", "research", "path"), "/skills/research/SKILL.md"),
        (("skills", "research", "path"), "C:/outside/SKILL.md"),
        (("skills", "research", "path"), "C:outside/SKILL.md"),
        (("skills", "research", "path"), "../research/SKILL.md"),
        (("skills", "research", "path"), "skills/../research/SKILL.md"),
        (("skills", "research", "path"), "skills/research/.."),
        (("skills", "research", "path"), r"skills\research\SKILL.md"),
        (("skills", "research", "sha256"), "PENDIENTE_64_HEX"),
        (("skills", "research", "sha256"), "a" * 63),
        (("skills", "research", "sha256"), "A" * 64),
        (("skills", "research", "sha256"), "z" * 64),
        (("skills", "research", "sha256"), True),
        (("skills", "grilling", "git_blob"), "a" * 41),
        (("skills", "grilling", "git_blob"), "A" * 40),
        (("skills", "grilling", "git_blob"), "z" * 40),
        (("skills", "grilling", "git_blob"), True),
        (("steps",), []),
        (("steps",), {}),
        (("steps", 0), []),
        (("steps", 1, "id"), True),
        (("steps", 1, "id"), "-leading"),
        (("steps", 1, "id"), "Invalid"),
        (("steps", 1, "id"), "a" * 65),
        (("steps", 0, "kind"), "interview"),
        (("steps", 0, "kind"), True),
        (("steps", 1, "kind"), "Skill"),
        (("steps", 1, "skill"), "undeclared"),
        (("steps", 1, "skill"), []),
        (("steps", 1, "skill"), True),
        (("steps", 0, "instruction"), ""),
        (("steps", 0, "instruction"), True),
        (("steps", 1, "instruction"), ""),
        (("steps", 1, "instruction"), True),
        (("steps", 1, "instruction"), "  "),
        (("steps", 0, "instruction"), "\t"),
        (("on_done", "directive"), " \n"),
        (("skills", "research", "path"), "   "),
        (("skills", "research", "path"), "skills/research/SKILL.md\x00"),
        (("steps", 1, "result"), {}),
        (("steps", 1, "result"), []),
        (("steps", 1, "result", "evidence"), "Object"),
        (("steps", 1, "result", "evidence"), "number"),
        (("steps", 1, "result", "evidence"), []),
        (("steps", 1, "result", "evidence"), True),
    ],
)
def test_validate_rejects_invalid_field_values(
    plugin_data: dict[str, Any], target: FieldTarget, value: object
) -> None:
    _field_parent(plugin_data, target)[target[-1]] = value
    assert _field_path(target) in _error_paths(skillrun.validate_plugin_data(plugin_data))


@pytest.mark.parametrize("name", ["Research", "-research", "a_b", "a" * 65])
def test_validate_rejects_invalid_skill_names(plugin_data: dict[str, Any], name: str) -> None:
    plugin_data["skills"][name] = plugin_data["skills"].pop("research")
    plugin_data["steps"][1]["skill"] = name
    assert f"skills.{name}" in _error_paths(skillrun.validate_plugin_data(plugin_data))


@pytest.mark.parametrize("name", ["Evidence", "1evidence", "with-hyphen", "a" * 65])
def test_validate_rejects_invalid_result_field_names(
    plugin_data: dict[str, Any], name: str
) -> None:
    plugin_data["steps"][1]["result"][name] = "string"
    assert f"steps[1].result.{name}" in _error_paths(skillrun.validate_plugin_data(plugin_data))


def test_validate_handles_non_string_mapping_keys(plugin_data: dict[str, Any]) -> None:
    plugin_data["skills"][True] = plugin_data["skills"].pop("research")
    plugin_data["steps"][1]["skill"] = True
    plugin_data["steps"][1]["result"][17] = "string"

    paths = _error_paths(skillrun.validate_plugin_data(plugin_data))
    assert any(path == "skills" or path.startswith("skills.") for path in paths)
    assert any(path == "steps[1].result" or path.startswith("steps[1].result.") for path in paths)


@pytest.mark.parametrize("pin_count", [0, 2])
def test_validate_requires_exactly_one_pin(plugin_data: dict[str, Any], pin_count: int) -> None:
    research = plugin_data["skills"]["research"]
    if pin_count == 0:
        del research["sha256"]
    else:
        research["git_blob"] = "a" * 40

    paths = _error_paths(skillrun.validate_plugin_data(plugin_data))
    assert paths & {"skills.research", "skills.research.sha256", "skills.research.git_blob"}


def test_validate_rejects_unused_skill(plugin_data: dict[str, Any]) -> None:
    plugin_data["skills"]["unused"] = {"path": "skills/unused/SKILL.md", "sha256": "a" * 64}
    _assert_message(skillrun.validate_plugin_data(plugin_data), "skills.unused", "unused")


def test_validate_rejects_seventeen_steps(plugin_data: dict[str, Any]) -> None:
    for index in range(14):
        plugin_data["steps"].append(dict(plugin_data["steps"][1], id=f"step-{index}"))
    assert "steps" in _error_paths(skillrun.validate_plugin_data(plugin_data))


@pytest.mark.parametrize(("index", "kind"), [(0, "skill"), (1, "grilling"), (2, "grilling")])
def test_validate_requires_grilling_at_index_zero_only(
    plugin_data: dict[str, Any], index: int, kind: str
) -> None:
    plugin_data["steps"][index]["kind"] = kind
    assert f"steps[{index}].kind" in _error_paths(skillrun.validate_plugin_data(plugin_data))


def test_validate_rejects_duplicate_step_ids(plugin_data: dict[str, Any]) -> None:
    plugin_data["steps"][2]["id"] = plugin_data["steps"][1]["id"]
    paths = _error_paths(skillrun.validate_plugin_data(plugin_data))
    assert paths & {"steps[1].id", "steps[2].id"}


def test_validate_reports_all_errors_in_sorted_order_without_mutating_input(
    plugin_data: dict[str, Any],
) -> None:
    plugin_data["schema"] = "skillrun/v2"
    plugin_data["description"] = []
    plugin_data["skills"]["research"]["sha256"] = "invalid"
    plugin_data["steps"][1]["result"]["count"] = False
    plugin_data["on_done"]["directive"] = True
    original = copy.deepcopy(plugin_data)

    errors = skillrun.validate_plugin_data(plugin_data)

    assert _error_paths(errors) == {
        "schema",
        "description",
        "skills.research.sha256",
        "steps[1].result.count",
        "on_done.directive",
    }
    assert errors == sorted(errors)
    assert skillrun.validate_plugin_data(plugin_data) == errors
    assert plugin_data == original


def test_load_exposes_plugin_skill_and_step_fields(valid_plugin_file: Path) -> None:
    data = json.loads(valid_plugin_file.read_text(encoding="utf-8"))
    plugin = skillrun.load_plugin(valid_plugin_file)

    assert isinstance(plugin, skillrun.Plugin)
    assert plugin.id == data["id"]
    assert plugin.description == data.get("description")
    assert plugin.on_done_directive == data.get("on_done", {}).get("directive")
    assert plugin.source == valid_plugin_file.resolve()
    assert plugin.digest == skillrun.plugin_digest(data)

    assert set(plugin.skills) == set(data["skills"])
    for name, raw_skill in data["skills"].items():
        skill = plugin.skills[name]
        assert isinstance(skill, skillrun.Skill)
        assert skill.name == name
        assert skill.path == raw_skill["path"]
        assert skill.sha256 == raw_skill.get("sha256")
        assert skill.git_blob == raw_skill.get("git_blob")

    assert isinstance(plugin.steps, tuple)
    for step, raw_step in zip(plugin.steps, data["steps"], strict=True):
        assert isinstance(step, skillrun.Step)
        assert step.id == raw_step["id"]
        assert step.skill == raw_step["skill"]
        assert step.kind == raw_step["kind"]
        assert dict(step.result) == raw_step["result"]
        assert step.instruction == raw_step.get("instruction")


def test_load_returns_frozen_dataclasses(valid_plugin_file: Path) -> None:
    plugin = skillrun.load_plugin(valid_plugin_file)
    for instance, field in [
        (plugin, "id"),
        (plugin.skills["grilling"], "name"),
        (plugin.steps[0], "id"),
    ]:
        assert is_dataclass(instance)
        with pytest.raises(FrozenInstanceError):
            setattr(instance, field, "changed")


def test_load_resolves_source_for_relative_string_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plugin_data: dict[str, Any]
) -> None:
    path = tmp_path / "plugin.json"
    path.write_text(json.dumps(plugin_data), encoding="utf-8")
    (tmp_path / "nested").mkdir()
    monkeypatch.chdir(tmp_path)

    assert skillrun.load_plugin("nested/../plugin.json").source == path.resolve()


def test_digest_uses_canonical_utf8_json(plugin_data: dict[str, Any], tmp_path: Path) -> None:
    compact = json.dumps(plugin_data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    reformatted = tmp_path / "reformatted.json"
    reformatted.write_text(compact, encoding="utf-8")

    assert skillrun.plugin_digest(plugin_data) == COMPLETE_DIGEST
    assert skillrun.plugin_digest(json.loads(compact)) == COMPLETE_DIGEST
    assert skillrun.load_plugin(reformatted).digest == COMPLETE_DIGEST


@pytest.mark.parametrize(
    "contents",
    [
        pytest.param(None, id="missing-file"),
        pytest.param(b'{"id": "\xff"}', id="invalid-utf8"),
        pytest.param(b'{"id":', id="invalid-json"),
        pytest.param(b'["not-an-object"]', id="non-object-json"),
    ],
)
def test_load_reports_file_and_root_errors_at_dollar(
    tmp_path: Path, contents: bytes | None
) -> None:
    path = tmp_path / "plugin.json"
    if contents is not None:
        path.write_bytes(contents)

    with pytest.raises(skillrun.PluginError) as exc:
        skillrun.load_plugin(path)
    errors = exc.value.errors
    assert isinstance(errors, tuple)
    assert _error_paths(errors) == {"$"}


@pytest.mark.parametrize(
    "target",
    [
        ("schema",),
        ("skills", "research"),
        ("skills", "grilling", "path"),
        ("steps", 0, "kind"),
        ("steps", 0, "result", "summary"),
        ("on_done", "directive"),
    ],
    ids=["root", "skills-map", "skill", "step", "result", "on-done"],
)
def test_load_rejects_duplicate_json_keys_at_any_depth(
    plugin_data: dict[str, Any],
    tmp_path: Path,
    target: tuple[str] | tuple[str, *tuple[str | int, ...], str],
) -> None:
    key = target[-1]
    value = _field_parent(plugin_data, target)[key]
    document = json.dumps(plugin_data)
    member = json.dumps({key: value})[1:-1]
    assert member in document
    path = tmp_path / "plugin.json"
    path.write_text(document.replace(member, f"{member}, {member}", 1), encoding="utf-8")

    with pytest.raises(skillrun.PluginError) as exc:
        skillrun.load_plugin(path)
    errors = exc.value.errors
    assert isinstance(errors, tuple)
    assert len(errors) == 1
    _assert_message(errors, "$", "duplicate")
    _assert_message(errors, "$", key)


def test_load_reports_all_schema_errors_in_a_sorted_tuple(
    tmp_path: Path, plugin_data: dict[str, Any]
) -> None:
    plugin_data["id"] = True
    plugin_data["steps"][1]["instruction"] = ""
    plugin_data["skills"]["research"]["path"] = "../research/SKILL.md"
    path = tmp_path / "plugin.json"
    path.write_text(json.dumps(plugin_data), encoding="utf-8")

    with pytest.raises(skillrun.PluginError) as exc:
        skillrun.load_plugin(path)

    errors = exc.value.errors
    assert isinstance(exc.value, Exception)
    assert isinstance(errors, tuple)
    assert _error_paths(errors) == {"id", "steps[1].instruction", "skills.research.path"}
    assert errors == tuple(sorted(errors))
    assert list(errors) == skillrun.validate_plugin_data(plugin_data)


def test_check_result_accepts_every_exact_type_and_untyped_nested_content() -> None:
    contract = MappingProxyType(
        {
            "summary": "string",
            "decisions": "array",
            "details": "object",
            "count": "integer",
            "verified": "boolean",
        }
    )
    value = {
        "summary": "",
        "decisions": [1, False, None, {"reason": ["scope", 2.0]}],
        "details": {"topic": True, "findings": [{"decisions": []}]},
        "count": 0,
        "verified": False,
    }
    assert skillrun.check_result(contract, value) == []


@pytest.mark.parametrize("value", [None, [], True, "summary"])
def test_check_result_requires_a_dict(value: object) -> None:
    assert _error_paths(skillrun.check_result({"summary": "string"}, value)) == {"result"}


@pytest.mark.parametrize(
    ("type_name", "value"),
    [
        ("string", True),
        ("array", (1, 2)),
        ("object", [["key", "value"]]),
        ("object", MappingProxyType({"key": "value"})),
        ("integer", True),
        ("integer", 2.0),
        ("integer", _Severity.LOW),
        ("boolean", 1),
    ],
)
def test_check_result_rejects_inexact_types(type_name: str, value: object) -> None:
    assert _error_paths(skillrun.check_result({"field": type_name}, {"field": value})) == {
        "result.field"
    }


def test_check_result_reports_missing_extra_and_mistyped_fields_in_order() -> None:
    errors = skillrun.check_result(
        {"z_missing": "string", "a_wrong_type": "integer"},
        {"middle_extra": "extra", "a_wrong_type": False},
    )
    assert _error_paths(errors) == {
        "result.z_missing",
        "result.middle_extra",
        "result.a_wrong_type",
    }
    assert errors == sorted(errors)


def test_validate_requires_grilling_skill_in_first_step(plugin_data: dict[str, Any]) -> None:
    plugin_data["steps"][0]["skill"] = "research"
    plugin_data["skills"].pop("grilling")
    assert "steps[0].skill" in _error_paths(skillrun.validate_plugin_data(plugin_data))


def test_load_reports_unencodable_text_together_with_schema_errors(
    tmp_path: Path, plugin_data: dict[str, Any]
) -> None:
    path = tmp_path / "plugin.json"
    raw = json.dumps(plugin_data | {"id": False, "description": "x"})
    path.write_text(raw.replace('"x"', '"\\ud800"'), encoding="utf-8")
    with pytest.raises(skillrun.PluginError) as excinfo:
        skillrun.load_plugin(path)
    assert {"$", "id"} <= _error_paths(excinfo.value.errors)
