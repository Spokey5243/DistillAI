"""Real product ASGI service with synthetic knowledge maintenance; no model process."""
from copy import deepcopy
import json
from pathlib import Path
import sys

from distillai import knowledge
from distillai.config import Config
from distillai.runtime import Runtime
from distillai.startup import run_service
from distillai.storage import Store, atomic_json


A, B = "a" * 32, "b" * 32
HTML = '<script>window.syntheticScriptRan = true</script><img src=x onerror="window.syntheticScriptRan=true">'


def main(home):
    store = Store(home)
    queue = home / "codex/queue/synthetic.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(json.dumps({"role": "user", "text": "Synthetic explanation " + HTML}) + "\n", encoding="utf-8")
    source = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}
    (home / "knowledge").mkdir()
    for identifier, name in ((A, "Alpha"), (B, "Beta")):
        atomic_json(home / "knowledge" / (identifier + ".json"),
            {"id": identifier, "name": name, "content": {"summary": HTML, "source_refs": [source]}})

    def execute(task, control):
        request = knowledge.execution_task(control, task)["inputs"]["user_edit"]
        directory = "knowledge" if request["record_kind"] == "knowledge" else "relations"
        path = Path(task["workspace"]) / directory / (request["record_id"] + ".json")
        record = json.loads(path.read_bytes())
        for field, value in request["changes"].items():
            if field == "content":
                record[field].update(deepcopy(value))
            else:
                record[field] = deepcopy(value)
        atomic_json(path, record)
        return {"knowledge_refs": [{"id": request["record_id"]}], "relation_refs": [], "reason": "Synthetic explicit edit"}

    runtime = Runtime(store, Config(store), execute,
        lambda task, result: knowledge.validate_task(runtime, task, result),
        prepare_result=lambda task, result: knowledge.prepare_result(runtime, task, result),
        after_commit=lambda task: knowledge.after_commit(runtime, task))
    run_service(runtime, material_register=lambda ref: None)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
