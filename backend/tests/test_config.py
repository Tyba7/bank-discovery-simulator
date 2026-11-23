import pytest

from app.config import ROLES, ConfigError, load_role_settings, load_settings
from app.llm import build_llms

LLAMA = '{"chat_template_kwargs": {"enable_thinking": false}}'


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """A known default setup, with every per-role override cleared (the real .env may set some)."""
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("LLM_API_KEY", "local-key")
    monkeypatch.setenv("LLM_MODEL", "qwen-local")
    monkeypatch.setenv("LLM_EXTRA_BODY", LLAMA)
    for role in ROLES:
        for key in ("BASE_URL", "API_KEY", "MODEL", "EXTRA_BODY"):
            monkeypatch.delenv(f"{role.upper()}_{key}", raising=False)
    return monkeypatch


def test_without_overrides_every_role_gets_the_default_and_one_shared_client():
    roles = load_role_settings()
    assert all(settings == load_settings() for settings in roles.values())
    llms = build_llms(roles)
    assert len({id(llm) for llm in llms.values()}) == 1  # identical to the single-model behaviour before roles


def test_empty_override_is_the_same_as_unset(env):
    for role in ROLES:
        for key in ("BASE_URL", "API_KEY", "MODEL", "EXTRA_BODY"):
            env.setenv(f"{role.upper()}_{key}", "  ")
    assert all(settings == load_settings() for settings in load_role_settings().values())


def test_one_role_can_use_another_model_and_its_own_reasoning_switch(env):
    env.setenv("COACH_MODEL", "big-model")
    env.setenv("COACH_EXTRA_BODY", '{"chat_template_kwargs": {"enable_thinking": true}}')
    roles = load_role_settings()
    assert roles["coach"].llm_model == "big-model"
    assert roles["coach"].llm_extra_body == {"chat_template_kwargs": {"enable_thinking": True}}
    assert roles["classifier"] == roles["client"] == roles["guard"] == load_settings()
    llms = build_llms(roles)
    assert llms["coach"] is not llms["classifier"] and llms["classifier"] is llms["guard"]


def test_provider_switches_are_not_inherited_by_a_role_on_another_server(env):
    env.setenv("GUARD_BASE_URL", "https://router.example/v1")
    env.setenv("GUARD_MODEL", "vendor/model")
    assert load_role_settings()["guard"].llm_extra_body == {}  # llama.cpp's switch would mean nothing there
    env.setenv("CLIENT_EXTRA_BODY", "{}")  # "{}" clears it even on the same server
    assert load_role_settings()["client"].llm_extra_body == {}


def test_bad_json_names_the_setting(env):
    env.setenv("CLASSIFIER_EXTRA_BODY", "{not json")
    with pytest.raises(ConfigError, match="CLASSIFIER_EXTRA_BODY"):
        load_role_settings()
