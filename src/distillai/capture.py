"""Synchronous, model-free capture; notification is only a bounded wake-up hint."""
import json
from pathlib import Path
import re
import socket
import time
from urllib.parse import urlsplit
from typing import Annotated, TypedDict

from pydantic import ConfigDict, Field, TypeAdapter, with_config

from .sources import entry, now, queue_path, utc
from .storage import atomic_json
from .windows import FileHandle, pinned_path


SYSTEM_TAGS = ("environment_context", "turn_aborted", "user_instructions", "apps_instructions",
               "plugins_instructions", "skills_instructions", "collaboration_mode")
TRIVIAL_SHELL = ("cd", "ls", "pwd", "echo", "cat", "head", "tail", "which", "type", "grep", "rg", "find",
                 "fd", "wc", "sed", "awk", "less", "more", "stat", "file", "tree", "du", "df", "env", "printf",
                 "sort", "uniq", "cut", "jq", "open", "true", "sleep", "date",
                 "git status", "git log", "git diff", "git show", "git branch")


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class CaptureCursor(TypedDict):
    count: Annotated[int, Field(ge=0)]
    at: str


CAPTURE_CURSOR = TypeAdapter(CaptureCursor)


def session_key(value):
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def parse_rollout(path):
    rows = []
    for line in Path(path).read_bytes().split(b"\n"):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "response_item":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
            continue
        content = payload.get("content")
        if isinstance(content, list):
            content = "\n".join(block["text"] for block in content if isinstance(block, dict)
                                and block.get("type") in ("input_text", "output_text", "text")
                                and isinstance(block.get("text"), str))
        if not isinstance(content, str) or not content.strip():
            continue
        text = content.strip()
        if payload["role"] == "user" and any(text.startswith((f"<{tag}>", f"<{tag} ")) for tag in SYSTEM_TAGS):
            continue
        row = {"role": payload["role"], "text": text}
        at = utc(event.get("timestamp"))
        if at is not None:
            row["at"] = at
        rows.append(row)
    return rows


def summarize_tool(name, inputs):
    if not isinstance(name, str) or not name or name.startswith("mcp__distillai__"):
        return ""
    inputs = inputs if isinstance(inputs, dict) else {}
    if name in ("Bash", "shell", "local_shell", "exec"):
        command = inputs.get("command", "")
        if isinstance(command, list) and all(isinstance(part, str) for part in command):
            command = " ".join(command)
        if not isinstance(command, str):
            return ""
        command = command.strip()
        if not command or any(command == trivial or command.startswith(trivial + " ") for trivial in TRIVIAL_SHELL):
            return ""
        return "ran: " + command[:120]
    if name == "apply_patch":
        patch = inputs.get("input") if isinstance(inputs.get("input"), str) else inputs.get("patch", "")
        files = re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch, re.MULTILINE) if isinstance(patch, str) else []
        return "edited: " + ", ".join(files[:5]) if files else "applied a patch"
    return "used " + name


def diagnostic(home, event, key, stage, error):
    try:
        from loguru import logger
        from .diagnostics import diagnostic_sink
        with diagnostic_sink(home, "capture"):
            logger.bind(component="capture", event=event if event in ("Stop", "PreCompact", "PostToolUse") else "unknown",
                session_key=key, stage=stage, error_code=type(error).__name__,
                winerror=getattr(error, "winerror", None)).warning("capture_failed")
    except Exception:
        pass


def _cursor(path, total):
    try:
        value = CAPTURE_CURSOR.validate_json(path.read_bytes())
        count = value["count"]
        if count <= total and utc(value["at"]) is not None:
            return count
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return 0


def _tail(data):
    lines = data.split(b"\n")
    for line in lines[:-1]:
        entry(line)
    tail = lines[-1]
    if not tail:
        return len(data), b""
    try:
        text = tail.decode("utf-8")
    except UnicodeDecodeError as error:
        if error.reason != "unexpected end of data":
            raise
        text = tail[:error.start].decode("utf-8")
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        # Only a parseable prefix cut at EOF is known to be an unregistered partial entry.
        if error.pos < len(text.rstrip()) and not error.msg.startswith("Unterminated string"):
            raise
        return len(data) - len(tail), b""
    entry(tail)
    return len(data), b"\n"


def capture(home, payload):
    home = Path(home)
    event, key, stage = "unknown", None, "input"
    try:
        event = payload.get("hook_event_name")
        session = payload.get("session_id")
        if not isinstance(session, str) or not session or event not in ("Stop", "PreCompact", "PostToolUse"):
            return "skipped"
        key = session_key(session)
        if event == "PostToolUse":
            inputs = payload.get("tool_input")
            # Codex exposes apply_patch source as command; keep the reference summary rules.
            if payload.get("tool_name") == "apply_patch" and isinstance(inputs, dict) and "command" in inputs:
                inputs = {**inputs, "input": inputs["command"]}
            text = summarize_tool(payload.get("tool_name"), inputs)
            if not text:
                return "skipped"
            rows = [{"role": "tool", "text": text, "at": now()}]
        elif not isinstance(payload.get("transcript_path"), str) or not payload["transcript_path"]:
            return "skipped"
        path = queue_path(home, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        cursor = home / "codex" / "cursors" / (key + ".json")
        cursor.parent.mkdir(parents=True, exist_ok=True)
        stage = "write_lock"
        with pinned_path(path) as parent, FileHandle(path, writable=True, open_always=True, parent=parent) as queue:
            stage = "rollout"
            if event != "PostToolUse":
                rows = parse_rollout(payload["transcript_path"])
                total = len(rows)
                rows = rows[_cursor(cursor, total):]
            stage = "queue"
            offset, newline = _tail(queue.read())
            encoded = b"".join((json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8") for row in rows)
            queue.write(newline + encoded, offset=offset)
            if event != "PostToolUse":
                stage = "cursor"
                atomic_json(cursor, {"count": total, "at": now()})
        if rows:
            notify(home, key)
        return "saved" if rows else "unchanged"
    except Exception as error:
        if stage == "write_lock" and getattr(error, "winerror", None) in (32, 33):
            return "busy"
        diagnostic(home, event, key, stage, error)
        return "error"


def notify(home, key):
    """Send only to a recorded loopback instance, with one shared 200ms deadline."""
    try:
        instance = json.loads((Path(home) / "instance.json").read_text(encoding="utf-8"))
        url = urlsplit(instance["url"])
        token = instance["token"]
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                or url.path not in ("", "/") or url.query or url.fragment or url.username or url.password
                or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", token)):
            return
        body = json.dumps({"connector": "codex", "session_key": key}).encode("utf-8")
        request = (f"POST /v1/material-notifications HTTP/1.1\r\nHost: 127.0.0.1:{url.port}\r\n"
                   f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode("ascii") + body
        deadline = time.monotonic() + .2
        with socket.socket() as connection:
            connection.settimeout(max(.001, deadline - time.monotonic()))
            connection.connect(("127.0.0.1", url.port))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            connection.settimeout(remaining)
            connection.sendall(request)
    except Exception:
        pass
