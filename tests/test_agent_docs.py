import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("options", [(), ("--no-coupling",)])
def test_invalid_agents_utf8_reports_all_findings(tmp_path: Path, options: tuple[str, ...]) -> None:
    # Isolate Git discovery and any repository or index overrides inherited from a hook.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "init", "--quiet", "--template="], cwd=tmp_path, env=env, check=True)

    guard = tmp_path / "tools/check_agent_docs.py"
    guard.parent.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "tools/check_agent_docs.py", guard)
    docs = tmp_path / "docs/agent"
    docs.mkdir(parents=True)
    for name in ("CONTEXT", "ARCHITECTURE", "CODEMAP", "RUNTIME"):
        (docs / f"{name}.md").write_text("# Doc\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_bytes(b"# \xff\n")
    (docs / "RUNTIME.md").write_text("{{pending}}\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-IB", str(guard), *options],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "agent-docs: hallazgos bloqueantes",
        "  - AGENTS.md: no es UTF-8 válido",
        "  - docs/agent/RUNTIME.md: placeholder sin resolver {{pending}}",
    ]
