"""Product startup and task-child entry points."""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(prog="distillai")
    parser.add_argument("mode", choices=["check", "start", "serve", "stop", "mcp", "web", "task-child"])
    parser.add_argument("--home")
    parser.add_argument("--hermes-source")
    parser.add_argument("--hermes-python")
    options = parser.parse_args()
    if options.mode == "task-child":
        from .hermes import task_child
        task_child()
        return
    from .startup import (check_environment, data_home, live_instance, public_instance,
                          run_service, start_product, stop_background, load_launch)
    home = data_home(options.home)
    if options.mode == "stop":
        print(json.dumps({"stopped": stop_background(home)}))
        return
    saved = home / "config" / "launch.json"
    launch = load_launch(home, hermes_source=options.hermes_source, hermes_python=options.hermes_python)
    source, python = launch.hermes_source, launch.hermes_python
    if not source or not python:
        parser.error("Explicit --hermes-source and --hermes-python are required before the first start")
    environment = check_environment(source, python)
    if options.mode == "check":
        print(json.dumps({"environment": environment, "instance": public_instance(live_instance(home))}))
        return
    from .storage import atomic_json, Store
    from .config import Config
    from .hermes import HermesExecutor
    from .runtime import Runtime
    store = Store(home)
    if options.mode in {"start", "mcp", "web"}:
        product_src = str(Path(__file__).resolve().parents[1])
        with store.locked():
            atomic_json(saved, {"hermes_source": str(Path(source).resolve()), "hermes_python": str(Path(python).resolve()),
                                "base_python": environment["base_python"], "product_src": product_src})
        if options.mode == "mcp":
            from .mcp import run_stdio
            run_stdio(home)
            return
        instance = start_product(home)
        if options.mode == "web":
            import webbrowser
            from .startup import instance_request
            opened = instance_request(instance, "/internal/web/bootstrap", method="POST", body={})
            launched = webbrowser.open(opened["url"])
            print(json.dumps({"browser_opened": launched, **({"url": opened["url"]} if not launched else {})}))
            return
        print(json.dumps({"instance": public_instance(instance)}))
        return
    config = Config(store, protected_paths=(Path(source).resolve(), Path(python).resolve().parent.parent,
                                            Path(environment["runtime_dir"])))
    executor = HermesExecutor(source, python,
                              runtime_dir=environment["runtime_dir"], base_python=environment["base_python"])

    def business(task):
        module = {"episode": "episode", "knowledge": "knowledge", "cognition": "cognition",
                  "expansion": "expansion", "context": "context", "query": "context",
                  "screening": "context", "correction": "episode"}[task["kind"]]
        return importlib.import_module("distillai." + module)

    def execute(task, runtime):
        prepared = business(task).execution_task(runtime, task)
        return executor(prepared, runtime)

    runtime = Runtime(store, config, execute,
                      lambda task, result: business(task).validate_task(runtime, task, result),
                      after_commit=lambda task: business(task).after_commit(runtime, task),
                      prepare_result=lambda task, result: business(task).prepare_result(runtime, task, result))
    runtime.search_environment_key = os.environ.get("TAVILY_API_KEY", "")
    runtime.expansion_ready = True  # G3: direct child Tavily Search/Extract and M04→M07, 2026-10-17.
    from .episode import register_material
    run_service(runtime, material_register=lambda ref: register_material(runtime, ref))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": {"code": type(error).__name__}}), file=sys.stderr)
        raise SystemExit(1)
