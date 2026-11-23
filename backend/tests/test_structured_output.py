import json
import threading

import litellm

from app.config import Settings
from app.content import load_content
from app.interview import classification_model, guard_model
from app.llm import LLM, _strict

SETTINGS = Settings("http://fake", "fake-key", "fake-model", 1.0, {})


def objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from objects(value)


def test_every_object_in_the_schema_is_closed():
    content = load_content()
    schema = _strict(classification_model(content.clients["maria_santos"], list(content.products)).model_json_schema())
    assert all(o["additionalProperties"] is False for o in objects(schema))


def test_parallel_failures_drop_an_unsupported_mode_only_once(monkeypatch):
    barrier = threading.Barrier(8)

    def complete(**kwargs):
        if kwargs.get("response_format", {}).get("type") == "json_schema":
            barrier.wait(timeout=5)  # every thread fails on json_schema at the same moment
            raise litellm.BadRequestError("json_schema not supported", "fake-model", "openai", response=None)
        reply = {"reason": "ok", "leaked_need_ids": [], "broke_character": False, "invented_fact": False}
        return litellm.ModelResponse(choices=[{"message": {"role": "assistant", "content": json.dumps(reply)}}])

    monkeypatch.setattr(litellm, "completion", complete)
    llm = LLM(SETTINGS)
    errors = []

    def call():
        try:
            llm.chat_json([{"role": "user", "content": "check"}], guard_model(["x"]))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and llm.json_modes == ["json_object", "prompt"]
