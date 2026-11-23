"""API without a model: a scripted LiteLLM stands in for the provider."""

import json

import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.content import load_content
from app.llm import LLM
from app.main import MODEL_DOWN, create_app

SETTINGS = Settings("http://fake", "fake-key", "fake-model", 1.0, {})


def reply(payload) -> litellm.ModelResponse:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return litellm.ModelResponse(choices=[{"message": {"role": "assistant", "content": content}}])


class FakeModel:
    """Classifier unlocks the lease for questions about leases; the client echoes; the coach writes a minimal draft."""

    def __init__(self):
        self.down = False  # True: every plain chat call (the client persona) fails

    def __call__(self, **kwargs):
        schema = kwargs.get("response_format", {}).get("json_schema", {}).get("name")
        last = kwargs["messages"][-1]["content"]
        if schema == "Classification":
            return reply(
                {
                    "reason": "test",
                    "unlocks": ["existing_lease"] if "lease" in last.lower() else [],
                    "products_proposed": [],
                    "on_topic": True,
                    "injection_attempt": False,
                    "question_type": "open",
                }
            )
        if schema == "GuardVerdict":
            return reply({"reason": "ok", "leaked_need_ids": [], "broke_character": False, "invented_fact": False})
        if schema == "SummaryLabels":
            return reply({"reason": "test", "need_ids": []})
        if schema == "CoachFeedback":
            return reply(
                {
                    "went_well": [],
                    "missed_needs": [],
                    "product_notes": [],
                    "question_feedback": "ok",
                    "next_steps": ["x"],
                }
            )
        if self.down:
            raise litellm.APIConnectionError("connection refused", llm_provider="openai", model="fake-model")
        return reply("Thank you, that is a good question.")


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(litellm, "completion", fake)
    return fake


@pytest.fixture
def api(model):
    with TestClient(create_app(llm=LLM(SETTINGS))) as client:
        yield client


def start(api, client_id="khalid_al_mansouri") -> str:
    r = api.post("/api/sessions", json={"client_id": client_id})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def test_public_endpoints_never_expose_hidden_information(api):
    content = load_content()
    secrets = [x for c in content.clients.values() for n in c.hidden_needs for x in (n.id, n.fact, n.topic)]
    secrets += [t for p in content.products.values() for t in p.tags] + ["hidden_needs", "unlocked"]
    sid = start(api)
    api.post(f"/api/sessions/{sid}/messages", json={"message": "Do you have any leases?"})
    for path in ["/api/clients", "/api/products", f"/api/sessions/{sid}"]:
        text = api.get(path).text
        assert not [s for s in secrets if s in text], path


def test_interview_feedback_and_export(api):
    sid = start(api)
    r = api.post(f"/api/sessions/{sid}/messages", json={"message": "How is business?"})
    assert r.status_code == 200 and r.json()["turns_left"] == 39
    r = api.post(
        f"/api/sessions/{sid}/feedback",
        json={"summary": "Wants a third café.", "recommendations": [{"product_id": "business_overdraft"}]},
    )
    assert r.status_code == 200
    fb = r.json()
    assert {m["need_id"] for m in fb["missed_needs"]} == {"existing_lease", "seasonal_cash_flow", "sharia_compliance"}
    assert next(p for p in fb["products"] if p["id"] == "business_overdraft")["outcome"] == "unsuitable"
    assert "checks" not in fb and "events" not in fb
    assert api.post(f"/api/sessions/{sid}/messages", json={"message": "One more?"}).status_code == 409
    assert api.get(f"/api/sessions/{sid}").json()["finished"] is True
    export = api.get(f"/api/sessions/{sid}/export")
    assert "attachment" in export.headers["content-disposition"]
    assert len(export.json()["conversation"]) == 3 and export.json()["feedback"]["client_id"] == "khalid_al_mansouri"


def test_bad_requests_get_clear_errors(api):
    assert api.post("/api/sessions", json={"client_id": "nobody"}).status_code == 404
    assert api.post("/api/sessions/nope/messages", json={"message": "hi"}).status_code == 404
    sid = start(api)
    assert api.post(f"/api/sessions/{sid}/messages", json={"message": ""}).status_code == 422
    r = api.post(f"/api/sessions/{sid}/feedback", json={"recommendations": [{"product_id": "gold_card"}]})
    assert r.status_code == 422 and "gold_card" in r.json()["detail"]


def test_model_down_gives_a_clear_message_and_the_failed_turn_leaves_no_trace(api, model):
    sid = start(api)
    model.down = True
    r = api.post(f"/api/sessions/{sid}/messages", json={"message": "Do you have any leases?"})
    assert r.status_code == 503 and r.json()["detail"] == MODEL_DOWN
    model.down = False
    assert api.post(f"/api/sessions/{sid}/messages", json={"message": "How is business?"}).status_code == 200
    session = api.get(f"/api/sessions/{sid}").json()
    assert [m["content"] for m in session["messages"] if m["role"] == "student"] == ["How is business?"]
    fb = api.post(f"/api/sessions/{sid}/feedback", json={}).json()
    assert "existing_lease" in {m["need_id"] for m in fb["missed_needs"]}  # the failed lease question unlocked nothing


def test_model_down_at_start(api, model):
    model.down = True
    r = api.post("/api/sessions", json={"client_id": "maria_santos"})
    assert r.status_code == 503 and r.json()["detail"] == MODEL_DOWN


def test_security_headers(api):
    headers = api.get("/api/health").headers
    assert headers["x-content-type-options"] == "nosniff" and headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in headers["content-security-policy"]
