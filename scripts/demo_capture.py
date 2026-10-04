"""Send synthetic events through the real hook command; no model request."""
import json
import os
from pathlib import Path
import subprocess
import uuid

plugin = Path(__file__).resolve().parents[1] / "plugins/distill-capture"
hooks = json.loads((plugin / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
session = "demo-" + str(uuid.uuid4())
for event, message in [("UserPromptSubmit", {"prompt": "DISTILL-DEMO：中文测试\n第二行"}),
                       ("Stop", {"last_assistant_message": "收到。这是模拟输入，不是真实会话。"})]:
    payload = {
        "session_id": session, "turn_id": "demo-turn", "hook_event_name": event,
        "cwd": str(Path.cwd()), "model": "demo", "transcript_path": None,
        "test_fixture": True, **message,
    }
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", hooks[event][0]["hooks"][0]["command"]],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), capture_output=True,
        env={**os.environ, "PLUGIN_ROOT": str(plugin)}, timeout=10,
    )
    if result.returncode or result.stderr or result.stdout.strip() != b"{}":
        raise RuntimeError(f"Hook failed: {result.stdout!r} {result.stderr!r}")
home = Path(os.environ.get("DISTILLAI_HOME", str(Path.home() / ".distallAI")))
path = home / "data/sessions" / f"{session}.jsonl"
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
assert len(rows) == 2 and rows[0]["payload"]["prompt"].endswith("\n第二行")
print(f"PASS (synthetic events): {path}")
