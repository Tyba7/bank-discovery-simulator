import json
import threading

import litellm
import pytest

from app.config import Settings
from app.content import load_content
from app.interview import classification_model, classify_message, decide_unlocks, guard_model, needs_unlocked_by
from app.llm import LLM, LLMOutputError, _strict
from app.prompts import Prompt

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
    for decide in (False, True):
        model = classification_model(content.clients["maria_santos"], list(content.products), decide)
        assert all(o["additionalProperties"] is False for o in objects(_strict(model.model_json_schema())))


def test_decide_schema_has_one_required_field_per_need_and_code_unlocks_only_direct():
    content = load_content()
    client = content.clients["khalid_al_mansouri"]
    schema = _strict(classification_model(client, list(content.products), decide=True).model_json_schema())
    asks = schema["$defs"]["AsksAbout"]
    need_ids = sorted(n.id for n in client.hidden_needs)
    assert sorted(asks["properties"]) == need_ids and sorted(asks["required"]) == need_ids
    assert "unlocks" not in schema["properties"]  # the model no longer names the unlocks
    assert decide_unlocks(
        {"existing_lease": "nearby", "seasonal_cash_flow": "direct", "sharia_compliance": "none"}
    ) == ["seasonal_cash_flow"]


def test_decide_classifier_returns_the_usual_unlocks_list(monkeypatch):
    content = load_content()
    client = content.clients["khalid_al_mansouri"]
    reply = {
        "reason": "asks about borrowing; rent is a running cost",
        "asks_about": {"existing_lease": "direct", "seasonal_cash_flow": "nearby", "sharia_compliance": "none"},
        "products_proposed": [],
        "on_topic": True,
        "injection_attempt": False,
        "question_type": "closed",
    }
    monkeypatch.setattr(
        litellm,
        "completion",
        lambda **kw: litellm.ModelResponse(choices=[{"message": {"role": "assistant", "content": json.dumps(reply)}}]),
    )
    result = classify_message(
        content, LLM(SETTINGS), Prompt("classifier", "decide"), client, [], "Any loans?", decide=True
    )
    assert result["unlocks"] == ["existing_lease"] and result["asks_about"]["seasonal_cash_flow"] == "nearby"
    assert needs_unlocked_by(content, client, {**result, "injection_attempt": True}) == set()  # still blocked


def test_parallel_failures_drop_an_unsupported_mode_only_once(monkeypatch):
    barrier = threading.Barrier(8)

    def complete(**kwargs):
        if kwargs.get("response_format", {}).get("type") == "json_schema":
            barrier.wait(timeout=5)  # every thread fails on json_schema at the same moment
            raise litellm.BadRequestError("json_schema not supported", "fake-model", "openai", response=None)
        reply = {"reason": "ok", "revealed_need_ids": [], "broke_character": False, "invented_fact": False}
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


def reply(text, finish):
    return litellm.ModelResponse(choices=[{"message": {"role": "assistant", "content": text}, "finish_reason": finish}])


def test_cut_off_json_is_asked_again_with_more_room_not_repaired(monkeypatch):
    good = json.dumps({"reason": "ok", "revealed_need_ids": [], "broke_character": False, "invented_fact": False})
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return reply('{"reason": "Wait, let me look', "length") if len(calls) == 1 else reply(good, "stop")

    monkeypatch.setattr(litellm, "completion", complete)
    verdict = LLM(SETTINGS).chat_json([{"role": "user", "content": "check"}], guard_model(["x"]), max_tokens=100)
    assert verdict.reason == "ok"
    assert [c["max_tokens"] for c in calls] == [100, 200]
    assert all("invalid" not in str(c["messages"]) for c in calls)  # the half reply was never shown back as a repair


def test_json_cut_off_twice_fails_after_two_calls(monkeypatch):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return reply('{"reason": "still going', "length")

    monkeypatch.setattr(litellm, "completion", complete)
    with pytest.raises(LLMOutputError):
        LLM(SETTINGS).chat_json([{"role": "user", "content": "check"}], guard_model(["x"]), max_tokens=100)
    assert len(calls) == 2
