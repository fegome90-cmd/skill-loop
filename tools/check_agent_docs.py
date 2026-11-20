#!/usr/bin/env python3
"""Guard de documentación de agentes: estructura y acoplamiento con el contrato.

Uso:
    python tools/check_agent_docs.py                # estructura + acoplamiento
    python tools/check_agent_docs.py --no-coupling  # solo estructura

Sale con 0 si pasa y 1 si hay hallazgos. No existe bandera para forzar.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOCS = (
    Path("AGENTS.md"),
    Path("docs/agent/CONTEXT.md"),
    Path("docs/agent/ARCHITECTURE.md"),
    Path("docs/agent/CODEMAP.md"),
    Path("docs/agent/RUNTIME.md"),
)

# Archivos cuyo cambio obliga a revisar la documentación de agentes.
CONTRACT_SURFACES = frozenset(
    {
        "pyproject.toml",
        "Makefile",
        ".pre-commit-config.yaml",
        "docs/constitution/SOURCE.lock",
        "docs/constitution/AGENTIC-CONSTITUTION.md",
    }
)

DRAFT_MARKER = "<!-- agent-docs-kit:draft -->"
PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}")
LINK = re.compile(r"\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)\s*\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def routing_findings() -> list[str]:
    agents = ROOT / "AGENTS.md"
    if not agents.is_file():
        return []
    text = agents.read_text(encoding="utf-8")
    missing = [
        f"AGENTS.md: no enruta a docs/agent/{rel.stem}.md"
        for rel in DOCS[1:]
        if f"docs/agent/{rel.stem}.md" not in text
    ]
    return missing


def link_findings(rel: Path, path: Path, text: str) -> list[str]:
    findings: list[str] = []
    for match in LINK.finditer(text):
        target = match.group(1).strip("<>")
        if target.startswith(EXTERNAL_PREFIXES):
            continue
        clean = target.split("#", 1)[0]
        if clean and not (path.parent / clean).exists():
            findings.append(f"{rel}: enlace local roto -> {target}")
    return findings


def structure_findings() -> list[str]:
    findings: list[str] = []
    for rel in DOCS:
        path = ROOT / rel
        if not path.is_file():
            findings.append(f"{rel}: falta el documento")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"{rel}: no es UTF-8 válido")
            continue
        if b"\r\n" in path.read_bytes():
            findings.append(f"{rel}: contiene CRLF, se exige LF")
        if DRAFT_MARKER in text:
            findings.append(f"{rel}: conserva el marcador de borrador")
        findings.extend(
            f"{rel}: placeholder sin resolver {match.group(0)}"
            for match in PLACEHOLDER.finditer(text)
        )
        findings.extend(link_findings(rel, path, text))
    findings.extend(routing_findings())
    return findings


def staged_paths() -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in completed.stdout.split("\n") if line]


def coupling_findings() -> list[str]:
    staged = staged_paths()
    if not staged:
        return []
    touched = sorted(path for path in staged if path in CONTRACT_SURFACES)
    if not touched:
        return []
    if any(path == "AGENTS.md" or path.startswith("docs/agent/") for path in staged):
        return []
    return [
        "acoplamiento: cambió el contrato ("
        + ", ".join(touched)
        + ") sin tocar AGENTS.md ni docs/agent/. Actualiza el documento que "
        "describe ese contrato, o el commit queda bloqueado."
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-coupling",
        action="store_true",
        help="omite la comprobación de acoplamiento con el contrato",
    )
    args = parser.parse_args(argv)

    findings = structure_findings()
    if not args.no_coupling:
        findings.extend(coupling_findings())

    if not findings:
        print("agent-docs: OK (estructura" + ("" if args.no_coupling else " y acoplamiento") + ")")
        return 0

    print("agent-docs: hallazgos bloqueantes", file=sys.stderr)
    for finding in findings:
        print(f"  - {finding}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
