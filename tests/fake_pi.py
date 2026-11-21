"""Subprocess stand-in for Pi 1.6.0 RPC. It never invokes tools or a model."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

Record = dict[str, Any]
TIMESTAMP = "2026-11-20T20:00:00.000Z"
MESSAGE_TIMESTAMP = 1795204800000
PLAIN_REPLY = "Fixture answer"
SEPARATOR_REPLY = "Line\u2028separator\u2029paragraph"
REJECTED = {"queued", "handled", "rejected"}
BAD_WIRE = {
    "invalid-json": b'{"type":\n',
    "non-object": b'["agent_settled"]\n',
    "non-string-type": b'{"type":42}\n',
    "invalid-utf8": b'{"type":"message_end","message":"\xff"}\n',
}
SWITCHED_BRANCHES = {
    "branch-diverged",
    "branch-mismatch",
    "branch-user-mismatch",
    "branch-extra-user",
    "branch-wrong-stop",
}


def read_records(path: Path) -> list[Record]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="\n") as stream:
        return [json.loads(line) for line in stream]


def append_record(path: Path, record: Record) -> None:
    with path.open("ab") as stream:
        stream.write(json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n")


def emit_bytes(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def text_block(text: str) -> Record:
    return {"type": "text", "text": text}


def assistant(content: list[Record], stop_reason: str) -> Record:
    usage_keys = ("input", "output", "cacheRead", "cacheWrite", "totalTokens")
    return {
        "role": "assistant",
        "content": content,
        "stopReason": stop_reason,
        "api": "openai-responses",
        "provider": "fake",
        "model": "fake",
        "usage": dict.fromkeys(usage_keys, 0) | {"cost": dict.fromkeys(usage_keys, 0)},
        "timestamp": MESSAGE_TIMESTAMP,
    }


class Session:
    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.path = options.session_dir / f"{options.session_id}.jsonl"
        self.entries = read_records(self.path)[1:]
        self.leaf_id = self.entries[-1]["id"] if self.entries else None
        self.turns = 0
        if not self.path.exists():
            append_record(
                self.path,
                {
                    "type": "session",
                    "version": 3,
                    "id": options.session_id,
                    "timestamp": TIMESTAMP,
                    "cwd": os.getcwd(),
                },
            )

    def append_entry(self, entry_type: str, **fields: object) -> None:
        entry_id = f"{len(self.entries) + 1:08x}"
        entry = {
            "type": entry_type,
            "id": entry_id,
            "parentId": self.leaf_id,
            "timestamp": TIMESTAMP,
            **fields,
        }
        append_record(self.path, entry)
        self.entries.append(entry)
        self.leaf_id = entry_id

    def emit(self, record: Record) -> None:
        newline = b"\r\n" if self.options.scenario == "crlf" else b"\n"
        emit_bytes(json.dumps(record, ensure_ascii=False).encode("utf-8") + newline)

    def respond(
        self, command: Record, data: Record | None = None, *, error: str | None = None
    ) -> None:
        record = {
            "type": "response",
            "id": command["id"],
            "command": command["type"],
            "success": error is None,
        }
        self.emit(record | ({"data": data} if error is None else {"error": error}))

    def get_state(self, command: Record) -> None:
        scenario = self.options.scenario
        if scenario == "state-rejected":
            self.respond(command, error="State unavailable")
            return
        session_id = self.options.session_id if scenario != "wrong-session-id" else "other"
        session_file = self.path
        if scenario == "outside-session-file":
            other_dir = self.path.parent.with_name(f"{self.path.parent.name}-other")
            other_dir.mkdir(exist_ok=True)
            session_file = other_dir / self.path.name
            session_file.write_bytes(self.path.read_bytes())
        self.respond(
            command,
            {
                "sessionId": session_id,
                "sessionFile": str(session_file),
                "isStreaming": scenario == "streaming-on-start",
            },
        )

    def get_commands(self, command: Record) -> None:
        if not self.options.skill:
            self.respond(command, {"commands": []})
            return
        skills: list[Record] = [
            {
                "name": f"skill:{path.parent.name}",
                "source": "skill",
                "sourceInfo": {
                    "path": str(path),
                    "source": "cli",
                    "scope": "temporary",
                    "origin": "top-level",
                },
            }
            for path in self.options.skill
        ]
        scenario = self.options.scenario
        if scenario == "missing-skill":
            skills.pop(0)
        elif scenario == "extra-skill":
            skills.append(skills[0] | {"name": "skill:unexpected"})
        elif scenario == "duplicate-skill":
            skills.append(skills[0])
        elif scenario == "mislocated-skill":
            original = self.options.skill[0]
            wrong = Path.cwd() / "wrong-root" / original.parent.name / original.name
            wrong.parent.mkdir(parents=True, exist_ok=True)
            wrong.write_bytes(original.read_bytes())
            skills[0]["sourceInfo"]["path"] = str(wrong)

        # A matching name with a different source cannot satisfy a skill registration.
        other = {
            "name": f"skill:{self.options.skill[0].parent.name}",
            "source": "prompt",
            "sourceInfo": {
                "path": str(Path.cwd() / "fixture-prompt.md"),
                "source": "local",
                "scope": "project",
                "origin": "top-level",
            },
        }
        self.respond(command, {"commands": [other, *skills]})

    def get_entries(self, command: Record) -> None:
        since = command.get("since")
        if since is None:
            self.respond(command, {"entries": self.entries, "leafId": self.leaf_id})
            return
        for index, entry in enumerate(self.entries):
            if entry["id"] == since:
                self.respond(
                    command, {"entries": self.entries[index + 1 :], "leafId": self.leaf_id}
                )
                return
        self.respond(command, error="Unknown cursor")

    def prompt(self, command: Record) -> bool:
        self.turns += 1
        scenario = self.options.scenario if self.turns >= self.options.fault_turn else "plain"
        if scenario == "eof-before-response":
            return False
        if scenario == "hang-before-response":
            return True
        if scenario == "slow-response":
            time.sleep(0.9)
        if scenario in REJECTED:
            if scenario == "rejected":
                self.respond(command, error="Prompt rejected")
            else:
                self.respond(command, {"disposition": scenario})
            return True

        if scenario == "interleaved":
            self.emit_turn(command, scenario)
        append_record(self.options.log, {"event": "started-response"})
        self.respond(command, {"disposition": "started"})
        if scenario == "eof-after-response":
            return False
        if scenario in BAD_WIRE:
            emit_bytes(BAD_WIRE[scenario])
        elif scenario == "unknown-id":
            self.respond(command | {"id": "unrelated-id"}, {"disposition": "started"})
        elif scenario == "extension-ui":
            self.emit({"type": "extension_ui_request", "id": "question", "method": "input"})
        elif scenario != "interleaved":
            self.emit_turn(command, scenario)
        return True

    def emit_turn(self, command: Record, scenario: str) -> None:
        cursor = self.leaf_id
        user = {"role": "user", "content": command["message"], "timestamp": MESSAGE_TIMESTAMP}
        if scenario == "expanded-prompt":
            user["content"] = [
                text_block("Expanded skill instruction"),
                text_block(command["message"]),
            ]
        reply = (
            self.options.reply[self.turns - 1]
            if self.turns <= len(self.options.reply)
            else PLAIN_REPLY
        )
        content = [text_block(reply)]
        if scenario == "separators":
            content = [
                text_block(SEPARATOR_REPLY),
                {"type": "thinking", "thinking": "Hidden"},
                text_block("Second block"),
            ]
        final = assistant(content, scenario if scenario in {"error", "length"} else "stop")

        if scenario == "branch-correct":
            self.append_entry("message", message=user)
            self.append_entry("message", message=final)
            self.leaf_id = cursor

        self.emit({"type": "agent_start"})
        self.emit({"type": "turn_start"})
        self.emit({"type": "new_event_for_forward_compatibility"})
        if scenario == "metadata":
            self.append_entry(
                "message",
                message={
                    "role": "system",
                    "content": "Synthetic test session",
                    "timestamp": MESSAGE_TIMESTAMP,
                },
            )
        self.emit_message(user)
        if scenario == "metadata":
            self.append_entry("session_info", name="Synthetic turn")
        if scenario == "tool":
            self.emit_tool_turn()
        self.emit_message(final)
        self.emit({"type": "turn_end", "message": final, "toolResults": []})
        self.emit({"type": "agent_end", "messages": [user, final], "willRetry": False})

        if scenario in SWITCHED_BRANCHES:
            # The abandoned branch above matches both message_end records.
            self.leaf_id = None if scenario == "branch-diverged" else cursor
            if scenario == "branch-user-mismatch":
                user = user | {"content": "Mismatched input"}
            self.append_entry("message", message=user)
            if scenario == "branch-extra-user":
                self.append_entry("message", message=user)
            if scenario == "branch-mismatch":
                final = assistant([text_block("Mismatched reply")], "stop")
            elif scenario == "branch-wrong-stop":
                final = final | {"stopReason": "error"}
            self.append_entry("message", message=final)
        if scenario != "hang":
            self.emit({"type": "agent_settled", "aborted": scenario == "aborted"})

    def emit_message(self, message: Record) -> None:
        initial = message
        if message["role"] == "assistant":
            initial = message | {"content": [], "stopReason": "pending"}
        self.emit({"type": "message_start", "message": initial})
        self.append_entry("message", message=message)
        self.emit({"type": "message_end", "message": message})

    def emit_tool_turn(self) -> None:
        arguments = {"path": "fixture.txt"}
        pending = assistant(
            [{"type": "toolCall", "id": "call-read", "name": "read", "arguments": arguments}],
            "toolUse",
        )
        self.emit_message(pending)
        tool = {"toolCallId": "call-read", "toolName": "read"}
        content = [text_block("Synthetic tool output")]
        self.emit({"type": "tool_execution_start", **tool, "args": arguments})
        self.emit(
            {
                "type": "tool_execution_update",
                **tool,
                "args": arguments,
                "partialResult": {"content": content, "details": {}},
            }
        )
        self.emit(
            {
                "type": "tool_execution_end",
                **tool,
                "result": {"content": content, "details": {}},
                "isError": False,
            }
        )
        result = {
            "role": "toolResult",
            **tool,
            "content": content,
            "isError": False,
            "timestamp": MESSAGE_TIMESTAMP,
        }
        self.emit_message(result)
        self.emit({"type": "turn_end", "message": pending, "toolResults": [result]})
        self.emit({"type": "turn_start"})


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--scenario", default="plain")
    parser.add_argument("--fault-turn", type=int, default=1)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--reply", action="append", default=[])
    parser.add_argument("--mode", required=True, choices=["rpc"])
    parser.add_argument("--session-dir", required=True, type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--tools", required=True)
    parser.add_argument("--skill", type=Path, action="append", default=[])
    for flag in ("context-files", "extensions", "mcp", "skills", "prompt-templates"):
        parser.add_argument(f"--no-{flag}", action="store_true")
    options = parser.parse_args()

    count = sum(record["event"] == "spawn" for record in read_records(options.log))
    append_record(
        options.log,
        {
            "event": "spawn",
            "argv": sys.argv[1:],
            "cwd": os.getcwd(),
            "env_keys": sorted(os.environ),
            "pid": os.getpid(),
            "spawn_count": count + 1,
        },
    )
    print("Fake Pi stderr diagnostic", file=sys.stderr, flush=True)
    print('{"type":"extension_ui_request","id":"stderr-only"}', file=sys.stderr, flush=True)
    if options.scenario == "close-failure":
        signal.signal(signal.SIGTERM, lambda *_: append_record(options.log, {"event": "sigterm"}))
    session = Session(options)
    handlers = {
        "get_state": session.get_state,
        "get_commands": session.get_commands,
        "get_entries": session.get_entries,
    }
    for line in sys.stdin.buffer:
        command = json.loads(line)
        append_record(options.log, {"event": "command", "command": command})
        kind = command["type"]
        if kind == "prompt":
            if not session.prompt(command):
                return 0
        elif kind in handlers:
            handlers[kind](command)
            after_fault_turn = kind == "get_entries" and session.turns >= options.fault_turn
            if after_fault_turn and options.scenario == "late-invalid-json":
                # Wait until the supervisor has verified history and entered confirmation.
                release = options.log.with_suffix(".emit-invalid")
                deadline = time.monotonic() + 5
                while not release.exists():
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Supervisor did not reach confirmation")
                    time.sleep(0.01)
                emit_bytes(BAD_WIRE["invalid-json"])
            if after_fault_turn and options.scenario == "invalid-json-on-stdin-eof":
                session.emit({"type": "before_stdin_eof"})
        else:
            session.respond(command, error="Unsupported fake Pi command")

    append_record(options.log, {"event": "eof"})
    if options.scenario == "invalid-json-on-stdin-eof":
        emit_bytes(BAD_WIRE["invalid-json"])
        append_record(options.log, {"event": "invalid-json-written"})
    if options.scenario == "truncated-record-on-stdin-eof":
        # A complete-looking but unterminated record: no LF before a clean exit.
        emit_bytes(b'{"type":"queue_update"}')
        append_record(options.log, {"event": "truncated-record-written"})
    if options.scenario == "stream-descendant-on-eof":
        writer = os.fork()
        if writer == 0:
            append_record(options.log, {"event": "descendant", "pid": os.getpid()})
            deadline = time.monotonic() + 5
            with suppress(OSError):
                while time.monotonic() < deadline:
                    os.write(1, b'{"type":"queue_update"}\n')
                    time.sleep(0.001)
            os._exit(0)
    if options.scenario == "close-failure":
        # Leave time for the host's TERM/KILL sequence, with a cap if it never kills.
        time.sleep(8)
    return 1 if options.scenario == "close-nonzero" else 0


if __name__ == "__main__":
    sys.exit(main())
