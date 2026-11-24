"""TerminalConsole output and input through injected text streams."""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING

import pytest

import skillrun

if TYPE_CHECKING:
    from collections.abc import Callable


def terminal(
    stdin: StringIO, stderr: StringIO, new_id: Callable[[], str] = lambda: "test-id"
) -> skillrun.Console:
    console: skillrun.Console = getattr(skillrun, "TerminalConsole")(  # noqa: B009
        stdin=stdin, stderr=stderr, new_id=new_id
    )
    return console


def test_terminal_shows_and_asks_only_on_injected_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    answer = "  Verbatim café\t "
    stderr = StringIO()
    console = terminal(StringIO(answer + "\n"), stderr)

    console.show("discovery", "  First line\nSecond line  ")
    assert stderr.getvalue() == "  First line\nSecond line  \n"

    console.notice("discovery", "Try the synthesis again.")
    assert stderr.getvalue().splitlines()[-1] == "skillrun: Try the synthesis again."

    assert console.ask("discovery") == answer
    assert stderr.getvalue().endswith("> ")
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("answer", "confirmed"), [("  S \t", True), (" n ", False)], ids=["approve", "decline"]
)
def test_terminal_confirmation_reasks_and_returns_injected_event_id(
    answer: str, confirmed: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    stderr = StringIO()
    ids = iter(("event-001", "event-002"))
    console = terminal(StringIO(f"maybe\n\n{answer}\n"), stderr, lambda: next(ids))

    assert console.confirm("discovery", {"z": "café", "a": [1, 2]}) == (
        confirmed,
        "console:event-001",
    )

    prompt = "¿Confirmas? [s/n] "
    printed_result, *prompts = stderr.getvalue().split(prompt)
    assert printed_result.rstrip("\n") == '{\n  "a": [\n    1,\n    2\n  ],\n  "z": "café"\n}'
    assert len(prompts) == 3 and all(not part.strip() for part in prompts)
    assert next(ids) == "event-002"
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("operation", ["ask", "confirm"])
def test_terminal_eof_raises_after_writing_the_prompt(operation: str) -> None:
    stderr = StringIO()
    ids = iter(("event-001",))
    console = terminal(StringIO(""), stderr, lambda: next(ids))

    with pytest.raises(EOFError):
        if operation == "ask":
            console.ask("discovery")
        else:
            console.confirm("discovery", {"summary": "Agreed scope"})

    assert stderr.getvalue().endswith("> " if operation == "ask" else "¿Confirmas? [s/n] ")
    assert next(ids) == "event-001"
