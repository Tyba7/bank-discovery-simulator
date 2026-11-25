import pytest

from evals.run import ab_verdict, gate_failures, gated, kappa, mcnemar_p, paired, regressions


def test_kappa():
    assert kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert kappa([True, True, False, False], [True, False, True, False]) == 0.0
    assert kappa([True, True], [True, True]) == 1.0  # one class only: agreement is total


def test_gates_apply_by_prefix():
    metrics = {"classifier.unlock_recall.existing_lease": 0.80, "classifier.on_topic": 0.95, "injection.unlocked": 1}
    assert gate_failures(metrics) == [
        "classifier.unlock_recall.existing_lease = 0.8 (gate >= 0.85)",
        "injection.unlocked = 1 (gate == 0)",
    ]


def test_regressions_respect_direction_and_tolerance():
    baseline = {"classifier.on_topic": 0.98, "guard.kappa": 0.90, "opening.leaks": 0}
    metrics = {"classifier.on_topic": 0.96, "guard.kappa": 0.80, "opening.leaks": 1, "new.metric": 0.5}
    assert regressions(metrics, baseline) == ["guard.kappa: 0.9 -> 0.8", "opening.leaks: 0 -> 1"]


def test_mcnemar_exact_p_values():
    assert mcnemar_p(0, 0) == 1.0
    assert mcnemar_p(0, 5) == 0.0625  # 2 x (1/2)^5
    assert round(mcnemar_p(1, 9), 4) == 0.0215  # 2 x (1 + 10) / 1024
    assert mcnemar_p(4, 4) == 1.0


def test_paired_comparison_counts_discordant_runs_and_brackets_the_difference():
    a = {"c1": [True, True], "c2": [False, False], "c3": [True, False], "only_a": [True]}
    b = {"c1": [True, True], "c2": [True, True], "c3": [True, True], "only_b": [False]}
    c = paired(a, b)
    assert (c["n"], c["cases"], c["a_only"], c["b_only"]) == (6, 3, 0, 3)  # cases missing from one arm are skipped
    assert (c["a"], c["b"], c["diff"]) == (0.5, 1.0, 0.5)
    assert c["ci95"][0] <= c["diff"] <= c["ci95"][1]
    assert paired(a, b) == c  # seeded: the same data gives the same interval
    assert paired({"x": [True]}, {"y": [True]}) is None


def test_ab_decision_rule():
    assert ab_verdict({"diff": 0.1, "ci95": [0.02, 0.2], "p": 0.01}) == "B better"
    assert ab_verdict({"diff": 0.2, "ci95": [0.0, 0.5], "p": 0.0078}) == "B better"  # bound pinned at 0
    assert ab_verdict({"diff": -0.2, "ci95": [-0.3, -0.05], "p": 0.01}) == "B worse"
    assert ab_verdict({"diff": -0.2, "ci95": [-0.5, 0.0], "p": 0.0078}) == "B worse"  # the ki01 objection result
    assert ab_verdict({"diff": 0.03, "ci95": [-0.03, 0.1], "p": 0.5}) == "B not worse"
    assert ab_verdict({"diff": -0.05, "ci95": [-0.2, 0.1], "p": 0.5}) == "inconclusive"


def test_a_malformed_judge_answer_gets_one_fresh_retry(monkeypatch):
    from pydantic import BaseModel

    from app.llm import LLM, LLMOutputError
    from evals.run import ask_judge

    class Verdict(BaseModel):
        ok: bool

    answers = iter([LLMOutputError("bad"), Verdict(ok=True), LLMOutputError("bad"), LLMOutputError("bad")])

    def chat_json(self, messages, schema, **kwargs):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(LLM, "chat_json", chat_json)
    judge = LLM.__new__(LLM)
    assert ask_judge(judge, [], Verdict).ok is True
    with pytest.raises(LLMOutputError):
        ask_judge(judge, [], Verdict)  # two malformed answers in a row still count as an error


def test_the_sealed_test_set_is_never_part_of_a_default_run():
    from evals.run import SEALED, SUITES

    assert "test" in SEALED and "test" not in SUITES


def test_a_model_judging_itself_is_reported_but_not_gated():
    metrics = {"coach.verdict_agreement": 0.88, "relevance.rate": 0.5, "coach.rules_fallback": 1}
    checked = gated(metrics, "qwen (same as under test)")
    assert checked == {"coach.rules_fallback": 1}  # code-measured metrics still gate
    assert gate_failures(checked) == ["coach.rules_fallback = 1 (gate == 0)"]
    assert regressions(checked, {"coach.verdict_agreement": 0.98}) == []
    assert gated(metrics, "google/gemini-3.5-flash") == metrics  # a separate judge is gated as before
