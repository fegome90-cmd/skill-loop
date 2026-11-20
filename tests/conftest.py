import json
from pathlib import Path

import pytest

PLUGIN_FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


@pytest.fixture(params=["minimal", "complete"])
def valid_plugin_file(request):
    return PLUGIN_FIXTURES / f"{request.param}.json"


@pytest.fixture
def plugin_data():
    return json.loads((PLUGIN_FIXTURES / "complete.json").read_text(encoding="utf-8"))


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[1]
