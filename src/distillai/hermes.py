"""The only direct AIAgent integration; each invocation has its own waiting subprocess."""
from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from http.client import HTTPConnection
from urllib.parse import urlsplit

from .runtime import BudgetError
from .sources import read_source
from .windows import ProcessJob


class HermesError(RuntimeError):
    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail


def _program_tool(frame, name, args):
    target = urlsplit(frame["model_base"])
    if (name not in {"evaluate_episode_boundary", "evaluate_episode_revision", "read_episode_source", "new_record_id", "audit_reads", "web_search", "fetch_page"} or target.scheme != "http"
            or target.hostname != "127.0.0.1" or not target.port
            or target.path != "/internal/tasks/" + frame["id"] + "/v1"):
        raise HermesError("Program tool requires its task loopback endpoint")
    connection = HTTPConnection("127.0.0.1", target.port, timeout=75 if name in {"web_search", "fetch_page"} else 10)
    try:
        connection.request("POST", target.path.removesuffix("/v1") + "/tools/" + name,
            body=json.dumps(args, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + frame["token"], "Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise HermesError("Program tool response exceeds 8 MiB")
        if response.status != 200:
            raise HermesError("Program tool rejected the request")
        return json.loads(raw)
    finally:
        connection.close()


class HermesExecutor:
    def __init__(self, source, python, model_base, *, runtime_dir, base_python):
        self.source = Path(source).resolve()
        self.python = Path(python).resolve()
        self.base_python = Path(base_python).resolve()
        self.model_base = model_base
        self.runtime_dir = Path(runtime_dir).resolve()
        if not (self.source / "run_agent.py").is_file() or not self.python.is_file() or not self.base_python.is_file():
            raise ValueError("Hermes source and a prepared application interpreter are required")

    def __call__(self, task, runtime):
        model = task["config"]["values"]["llm"]["model"]
        if not model:
            raise HermesError("Task has no configured model")
        inputs = dict(task["inputs"])
        sources = [read_source(runtime.store.home, ref) for ref in inputs.get("source_refs", [])
                   if ref.get("connector") == "codex"]
        if sources and "sources" not in inputs:
            inputs["sources"] = sources
        token = runtime.issue_token(task["id"])
        product_src = str(Path(__file__).resolve().parents[1])
        bootstrap = f"import sys;sys.path[:0]={[product_src, str(self.source)]!r};from distillai.__main__ import main;main()"
        environment = {name: value for name, value in os.environ.items()
                       if not name.upper().endswith(("_API_KEY", "_TOKEN", "_SECRET", "_KEY"))
                       and not name.upper().startswith(("HERMES_", "TERMINAL_"))}
        environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HERMES_SAFE_MODE="1",
                           PYTHON_DOTENV_DISABLED="1", NO_PROXY="localhost,127.0.0.1,::1",
                           HERMES_RUNTIME_DIR=str(self.runtime_dir), TERMINAL_ENV="local")
        environment["__PYVENV_LAUNCHER__"] = str(self.python)
        with tempfile.TemporaryDirectory(prefix=task["id"] + "-runtime-", dir=runtime.store.home / "workspaces") as temporary:
            home = Path(temporary)
            environment.update(HERMES_HOME=str(home / "hermes"), TEMP=str(home), TMP=str(home))
            environment["TERMINAL_CWD"] = task.get("workspace", str(home))
            frame = {"id": task["id"], "kind": task["kind"], "inputs": inputs,
                     "workspace": task.get("workspace", str(home)), "home": str(home / "hermes"),
                     "model": model, "model_base": self.model_base(task["id"]), "token": token,
                     "max_model_calls": task["config"]["values"]["runtime"]["max_model_calls"],
                     "prompt": runtime.store.read_version(task["prompt_version"]).decode("utf-8")}
            encoded = (json.dumps(frame, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
            if len(encoded) > 8 * 1024 * 1024:
                raise ValueError("Task subprocess input exceeds 8 MiB")
            with (home / "result.json").open("w+b") as output, ProcessJob() as job:
                # Direct interpreter keeps the Job PID authoritative; the Windows venv redirector creates another process.
                child = subprocess.Popen([str(self.base_python), "-I", "-B", "-c", bootstrap, "task-child"],
                    cwd=product_src, env=environment, stdin=subprocess.PIPE, stdout=output,
                    stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
                assigned = False
                try:
                    job.assign(child.pid)
                    assigned = True
                    runtime.attach_job(task["id"], job)
                    job.resume(child.pid)
                    child.stdin.write(encoded)
                    child.stdin.close()
                    child.wait()
                    job.stop()
                    output.seek(0)
                    received = output.read(8 * 1024 * 1024 + 1)
                    if len(received) > 8 * 1024 * 1024:
                        raise HermesError("Task subprocess output exceeds 8 MiB")
                    report = json.loads(received) if received else {}
                    if isinstance(report.get("final_response"), str):
                        version = runtime.store.put_version(report["final_response"].encode("utf-8"))
                        with runtime.store.locked():
                            saved = runtime.task(task["id"])
                            saved["model_output_version"] = version
                            runtime._save(saved)
                    if child.returncode:
                        if runtime.task(task["id"]).get("budget_exhausted"):
                            raise BudgetError("Task requested an additional generation after exhausting its budget")
                        raise HermesError("AIAgent child did not complete", report.get("error"))
                    return report["result"]
                finally:
                    if not child.stdin.closed:
                        child.stdin.close()
                    job.stop()
                    if child.poll() is None:
                        if not assigned:
                            child.kill()
                        child.wait(timeout=5)


def task_child():
    """The parent assigns and resumes this process before sending the first input line."""
    frame = json.loads(sys.stdin.buffer.readline(8 * 1024 * 1024 + 1))
    protocol = sys.stdout.buffer
    agent = None
    result = None
    error = None
    final_response = None
    stage = "configuration"
    with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink), redirect_stderr(sink):
        try:
            os.chdir(frame["workspace"])
            home = Path(frame["home"])
            home.mkdir(parents=True, exist_ok=True)
            configuration = {"compression": {"enabled": False}, "plugins": {"enabled": []},
                             "skills": {"auto_load": []}, "mcp_servers": {}, "auxiliary": {},
                             "tools": {"tool_search": {"enabled": "off"}}}
            (home / "config.yaml").write_text(json.dumps(configuration), encoding="utf-8")
            import hermes_cli.env_loader as env_loader
            # The pinned Library loads source .env even when python-dotenv is disabled.
            env_loader.load_hermes_dotenv = lambda **kwargs: []
            from run_agent import AIAgent
            from tools.registry import registry
            from .tools import register_read_tools, register_episode_tools, register_knowledge_tools, register_cognition_tools, register_context_tools, register_expansion_tools
            stage = "tools"
            allowed = set()
            enabled = []
            if frame["kind"] != "screening":
                allowed = register_read_tools(registry, frame["inputs"],
                    on_records=(lambda refs: _program_tool(frame, "audit_reads", {"records": refs})) if frame["kind"] == "query" else None,
                    on_sources=(lambda refs: _program_tool(frame, "audit_reads", {"sources": refs})) if frame["kind"] == "query" else None,
                    on_missing_source=(lambda args: _program_tool(frame, "read_episode_source", args)) if frame["kind"] == "episode" else None)
                if allowed:
                    enabled.append("distillai_read")
                if frame["kind"] == "episode" and frame["inputs"].get("episode_records"):
                    allowed.update(register_episode_tools(registry, lambda args: _program_tool(frame, "evaluate_episode_boundary", args),
                        lambda args: _program_tool(frame, "evaluate_episode_revision", args)))
                    enabled.append("distillai_episode")
                if frame["kind"] == "knowledge" and not frame["inputs"].get("user_edit"):
                    allowed.update(register_knowledge_tools(registry, lambda args: _program_tool(frame, "new_record_id", args)))
                    enabled.append("distillai_knowledge")
                if frame["kind"] == "cognition":
                    allowed.update(register_cognition_tools(registry, lambda args: _program_tool(frame, "new_record_id", args)))
                    enabled.append("distillai_cognition")
                if frame["kind"] == "context":
                    allowed.update(register_context_tools(registry, lambda args: _program_tool(frame, "new_record_id", args)))
                    enabled.append("distillai_context")
                if frame["kind"] == "expansion":
                    allowed.update(register_expansion_tools(registry, lambda tool, args: _program_tool(frame, tool, args)))
                    enabled.append("distillai_expansion")
                if frame["kind"] != "query":
                    enabled.extend(["file", "terminal"])
                    allowed.update({"read_file", "write_file", "patch", "search_files", "terminal", "process_manage"})
            stage = "initialize"
            agent = AIAgent(model=frame["model"], provider="custom", api_mode="chat_completions",
                base_url=frame["model_base"], api_key=frame["token"], quiet_mode=True,
                enabled_toolsets=enabled, skip_context_files=True, skip_memory=True,
                skip_background_review=True, load_soul_identity=False, save_trajectories=False,
                checkpoints_enabled=False, max_iterations=frame["max_model_calls"] + 1,
                ephemeral_system_prompt=frame["prompt"], cwd=frame["workspace"])
            actual = {tool["function"]["name"] for tool in agent.tools or []}
            stage = "tool_manifest"
            if actual - allowed:
                raise HermesError("Unexpected tools: " + ", ".join(sorted(actual - allowed)))
            visible_inputs = {key: value for key, value in frame["inputs"].items()
                              if frame["kind"] != "query" or key not in {"records", "sources"}}
            user_input = {"task_id": frame["id"], "kind": frame["kind"], "inputs": visible_inputs,
                          "workspace": frame["workspace"], "available_tools": sorted(actual)}
            stage = "generation"
            response = agent.run_conversation(json.dumps(user_input, ensure_ascii=False), task_id=frame["id"])
            final_response = response.get("final_response")
            if response.get("error") or not response.get("completed"):
                raise HermesError("AIAgent returned an incomplete result")
            stage = "parse_result"
            result = json.loads(response["final_response"])
        except Exception as exc:
            error = {"code": type(exc).__name__, "stage": stage}
            if stage in {"initialize", "tool_manifest"}:
                error["message"] = str(exc).replace(frame["token"], "[redacted]")[:240]
        finally:
            if agent is not None:
                agent.close()
    report = {"result": result} if error is None else {"error": error}
    report["final_response"] = final_response
    protocol.write(json.dumps(report, ensure_ascii=False).encode("utf-8"))
    protocol.flush()
    if error is not None:
        raise SystemExit(1)
