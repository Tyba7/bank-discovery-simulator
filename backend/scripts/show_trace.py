"""Print a call log (LLM_CALL_LOG) as a readable tree: session, then turn, then each node with its model calls.

    uv run python -m scripts.show_trace logs/calls.jsonl                 # every session, every turn
    uv run python -m scripts.show_trace logs/calls.jsonl --session ID    # one session (a prefix is enough)
    uv run python -m scripts.show_trace logs/calls.jsonl --turn 3 --full # one turn, with every prompt and raw output
    uv run python -m scripts.show_trace logs/eval-….jsonl --session default:p-k-04 --full  # one eval case (arm:case)

The student's words and the client's replies appear only when the log was written with LLM_CALL_LOG_CONTENT=1.
Eval runs write their own log (evals/run.py prints its path); calls made outside an interview, such as a single
classifier case, are grouped by A/B arm and case id instead of by session.
"""

import argparse
import html
import json
import re
import sys
from collections import defaultdict

# The decision fields worth showing per node; everything else stays in the file.
NODE_FIELDS = {
    "check_input": ("flag",),
    "classify": ("unlocks", "products_proposed", "injection_attempt", "on_topic", "question_type", "reason"),
    "update_unlocked": ("pending",),
    "client_reply": ("attempt",),
    "guard": ("leaked", "number_leak", "new_number", "broke_character", "invented_fact", "reason"),
    "finish": ("added", "discarded"),  # saved unlocks; discarded = earned but the turn fell back
}
MESSAGE = re.compile(r"<message>\n(.*)\n</message>\s*$", re.DOTALL)


def load(path: str) -> list[dict]:
    rows = []
    with open(path) as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"skipping line {n}: not JSON", file=sys.stderr)
    return rows


def student_words(calls: list[dict]) -> str | None:
    """The student's message, read back from the classifier's request (only present with content logging)."""
    for c in calls:
        if c.get("role") == "classifier" and c.get("messages") and (m := MESSAGE.search(c["messages"][-1]["content"])):
            return html.unescape(m.group(1))  # fence() escaped < and >
    return None


def call_line(c: dict) -> str:
    tokens = f"{c.get('tokens_in')}->{c.get('tokens_out')} tok" if c.get("status") == "ok" else c.get("error")
    flags = [f"finish={c.get('finish')}"] if c.get("status") == "ok" else ["ERROR"]
    if c.get("attempt", 1) > 1:
        flags.append(f"attempt {c['attempt']} (repair)")
    if c.get("code"):
        flags.append(c["code"])
    return f"└ call {c.get('role', '?')}  {c.get('ms', '?')} ms  {tokens}  {'  '.join(flags)}"


def full_call(c: dict, indent: str) -> list[str]:
    if "messages" not in c:
        return [f"{indent}(no prompt in this log: write it with LLM_CALL_LOG_CONTENT=1)"]
    out = []
    for m in c["messages"]:
        out.append(f"{indent}[{m['role']}]")
        out += [f"{indent}  {line}" for line in m["content"].splitlines()]
    out.append(f"{indent}[output]")
    out += [f"{indent}  {line}" for line in (c.get("output") or "(empty)").splitlines()]
    return out


def render(rows: list[dict], session: str | None = None, turn: int | None = None, full: bool = False) -> str:
    # Calls are written when they end, just before their node's row: attach each call to the next node row.
    turns: dict[tuple, list[tuple[dict, list[dict]]]] = defaultdict(list)
    pending: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        group = r.get("session") or (f"{r['arm']}:{r['case']}" if r.get("case") else None)
        key = (group, r.get("turn"))
        if r.get("kind") == "call":
            pending[key].append(r)
        elif r.get("kind") == "node":
            turns[key].append((r, pending.pop(key, [])))
    for key, calls in pending.items():  # calls outside the graph (coach, evals) or a node that crashed
        label = calls[0].get("node") or (f"{calls[0]['suite']} case" if calls[0].get("suite") else "(no node)")
        turns[key].append(({"node": label, "ms": None}, calls))

    out = []
    for (sid, t), nodes in turns.items():
        if session and not str(sid).startswith(session):
            continue
        if turn is not None and t != turn:
            continue
        calls = [c for _, cs in nodes for c in cs]
        said = student_words(calls)
        title = "opening" if t == 0 else f'"{said}"' if said else "(student text not logged)"
        out.append(f"session {sid}  turn {t}  {title}")
        for node, node_calls in nodes:
            details = [
                f"{k}={node[k]!r}" if k == "reason" else f"{k}={node[k]}"
                for k in NODE_FIELDS.get(node["node"], ())
                if k in node and node[k] not in (None, [], False)
            ]
            if node["node"] == "guard":
                failed = any(
                    node.get(k) for k in ("leaked", "number_leak", "new_number", "broke_character", "invented_fact")
                )
                details.insert(0, "REJECTED" if failed else "pass")
            details += [f"{e['code']}: {e['detail']}" for e in node.get("events", [])]
            ms = "" if node.get("ms") is None else f"{node['ms']:>6} ms"
            out.append(f"  {node['node']:<16}{ms}  {'  '.join(details)}".rstrip())
            for c in node_calls:
                out.append(f"     {call_line(c)}")
                if c.get("role") == "client" and c.get("output") and not full:
                    out.append(f'       "{c["output"]}"')
                if full:
                    out += full_call(c, "       ")
        out.append("")
    return "\n".join(out) if out else "no matching rows"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="the LLM_CALL_LOG file")
    parser.add_argument("--session", help="session id, or its first characters")
    parser.add_argument("--turn", type=int, help="0 is the opening")
    parser.add_argument("--full", action="store_true", help="print every prompt and raw output")
    args = parser.parse_args()
    print(render(load(args.path), args.session, args.turn, args.full))


if __name__ == "__main__":
    main()
