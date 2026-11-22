import json
import os
from dataclasses import dataclass

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


def load_settings() -> Settings:
    extra = os.environ.get("LLM_EXTRA_BODY", "").strip()
    try:
        extra_body = json.loads(extra) if extra else {}
    except json.JSONDecodeError as e:
        raise ConfigError(f"LLM_EXTRA_BODY must be valid JSON: {e}") from None
    return Settings(
        llm_base_url=_required("LLM_BASE_URL"),
        llm_api_key=_required("LLM_API_KEY"),
        llm_model=_required("LLM_MODEL"),
        llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
        llm_extra_body=extra_body,
    )
