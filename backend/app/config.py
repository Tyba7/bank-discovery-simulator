import json
import os
from dataclasses import dataclass, replace

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required setting {name}. Copy .env.example to .env and fill it in.")
    return value


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float
    llm_extra_body: dict

    def __repr__(self) -> str:  # never print the key
        return f"Settings(llm_base_url={self.llm_base_url!r}, llm_model={self.llm_model!r})"


ROLES = ("classifier", "client", "guard", "coach")


def _json(name: str, raw: str) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise ConfigError(f"{name} must be valid JSON: {e}") from None


def load_settings() -> Settings:
    """The default model settings (LLM_*), used by every role that does not override them."""
    extra_body = _json("LLM_EXTRA_BODY", os.environ.get("LLM_EXTRA_BODY", "").strip())
    return Settings(
        llm_base_url=_required("LLM_BASE_URL"),
        llm_api_key=_required("LLM_API_KEY"),
        llm_model=_required("LLM_MODEL"),
        llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
        llm_extra_body=extra_body,
    )


def load_role_settings() -> dict[str, Settings]:
    """Settings per role. CLASSIFIER_*, CLIENT_*, GUARD_* and COACH_* (BASE_URL, API_KEY, MODEL, EXTRA_BODY) override
    LLM_*; unset or empty values fall back to it. EXTRA_BODY carries provider-specific switches such as turning
    reasoning off, so a role that uses a different BASE_URL does not inherit LLM_EXTRA_BODY. "{}" clears it."""
    default = load_settings()
    roles = {}
    for role in ROLES:
        prefix = role.upper()

        def env(key: str, prefix: str = prefix) -> str:
            return os.environ.get(f"{prefix}_{key}", "").strip()

        base_url = env("BASE_URL") or default.llm_base_url
        if env("EXTRA_BODY"):
            extra_body = _json(f"{prefix}_EXTRA_BODY", env("EXTRA_BODY"))
        else:
            extra_body = default.llm_extra_body if base_url == default.llm_base_url else {}
        roles[role] = replace(
            default,
            llm_base_url=base_url,
            llm_api_key=env("API_KEY") or default.llm_api_key,
            llm_model=env("MODEL") or default.llm_model,
            llm_extra_body=extra_body,
        )
    return roles
