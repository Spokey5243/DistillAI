"""Data-root singleton ownership and native client startup/stop helpers."""
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timezone
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import threading
import time
import uuid
import importlib
from urllib.parse import urlsplit
import httpx
import anyio
import portalocker
from loguru import logger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED, EVENT_JOB_SUBMITTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .server import BackendServer
from .storage import atomic_json
from .diagnostics import diagnostic_sink


HERMES_SHA = "a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed"


def load_launch(home, **overrides):
    from pydantic_settings import BaseSettings, JsonConfigSettingsSource, SettingsConfigDict

    class Launch(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="DISTILLAI_", env_file=None, secrets_dir=None,
            json_file=Path(home) / "config/launch.json", extra="ignore")
        hermes_source: str | None = None
        hermes_python: str | None = None

        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
            return init_settings, env_settings, JsonConfigSettingsSource(settings_cls)

    return Launch(**{name: value for name, value in overrides.items() if value is not None})


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
    for name in ("fastapi", "uvicorn", "httpx", "fastmcp", "pydantic", "loguru", "networkx"):
        importlib.import_module(name)
    code = (
        "import sys,json,importlib.metadata as m;"
        f"sys.path.insert(0,{str(source)!r});"
        "import hermes_cli.env_loader as loader;loader.load_hermes_dotenv=lambda **kwargs:[];"
        "from run_agent import AIAgent;"
        "assert sys.version_info >= (3,13);"
        "print(json.dumps({'python':sys.executable,'base_python':sys._base_executable,'prefix':sys.prefix,'python_version':sys.version.split()[0],"
        "'base_prefix':sys.base_prefix,'openai_version':m.version('openai'),'httpx_version':m.version('httpx')}))")
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


def instance_url(instance):
    url = urlsplit(instance["url"])
    if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.path or url.query or url.fragment or url.username:
        raise ValueError("Invalid local instance address")
    return instance["url"]


def instance_request(instance, path, *, method="GET", body=None, timeout=3):
    address = instance_url(instance)
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout) as client:
        with client.stream(method, address + path, json=body,
                headers={"Authorization": "Bearer " + instance["token"], "Content-Type": "application/json"}) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 2 * 1024 * 1024:
                    raise ValueError("Local control response exceeds 2 MiB")
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
    except (OSError, ValueError, TypeError, KeyError, httpx.HTTPError):
        return None


@contextmanager
def _lease(home):
    path = data_home(home) / ".instance.lock"
    lease = portalocker.Lock(path, mode="a+b", timeout=0)
    try:
        lease.acquire()
    except portalocker.LockException:
        yield False
        return
    try:
        yield True
    finally:
        lease.release()


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


def start_product(home):
    product_src = str(Path(__file__).resolve().parents[1])
    bootstrap = f"import sys;sys.path.insert(0,{product_src!r});from distillai.__main__ import main;main()"
    return start_background(home, [sys._base_executable, "-I", "-B", "-c", bootstrap, "serve", "--home", str(home)],
                            python_launcher=sys.executable)


@asynccontextmanager
async def service_lifespan(runtime, control, *, material_register=None):
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(timezone=timezone.utc)
    scan_lock = threading.Lock()
    scan_requested = threading.Event()
    intervals, lifecycle_versions = {}, {}
    scheduled_jobs = set()
    jobs_idle = asyncio.Event()
    jobs_idle.set()

    def job_activity(event):
        # All jobs coalesce and allow one instance, so each ID has at most one future.
        if event.code == EVENT_JOB_SUBMITTED:
            scheduled_jobs.add(event.job_id)
            jobs_idle.clear()
        else:
            scheduled_jobs.discard(event.job_id)
            if not scheduled_jobs:
                jobs_idle.set()

    def close_episode(key):
        from .episode import register_close
        try:
            if not runtime.store.state.failed:
                register_close(runtime, key)
                runtime.wake()
        except Exception as error:
            logger.bind(component="backend", session_key=key, stage="closing",
                error_code=type(error).__name__).error("closing_registration_failed")

    def explore():
        from .expansion import tick
        try:
            if not runtime.store.state.failed:
                tick(runtime)
        except Exception as error:
            logger.bind(component="backend", stage="exploration",
                error_code=type(error).__name__).error("exploration_registration_failed")

    def scan():
        with scan_lock:
            scan_requested.clear()
            try:
                if runtime.store.state.failed:
                    runtime.close()
                    return
                runtime.finish_post_commits()
                runtime.discover_materials(register=material_register)
                from .context import reconcile_feedback
                from .lifecycle import tick, read
                reconcile_feedback(runtime)
                tick(runtime)
                explore()
                runtime.dispatch()
                config = runtime.config.read()["values"]
                for identifier, seconds in (("scan", config["runtime"]["poll_interval_seconds"]),
                                             ("expansion", config["expansion"]["interval_seconds"])):
                    if intervals.get(identifier) != seconds:
                        scheduler.reschedule_job(identifier, trigger=IntervalTrigger(seconds=min(seconds, threading.TIMEOUT_MAX), timezone=timezone.utc))
                        intervals[identifier] = seconds
                for path in sorted((runtime.store.home / "events/lifecycle").glob("*.json")):
                    record = read(runtime, path.stem)
                    if lifecycle_versions.get(path.stem) == record["sequence"]:
                        continue
                    identifier = "episode:" + path.stem
                    if scheduler.get_job(identifier) is not None:
                        scheduler.remove_job(identifier)
                    lifecycle_versions[path.stem] = record["sequence"]
                    if record["deadline"] is not None and record["code"] is None:
                        scheduler.add_job(close_episode, "date", id=identifier, args=[path.stem],
                            run_date=datetime.fromisoformat(record["deadline"].replace("Z", "+00:00")),
                            misfire_grace_time=None, max_instances=1, coalesce=True)
            except sqlite3.Error as error:
                logger.bind(component="backend", stage="scan", error_code=type(error).__name__).error("control_state_unavailable")
                runtime.store.state.failed = True
                try:
                    runtime.close()
                except Exception as stop_error:
                    logger.bind(component="backend", stage="stop", error_code=type(stop_error).__name__).error("stop_pending")
            except Exception as error:
                logger.bind(component="backend", stage="scan", error_code=type(error).__name__).error("material_scan_failed")

    def wake():
        if not control.stopping.is_set() and scheduler.running and scheduler.get_job("scan") is not None:
            scan_requested.set()
            scheduler.modify_job("scan", next_run_time=datetime.now(timezone.utc))

    def scan_finished(event):
        # max_instances may coalesce a wakeup while the previous scan is still running.
        if event.job_id == "scan" and scan_requested.is_set():
            loop.call_soon_threadsafe(wake)

    async def stop_requested():
        await anyio.to_thread.run_sync(control.stopping.wait)
        control.server.should_exit = True

    scheduler.add_job(scan, "interval", seconds=1, id="scan", next_run_time=datetime.now(timezone.utc),
                      max_instances=1, coalesce=True)
    scheduler.add_job(explore, "interval", seconds=3600, id="expansion", max_instances=1, coalesce=True)
    scheduler.add_listener(scan_finished, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    scheduler.add_listener(job_activity, EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    scheduler.start()
    runtime.on_wake = lambda: loop.call_soon_threadsafe(wake)
    instance = {"instance_id": control.instance_id, "pid": os.getpid(), "protocol": 1,
                "url": control.url, "token": control.token, "launch_id": os.environ.get("DISTILLAI_START_NONCE")}
    async def publish_instance():
        # Uvicorn starts listening after the ASGI lifespan has yielded.
        while not control.server.started:
            await anyio.sleep(.01)
        await anyio.to_thread.run_sync(lambda: atomic_json(runtime.store.home / "instance.json", instance))
        logger.bind(component="backend", stage="ready").info("backend_ready")

    async with anyio.create_task_group() as group:
        group.start_soon(stop_requested)
        group.start_soon(publish_instance)
        try:
            yield
        finally:
            runtime.on_wake = None
            control.stopping.set()
            scheduler.pause()
            with anyio.CancelScope(shield=True):
                # AsyncIOExecutor.shutdown cancels futures even with wait=True.
                await jobs_idle.wait()
                scheduler.shutdown(wait=True)
                def finish():
                    with scan_lock:
                        runtime.close()
                await anyio.to_thread.run_sync(finish)
            group.cancel_scope.cancel()


def run_service(runtime, *, material_register=None):
    home = runtime.store.home
    with diagnostic_sink(home, "backend"), _lease(home) as owned:
        if not owned:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if live_instance(home) is not None:
                    return
                time.sleep(.05)
            raise RuntimeError("Another process owns this data root but has not become healthy")
        if live_instance(home) is not None:
            return
        logger.bind(component="backend", stage="startup").info("backend_starting")
        runtime.recover_tasks()
        if not hasattr(runtime, "knowledge_index"):
            from .knowledge import KnowledgeIndex
            runtime.knowledge_index = KnowledgeIndex(runtime.store)
            try:
                runtime.knowledge_index.rebuild()
            except Exception as error:
                runtime.store.event({"event": "knowledge_index_pending", "code": type(error).__name__})
                logger.bind(component="backend", stage="index", error_code=type(error).__name__).warning("knowledge_index_pending")
        @asynccontextmanager
        async def lifespan(app):
            async with service_lifespan(runtime, app.state.control, material_register=material_register):
                yield
        server = BackendServer(runtime, lifespan=lifespan)
        try:
            server.serve_forever()
        finally:
            while True:
                try:
                    runtime.close()
                    break
                except Exception as exc:
                    logger.bind(component="backend", stage="stop", error_code=type(exc).__name__).error("stop_pending")
                    try:
                        runtime.store.event({"event": "stop_pending", "error": type(exc).__name__})
                    except (OSError, sqlite3.Error):
                        pass
                    runtime._wake.clear()
                    runtime._wake.wait(1)
            server.server_close()
            with runtime.store.locked():
                path = home / "instance.json"
                if path.is_file():
                    current = json.loads(path.read_text(encoding="utf-8"))
                    if current["instance_id"] == server.instance_id:
                        path.unlink()
            logger.bind(component="backend", stage="stop").info("backend_stopped")
