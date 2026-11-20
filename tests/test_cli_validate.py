import json
import os
import subprocess
import sys
from os import PathLike
from pathlib import Path
from typing import Any, NoReturn

import pytest

import skillrun


def _read_json_line(stdout: str) -> dict[str, Any]:
    assert len(stdout.splitlines()) == 1, repr(stdout)
    response = json.loads(stdout)
    assert isinstance(response, dict)
    return response


def test_validate_main_accepts_unavailable_skill_files(
    valid_plugin_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = json.loads(valid_plugin_file.read_text(encoding="utf-8"))
    for skill in data["skills"].values():
        assert not (valid_plugin_file.parent / skill["path"]).exists()

    assert skillrun.main(["validate", str(valid_plugin_file)]) == 0

    response = _read_json_line(capsys.readouterr().out)
    assert response == {
        "ok": True,
        "plugin_id": data["id"],
        "digest": skillrun.plugin_digest(data),
    }
    assert response["ok"] is True


@pytest.mark.parametrize(
    "contents",
    [
        pytest.param('{"id":false,"steps":[]}', id="schema-errors"),
        pytest.param(None, id="missing-file"),
        pytest.param('{"id":', id="invalid-json"),
        pytest.param('{"id":"first","id":"second"}', id="duplicate-key"),
    ],
)
def test_validate_main_maps_plugin_errors_to_blocked_response(
    tmp_path: Path, contents: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "plugin.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    with pytest.raises(skillrun.PluginError) as exc:
        skillrun.load_plugin(path)

    assert skillrun.main(["validate", str(path)]) == 10

    output = capsys.readouterr()
    response = _read_json_line(output.out)
    assert response == {"ok": False, "errors": list(exc.value.errors)}
    assert response["ok"] is False
    assert output.err.strip()


def test_validate_main_maps_unexpected_exceptions_to_internal_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_path: str | PathLike[str]) -> NoReturn:
        raise RuntimeError("unexpected loader failure")

    monkeypatch.setattr(skillrun, "load_plugin", fail)

    assert skillrun.main(["validate", "plugin.json"]) == 70

    response = _read_json_line(capsys.readouterr().out)
    assert response["ok"] is False
    assert response["internal"] is True
    assert response["errors"] and all(e.startswith("$: ") for e in response["errors"])


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="missing-subcommand"),
        pytest.param(["unknown-subcommand"], id="unknown-subcommand"),
        pytest.param(["validate"], id="missing-path"),
    ],
)
def test_main_returns_usage_error_without_system_exit(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert skillrun.main(argv) == 2
    stdout = capsys.readouterr().out
    if stdout.strip():
        json.loads(stdout)


@pytest.mark.parametrize("valid", [True, False], ids=["valid-plugin", "invalid-plugin"])
def test_python_module_validate_emits_one_json_line(
    repo_root: Path, tmp_path: Path, plugin_data: dict[str, Any], valid: bool
) -> None:
    path = tmp_path / "plugin.json"
    if not valid:
        plugin_data["steps"][0]["result"]["summary"] = "invalid-type"
    path.write_text(json.dumps(plugin_data), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "skillrun", "validate", str(path)],
        cwd=repo_root,
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=15,
    )

    assert completed.returncode == (0 if valid else 10), completed.stderr
    response = _read_json_line(completed.stdout)
    if valid:
        assert response == {
            "ok": True,
            "plugin_id": plugin_data["id"],
            "digest": skillrun.plugin_digest(plugin_data),
        }
        assert response["ok"] is True
    else:
        assert response["ok"] is False
        assert any(error.startswith("steps[0].result.summary: ") for error in response["errors"])
        assert completed.stderr.strip()


def test_validate_main_rejects_placeholder_pin_in_github_gateway(
    repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plugin_file = repo_root / "plugins" / "github-gateway" / "plugin.json"
    assert skillrun.main(["validate", str(plugin_file)]) == 10

    response = _read_json_line(capsys.readouterr().out)
    assert response["ok"] is False
    assert any(error.startswith("skills.github-project.sha256: ") for error in response["errors"])
