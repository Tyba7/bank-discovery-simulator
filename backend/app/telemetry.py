"""Per-call records for every model call, linked to the graph node, turn, session and role that made it.

Everything stays local: the in-state trace, a log line, and an optional JSONL file (LLM_CALL_LOG).
"""

import json
import logging
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

log = logging.getLogger(__name__)

_labels: ContextVar[dict] = ContextVar("llm_labels", default={})  # noqa: B039 -- never mutated, only replaced
_sinks: ContextVar[tuple[list, ...]] = ContextVar("llm_sinks", default=())
_file_lock = threading.Lock()


@contextmanager
def llm_scope(**labels):
    """Adds labels to every model call made inside, and yields the list those calls are collected into.

    Scopes nest: an outer scope (an eval suite) also collects the calls of inner scopes (graph nodes).
    """
    calls: list[dict] = []
    label_token = _labels.set({**_labels.get(), **labels})
    sink_token = _sinks.set((*_sinks.get(), calls))
    try:
        yield calls
    finally:
        _sinks.reset(sink_token)
        _labels.reset(label_token)


def record(call: dict) -> dict:
    entry = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), **_labels.get(), **call}
    for sink in _sinks.get():
        sink.append(entry)
    log.info("llm_call %s", json.dumps(entry))
    if path := os.environ.get("LLM_CALL_LOG", "").strip():
        with _file_lock, open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    return entry
