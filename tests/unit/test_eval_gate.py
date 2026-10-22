"""Tests of the regression gates of chapter 18.8 on synthetic metrics."""

import pytest

from keel.evaluation import gates
from keel.evaluation import runner

pytestmark = pytest.mark.unit

PASSING = {
    "recall_at_25": 0.90,
    "mrr": 0.70,
    "faithfulness": 0.95,
    "citation_precision": 0.92,
    "coverage_completeness": 1.0,
    "numeric_accuracy": 1.0,
    "schema_validity": 1.0,
    "refusal_correctness": 1.0,
    "latency_p95_s": 30.0,
    "mean_cost_usd": 0.12,
}


def test_eval_gate() -> None:
    results = gates.evaluate(PASSING)
    assert [r.gate.key for r in results] == [g.key for g in gates.GATES]
    assert len(results) == 10
    assert {r.status for r in results} == {gates.PASSED}
    assert not gates.blocked(results)
    for key, bad in [
        ("recall_at_25", 0.84),
        ("mrr", 0.59),
        ("coverage_completeness", 0.99),
        ("schema_validity", 0.97),
        ("latency_p95_s", 40.1),
        ("mean_cost_usd", 0.26),
    ]:
        failed = gates.evaluate({**PASSING, key: bad})
        assert gates.blocked(failed), key
        assert [r.gate.key for r in failed if r.status == gates.FAILED] == [key]


def test_gate_thresholds_are_inclusive() -> None:
    edge = {
        **PASSING,
        "recall_at_25": 0.85,
        "mrr": 0.60,
        "latency_p95_s": 40.0,
        "mean_cost_usd": 0.25,
    }
    assert not gates.blocked(gates.evaluate(edge))


def test_pending_gate_does_not_block() -> None:
    results = gates.evaluate({"recall_at_25": 0.9, "mrr": 0.7})
    pending = [r for r in results if r.status == gates.PENDING]
    assert len(pending) == 8
    assert all(r.value is None for r in pending)
    assert not gates.blocked(results)


def test_gate_rule_text() -> None:
    by_key = {g.key: g for g in gates.GATES}
    assert by_key["recall_at_25"].rule == ">= 0.85"
    assert by_key["latency_p95_s"].rule == "<= 40.00 s"
    assert by_key["mean_cost_usd"].rule == "<= 0.25 USD"


def make_run(results: list[runner.QuestionResult]) -> runner.EvalRun:
    info = runner.RunInfo(
        run_id="eval-x",
        started_at="2026-10-21T00:00:00+00:00",
        golden_version="1.0.0",
        index_version="1.0.1",
        build_id="b",
        chunks_sha256="c",
        prompt_version="1.0.0",
        model="m",
    )
    return runner.EvalRun(info, (runner.MAIN,), tuple(results))


def test_run_gate_values_from_results() -> None:
    def scored(qid: str, recall: float, mrr: float) -> runner.QuestionResult:
        return runner.QuestionResult(
            qid,
            "single_company",
            "hybrid",
            runner.SCORED,
            metrics={"recall_at_25": recall, "mrr": mrr},
        )

    run = make_run(
        [
            scored("G-01", 1.0, 1.0),
            scored("G-02", 0.5, 0.25),
            runner.QuestionResult("G-22", "out_of_corpus", "", runner.REFUSED),
            runner.QuestionResult(
                "G-23", "out_of_corpus", "", runner.MISSED_REFUSAL
            ),
        ]
    )
    values = run.gate_values()
    assert values["recall_at_25"] == 0.75
    assert values["mrr"] == 0.625
    assert values["refusal_correctness"] == 0.5
    by_key = {r.gate.key: r for r in run.gates()}
    assert by_key["recall_at_25"].status == gates.FAILED
    assert by_key["refusal_correctness"].status == gates.FAILED
    assert by_key["faithfulness"].status == gates.PENDING


def test_wrong_refusal_counts_as_zero() -> None:
    run = make_run(
        [
            runner.QuestionResult(
                "G-01",
                "single_company",
                "hybrid",
                runner.WRONG_REFUSAL,
                metrics={"recall_at_25": 0.0, "mrr": 0.0},
            ),
            runner.QuestionResult(
                "G-02",
                "single_company",
                "hybrid",
                runner.SCORED,
                metrics={"recall_at_25": 1.0, "mrr": 1.0},
            ),
        ]
    )
    assert run.gate_values()["recall_at_25"] == 0.5
    assert run.refusal_correctness() is None
