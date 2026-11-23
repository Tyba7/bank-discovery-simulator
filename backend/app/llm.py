import json
import logging
import re
import threading
import time

import litellm
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.telemetry import record

litellm.suppress_debug_info = True
log = logging.getLogger(__name__)

# Strongest first. Not every OpenAI-compatible server supports json_schema.
JSON_MODES = ("json_schema", "json_object", "prompt")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class LLMOutputError(RuntimeError):
    pass


def _cost(response) -> float | None:
    # Router-reported cost first (OpenRouter-style usage.cost), then LiteLLM's price table; None when unknown.
    usage_cost = getattr(getattr(response, "usage", None), "cost", None)
    if usage_cost is not None:
        return float(usage_cost)
    try:
        return litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 -- local and unlisted models have no price
        return None


def _extract_json(text: str) -> str:
    # Drop code fences, then decode the first JSON object and ignore any text around it.
    text = _FENCE.sub("", text.strip())
    start = text.find("{")
    if start == -1:
        return text
    try:
        return json.dumps(json.JSONDecoder().raw_decode(text, start)[0])
    except json.JSONDecodeError:
        return text


def _strict(node):
    """Closed objects everywhere: Anthropic requires it for json_schema output, and OpenAI strict mode does too."""
    if isinstance(node, dict):
        if node.get("type") == "object":
            node.setdefault("additionalProperties", False)
        for value in node.values():
            _strict(value)
    elif isinstance(node, list):
        for value in node:
            _strict(value)
    return node


def _with_schema_instruction(messages: list[dict], schema_json: dict) -> list[dict]:
    # Merge into the first system message: some chat templates reject a second system message.
    note = "Reply with only a JSON object that matches this JSON schema:\n" + json.dumps(schema_json)
    if messages and messages[0]["role"] == "system":
        return [{"role": "system", "content": messages[0]["content"] + "\n\n" + note}, *messages[1:]]
    return [{"role": "system", "content": note}, *messages]


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


class LLM:
    def __init__(self, settings: Settings, json_modes: tuple[str, ...] = JSON_MODES):
        self.s = settings
        self.json_modes = list(json_modes)  # a mode the server rejects is dropped for the rest of the run
        self._modes_lock = threading.Lock()

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

    def _complete(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        mode: str | None = None,
        attempt: int = 1,
        **extra,
    ) -> str:
        call = {"model": self.s.llm_model, "json_mode": mode, "attempt": attempt, "max_tokens": max_tokens}
        start = time.perf_counter()
        try:
            response = litellm.completion(messages=messages, **extra, **self._params(temperature, max_tokens))
        except Exception as e:
            record({**call, "status": "error", "error": type(e).__name__, "ms": _ms(start)})
            raise
        choice, usage = response.choices[0], getattr(response, "usage", None)
        truncated = choice.finish_reason == "length"
        record(
            {
                **call,
                "status": "ok",
                "ms": _ms(start),
                "tokens_in": getattr(usage, "prompt_tokens", None),
                "tokens_out": getattr(usage, "completion_tokens", None),
                "cost": _cost(response),
                "finish": choice.finish_reason,
                **({"code": "LLM-002"} if truncated else {"code": "LLM-003"} if attempt > 1 else {}),
            }
        )
        if truncated:
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
                with self._modes_lock:  # parallel calls can fail on the same mode; drop it only once
                    if self.json_modes[0] != mode:
                        continue
                    if len(self.json_modes) == 1:
                        raise
                    log.warning("LLM-001 %s not supported by %s, falling back: %s", mode, self.s.llm_model, e)
                    self.json_modes.pop(0)

    def _chat_json(self, messages, schema, mode, temperature, max_tokens) -> BaseModel:
        schema_json = _strict(schema.model_json_schema())
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

        text = self._complete(messages, temperature, max_tokens, mode, **extra)
        try:
            return schema.model_validate_json(_extract_json(text))
        except ValidationError as e:
            log.warning("LLM-003 invalid structured output (%s mode), repairing once", mode)
            repair = [
                *messages,
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That JSON is invalid: {e}. Reply with only the corrected JSON object."},
            ]
            text = self._complete(repair, temperature, max_tokens, mode, attempt=2, **extra)
            try:
                return schema.model_validate_json(_extract_json(text))
            except ValidationError as e2:
                raise LLMOutputError(f"{schema.__name__}: model output invalid after repair") from e2
