"""The only direct AIAgent integration; each invocation has its own waiting subprocess."""
from contextlib import redirect_stderr, redirect_stdout, contextmanager, ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import threading
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, Field, TypeAdapter, with_config

from .config import ModelConnection, PositiveInt
from .ipc import MAX_MESSAGE
from .runtime import BudgetError, TaskKind
from .sources import Identifier, NonblankText, read_source
from .windows import ProcessJob


def _history_request(body):
    def visible(value):
        if isinstance(value, list):
            return [visible(item) for item in value if not isinstance(item, dict) or item.get("type") not in
                    {"thinking", "reasoning", "analysis", "redacted_thinking"}]
        if isinstance(value, dict):
            return {name: visible(item) for name, item in value.items() if name not in
                    {"reasoning_content", "reasoning", "thinking", "analysis", "signature"}}
        return value
    return visible({name: item for name, item in body.items() if name in
                    {"model", "messages", "tools", "tool_choice", "parallel_tool_calls", "stream", "stream_options",
                     "max_tokens", "temperature", "top_p", "stop", "response_format"}})


class HermesError(RuntimeError):
    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail


DiagnosticCode = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ChildDiagnostic(TypedDict):
    code: DiagnosticCode
    stage: Literal["configuration", "tools", "initialize", "tool_manifest", "generation", "parse_result"]
    message: NotRequired[Literal["Task setup did not match its fixed configuration"]]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class TaskMessage(TypedDict):
    operation: str
    arguments: dict[str, Any]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class GenerationAttempt(TypedDict):
    attempt_id: Identifier


class GenerationRequest(GenerationAttempt):
    request: dict[str, Any]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class WebCall(TypedDict):
    tool: Literal["web_search", "fetch_page"]
    arguments: dict[str, Any]


class WebResponse(WebCall):
    response: Any


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class CompletionReport(TypedDict, total=False):
    result: Any
    error: ChildDiagnostic | None
    final_response: str | None


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class PipeBootstrap(TypedDict):
    address: Annotated[str, Field(pattern=r"^\\\\\.\\pipe\\distillai-[0-9a-f]{32}$")]
    authkey: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class TaskInput(TypedDict):
    id: Identifier
    kind: TaskKind
    inputs: dict[str, Any]
    workspace: NonblankText
    home: NonblankText
    llm: ModelConnection
    max_model_calls: PositiveInt
    prompt: str
    search_key: NotRequired[str]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class OperationError(TypedDict):
    code: DiagnosticCode


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class OperationFailure(TypedDict):
    error: OperationError


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class OperationResult(TypedDict):
    result: Any


PIPE_BOOTSTRAP = TypeAdapter(PipeBootstrap)
TASK_INPUT = TypeAdapter(TaskInput)
PROGRAM_REPLY = TypeAdapter(OperationResult | OperationFailure)
TASK_MESSAGE = TypeAdapter(TaskMessage)
PROGRAM_ARGUMENTS = TypeAdapter(dict[str, Any], config=ConfigDict(strict=True, hide_input_in_errors=True))
GENERATION_ATTEMPT = TypeAdapter(GenerationAttempt)
GENERATION_REQUEST = TypeAdapter(GenerationRequest)
WEB_CALL = TypeAdapter(WebCall)
WEB_RESPONSE = TypeAdapter(WebResponse)
COMPLETION_REPORT = TypeAdapter(CompletionReport)


def _program_tool(frame, name, args):
    if name in {"web_search", "fetch_page"}:
        return _search_tool(frame, name, args)
    channel = frame["_channel"]
    with frame["_channel_lock"]:
        channel.send_bytes(json.dumps({"operation": name, "arguments": args}, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        try:
            response = PROGRAM_REPLY.validate_json(channel.recv_bytes(MAX_MESSAGE))
        except ValueError:
            raise HermesError("Invalid program operation reply") from None
    if "error" in response:
        code = response["error"]["code"]
        if code == "BudgetError":
            raise BudgetError("Task generation budget exhausted")
        raise HermesError("Program operation rejected: " + code)
    return response["result"]


@contextmanager
def _tavily_client():
    import httpx
    from plugins.web.tavily import provider
    with httpx.Client(follow_redirects=False) as client:
        original_send, original_httpx = client.send, provider.httpx
        def send(request, **options):
            if str(request.url) not in {"https://api.tavily.com/search", "https://api.tavily.com/extract"}:
                raise ValueError("Search requires the fixed Tavily endpoint")
            request.headers["accept-encoding"] = "identity"
            options["stream"] = True
            response = original_send(request, **options)
            try:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("Search response exceeds 2 MiB")
                headers = {key: value for key, value in response.headers.items() if key.lower() not in {"content-encoding", "content-length"}}
                return httpx.Response(response.status_code, headers=headers, content=bytes(body), request=request)
            finally:
                response.close()
        client.send = send
        provider.httpx = client
        try:
            yield
        finally:
            provider.httpx = original_httpx


def _search_tool(frame, name, arguments):
    import httpx
    prepared = _program_tool(frame, "prepare_web_call", {"tool": name, "arguments": arguments})
    from plugins.web.tavily.provider import _tavily_request, _normalize_tavily_search_results, _normalize_tavily_documents
    try:
        raw = _tavily_request(prepared["endpoint"], prepared["payload"], api_key=frame["search_key"])
        if not isinstance(raw, dict) or not isinstance(raw.get("results"), list) or any(not isinstance(item, dict) for item in raw["results"]):
            raise ValueError("Invalid Tavily response")
        response = _normalize_tavily_search_results(raw) if name == "web_search" else _normalize_tavily_documents(raw)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        response = {"error": {"code": "quota_or_rate_limit" if status in {402, 429, 432, 433} else "search_failed" if name == "web_search" else "page_read_failed", "http_status": status}}
    except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
        response = {"error": {"code": "search_failed" if name == "web_search" else "page_read_failed"}}
    return _program_tool(frame, "complete_web_call", {"tool": name, "arguments": arguments, "response": response})


def _meter_client(client, frame):
    import httpx
    client.follow_redirects = False
    original_send = client.send

    def send(request, **options):
        expected = frame["llm"]["base_url"].rstrip("/") + "/chat/completions"
        body = json.loads(request.content)
        if request.method != "POST" or str(request.url) != expected or body.get("model") != frame["llm"]["model"]:
            raise HermesError("SDK request does not match the fixed task endpoint and model")
        if not frame["llm"]["api_key"]:
            request.headers.pop("authorization", None)
        attempt = uuid.uuid4().hex
        try:
            _program_tool(frame, "reserve_generation", {"attempt_id": attempt, "request": _history_request(body)})
        except BudgetError:
            # SDK exception wrapping would classify a hook exception as a retryable connection failure.
            return httpx.Response(400, request=request, json={"error": {"code": "budget_exhausted", "message": "Task generation budget exhausted"}})
        try:
            return original_send(request, **options)
        except httpx.ConnectError:
            _program_tool(frame, "release_unissued_generation", {"attempt_id": attempt})
            raise
    client.send = send
    return client


def _operation(runtime, task_id, name, arguments):
    PROGRAM_ARGUMENTS.validate_python(arguments)
    runtime._live(task_id)
    if name == "reserve_generation":
        GENERATION_REQUEST.validate_python(arguments)
        snapshot = _history_request(arguments["request"])
        request_version = runtime.store.put_version(json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        return runtime.reserve_generation(task_id, attempt_id=arguments["attempt_id"], request_version=request_version)
    if name == "release_unissued_generation":
        GENERATION_ATTEMPT.validate_python(arguments)
        runtime.release_unissued_generation(task_id, arguments["attempt_id"])
        return {"released": True}
    if name in {"evaluate_episode_boundary", "evaluate_episode_revision", "read_episode_source"}:
        from .episode import evaluate, evaluate_revision, read_episode_source
        return {"evaluate_episode_boundary": evaluate, "evaluate_episode_revision": evaluate_revision,
                "read_episode_source": read_episode_source}[name](runtime, task_id, arguments)
    if name == "audit_reads":
        from .context import AUDIT_ARGS, audit_reads
        AUDIT_ARGS.validate_python(arguments)
        if not arguments:
            raise ValueError("Invalid read audit")
        return audit_reads(runtime, task_id, arguments.get("records", []), arguments.get("sources", []))
    if name in {"prepare_web_call", "complete_web_call"}:
        from .expansion import prepare_web_call, web_tool
        (WEB_CALL if name == "prepare_web_call" else WEB_RESPONSE).validate_python(arguments)
        if name == "prepare_web_call":
            return prepare_web_call(runtime, task_id, arguments["tool"], arguments["arguments"])
        return web_tool(runtime, task_id, arguments["tool"], arguments["arguments"], arguments["response"])
    if name == "new_record_id":
        kind = arguments.get("record_kind")
        if kind == "candidate":
            from .context import ALLOCATION_ARGS, allocate_candidate
            ALLOCATION_ARGS.validate_python(arguments)
            return allocate_candidate(runtime, task_id)
        if kind in {"observation", "hypothesis"}:
            from .cognition import ALLOCATION_ARGS, allocate_id
            ALLOCATION_ARGS.validate_python(arguments)
            if kind == "hypothesis" and "source_refs" in arguments:
                raise ValueError("Hypothesis allocation does not accept observation sources")
            return allocate_id(runtime, task_id, kind, arguments.get("source_refs"))
        from .knowledge import ALLOCATION_ARGS, allocate_id
        ALLOCATION_ARGS.validate_python(arguments)
        return allocate_id(runtime, task_id, kind)
    raise ValueError("Unknown program operation")


class HermesExecutor:
    def __init__(self, source, python, *, runtime_dir, base_python):
        self.source, self.python = Path(source).resolve(), Path(python).resolve()
        self.base_python, self.runtime_dir = Path(base_python).resolve(), Path(runtime_dir).resolve()
        if not (self.source / "run_agent.py").is_file() or not self.python.is_file() or not self.base_python.is_file():
            raise ValueError("Hermes source and a prepared application interpreter are required")

    def __call__(self, task, runtime):
        from .ipc import TaskPipe
        private = runtime.config.private(task["config"]["version"])["values"]
        llm = private["llm"]
        if not llm["model"] or not llm["base_url"]:
            raise HermesError("Task has no configured model endpoint")
        inputs = dict(task["inputs"])
        sources = [read_source(runtime.store.home, ref) for ref in inputs.get("source_refs", []) if ref.get("connector") == "codex"]
        if sources and "sources" not in inputs:
            inputs["sources"] = sources
        product_src = str(Path(__file__).resolve().parents[1])
        bootstrap = f"import sys;sys.path[:0]={[product_src, str(self.source)]!r};from distillai.__main__ import main;main()"
        environment = {name: value for name, value in os.environ.items()
            if not name.upper().endswith(("_API_KEY", "_TOKEN", "_SECRET", "_KEY"))
            and not name.upper().startswith(("HERMES_", "TERMINAL_")) and name.upper() != "TAVILY_BASE_URL"}
        environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HERMES_SAFE_MODE="1",
            PYTHON_DOTENV_DISABLED="1", HERMES_RUNTIME_DIR=str(self.runtime_dir), TERMINAL_ENV="local",
            __PYVENV_LAUNCHER__=str(self.python))
        with tempfile.TemporaryDirectory(prefix=task["id"] + "-runtime-", dir=runtime.store.home / "workspaces") as temporary, ProcessJob() as job:
            home = Path(temporary)
            environment.update(HERMES_HOME=str(home / "hermes"), TEMP=str(home), TMP=str(home),
                TERMINAL_CWD=task.get("workspace", str(home)))
            frame = {"id": task["id"], "kind": task["kind"], "inputs": inputs,
                "workspace": task.get("workspace", str(home)), "home": str(home / "hermes"),
                "llm": llm,
                "max_model_calls": task["config"]["values"]["runtime"]["max_model_calls"],
                "prompt": runtime.store.read_version(task["prompt_version"]).decode("utf-8")}
            if task["kind"] == "expansion":
                frame["search_key"] = private["search"]["api_key"] or getattr(runtime, "search_environment_key", "")
            with TaskPipe(job) as channel:
                child = subprocess.Popen([str(self.base_python), "-I", "-B", "-c", bootstrap, "task-child"],
                    cwd=product_src, env=environment, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
                assigned = False
                try:
                    job.assign(child.pid)
                    assigned = True
                    runtime.attach_job(task["id"], job)
                    job.resume(child.pid)
                    child.stdin.write((json.dumps({"address": channel.address, "authkey": channel.authkey.hex()}) + "\n").encode())
                    child.stdin.close()
                    channel.accept(timeout=10, cancelled=lambda: child.poll() is not None)
                    channel.send(json.dumps(frame, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                    while True:
                        try:
                            message = TASK_MESSAGE.validate_json(channel.receive(cancelled=lambda: child.poll() is not None))
                        except ValueError:
                            raise HermesError("Invalid task communication frame") from None
                        name, arguments = message["operation"], message["arguments"]
                        if name == "complete":
                            try:
                                COMPLETION_REPORT.validate_python(arguments)
                            except ValueError:
                                raise HermesError("Invalid task completion") from None
                            if not arguments.get("error") and "result" not in arguments:
                                raise HermesError("Task completion has no result")
                            channel.send(b'{"result":null}')
                            child.wait(timeout=5)
                            job.stop()
                            if isinstance(arguments.get("final_response"), str):
                                version = runtime.store.put_version(arguments["final_response"].encode("utf-8"))
                                with runtime.store.locked():
                                    saved = runtime.task(task["id"])
                                    saved["model_output_version"] = version
                                    runtime._save(saved)
                            if child.returncode or arguments.get("error"):
                                if arguments.get("error"):
                                    detail = arguments["error"]
                                    from loguru import logger  # Only the parent executor imports the product logger.
                                    logger.bind(component="backend", task_id=task["id"], stage=detail["stage"],
                                        error_code=detail["code"]).warning("agent_failed")
                                if runtime.task(task["id"]).get("budget_exhausted"):
                                    raise BudgetError("Task requested a generation after exhausting its budget")
                                raise HermesError("AIAgent child did not complete", arguments.get("error"))
                            return arguments["result"]
                        try:
                            result = _operation(runtime, task["id"], name, arguments)
                            response = {"result": result}
                        except Exception as error:
                            response = {"error": {"code": type(error).__name__}}
                        channel.send(json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8"))
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
    from multiprocessing.connection import Client
    try:
        bootstrap = PIPE_BOOTSTRAP.validate_json(sys.stdin.buffer.readline(4097))
    except ValueError:
        raise HermesError("Invalid task pipe bootstrap") from None
    protocol = Client(bootstrap["address"], family="AF_PIPE", authkey=bytes.fromhex(bootstrap["authkey"]))
    try:
        frame = TASK_INPUT.validate_json(protocol.recv_bytes(MAX_MESSAGE))
    except ValueError:
        protocol.close()
        raise HermesError("Invalid task input") from None
    frame["_channel"] = protocol
    frame["_channel_lock"] = threading.RLock()
    agent = None
    result = None
    error = None
    final_response = None
    stage = "configuration"
    with ExitStack() as resources, open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink), redirect_stderr(sink):
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
            if frame["kind"] == "expansion":
                resources.enter_context(_tavily_client())
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
            from agent.ssl_verify import resolve_httpx_verify

            class TaskAgent(AIAgent):
                def _create_openai_client(self, client_kwargs, *, reason, shared):
                    kwargs = dict(client_kwargs)
                    verify = resolve_httpx_verify(ca_bundle=kwargs.get("ssl_ca_cert"),
                        ssl_verify=kwargs.get("ssl_verify"), base_url=str(kwargs.get("base_url", "")))
                    client = self._build_keepalive_http_client(str(kwargs.get("base_url", "")), verify=verify)
                    if client is None:
                        raise HermesError("Metered SDK HTTP client is unavailable")
                    _meter_client(client, frame)
                    kwargs.update(http_client=client, max_retries=0)
                    try:
                        return super()._create_openai_client(kwargs, reason=reason, shared=shared)
                    except BaseException:
                        client.close()
                        raise

            parameters = dict(frame["llm"]["parameters"])
            max_tokens = parameters.pop("max_tokens", None)
            thinking = parameters.pop("thinking", None)
            if thinking is not None:
                parameters["extra_body"] = {"thinking": thinking}
            agent = TaskAgent(model=frame["llm"]["model"], provider="custom", api_mode="chat_completions",
                base_url=frame["llm"]["base_url"], api_key=frame["llm"]["api_key"] or "no-key-required", quiet_mode=True,
                max_tokens=max_tokens, request_overrides=parameters,
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
                error["message"] = "Task setup did not match its fixed configuration"
        finally:
            if agent is not None:
                agent.close()
    report = {"result": result} if error is None else {"error": error}
    report["final_response"] = final_response
    protocol.send_bytes(json.dumps({"operation": "complete", "arguments": report}, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    try:
        if PROGRAM_REPLY.validate_json(protocol.recv_bytes(MAX_MESSAGE)) != {"result": None}:
            raise HermesError("Invalid task completion acknowledgement")
    finally:
        protocol.close()
    if error is not None:
        raise SystemExit(1)
