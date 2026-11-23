import json

import litellm
import pytest

from app.config import Settings
from app.content import load_content
from app.interview import build_interview_graph, guard_model
from app.llm import LLM
from app.telemetry import llm_scope
from evals.run import llm_usage

SETTINGS = Settings("http://fake", "fake-key", "fake-model", 1.0, {})
CLASSIFICATION = {
    "reason": "asks about borrowing",
    "unlocks": ["existing_lease"],
    "products_proposed": [],
    "on_topic": True,
    "injection_attempt": False,
    "question_type": "open",
}
GUARD = {"reason": "fine", "leaked_need_ids": [], "broke_character": False, "invented_fact": False}


def response(text, finish="stop"):
    return litellm.ModelResponse(
        choices=[{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
    )


@pytest.fixture
def fake_completion(monkeypatch):
    """Answers like the real server would: JSON for each schema, plain text for the client persona."""

    def complete(**kwargs):
        schema = kwargs.get("response_format", {}).get("json_schema", {}).get("name")
        if schema == "Classification":
            return response(json.dumps(CLASSIFICATION))
        if schema == "GuardVerdict":
            return response(json.dumps(GUARD))
        return response("We still pay a lease on the café equipment.")

    monkeypatch.setattr(litellm, "completion", complete)


def test_call_is_recorded_with_labels_tokens_and_log_file(fake_completion, tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CALL_LOG", str(tmp_path / "calls.jsonl"))
    with llm_scope(node="client_reply", role="client") as calls:
        LLM(SETTINGS).chat([{"role": "user", "content": "hi"}])
    [call] = calls
    assert call["node"] == "client_reply" and call["role"] == "client" and call["model"] == "fake-model"
    assert (call["status"], call["tokens_in"], call["tokens_out"], call["finish"]) == ("ok", 100, 10, "stop")
    assert json.loads((tmp_path / "calls.jsonl").read_text())["node"] == "client_reply"


def test_failed_call_is_recorded_then_raised(monkeypatch):
    def boom(**kwargs):
        raise litellm.Timeout("timed out", model="fake-model", llm_provider="openai")

    monkeypatch.setattr(litellm, "completion", boom)
    with llm_scope(role="guard") as calls, pytest.raises(litellm.Timeout):
        LLM(SETTINGS).chat([{"role": "user", "content": "hi"}])
    assert [(c["status"], c["error"]) for c in calls] == [("error", "Timeout")]


def test_repair_retry_is_a_second_call(monkeypatch):
    replies = iter([response("not json"), response(json.dumps(GUARD))])
    monkeypatch.setattr(litellm, "completion", lambda **kwargs: next(replies))

    with llm_scope() as calls:
        LLM(SETTINGS).chat_json([{"role": "user", "content": "check"}], guard_model(["existing_lease"]))
    assert [(c["attempt"], c.get("code")) for c in calls] == [(1, None), (2, "LLM-003")]
    assert llm_usage(calls)["? / fake-model"]["repairs"] == 1


def test_every_model_call_is_traced_under_its_node(fake_completion):
    llm = LLM(SETTINGS)
    graph = build_interview_graph(load_content(), {"classifier": llm, "client": llm, "guard": llm})
    config = {"configurable": {"thread_id": "s1"}}
    with llm_scope(suite="test") as all_calls:
        graph.invoke({"client_id": "khalid_al_mansouri"}, config)
        state = graph.invoke({"student_message": "Is the business repaying any borrowing?"}, config)
    roles = {t["node"]: [c["role"] for c in t.get("llm", [])] for t in state["trace"]}
    assert roles["opening"] == ["client"] and roles["classify"] == ["classifier"]
    assert roles["client_reply"] == ["client"] and roles["guard"] == ["guard"]
    assert roles["update_unlocked"] == [] and roles["finish"] == []
    assert len(all_calls) == 4 and {c["session"] for c in all_calls} == {"s1"}  # outer scope sees every call
