"""The retrieval metrics of chapter 18.3, as pure functions.

Each function takes the ranked chunk IDs of 1 question (the context, best
first) and its judgments. A metric is None when it does not apply, such as
a recall without any relevant chunk; the means skip those values.

Recall at k divides by min(k, R) for R relevant chunks (the capped recall
of the IR literature). A section-level label holds every chunk of a
section, often more than k, so the plain share R would cap recall at 25
far below 1 even for a perfect context.
"""

from __future__ import annotations

from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
import math

RECALL_KS = (10, 25, 48)
MRR_DEPTH = 48
NDCG_DEPTH = 10


def recall_at_k(
    ranked: Sequence[str], relevant: Collection[str], k: int
) -> float | None:
    """The capped share of relevant chunks in the top k.

    Args:
        ranked: The chunk IDs, best first.
        relevant: The relevant chunk IDs.
        k: The cut.

    Returns:
        Hits in the top k divided by min(k, R), or None when R is 0.
    """
    if not relevant or k <= 0:
        return None
    hits = sum(1 for chunk_id in ranked[:k] if chunk_id in relevant)
    return hits / min(k, len(relevant))


def reciprocal_rank(
    ranked: Sequence[str], relevant: Collection[str], depth: int = MRR_DEPTH
) -> float | None:
    """1 divided by the rank of the first relevant chunk.

    Args:
        ranked: The chunk IDs, best first.
        relevant: The relevant chunk IDs.
        depth: The deepest rank that counts.

    Returns:
        The reciprocal rank, 0.0 when no relevant chunk is in the top
        `depth`, or None when there is no relevant chunk at all.
    """
    if not relevant:
        return None
    for rank, chunk_id in enumerate(ranked[:depth], start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def _dcg(gains: Iterable[float]) -> float:
    return sum(g / math.log2(rank + 1) for rank, g in enumerate(gains, 1))


def ndcg_at_k(
    ranked: Sequence[str], grades: Mapping[str, int], k: int = NDCG_DEPTH
) -> float | None:
    """The normalized discounted cumulative gain of the grades at k.

    The gain of a chunk is its grade (2, 1, or 0; an unjudged chunk is 0),
    discounted by log2 of its rank plus 1. The ideal ranking sorts every
    judged grade, best first.

    Args:
        ranked: The chunk IDs, best first.
        grades: The grade per chunk ID.
        k: The cut.

    Returns:
        DCG at k divided by the ideal DCG at k, or None without a positive
        grade.
    """
    ideal = _dcg(
        sorted((g for g in grades.values() if g > 0), reverse=True)[:k]
    )
    if ideal <= 0:
        return None
    return _dcg(grades.get(c, 0) for c in ranked[:k]) / ideal


def coverage_recall(
    ranked: Sequence[str],
    relevant: Collection[str],
    tickers: Mapping[str, str],
    expected: Sequence[str],
) -> float | None:
    """The share of expected companies with a relevant chunk in context.

    Args:
        ranked: The chunk IDs of the context.
        relevant: The relevant chunk IDs.
        tickers: The ticker of each relevant chunk.
        expected: The expected companies.

    Returns:
        The share, or None for a question with fewer than 2 companies.
    """
    if len(expected) < 2:
        return None
    covered = {tickers.get(c) for c in ranked if c in relevant}
    return sum(1 for t in expected if t in covered) / len(expected)


def mean(values: Iterable[float | None]) -> float | None:
    """The mean of the values that are not None.

    Args:
        values: The values.

    Returns:
        The mean, or None when every value is None.
    """
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def percentile(values: Sequence[float], share: float) -> float | None:
    """The percentile by linear interpolation between the closest ranks.

    Args:
        values: The values.
        share: The percentile as a share, such as 0.95.

    Returns:
        The value, or None for no values.
    """
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * min(1.0, max(0.0, share))
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def question_metrics(
    ranked: Sequence[str],
    grades: Mapping[str, int],
    relevant: Collection[str],
    tickers: Mapping[str, str],
    expected: Sequence[str],
) -> dict[str, float | None]:
    """Every retrieval metric of 1 question.

    Args:
        ranked: The chunk IDs of the context, best first.
        grades: The grade per chunk ID.
        relevant: The relevant chunk IDs.
        tickers: The ticker of each judged chunk.
        expected: The expected companies.

    Returns:
        The metrics by name: `recall_at_10`, `recall_at_25`,
        `recall_at_48`, `mrr`, `ndcg_at_10`, and `coverage_recall`.
    """
    values: dict[str, float | None] = {
        f"recall_at_{k}": recall_at_k(ranked, relevant, k) for k in RECALL_KS
    }
    values["mrr"] = reciprocal_rank(ranked, relevant)
    values["ndcg_at_10"] = ndcg_at_k(ranked, grades)
    values["coverage_recall"] = coverage_recall(
        ranked, relevant, tickers, expected
    )
    return values
