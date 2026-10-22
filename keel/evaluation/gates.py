"""The 10 regression gates of chapter 18.8.

A gate passes, fails, or is pending: a pending gate has no measured value
yet (the answer gates until the answer path of stage 7 joins the harness),
or its value rests on too few judged answers. The 2 judge gates
(faithfulness and citation precision) are means over the judged answers, so
they gate only when the run judged at least `MIN_JUDGED_ANSWERS` answers;
below that the value is reported with its sample size and the gate stays
pending (the minimum sample rule). The CI subset on the mini corpus judges
1 answer, whose faithfulness swings around the threshold from run to run;
the full golden set judges 24 and gates as before. `keel eval --gate` exits
1 when any gate fails; a pending gate never blocks on its own, and the
report lists it.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
from typing import Final
from typing import Literal

PASSED: Final = "pass"
FAILED: Final = "fail"
PENDING: Final = "pending"
Status = Literal["pass", "fail", "pending"]
MIN_JUDGED_ANSWERS: Final = 5
SAMPLED_GATES: Final = frozenset({"faithfulness", "citation_precision"})


@dataclasses.dataclass(frozen=True)
class Gate:
    """1 regression gate.

    Attributes:
        key: The metric key in the run values.
        name: The name of the chapter table.
        threshold: The threshold.
        at_most: True when the value must be at most the threshold (latency
            and cost), False for at least.
        unit: The unit for the report, such as `s` or `USD`.
    """

    key: str
    name: str
    threshold: float
    at_most: bool = False
    unit: str = ""

    @property
    def rule(self) -> str:
        """The threshold as the report prints it, such as `>= 0.85`."""
        sign = "<=" if self.at_most else ">="
        unit = f" {self.unit}" if self.unit else ""
        return f"{sign} {self.threshold:.2f}{unit}"

    def check(self, value: float | None) -> Status:
        """Compare a value with the threshold.

        Args:
            value: The measured value, or None when not measured.

        Returns:
            `pass`, `fail`, or `pending`.
        """
        if value is None:
            return PENDING
        if self.at_most:
            return PASSED if value <= self.threshold else FAILED
        return PASSED if value >= self.threshold else FAILED


GATES = (
    Gate("recall_at_25", "Recall at 25", 0.85),
    Gate("mrr", "MRR", 0.60),
    Gate("faithfulness", "Faithfulness", 0.90),
    Gate("citation_precision", "Citation precision", 0.90),
    Gate(
        "coverage_completeness",
        "Coverage completeness on comparison and sector questions",
        1.00,
    ),
    Gate("numeric_accuracy", "Numeric accuracy", 0.90),
    Gate("schema_validity", "Schema validity", 1.00),
    Gate("refusal_correctness", "Refusal correctness", 1.00),
    Gate("latency_p95_s", "Latency p95", 40.0, at_most=True, unit="s"),
    Gate(
        "mean_cost_usd",
        "Mean cost per question",
        0.25,
        at_most=True,
        unit="USD",
    ),
)


@dataclasses.dataclass(frozen=True)
class GateResult:
    """The outcome of 1 gate.

    Attributes:
        gate: The gate.
        value: The measured value, or None.
        status: `pass`, `fail`, or `pending`.
        sample: The number of judged answers behind the value, for the
            sampled gates; None for the other gates.
    """

    gate: Gate
    value: float | None
    status: Status
    sample: int | None = None

    @property
    def undersampled(self) -> bool:
        """True when the gate is pending because of the minimum sample."""
        return (
            self.sample is not None
            and self.value is not None
            and self.status == PENDING
        )

    @property
    def status_text(self) -> str:
        """The status as the report prints it, such as `pending (n=1)`."""
        if self.undersampled:
            return f"{PENDING} (sample n={self.sample})"
        return self.status


def _check(gate: Gate, value: float | None, sample: int | None) -> GateResult:
    status = gate.check(value)
    if (
        gate.key in SAMPLED_GATES
        and sample is not None
        and sample < MIN_JUDGED_ANSWERS
        and value is not None
    ):
        status = PENDING
    return GateResult(gate, value, status, sample)


def evaluate(
    values: Mapping[str, float | None],
    gates: Sequence[Gate] = GATES,
    judged: int | None = None,
) -> tuple[GateResult, ...]:
    """Check every gate against the run values.

    Args:
        values: The run values by metric key; an absent key is pending.
        gates: The gates.
        judged: The number of judged answers behind the sampled gates, or
            None when the sample is not known (no minimum applies). Below
            `MIN_JUDGED_ANSWERS` the sampled gates stay pending.

    Returns:
        1 result per gate, in gate order.
    """
    return tuple(
        _check(g, values.get(g.key), judged if g.key in SAMPLED_GATES else None)
        for g in gates
    )


def blocked(results: Sequence[GateResult]) -> bool:
    """Tell whether a release stays blocked (any gate failed).

    Args:
        results: The gate results.

    Returns:
        True when at least 1 gate failed.
    """
    return any(r.status == FAILED for r in results)
