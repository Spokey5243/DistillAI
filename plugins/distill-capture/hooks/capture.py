"""Windows-only Codex hook: stdin JSON -> local JSONL; stdout never injects context."""
from datetime import datetime, timezone
import json
import msvcrt
import os
from pathlib import Path
import re
import sys
import time
import uuid


def append_locked(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        # ponytail: one Windows byte-range lock per file; use SQLite when queries are needed.
        # ponytail: at most 2s per lock within the 5s Hook timeout; queue if bursts need lossless capture.
        deadline = time.monotonic() + 2
        while True:
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        try:
            stream.seek(0, os.SEEK_END)
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def resolve_platform(argv):
    # One script serves every host agent; --platform marks the event source.
    if "--platform" in argv:
        index = argv.index("--platform")
        if index + 1 < len(argv) and re.fullmatch(r"[a-z0-9_-]{1,32}", argv[index + 1]):
            return argv[index + 1]
    return "codex"


def main():
    home = Path(os.environ.get("DISTILLAI_HOME", str(Path.home() / ".distallAI")))
    platform = resolve_platform(sys.argv)
    event = "unknown"
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("Hook input must be a JSON object")
        session = payload.get("session_id")
        if (not isinstance(session, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session)
                or re.fullmatch(r"CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9]", session, re.I)):
            raise ValueError("Invalid session_id")
        event = payload.get("hook_event_name")
        roles = {"UserPromptSubmit": "user", "Stop": "assistant"}
        if event not in roles:
            raise ValueError("Unsupported hook event")
        content_key = "prompt" if event == "UserPromptSubmit" else "last_assistant_message"
        content = payload.get(content_key)
        if not isinstance(content, str) and not (event == "Stop" and content is None):
            raise ValueError("Message must be text (Stop may be null)")
        record = {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "platform": platform,
            "session_id": session,
            "turn_id": payload.get("turn_id"),
            "hook_event_name": event,
            "role": roles[event],
            "payload": payload,
        }
        append_locked(home / "data" / "sessions" / f"{session}.jsonl",
                      json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as error:
        # Do not log the message body; keep failures separate from learning evidence.
        entry = json.dumps({"captured_at": datetime.now(timezone.utc).isoformat(),
                            "event": event, "error": type(error).__name__,
                            "detail": str(error)}, ensure_ascii=True) + "\n"
        try:
            append_locked(home / "logs" / "capture-errors.log", entry)
        except Exception:
            pass
        sys.stderr.write("Distill capture failed; see ~/.distallAI/logs/capture-errors.log\n")
    # Stop requires JSON; {} also leaves UserPromptSubmit unchanged.
    print("{}")


if __name__ == "__main__":
    main()
