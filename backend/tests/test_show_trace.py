from scripts.show_trace import render


def call(node, turn, role, session="s1", **extra):
    return {"kind": "call", "session": session, "turn": turn, "node": node, "role": role, "status": "ok", "ms": 5,
            "tokens_in": 10, "tokens_out": 2, "finish": "stop", "attempt": 1, **extra}  # fmt: skip


def node(name, turn, session="s1", **extra):
    return {"kind": "node", "session": session, "turn": turn, "node": name, "ms": 5, **extra}


QUESTION = {"role": "user", "content": "<conversation>\n</conversation>\n<message>\nIs income &lt; 5,000?\n</message>"}
ROWS = [
    call("opening", 0, "client", output="Good morning."),
    node("opening", 0),
    node("check_input", 1, flag=None),
    call("classify", 1, "classifier", messages=[QUESTION], output="not json"),
    call("classify", 1, "classifier", attempt=2, code="LLM-003", messages=[QUESTION], output="{}"),
    node("classify", 1, unlocks=["existing_lease"], reason="asks about debt"),
    node("update_unlocked", 1, pending=["existing_lease"]),
    call("client_reply", 1, "client", output="We owe a little."),
    node("client_reply", 1, attempt=1),
    call("guard", 1, "guard"),
    node("guard", 1, leaked=["sharia_compliance"], events=[{"code": "CLI-001", "detail": "sharia_compliance"}]),
    node("finish", 1, added=[], discarded=["existing_lease"]),
    node("opening", 0, session="s2"),
]


def test_a_turn_reads_in_order_with_each_call_under_its_node():
    lines = render(ROWS, session="s1", turn=1).splitlines()
    assert lines[0] == 'session s1  turn 1  "Is income < 5,000?"'  # read back from the request, unescaped
    nodes = [line.split()[0] for line in lines[1:] if line.startswith("  ") and not line.startswith("     ")]
    assert nodes == ["check_input", "classify", "update_unlocked", "client_reply", "guard", "finish"]
    text = "\n".join(lines)
    assert text.index("call classifier") < text.index("update_unlocked")  # attached to classify, not the next node
    assert "attempt 2 (repair)  LLM-003" in text and '"We owe a little."' in text
    assert "REJECTED" in text and "CLI-001: sharia_compliance" in text


def test_filters_and_full_mode():
    assert "s2" not in render(ROWS, session="s1") and "turn 0  opening" in render(ROWS, session="s2")
    full = render(ROWS, session="s1", turn=1, full=True)
    assert "[output]\n         not json" in full  # the invalid JSON before the repair is visible
    assert "LLM_CALL_LOG_CONTENT=1" in full  # the guard call was logged without content, and says so
    assert render(ROWS, turn=7) == "no matching rows"


def test_eval_calls_outside_an_interview_are_grouped_by_arm_and_case():
    question = {"role": "user", "content": "<conversation>\n</conversation>\n<message>\nAny loans?\n</message>"}
    rows = [
        {
            **call(None, None, "classifier", session=None, messages=[question], output="{}"),
            "arm": "decide",
            "case": "p-k-04",
        },
        {**call(None, None, "classifier", session=None), "arm": "default", "case": "p-k-04"},
    ]
    text = render(rows, session="decide:p-k-04")
    assert text.startswith('session decide:p-k-04  turn None  "Any loans?"') and "default:" not in text


def test_student_text_is_marked_missing_without_content_logging():
    rows = [node("check_input", 1), call("classify", 1, "classifier"), node("classify", 1)]
    assert render(rows).startswith("session s1  turn 1  (student text not logged)")
