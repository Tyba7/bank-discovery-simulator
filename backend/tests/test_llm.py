import operator
from typing import Annotated, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.config import load_settings
from app.llm import JSON_MODES, LLM

pytestmark = pytest.mark.llm


class Topic(BaseModel):
    about_savings: bool
    about_loans: bool


def ask(question: str) -> list[dict]:
    return [{"role": "user", "content": f"Classify this question from a bank adviser to a client: {question!r}"}]


@pytest.fixture(scope="module")
def settings():
    return load_settings()


def test_chat_returns_text(settings):
    assert LLM(settings).chat([{"role": "user", "content": "Say hello."}]).strip()


@pytest.mark.parametrize("mode", JSON_MODES)
def test_chat_json_works_in_each_mode(settings, mode):
    topic = LLM(settings, json_modes=(mode,)).chat_json(ask("How much do you save each month?"), Topic)
    assert topic.about_savings and not topic.about_loans


class State(TypedDict):
    questions: Annotated[list[str], operator.add]
    topics: Annotated[list[dict], operator.add]


def test_langgraph_node_calls_llm_and_checkpointer_keeps_state(settings):
    llm = LLM(settings)

    def classify(state: State) -> dict:
        return {"topics": [llm.chat_json(ask(state["questions"][-1]), Topic).model_dump()]}

    builder = StateGraph(State)
    builder.add_node("classify", classify)
    builder.add_edge(START, "classify")
    builder.add_edge("classify", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    graph.invoke({"questions": ["How much do you save each month?"]}, config)
    state = graph.invoke({"questions": ["Do you have any loans right now?"]}, config)

    assert len(state["topics"]) == 2  # the checkpointer kept turn 1
    assert state["topics"][0]["about_savings"] and state["topics"][1]["about_loans"]
