"""Loguru sink ownership for independent product processes."""
from contextlib import contextmanager
import os
from pathlib import Path

from loguru import logger


FIELDS = {"component", "event", "session_key", "task_id", "stage", "error_code", "winerror", "invocation"}


@contextmanager
def diagnostic_sink(home, component):
    sink = None
    try:
        # Putting PID inside the time field keeps Loguru retention working across processes.
        path = Path(home) / "logs" / f"{component}-{{time:YYYYMMDD_HHmmss_SSSSSS-{os.getpid()}}}.jsonl"
        sink = logger.add(path,
            mode="x", format="{time:YYYY-MM-DDTHH:mm:ss.SSSSSS!UTC}Z {message}", serialize=True, enqueue=True, catch=True,
            # A Hook writes one diagnostic; Loguru runs retention/compression on its close.
            rotation=None if component == "capture" else "5 MB", retention="7 days", compression="gz",
            diagnose=False, backtrace=False, encoding="utf-8",
            filter=lambda record: record["extra"].get("component") == component
                and record["exception"] is None and set(record["extra"]) <= FIELDS)
    except Exception:
        pass
    try:
        yield
    finally:
        if sink is not None:
            try:
                logger.complete()
            except Exception:
                pass
            try:
                logger.remove(sink)
            except Exception:
                pass
