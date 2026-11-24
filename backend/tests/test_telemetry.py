import json
from dataclasses import replace

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
GUARD = {"reason": "fine", "revealed_need_ids": [], "broke_character": False, "invented_fact": False}


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


LEASE_FACT = "QAR 180,000"  # in Khalid's locked existing_lease fact


def run_turn(log_file, monkeypatch, content: str | None):
    monkeypatch.setenv("LLM_CALL_LOG", str(log_file))
    if content is not None:
        monkeypatch.setenv("LLM_CALL_LOG_CONTENT", content)
    llm = LLM(SETTINGS)
    graph = build_interview_graph(load_content(), {"classifier": llm, "client": llm, "guard": llm})
    config = {"configurable": {"thread_id": "s1"}}
    graph.invoke({"client_id": "khalid_al_mansouri"}, config)
    graph.invoke({"student_message": "Is the business repaying any borrowing?"}, config)
    return [json.loads(line) for line in log_file.read_text().splitlines()]


def test_call_log_tells_the_turn_in_order_and_keeps_prompts_out_by_default(
    fake_completion, tmp_path, monkeypatch, caplog
):
    caplog.set_level("INFO")
    rows = run_turn(tmp_path / "logs" / "calls.jsonl", monkeypatch, content=None)  # logs/ does not exist yet
    assert [(r["kind"], r["node"]) for r in rows if r.get("turn") == 1] == [
        ("node", "check_input"),
        ("call", "classify"),  # a call is written when it ends, just before its node's row
        ("node", "classify"),
        ("node", "update_unlocked"),
        ("call", "client_reply"),
        ("node", "client_reply"),
        ("call", "guard"),
        ("node", "guard"),
        ("node", "finish"),
    ]
    classify = next(r for r in rows if r["kind"] == "node" and r["node"] == "classify")
    assert classify["unlocks"] == ["existing_lease"] and classify["session"] == "s1" and classify["calls"] == 1
    assert not any("messages" in r or "output" in r for r in rows)
    assert LEASE_FACT not in caplog.text


def test_call_log_content_holds_the_exact_request_and_raw_output(fake_completion, tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO")
    rows = run_turn(tmp_path / "calls.jsonl", monkeypatch, content="1")
    calls = {r["node"]: r for r in rows if r["kind"] == "call" and r.get("turn") == 1}
    assert calls["classify"]["messages"][-1]["content"].endswith("</message>")
    assert calls["classify"]["response_format"]["json_schema"]["name"] == "Classification"
    assert json.loads(calls["classify"]["output"]) == CLASSIFICATION
    assert calls["client_reply"]["output"] == "We still pay a lease on the café equipment."
    assert LEASE_FACT in json.dumps(calls["guard"]["messages"])  # the guard sees locked facts: in the file only
    assert LEASE_FACT not in caplog.text and '"messages"' not in caplog.text  # never in the server log


def test_separate_role_clients_are_each_counted_once(fake_completion):
    classifier, coach_llm = LLM(SETTINGS), LLM(replace(SETTINGS, llm_model="big-model"))
    with llm_scope() as calls:
        with llm_scope(role="classifier"):
            classifier.chat([{"role": "user", "content": "hi"}])
        with llm_scope(role="coach"):
            coach_llm.chat([{"role": "user", "content": "hi"}])
    usage = llm_usage(calls)
    assert {k: v["calls"] for k, v in usage.items()} == {"classifier / fake-model": 1, "coach / big-model": 1}
    assert sum(v["tokens_in"] for v in usage.values()) == 200  # 100 per call, nothing double-counted
