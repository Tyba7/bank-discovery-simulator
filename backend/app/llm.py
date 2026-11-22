import json
import logging
import re

import litellm
from pydantic import BaseModel, ValidationError

from app.config import Settings

litellm.suppress_debug_info = True
log = logging.getLogger(__name__)

# Strongest first. Not every OpenAI-compatible server supports json_schema.
JSON_MODES = ("json_schema", "json_object", "prompt")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class LLMOutputError(RuntimeError):
    pass


def _with_schema_instruction(messages: list[dict], schema_json: dict) -> list[dict]:
    # Merge into the first system message: some chat templates reject a second system message.
    note = "Reply with only a JSON object that matches this JSON schema:\n" + json.dumps(schema_json)
    if messages and messages[0]["role"] == "system":
        return [{"role": "system", "content": messages[0]["content"] + "\n\n" + note}, *messages[1:]]
    return [{"role": "system", "content": note}, *messages]


class LLM:
    def __init__(self, settings: Settings, json_modes: tuple[str, ...] = JSON_MODES):
        self.s = settings
        self.json_modes = list(json_modes)  # a mode the server rejects is dropped for the rest of the run

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

    def _complete(self, messages: list[dict], temperature: float, max_tokens: int, **extra) -> str:
        choice = litellm.completion(messages=messages, **extra, **self._params(temperature, max_tokens)).choices[0]
        if choice.finish_reason == "length":
            log.warning("LLM-002 reply truncated at max_tokens=%s", max_tokens)
        return choice.message.content or ""

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 300) -> str:
        return self._complete(messages, temperature, max_tokens)

    def chat_json(
        self, messages: list[dict], schema: type[BaseModel], temperature: float = 0.0, max_tokens: int = 300
    ) -> BaseModel:
        while True:
            mode = self.json_modes[0]
            try:
                return self._chat_json(messages, schema, mode, temperature, max_tokens)
            except litellm.BadRequestError as e:
                if len(self.json_modes) == 1:
                    raise
                log.warning("LLM-001 %s not supported by %s, falling back: %s", mode, self.s.llm_model, e)
                self.json_modes.pop(0)

    def _chat_json(self, messages, schema, mode, temperature, max_tokens) -> BaseModel:
        schema_json = schema.model_json_schema()
        if mode == "json_schema":
            extra = {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "schema": schema_json},
                }
            }
        else:  # the schema has to travel in the prompt
            messages = _with_schema_instruction(messages, schema_json)
            extra = {"response_format": {"type": "json_object"}} if mode == "json_object" else {}

        text = self._complete(messages, temperature, max_tokens, **extra)
        try:
            return schema.model_validate_json(_FENCE.sub("", text.strip()))
        except ValidationError as e:
            log.warning("LLM-003 invalid structured output (%s mode), repairing once", mode)
            repair = [
                *messages,
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That JSON is invalid: {e}. Reply with only the corrected JSON object."},
            ]
            text = self._complete(repair, temperature, max_tokens, **extra)
            try:
                return schema.model_validate_json(_FENCE.sub("", text.strip()))
            except ValidationError as e2:
                raise LLMOutputError(f"{schema.__name__}: model output invalid after repair") from e2
