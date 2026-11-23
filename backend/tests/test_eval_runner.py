from evals.run import gate_failures, kappa, regressions


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
