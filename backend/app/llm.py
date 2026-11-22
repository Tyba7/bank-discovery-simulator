"""The single model-access layer: every AI call in the app goes through here (LiteLLM)."""

import litellm
from pydantic import BaseModel

from app.config import Settings

litellm.suppress_debug_info = True


class LLM:
    def __init__(self, settings: Settings):
        self.s = settings

    def _params(self, temperature: float, max_tokens: int) -> dict:
        return {
            "model": f"openai/{self.s.llm_model}",  # "openai/" = any OpenAI-compatible server
            "api_base": self.s.llm_base_url,
            "api_key": self.s.llm_api_key,
            "timeout": self.s.llm_timeout_seconds,
            "num_retries": 2,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **({"extra_body": self.s.llm_extra_body} if self.s.llm_extra_body else {}),
        }

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 300) -> str:
        response = litellm.completion(messages=messages, **self._params(temperature, max_tokens))
        return response.choices[0].message.content or ""

    def chat_json(
        self, messages: list[dict], schema: type[BaseModel], temperature: float = 0.0, max_tokens: int = 300
    ) -> BaseModel:
        response = litellm.completion(
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            },
            **self._params(temperature, max_tokens),
        )
        return schema.model_validate_json(response.choices[0].message.content)
