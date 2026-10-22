"""Tests of the retrieval metrics of chapter 18.3."""

import math

import pytest

from keel.evaluation import metrics

pytestmark = pytest.mark.unit

RANKED = ["a", "b", "c", "d", "e"]


def test_recall_capped_by_k() -> None:
    # 3 relevant, 2 in the top 2: 2 / min(2, 3).
    assert metrics.recall_at_k(RANKED, {"a", "b", "z"}, 2) == 1.0
    # 3 relevant, 2 in the top 5: 2 / min(5, 3).
    assert metrics.recall_at_k(RANKED, {"a", "c", "z"}, 5) == pytest.approx(
        2 / 3
    )


def test_recall_without_relevant_is_none() -> None:
    assert metrics.recall_at_k(RANKED, set(), 10) is None
    assert metrics.recall_at_k(RANKED, {"a"}, 0) is None


def test_recall_of_a_large_section_reaches_one() -> None:
    relevant = {f"s{i}" for i in range(100)}
    ranked = [f"s{i}" for i in range(25)]
    assert metrics.recall_at_k(ranked, relevant, 25) == 1.0
    assert metrics.recall_at_k(ranked, relevant, 48) == pytest.approx(25 / 48)


def test_reciprocal_rank() -> None:
    assert metrics.reciprocal_rank(RANKED, {"c"}) == pytest.approx(1 / 3)
    assert metrics.reciprocal_rank(RANKED, {"z"}) == 0.0
    assert metrics.reciprocal_rank(RANKED, {"e"}, depth=4) == 0.0
    assert metrics.reciprocal_rank(RANKED, set()) is None


def test_ndcg_perfect_and_reversed() -> None:
    grades = {"a": 2, "b": 1, "c": 0}
    assert metrics.ndcg_at_k(["a", "b", "c"], grades) == pytest.approx(1.0)
    reversed_order = metrics.ndcg_at_k(["c", "b", "a"], grades)
    ideal = 2 + 1 / math.log2(3)
    actual = 1 / math.log2(3) + 2 / math.log2(4)
    assert reversed_order == pytest.approx(actual / ideal)


def test_ndcg_unjudged_counts_zero_and_no_gain_is_none() -> None:
    assert metrics.ndcg_at_k(["x", "a"], {"a": 2}) == pytest.approx(
        (2 / math.log2(3)) / 2
    )
    assert metrics.ndcg_at_k(["a"], {"a": 0}) is None


def test_ndcg_cut_at_k() -> None:
    grades = {"a": 2, "b": 2}
    assert metrics.ndcg_at_k(["x", "a", "b"], grades, k=1) == 0.0


def test_coverage_recall() -> None:
    tickers = {"a": "AAPL", "b": "TSLA", "c": "JPM"}
    relevant = {"a", "b", "c"}
    value = metrics.coverage_recall(
        ["a", "b", "x"], relevant, tickers, ["AAPL", "TSLA", "JPM"]
    )
    assert value == pytest.approx(2 / 3)
    assert metrics.coverage_recall(["a"], relevant, tickers, ["AAPL"]) is None


def test_mean_skips_none() -> None:
    assert metrics.mean([1.0, None, 0.0]) == 0.5
    assert metrics.mean([None, None]) is None


def test_percentile() -> None:
    assert metrics.percentile([], 0.5) is None
    assert metrics.percentile([5.0], 0.95) == 5.0
    assert metrics.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert metrics.percentile([10.0, 0.0], 1.0) == 10.0


def test_question_metrics_names() -> None:
    values = metrics.question_metrics(
        ["a", "b"], {"a": 2}, {"a"}, {"a": "AAPL"}, ["AAPL"]
    )
    assert set(values) == {
        "recall_at_10",
        "recall_at_25",
        "recall_at_48",
        "mrr",
        "ndcg_at_10",
        "coverage_recall",
    }
    assert values["mrr"] == 1.0
    assert values["coverage_recall"] is None
