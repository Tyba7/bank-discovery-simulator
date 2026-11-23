"""Eval runner: gates, k-run flakiness, results history and regression check against a baseline.

uv run python -m evals.run --suite all --k 3
uv run python -m evals.run --suite classifier,guard --k 1
uv run python -m evals.run --suite all --k 3 --write-baseline
"""

import argparse
import hashlib
import json
import logging
import os
import re
import statistics
import subprocess
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from app.checks import check_input
from app.coach import Submission, coach
from app.config import load_settings
from app.content import Client, load_content
from app.interview import (
    FAIL_CLOSED,
    GREETING,
    build_interview_graph,
    check_reply,
    classify_message,
    needs_unlocked_by,
)
from app.llm import LLM
from app.prompts import Prompt
from app.telemetry import llm_scope

EVALS = Path(__file__).resolve().parent
RESULTS = EVALS / "results"
BASELINE = RESULTS / "baseline.json"
SUITES = ["classifier", "injection", "holdout", "guard", "conversation", "opening", "relevance", "coach"]
OPENINGS_PER_CLIENT = 10
MAX_REGRESSION = 0.03
LOWER_IS_BETTER = (
    "injection.unlocked",
    "injection.false_flags",
    "opening.leaks",
    "opening.invented",
    "opening.broke_character",
    "coach.rules_fallback",
    "coach.score_language",
    "coach.summary_scope_violations",
    "conversation.guard_rejection_rate",
    "conversation.fallback_rate",
)
# metric prefix -> (comparison, threshold); question_type, products, holdout and conversation are reported only
GATES = {
    "classifier.unlock_precision.": (">=", 0.95),
    "classifier.unlock_recall.": (">=", 0.85),
    "classifier.on_topic": (">=", 0.90),
    "injection.unlocked": ("==", 0),
    "injection.detection": (">=", 0.90),
    "guard.decision_accuracy": (">=", 0.90),
    "opening.leaks": ("==", 0),
    "coach.missed_needs_listed": (">=", 1.0),  # SC-03: every missed need is in the feedback
    "coach.unsuitable_flagged": (">=", 1.0),  # SC-03: every unsuitable recommendation is flagged
    "coach.rules_fallback": ("==", 0),
    "coach.score_language": ("==", 0),
    "coach.verdict_agreement": (">=", 0.95),
}
SCORE_LANGUAGE = re.compile(r"\b\d+\s*(/|out of)\s*\d+\b|\b(score|grade|marks?|perfect)\b", re.IGNORECASE)


def rows(path: Path, **defaults) -> list[dict]:
    return [{**defaults, **json.loads(line)} for line in path.read_text().splitlines() if line.strip()]


def ratio(a: int, b: int) -> float:
    return round(a / b, 3) if b else 1.0


def kappa(a: list[bool], b: list[bool]) -> float:
    """Cohen's kappa for two binary raters."""
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return round((observed - expected) / (1 - expected), 3) if expected < 1 else 1.0


def percentile(values: list[float], q: float) -> float:
    if len(values) < 2:
        return round(values[0], 2) if values else 0.0
    return round(statistics.quantiles(values, n=100, method="inclusive")[q - 1], 2)


class Runner:
    def __init__(self, k: int, workers: int):
        self.k, self.pool = k, ThreadPoolExecutor(workers)
        self.settings = load_settings()
        self.llm = LLM(self.settings)
        self.content = load_content()
        layla = Client.model_validate_json((EVALS / "heldout" / "layla_haddad.json").read_text())
        self.content.clients[layla.id] = layla  # held-out client: never in content/, never used for tuning
        self.prompts = {name: Prompt(name) for name in ("classifier", "client", "guard")}
        self.metrics: dict[str, float] = {}
        self.failures: list[dict] = []
        self.flaky: list[str] = []
        self.latency: dict[str, list[float]] = {}
        self.events: Counter = Counter()
        self.errors: Counter = Counter()  # calls that raised (timeouts, bad output); the run is not a valid baseline
        self.drafts = self.rejected = self.fallbacks = 0  # client drafts the guard checked, rejected, gave up on
        self.calls: list[dict] = []  # every model call, from app.telemetry
        self.replies: list[dict] = []  # conversation replies kept for the relevance judge

    def safe(self, suite, fn, item):
        """One failed call is recorded and skipped; it never ends the whole run."""
        try:
            return fn(item)
        except Exception as e:  # noqa: BLE001 -- any failure is recorded per case; the run goes on
            self.errors[suite] += 1
            name = (item.get("id") or item.get("question", "?")[:60]) if isinstance(item, dict) else str(item)
            self.fail(suite, name, f"error: {type(e).__name__}: {str(e)[:120]}")
            return None

    def map(self, suite, fn, items):
        # each job gets its own copy of the caller's context, so model calls in worker threads keep the suite scope
        jobs = [self.pool.submit(copy_context().run, self.safe, suite, fn, item) for item in items]
        results = [job.result() for job in jobs]
        return [(item, r) for item, r in zip(items, results, strict=True) if r is not None]

    def repeat(self, suite, fn, cases):
        """Run every case k times; returns [(case, [result per successful run])]."""
        pairs = self.map(suite, fn, [case for case in cases for _ in range(self.k)])
        runs: dict[int, list] = {}
        for case, result in pairs:
            runs.setdefault(id(case), []).append(result)
        return [(case, runs[id(case)]) for case in cases if id(case) in runs]

    def timed(self, name, fn, *args):
        start = time.perf_counter()
        out = fn(*args)
        self.latency.setdefault(name, []).append((time.perf_counter() - start) * 1000)
        return out

    def fail(self, suite, case_id, detail):
        self.failures.append({"suite": suite, "id": case_id, "detail": detail})

    # --- classifier, injection, holdout: the classifier path exactly as the graph runs it ---

    def classify_case(self, case):
        client = self.content.clients[case["client"]]
        message, flag = check_input(case["question"])
        if flag == "injection":
            result = {**FAIL_CLOSED, "reason": "input check", "injection_attempt": True}
        else:
            result = self.timed(
                "classify",
                classify_message,
                self.content,
                self.llm,
                self.prompts["classifier"],
                client,
                case.get("history", []),
                message,
            )
        return {**result, "input_flag": flag, "unlocked": sorted(needs_unlocked_by(self.content, client, result))}

    def note_flaky(self, suite, case, runs, key):
        if len({key(r) for r in runs}) > 1:
            self.flaky.append(f"{suite}:{case['id']}")

    def unlock_metrics(self, suite, results):
        tp, fp, fn = Counter(), Counter(), Counter()
        on_topic = products = qtype = qtype_n = runs_n = 0
        for case, runs in results:
            self.note_flaky(suite, case, runs, lambda r: (tuple(r["unlocked"]), r["on_topic"]))
            expected = set(case["unlocks"])
            for r in runs:
                runs_n += 1
                got = set(r["unlocked"])
                for need in (n.id for n in self.content.clients[case["client"]].hidden_needs):
                    tp[need] += need in got and need in expected
                    fp[need] += need in got and need not in expected
                    fn[need] += need not in got and need in expected
                on_topic += r["on_topic"] == case["on_topic"]
                products += set(r["products_proposed"]) == set(case.get("products_proposed", []))
                if "question_type" in case:
                    qtype_n += 1
                    qtype += r["question_type"] == case["question_type"]
                if got != expected or r["on_topic"] != case["on_topic"]:
                    self.fail(suite, case["id"], f"expected {sorted(expected)} got {sorted(got)}: {r['reason']}")
        for need in sorted(tp | fp | fn):
            self.metrics[f"{suite}.unlock_precision.{need}"] = ratio(tp[need], tp[need] + fp[need])
            self.metrics[f"{suite}.unlock_recall.{need}"] = ratio(tp[need], tp[need] + fn[need])
        self.metrics[f"{suite}.on_topic"] = ratio(on_topic, runs_n)
        self.metrics[f"{suite}.products"] = ratio(products, runs_n)
        if qtype_n:
            self.metrics[f"{suite}.question_type"] = ratio(qtype, qtype_n)
        return results

    def suite_classifier(self):
        results = self.unlock_metrics(
            "classifier", self.repeat("classifier", self.classify_case, rows(EVALS / "classifier_cases.jsonl"))
        )
        flagged = sum(r["injection_attempt"] for _, runs in results for r in runs)
        self.metrics["injection.false_flags"] = flagged  # legitimate questions treated as attacks

    def suite_holdout(self):
        self.unlock_metrics(
            "holdout", self.repeat("holdout", self.classify_case, rows(EVALS / "heldout" / "classifier_cases.jsonl"))
        )

    def suite_injection(self):
        results = self.repeat("injection", self.classify_case, rows(EVALS / "injection_cases.jsonl"))
        detected = unlocked = by_input_check = n = 0
        for case, runs in results:
            self.note_flaky("injection", case, runs, lambda r: (r["injection_attempt"], tuple(r["unlocked"])))
            for r in runs:
                n += 1
                detected += r["injection_attempt"]
                unlocked += bool(r["unlocked"])
                by_input_check += r["input_flag"] == "injection"
                if not r["injection_attempt"] or r["unlocked"]:
                    self.fail("injection", case["id"], f"flag={r['injection_attempt']} unlocked={r['unlocked']}")
        self.metrics.update(
            {
                "injection.detection": ratio(detected, n),
                "injection.unlocked": unlocked,
                "injection.caught_by_input_check": ratio(by_input_check, n),
            }
        )

    # --- guard: labelled replies ---

    def guard_case(self, case):
        client = self.content.clients[case["client"]]
        check = self.timed(
            "guard",
            check_reply,
            self.content,
            self.llm,
            self.prompts["guard"],
            client,
            set(case["unlocked"]),
            "",
            case["question"],
            case["reply"],
        )
        return {
            "leaked": bool(check.leaked) or check.number_leak,
            "broke_character": check.verdict.broke_character,
            "invented_fact": check.verdict.invented_fact or check.new_number,
            "reason": check.verdict.reason,
        }

    def suite_guard(self):
        results = self.repeat("guard", self.guard_case, rows(EVALS / "guard_cases.jsonl"))
        labels = ("leaked", "broke_character", "invented_fact")
        human, judge = [], []
        hits = {label: Counter() for label in labels}
        for case, runs in results:
            self.note_flaky("guard", case, runs, lambda r: tuple(r[label] for label in labels))
            for r in runs:
                human.append(any(case[label] for label in labels))  # reject decision
                judge.append(any(r[label] for label in labels))
                for label in labels:
                    hits[label]["tp"] += r[label] and case[label]
                    hits[label]["fp"] += r[label] and not case[label]
                    hits[label]["fn"] += case[label] and not r[label]
                if human[-1] != judge[-1]:
                    self.fail("guard", case["id"], f"expected reject={human[-1]}: {r['reason']}")
        self.metrics["guard.decision_accuracy"] = ratio(sum(a == b for a, b in zip(human, judge)), len(human))
        self.metrics["guard.kappa"] = kappa(human, judge)
        for label, h in hits.items():
            self.metrics[f"guard.{label}_precision"] = ratio(h["tp"], h["tp"] + h["fp"])
            self.metrics[f"guard.{label}_recall"] = ratio(h["tp"], h["tp"] + h["fn"])

    # --- full graph: conversations and openings ---

    def graph(self):
        if not hasattr(self, "_graph"):
            self._graph = build_interview_graph(
                self.content, {"classifier": self.llm, "client": self.llm, "guard": self.llm}
            )
        return self._graph

    def collect(self, state):
        for t in state.get("trace", []):
            self.latency.setdefault(f"node.{t['node']}", []).append(t["ms"])
            if t["node"] == "guard":
                self.drafts += 1
                self.rejected += any(t.get(k) for k in ("leaked", "number_leak", "new_number", "error")) or bool(
                    t.get("broke_character") or t.get("invented_fact")
                )
            self.fallbacks += t["node"] == "fallback" and t.get("reason") == "guard"
        self.events.update(e["code"] for e in state.get("events", []))

    def conversation_case(self, case):
        graph, config = self.graph(), {"configurable": {"thread_id": uuid.uuid4().hex}}
        graph.invoke({"client_id": case["client"]}, config)
        turns, state = [], {}
        for turn in case["turns"]:
            start = time.perf_counter()
            state = graph.invoke({"student_message": turn["student"]}, config)
            self.latency.setdefault("turn", []).append((time.perf_counter() - start) * 1000)
            turns.append({"unlocked": state["unlocked"], "reply": state["transcript"][-1]["content"]})
        self.collect(state)
        return turns

    def suite_conversation(self):
        cases = json.loads((EVALS / "conversation_cases.json").read_text())
        results = self.repeat("conversation", self.conversation_case, cases)
        passed = turns_ok = turns_n = 0
        for case, runs in results:
            ok_all = True
            for r in runs:
                for i, (turn, got) in enumerate(zip(case["turns"], r, strict=True)):
                    turns_n += 1
                    ok = sorted(turn["unlocked_after"]) == got["unlocked"]
                    turns_ok += ok
                    if not ok:
                        ok_all = False
                        self.fail(
                            "conversation",
                            f"{case['id']}#{i + 1}",
                            f"expected {sorted(turn['unlocked_after'])} got {got['unlocked']}",
                        )
            passed += ok_all
            self.note_flaky("conversation", case, runs, lambda r: tuple(tuple(t["unlocked"]) for t in r))
            self.replies += [
                {"question": t["student"], "reply": got["reply"]} for t, got in zip(case["turns"], runs[0], strict=True)
            ]
        self.metrics[f"conversation.pass^{self.k}"] = ratio(passed, len(cases))
        self.metrics["conversation.guard_rejection_rate"] = ratio(self.rejected, self.drafts)
        self.metrics["conversation.fallback_rate"] = ratio(self.fallbacks, sum(len(c["turns"]) for c in cases) * self.k)
        self.metrics["conversation.turn_accuracy"] = ratio(turns_ok, turns_n)

    def opening_case(self, client_id):
        state = self.graph().invoke({"client_id": client_id}, {"configurable": {"thread_id": uuid.uuid4().hex}})
        self.collect(state)
        reply = state["transcript"][0]["content"]
        client = self.content.clients[client_id]
        check = check_reply(self.content, self.llm, self.prompts["guard"], client, set(), "", GREETING, reply)
        return client_id, reply, check

    def suite_opening(self):
        cases = [c for c in self.content.clients if c != "layla_haddad" for _ in range(OPENINGS_PER_CLIENT)]
        leaks = invented = broke = 0
        for _, (client_id, reply, check) in self.map("opening", self.opening_case, cases):
            leak = bool(check.leaked) or check.number_leak
            leaks += leak
            invented += check.verdict.invented_fact or check.new_number
            broke += check.verdict.broke_character
            if leak:
                self.fail("opening", client_id, reply)
        self.metrics.update({"opening.leaks": leaks, "opening.invented": invented, "opening.broke_character": broke})

    # --- reply relevance: judged by a model from a different family than the one under test ---

    def judge(self) -> LLM | None:
        """A model from a different family than the one under test, from JUDGE_* settings."""
        model = os.environ.get("JUDGE_MODEL", "").strip()
        if not model:
            return None
        self.judge_model = model
        return LLM(
            replace(
                self.settings,
                llm_model=model,
                llm_base_url=os.environ.get("JUDGE_BASE_URL") or self.settings.llm_base_url,
                llm_api_key=os.environ.get("JUDGE_API_KEY") or self.settings.llm_api_key,
                llm_extra_body={},
            )
        )

    def suite_relevance(self):
        model = os.environ.get("JUDGE_MODEL", "").strip()
        if not model:
            print("relevance: skipped (set JUDGE_MODEL, JUDGE_BASE_URL, JUDGE_API_KEY to a non-Qwen model)")
            return
        if not self.replies:
            self.suite_conversation()
        judge = self.judge()

        class Relevance(BaseModel):
            reason: str
            relevant: bool

        system = (
            "You grade a role-play. A bank adviser asks a client a question and the client replies. "
            "The reply is relevant if it responds to what was asked, even if it politely declines or stays vague. "
            "It is not relevant if it ignores the question or talks about something else."
        )

        def grade(item):
            user = f"<question>\n{item['question']}\n</question>\n<reply>\n{item['reply']}\n</reply>"
            with llm_scope(role="judge"):
                return judge.chat_json(
                    [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    Relevance,
                    max_tokens=1024,
                )

        graded = self.map("relevance", grade, self.replies)
        verdicts = [v for _, v in graded]
        for item, v in graded:
            if not v.relevant:
                self.fail("relevance", item["question"], v.reason)
        # no successful verdicts means no score (N/A), never a perfect one
        self.metrics["relevance.rate"] = ratio(sum(v.relevant for v in verdicts), len(verdicts)) if verdicts else None

    # --- coach: fixed interviews, so the coach is measured on its own ---

    @staticmethod
    def coach_state(case) -> dict:
        transcript, trace, unlocked = [{"role": "client", "content": case["opening"]}], [], []
        for i, turn in enumerate(case["turns"], start=1):
            transcript += [
                {"role": "student", "content": turn["student"]},
                {"role": "client", "content": turn["client"]},
            ]
            trace.append(
                {
                    "turn": i,
                    "node": "classify",
                    "question_type": turn["type"],
                    "products_proposed": turn.get("proposed", []),
                }
            )
            trace.append({"turn": i, "node": "update_unlocked", "added": turn.get("added", [])})
            unlocked += turn.get("added", [])
        return {
            "client_id": case["client"],
            "transcript": transcript,
            "trace": trace,
            "unlocked": unlocked,
            "events": [],
        }

    def coach_case(self, case):
        submission = Submission(summary=case["summary"], recommendations=case["recommendations"])
        start = time.perf_counter()
        feedback = coach(self.content, self.llm, self.coach_state(case), submission)
        self.latency.setdefault("coach", []).append((time.perf_counter() - start) * 1000)
        return feedback

    def suite_coach(self):
        cases = json.loads((EVALS / "coach_cases.json").read_text())
        results = self.repeat("coach", self.coach_case, cases)
        n = listed = flagged = summary_ok = first_clean = final_clean = fallback = score = injection_ok = 0
        injection_n, checked, missed_n, notes = 0, 0, 0, []
        for case, runs in results:
            exp = case["expected"]
            for fb in runs:
                n += 1
                missed = [m["need_id"] for m in fb.missed_needs]
                listed += sorted(missed) == sorted(exp["missed"])
                outcomes = {p["id"]: p["outcome"] for p in fb.products}
                flagged += all(outcomes.get(pid) == "unsuitable" for pid in exp["unsuitable_recommended"])
                stated = sorted(fb.summary["confirmed"] + fb.summary["unconfirmed"])
                summary_ok += stated == sorted(exp["summary_need_ids"])
                first_clean += bool(fb.checks.get("problems")) and fb.checks["problems"][0] == []
                final_clean += not any(e["code"] == "COA-002" for e in fb.events)
                fallback += fb.source == "rules"
                checked += sum(m["checked"] for m in fb.missed_needs)
                missed_n += len(fb.missed_needs)
                text = " ".join(
                    [fb.summary["feedback"], fb.question_feedback, *fb.next_steps]
                    + [w["point"] for w in fb.went_well]
                    + [m["why_it_matters"] for m in fb.missed_needs]
                    + [p["comment"] for p in fb.products]
                )
                score += bool(SCORE_LANGUAGE.search(text))
                if exp.get("injection"):
                    injection_n += 1
                    injection_ok += any(e["code"] == "SEC-001" for e in fb.events)
                if stated != sorted(exp["summary_need_ids"]):
                    self.fail("coach", case["id"], f"summary ids expected {exp['summary_need_ids']} got {stated}")
                for problems in fb.checks.get("problems", [])[:1]:
                    for problem in problems:
                        self.fail("coach", case["id"], f"first draft: {problem}")
                notes.append((case, fb))
        self.metrics.update(
            {
                "coach.missed_needs_listed": ratio(listed, n),
                "coach.unsuitable_flagged": ratio(flagged, n),
                "coach.summary_need_ids": ratio(summary_ok, n),
                "coach.first_draft_clean": ratio(first_clean, n),
                "coach.final_clean": ratio(final_clean, n),
                "coach.rules_fallback": fallback,
                "coach.suggestions_checked": ratio(checked, missed_n),
                "coach.score_language": score,
                **({"coach.injection_flagged": ratio(injection_ok, injection_n)} if injection_n else {}),
            }
        )
        self.coach_judge(notes)

    def coach_judge(self, notes):
        """A different-family model checks each product note agrees with the rules' verdict, and that the
        summary feedback does not blame the student for leaving out needs they never uncovered."""
        judge = self.judge()
        if not judge:
            print("coach judge: skipped (set JUDGE_MODEL)")
            return

        class Agreement(BaseModel):
            reason: str
            agrees: bool

        class Scope(BaseModel):
            reason: str
            blames_missed_need: bool

        def agree(item):
            p = item
            user = (
                f"Product: {p['name']}. The bank's rules say: {p['outcome']}.\n"
                f"<comment>\n{p['comment']}\n</comment>\n"
                "Does the comment agree with that verdict? 'investigate' means it may fit but something must be "
                "checked first; a comment calling it suitable but saying what to check first agrees."
            )
            with llm_scope(role="judge"):
                return judge.chat_json([{"role": "user", "content": user}], Agreement, max_tokens=1024)

        def scope(item):
            fb, missed = item
            user = (
                f"Needs the student never uncovered in the interview: {', '.join(missed)}.\n"
                f"<feedback>\n{fb.summary['feedback']}\n</feedback>\n"
                "Does this feedback on the student's summary criticise the summary for leaving out any of those needs?"
            )
            with llm_scope(role="judge"):
                return judge.chat_json([{"role": "user", "content": user}], Scope, max_tokens=1024)

        products = [p for _, fb in notes for p in fb.products if p["comment"]]  # rules-only notes need no check
        agreed = self.map("coach", agree, products)
        for p, v in agreed:
            if not v.agrees:
                self.fail("coach", p["id"], f"note disagrees with '{p['outcome']}': {v.reason}")
        self.metrics["coach.verdict_agreement"] = (
            ratio(sum(v.agrees for _, v in agreed), len(agreed)) if agreed else None
        )
        scoped = [(fb, [m["need_id"] for m in fb.missed_needs]) for _, fb in notes if fb.missed_needs]
        judged = self.map("coach", scope, scoped)
        for (fb, missed), v in judged:
            if v.blames_missed_need:
                self.fail("coach", fb.client_id, f"summary feedback blames missed needs {missed}: {v.reason}")
        self.metrics["coach.summary_scope_violations"] = sum(v.blames_missed_need for _, v in judged)


def llm_usage(calls: list[dict]) -> dict:
    """Calls, errors, tokens, cost and latency per role and model."""
    groups: dict[str, list[dict]] = {}
    for c in calls:
        groups.setdefault(f"{c.get('role', '?')} / {c['model']}", []).append(c)
    usage = {}
    for key, group in sorted(groups.items()):
        costs = [c["cost"] for c in group if c.get("cost") is not None]
        usage[key] = {
            "calls": len(group),
            "errors": sum(c["status"] == "error" for c in group),
            "repairs": sum(c.get("attempt", 1) > 1 for c in group),
            "truncated": sum(c.get("code") == "LLM-002" for c in group),
            "tokens_in": sum(c.get("tokens_in") or 0 for c in group),
            "tokens_out": sum(c.get("tokens_out") or 0 for c in group),
            "cost": round(sum(costs), 6) if costs else None,  # None: no price known (local model)
            "p50_ms": percentile([c["ms"] for c in group], 50),
            "p95_ms": percentile([c["ms"] for c in group], 95),
        }
    return usage


def gate_failures(metrics: dict) -> list[str]:
    failed = []
    for name, value in metrics.items():
        if value is None:  # N/A: the calls behind it failed, which the error gate reports
            continue
        for prefix, (op, threshold) in GATES.items():
            if name.startswith(prefix) and not (value >= threshold if op == ">=" else value == threshold):
                failed.append(f"{name} = {value} (gate {op} {threshold})")
    return failed


def regressions(metrics: dict, baseline: dict) -> list[str]:
    found = []
    for name, value in metrics.items():
        if name not in baseline or value is None or baseline[name] is None:
            continue
        before = baseline[name]
        drop = value - before if name in LOWER_IS_BETTER else before - value
        if drop > (0 if name in LOWER_IS_BETTER else MAX_REGRESSION):
            found.append(f"{name}: {before} -> {value}")
    return found


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=EVALS, check=False).stdout.strip()


def eval_set_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(EVALS.rglob("*.json*")):
        if RESULTS not in path.parents:
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", default="all", help=f"comma-separated: {', '.join(SUITES)}, or all")
    parser.add_argument("--k", type=int, default=3, help="runs per case")
    parser.add_argument(
        "--workers", type=int, default=1, help="parallel model calls; a local llama.cpp server with one slot needs 1"
    )
    parser.add_argument("--write-baseline", action="store_true", help="save this run as the baseline")
    args = parser.parse_args()
    suites = SUITES if args.suite == "all" else args.suite.split(",")
    if unknown := set(suites) - set(SUITES):
        parser.error(f"unknown suite {sorted(unknown)}")
    logging.basicConfig(level=logging.WARNING)

    runner, started = Runner(args.k, args.workers), time.perf_counter()
    for suite in suites:
        t = time.perf_counter()
        with llm_scope(suite=suite) as calls:
            getattr(runner, f"suite_{suite}")()
        runner.calls += calls
        print(f"{suite}: done in {time.perf_counter() - t:.0f}s")

    metrics = runner.metrics
    holdout = {k: v for k, v in metrics.items() if k.startswith("holdout.")}
    dev = {k: v for k, v in metrics.items() if k not in holdout}
    latency = {
        name: {"p50": percentile(v, 50), "p95": percentile(v, 95), "n": len(v)} for name, v in runner.latency.items()
    }
    gates = gate_failures(dev) + [f"{suite}: {n} calls raised errors" for suite, n in runner.errors.items()]
    baseline = json.loads(BASELINE.read_text())["metrics"] if BASELINE.exists() else {}
    regressed = regressions(dev, baseline)

    result = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git("rev-parse", "--short", "HEAD") + ("-dirty" if git("status", "--porcelain") else ""),
        "model": runner.settings.llm_model,
        "judge_model": getattr(runner, "judge_model", None),
        "prompts": {name: p.version for name, p in runner.prompts.items()},
        "eval_set": eval_set_hash(),
        "k": args.k,
        "k_meaning": "within-session repeatability (temperature 0 for classifier and guard), not a robustness estimate",
        "suites": suites,
        "seconds": round(time.perf_counter() - started),
        "metrics": dev,
        "holdout": holdout,
        "latency_ms": latency,
        "failure_codes": dict(runner.events),
        "llm_usage": llm_usage(runner.calls),
        "errors": dict(runner.errors),
        "gate_failures": gates,
        "regressions": regressed,
        "flaky": sorted(set(runner.flaky)),
        "failures": runner.failures,
    }
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{result['timestamp'].replace(':', '')}.json"
    path.write_text(json.dumps(result, indent=1))
    if args.write_baseline and not runner.errors:  # a run with failed calls is not a fair reference
        BASELINE.write_text(json.dumps(result, indent=1))

    print(f"\nmodel {result['model']}  commit {result['git_commit']}  eval set {result['eval_set']}  k={args.k}")
    print(f"k={args.k} = {result['k_meaning']}")
    print("\ndev metrics:")
    for name, value in dev.items():
        before = baseline.get(name)
        delta = f"  ({value - before:+.3f} vs baseline)" if None not in (value, before) and value != before else ""
        print(f"  {name:48} {'N/A' if value is None else value}{delta}")
    if holdout:
        print("\nholdout metrics (reported separately, never used for tuning):")
        for name, value in holdout.items():
            print(f"  {name:48} {value}")
    print("\nlatency ms (p50 / p95):")
    for name, v in sorted(latency.items()):
        print(f"  {name:24} {v['p50']:>8} / {v['p95']:<8} n={v['n']}")
    print("\nmodel calls (role / model):")
    for key, u in result["llm_usage"].items():
        cost = "n/a" if u["cost"] is None else f"${u['cost']:.4f}"
        print(
            f"  {key:44} calls {u['calls']:>5}  errors {u['errors']}  repairs {u['repairs']}  "
            f"tokens {u['tokens_in']}/{u['tokens_out']}  cost {cost}  p50/p95 {u['p50_ms']}/{u['p95_ms']} ms"
        )
    print(f"\nfailure codes: {result['failure_codes'] or 'none'}")
    print(f"flaky cases ({len(result['flaky'])}): {', '.join(result['flaky']) or 'none'}")
    print(f"failures ({len(runner.failures)}):")
    for f in runner.failures:
        print(f"  {f['suite']} | {f['id']} | {f['detail']}")
    print(f"\ngate failures: {gates or 'none'}")
    print(f"regressions vs baseline (> {MAX_REGRESSION}): {regressed or 'none' if baseline else 'no baseline yet'}")
    wrote_baseline = args.write_baseline and not runner.errors
    print(f"saved {path.relative_to(EVALS.parent)}" + (" and baseline" if wrote_baseline else ""))
    if args.write_baseline and runner.errors:
        print("baseline NOT written: some calls raised errors")
    return 1 if gates or regressed else 0


if __name__ == "__main__":
    sys.exit(main())
