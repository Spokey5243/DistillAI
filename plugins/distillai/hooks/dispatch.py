"""Codex command Hook: fail open and keep stdout reserved for Hook JSON."""
import json
import os
from pathlib import Path
import sys


def main():
    home = Path(os.environ.get("DISTILLAI_HOME", Path.home() / ".distillAI"))
    try:
        source = Path(__file__).resolve().parents[3] / "src"
        if not (source / "distillai" / "capture.py").is_file():
            launch = json.loads((home / "config" / "launch.json").read_text(encoding="utf-8"))
            source = Path(launch["product_src"])
        sys.path.insert(0, str(source))
        from distillai.capture import capture, diagnostic
        capture(home, json.loads(sys.stdin.buffer.read()))
    except Exception as error:
        if "diagnostic" in locals():
            diagnostic(home, "unknown", None, "dispatch", error)
    print("{}")


if __name__ == "__main__":
    main()
