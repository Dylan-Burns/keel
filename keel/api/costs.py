"""The cost preview of the admin jobs that call the model.

`keel eval --answers` makes 1 answer request and 1 judge request per
golden question, and `keel warm-cache` 1 answer request per demo question
that the answer cache does not hold yet. The preview counts those
requests and prices them before an admin starts the job.

The price of 1 answer is measured: the mean `cost_usd` of the answered
records of the configured model in the audit log (the newest 200). With
no such record yet, the estimate prices the measured token counts of
stage 15 (about 33,000 input and 2,800 output tokens per answer) with
`config/prices.yaml`. The judge has no audit record, so its estimate
always prices the measured judge tokens (about 11,000 input and 2,000
output tokens per answer, stage 10) with the judge model's prices.
"""

from __future__ import annotations

from collections.abc import Callable
import pathlib

import pydantic

from keel import cache
from keel import config
from keel import errors
from keel import warm_cache
from keel.api import history as history_log
from keel.evaluation import golden

ANSWER_INPUT_TOKENS = 33_000
ANSWER_OUTPUT_TOKENS = 2_800
JUDGE_INPUT_TOKENS = 11_000
JUDGE_OUTPUT_TOKENS = 2_000
AUDIT_SAMPLE = 200
MILLION = 1_000_000

KeyOf = Callable[[str], str]


class CostEstimate(pydantic.BaseModel):
    """The estimate of a job that calls the model.

    Attributes:
        kind: `eval` or `warm_cache`.
        questions: The questions the job reads.
        model_requests: The answer requests the job makes.
        judge_requests: The judge requests the job makes.
        answer_usd: The estimated USD of 1 answer.
        judge_usd: The estimated USD of 1 judge request.
        usd: The estimated USD of the job.
        basis: `audit` when the answer price comes from the audit log,
            `prices` when it comes from `config/prices.yaml`.
        confirm: The `confirm` value the job needs: `cost` for an eval
            with answers and for a warm-cache run that may answer, else
            None.
    """

    kind: str
    questions: int
    model_requests: int
    judge_requests: int
    answer_usd: float
    judge_usd: float
    usd: float
    basis: str
    confirm: str | None


COST_CONFIRM = "cost"


def _priced(
    prices: config.Prices, model: str, tokens_in: int, tokens_out: int
) -> float:
    entry = prices.models.get(model)
    if entry is None:
        return 0.0
    return (tokens_in * entry.input + tokens_out * entry.output) / MILLION


def measured_answer_usd(logs_dir: pathlib.Path, model: str) -> float | None:
    """The mean cost of the newest answered records of a model.

    Args:
        logs_dir: The logs directory with the audit log.
        model: The model.

    Returns:
        The mean USD, or None when the audit log has no such record.
    """
    costs = [
        float(record["cost_usd"])
        for record in history_log.read_records(logs_dir)
        if record.get("outcome") == "answered"
        and record.get("model") == model
        and isinstance(record.get("cost_usd"), int | float)
        and record["cost_usd"] > 0
    ]
    sample = costs[-AUDIT_SAMPLE:]
    return sum(sample) / len(sample) if sample else None


def unit_costs(settings: config.Settings) -> tuple[float, float, str]:
    """The USD of 1 answer and 1 judge request, and the answer basis.

    Args:
        settings: The loaded settings.

    Returns:
        (answer USD, judge USD, `audit` or `prices`).

    Raises:
        ConfigError: The prices file is absent or invalid.
    """
    prices = config.load_prices(settings.llm.prices)
    judge = _priced(
        prices,
        settings.llm.judge_model,
        JUDGE_INPUT_TOKENS,
        JUDGE_OUTPUT_TOKENS,
    )
    measured = measured_answer_usd(settings.logs.dir, settings.llm.model)
    if measured is not None:
        return measured, judge, "audit"
    answer = _priced(
        prices, settings.llm.model, ANSWER_INPUT_TOKENS, ANSWER_OUTPUT_TOKENS
    )
    return answer, judge, "prices"


def _estimate(  # pylint: disable=too-many-arguments
    settings: config.Settings,
    kind: str,
    questions: int,
    requests: int,
    judged: int,
) -> CostEstimate:
    answer, judge, basis = unit_costs(settings)
    usd = requests * answer + judged * judge
    return CostEstimate(
        kind=kind,
        questions=questions,
        model_requests=requests,
        judge_requests=judged,
        answer_usd=round(answer, 4),
        judge_usd=round(judge, 4),
        usd=round(usd, 2),
        basis=basis,
        confirm=COST_CONFIRM if requests or judged else None,
    )


def eval_estimate(
    settings: config.Settings,
    golden_path: pathlib.Path,
    *,
    answers: bool,
    judge: bool = True,
    subset: str | None = None,
) -> CostEstimate:
    """Estimate `keel eval` with or without the answers.

    Args:
        settings: The loaded settings.
        golden_path: The golden set file.
        answers: True when each question is answered (1 request each).
        judge: True when each answer is judged (1 more request each).
        subset: A subset tag or a comma list of IDs, or None for all.

    Returns:
        The estimate; 0 requests without the answers, and none for an
        out-of-scope question, which gets the refusal without a call.

    Raises:
        GoldenSetError: The golden set is not valid or the subset is
            empty.
        ConfigError: The prices file is absent or invalid.
    """
    chosen = golden.load_golden(golden_path).select(subset)
    # An out-of-scope question gets the refusal with no model request.
    asked = sum(1 for q in chosen if not q.expect_out_of_scope)
    requests = asked if answers else 0
    judged = requests if judge else 0
    return _estimate(settings, "eval", len(chosen), requests, judged)


def warm_cache_estimate(
    settings: config.Settings,
    answers: cache.AnswerCache | None,
    key_of: KeyOf | None,
    *,
    refresh: bool,
    facts_only: bool,
    golden_path: pathlib.Path = warm_cache.DEFAULT_GOLDEN,
) -> CostEstimate:
    """Estimate `keel warm-cache`: 1 request per question to answer.

    Args:
        settings: The loaded settings.
        answers: The answer cache, or None to count every question.
        key_of: The cache key of a question (the loaded pipeline), or
            None to count every question.
        refresh: Answer every question again.
        facts_only: Answer nothing.
        golden_path: The golden set file.

    Returns:
        The estimate.

    Raises:
        GoldenSetError: The golden set is not valid.
        ConfigError: The prices file is absent or invalid.
    """
    try:
        golden_set: golden.GoldenSet | None = golden.load_golden(golden_path)
    except errors.GoldenSetError:
        golden_set = None
    questions = warm_cache.demo_questions(
        settings.demo.example_questions, golden_set
    )
    if facts_only:
        requests = 0
    elif refresh or answers is None or key_of is None:
        requests = len(questions)
    else:
        requests = sum(
            1 for q in questions if answers.get(key_of(q.text)) is None
        )
    estimate = _estimate(settings, "warm_cache", len(questions), requests, 0)
    if not facts_only:
        # The cache can change before the job runs (a reload changes the
        # keys), so a job that may answer always needs the confirmation.
        estimate.confirm = COST_CONFIRM
    return estimate
