import json
from pathlib import Path
from typing import Any

import pytest

PLUGIN_FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


@pytest.fixture(params=["minimal", "complete"])
def valid_plugin_file(request: pytest.FixtureRequest) -> Path:
    return PLUGIN_FIXTURES / f"{request.param}.json"


@pytest.fixture
def plugin_data() -> dict[str, Any]:
    data: object = json.loads((PLUGIN_FIXTURES / "complete.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
