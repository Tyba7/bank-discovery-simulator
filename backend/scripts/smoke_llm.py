import time

from pydantic import BaseModel

from app.config import load_settings
from app.llm import LLM


class Check(BaseModel):
    ok: bool
    model_says: str


llm = LLM(load_settings())
t = time.perf_counter()
print(
    "plain:", llm.chat([{"role": "user", "content": "Say hello in five words."}]), f"({time.perf_counter() - t:.1f}s)"
)
t = time.perf_counter()
result = llm.chat_json([{"role": "user", "content": "Reply with ok=true and one short sentence."}], Check)
print("json: ", result, f"({time.perf_counter() - t:.1f}s)")
