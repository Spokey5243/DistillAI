"""Data-root singleton ownership and native client startup/stop helpers."""
from contextlib import contextmanager
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

from .server import BackendServer, _NoRedirect
from .storage import atomic_json


HERMES_SHA = "a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed"


def check_environment(source, python):
    source, python = Path(source).resolve(), Path(python).resolve()
    if not (source / "run_agent.py").is_file() or not python.is_file():
        raise ValueError("Provide Hermes source and its prepared application interpreter")
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"],
                           check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
    if revision != HERMES_SHA or dirty:
        raise ValueError("Hermes source does not match the clean, verified G1 revision")
    lock = Path(__file__).resolve().parents[2] / "uv.lock"
    code = (
        "import sys,json,tomllib,importlib.metadata as m;from mcp.server import MCPServer;"
        f"packages=tomllib.load(open({str(lock)!r},'rb'))['package'];"
        "assert sys.version_info >= (3,13);"
        "assert all(p['name']=='distillai' or m.version(p['name'])==p['version'] for p in packages);"
        "print(json.dumps({'python':sys.executable,'base_python':sys._base_executable,'prefix':sys.prefix,'python_version':sys.version.split()[0],"
        "'base_prefix':sys.base_prefix,'mcp_version':m.version('mcp')}))")
    checked = subprocess.run([str(python), "-I", "-B", "-c", code], check=True,
                             capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    details = json.loads(checked.stdout)
    for parent in python.parents:
        facts = parent / "facts.json"
        if facts.is_file():
            recorded = json.loads(facts.read_text(encoding="utf-8"))
            environment = recorded.get("packages", {}).get("venv", {}).get("environment")
            if environment and Path(environment).resolve() == Path(details["prefix"]).resolve():
                break
    else:
        raise ValueError("Interpreter is not the application environment recorded by Hermes PM")
    return {**details, "source": str(source), "source_sha": revision,
            "runtime_dir": str(Path(details["base_prefix"]).parent)}


def public_instance(instance):
    return None if instance is None else {name: instance[name] for name in
                                        ("instance_id", "pid", "protocol", "url", "ready")}


def data_home(home=None):
    return Path(home or os.environ.get("DISTILLAI_HOME", Path.home() / ".distillAI")).resolve()


def instance_request(instance, path, *, method="GET", body=None, timeout=3):
    url = urlsplit(instance["url"])
    if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.path or url.query or url.fragment or url.username:
        raise ValueError("Invalid local instance address")
    request = Request(instance["url"] + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None, method=method,
        headers={"Authorization": "Bearer " + instance["token"], "Content-Type": "application/json"})
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Local control response exceeds 2 MiB")
        return json.loads(data)


def live_instance(home):
    try:
        instance = json.loads((data_home(home) / "instance.json").read_text(encoding="utf-8"))
        if instance["protocol"] != 1 or type(instance["pid"]) is not int or instance["pid"] <= 0:
            return None
        health = instance_request(instance, "/v1/health", timeout=.3)
        if any(health[name] != instance[name] for name in ("instance_id", "pid", "protocol")):
            return None
        return {**instance, "ready": health["ready"]}
    except (OSError, ValueError, TypeError, KeyError):
        return None


@contextmanager
def _lease(home):
    path = data_home(home) / ".instance.lock"
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def start_background(home, command, timeout=10, *, python_launcher=None):
    current = live_instance(home)
    if current is not None and current["ready"]:
        return current
    message = "Cannot start an independent backend from this Windows process. Start scripts/start.ps1 -Action Serve outside the MCP client, then reconnect."
    launch_id = uuid.uuid4().hex
    environment = {**os.environ, "DISTILLAI_START_NONCE": launch_id}
    if python_launcher is not None:
        environment["__PYVENV_LAUNCHER__"] = str(python_launcher)
    try:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                                 env=environment)
    except OSError as error:
        if error.winerror == 5:
            raise RuntimeError(message) from None
        raise
    threading.Thread(target=child.wait, daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = live_instance(home)
        if current is not None and current["ready"] and (current.get("launch_id") == launch_id or child.poll() == 0):
            return current
        if child.poll() is not None:
            raise RuntimeError(f"Background startup exited before readiness ({child.returncode})")
        time.sleep(.05)
    raise TimeoutError("Background startup has not reported a verified ready instance")


def stop_background(home, timeout=10):
    instance = live_instance(home)
    if instance is None:
        return False
    instance_request(instance, "/internal/stop", method="POST", body={})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not (data_home(home) / "instance.json").exists():
            with _lease(home) as free:
                if free:
                    return True
        time.sleep(.05)
    raise TimeoutError("Background has not confirmed task stop and service exit")


def run_service(runtime, *, material_register=None):
    home = runtime.store.home
    with _lease(home) as owned:
        if not owned:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if live_instance(home) is not None:
                    return
                time.sleep(.05)
            raise RuntimeError("Another process owns this data root but has not become healthy")
        if live_instance(home) is not None:
            return
        runtime.recover_tasks()
        if not hasattr(runtime, "knowledge_index"):
            from .knowledge import KnowledgeIndex
            runtime.knowledge_index = KnowledgeIndex(runtime.store)
            try:
                runtime.knowledge_index.rebuild()
            except Exception as error:
                runtime.store.event({"event": "knowledge_index_pending", "code": type(error).__name__})
        server = BackendServer(runtime)
        instance = {"instance_id": server.instance_id, "pid": os.getpid(), "protocol": 1,
                    "url": server.url, "token": server.token,
                    "launch_id": os.environ.get("DISTILLAI_START_NONCE")}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with runtime.store.locked():
            atomic_json(home / "instance.json", instance)
        try:
            while not server.stopping.is_set():
                runtime.finish_post_commits()
                runtime.discover_materials(register=material_register)
                from .context import reconcile_feedback
                reconcile_feedback(runtime)
                from .expansion import tick
                tick(runtime)
                runtime.dispatch()
                interval = runtime.config.read()["values"]["runtime"]["poll_interval_seconds"]
                runtime._wake.wait(min(interval, threading.TIMEOUT_MAX))
                runtime._wake.clear()
        except KeyboardInterrupt:
            server.stopping.set()
        finally:
            while True:
                try:
                    runtime.close()
                    break
                except Exception as exc:
                    try:
                        runtime.store.event({"event": "stop_pending", "error": type(exc).__name__})
                    except OSError:
                        pass
                    runtime._wake.clear()
                    runtime._wake.wait(1)
            server.shutdown()
            thread.join(5)
            server.server_close()
            with runtime.store.locked():
                current = json.loads((home / "instance.json").read_text(encoding="utf-8"))
                if current["instance_id"] == server.instance_id:
                    (home / "instance.json").unlink()
