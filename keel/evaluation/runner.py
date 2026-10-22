"""Run the golden set through question understanding and retrieval.

Each question runs the understanding step once. An out-of-scope analysis
ends the question there: no retrieval and no model call (chapter 10.6). A
question in scope runs the retriever once per variant: the hybrid pipeline
of chapter 11, and for the ablation of chapter 18.7 lexical only, dense
only, and each of the 3 without the reranker. The models load once and the
variants share them.

The metrics read the context of each variant ranked by its final score
(the reranked chunks first, then the weighted fused score). The context
order of chapter 11.6 step 8 groups the chunks by company and period for
the prompt, so a cut at rank k of that order would measure the company
order instead of the ranking.

The answer metrics of chapter 18.4 (judge, citations, numbers, schema,
latency, cost) need the answer path of stage 7; they join this module as
another step per question, and the gates of `gates.py` already list them.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import datetime
import logging
import pathlib
import sqlite3
import time

from keel import config
from keel import errors
from keel import indexer
from keel import retriever
from keel import understanding
from keel.evaluation import gates
from keel.evaluation import golden
from keel.evaluation import metrics

logger = logging.getLogger(__name__)

SCORED = "scored"
REFUSED = "refused"
MISSED_REFUSAL = "missed_refusal"
WRONG_REFUSAL = "wrong_refusal"
INPUT_ERROR = "input_error"
ANSWER_ONLY = "answer_only"
TOP_SHOWN = 5


@dataclasses.dataclass(frozen=True)
class Variant:
    """1 retrieval configuration of the ablation.

    Attributes:
        name: The name in the report, such as `hybrid`.
        mode: `hybrid`, `lexical`, or `dense`.
        rerank: True to run the cross-encoder.
    """

    name: str
    mode: str
    rerank: bool = True


MAIN = Variant("hybrid", retriever.HYBRID)
ABLATION = (
    MAIN,
    Variant("lexical", retriever.LEXICAL),
    Variant("dense", retriever.DENSE),
    Variant("hybrid, no reranker", retriever.HYBRID, rerank=False),
    Variant("lexical, no reranker", retriever.LEXICAL, rerank=False),
    Variant("dense, no reranker", retriever.DENSE, rerank=False),
)


@dataclasses.dataclass(frozen=True)
class QuestionResult:  # pylint: disable=too-many-instance-attributes
    """The outcome of 1 question under 1 variant.

    Attributes:
        question_id: The question ID.
        type: The question type of the golden set.
        variant: The variant name; empty when no retrieval ran.
        outcome: `scored`, `refused`, `missed_refusal`, `wrong_refusal`,
            `input_error`, or `answer_only`.
        detail: The out-of-scope reason, the error, or the label note.
        label_level: `chunk` or `section`, or empty without metrics.
        metrics: The metrics by name.
        chunks: The chunks in the context.
        relevant: The relevant chunks the labels know.
        retrieval_ms: The retrieval time.
        top: The first chunk IDs of the ranking.
        sections: The context chunks per section.
    """

    question_id: str
    type: str
    variant: str
    outcome: str
    detail: str = ""
    label_level: str = ""
    metrics: Mapping[str, float | None] = dataclasses.field(
        default_factory=dict
    )
    chunks: int = 0
    relevant: int = 0
    retrieval_ms: float = 0.0
    top: tuple[str, ...] = ()
    sections: Mapping[str, int] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class RunInfo:
    """The identity of 1 eval run (chapter 18.9).

    Attributes:
        run_id: The run ID, such as `eval-20261021T120000Z`.
        started_at: The UTC start time.
        golden_version: The golden set version.
        index_version: The index version.
        build_id: The index build.
        chunks_sha256: The chunk digest of the index.
        prompt_version: The answer prompt version of the config.
        model: The answer model of the config.
        subset: The subset, or empty for all.
    """

    run_id: str
    started_at: str
    golden_version: str
    index_version: str
    build_id: str
    chunks_sha256: str
    prompt_version: str
    model: str
    subset: str = ""


@dataclasses.dataclass(frozen=True)
class EvalRun:
    """The results of 1 run.

    Attributes:
        info: The run identity.
        variants: The variants that ran, the main one first.
        results: Every question result.
        stale_labels: Questions whose labels come from another index.
        seconds: The wall time of the run.
    """

    info: RunInfo
    variants: tuple[Variant, ...]
    results: tuple[QuestionResult, ...]
    stale_labels: tuple[str, ...] = ()
    seconds: float = 0.0

    def scored(self, variant: str) -> list[QuestionResult]:
        """The results with retrieval metrics of 1 variant.

        Args:
            variant: The variant name.

        Returns:
            The results, in question order.
        """
        return [
            r
            for r in self.results
            if r.variant == variant and r.outcome in {SCORED, WRONG_REFUSAL}
        ]

    def summary(
        self, variant: str, kind: str | None = None
    ) -> dict[str, float | None]:
        """The mean of each metric over the scored questions.

        Args:
            variant: The variant name.
            kind: A question type, or None for every type.

        Returns:
            The means by metric name, plus `retrieval_ms_p50` and
            `retrieval_ms_p95`.
        """
        rows = [r for r in self.scored(variant) if kind in {None, r.type}]
        names = [*(f"recall_at_{k}" for k in metrics.RECALL_KS), "mrr"]
        names += ["ndcg_at_10", "coverage_recall"]
        values = {
            n: metrics.mean(r.metrics.get(n) for r in rows) for n in names
        }
        times = [r.retrieval_ms for r in rows if r.outcome == SCORED]
        values["retrieval_ms_p50"] = metrics.percentile(times, 0.5)
        values["retrieval_ms_p95"] = metrics.percentile(times, 0.95)
        return values

    def refusals(self) -> list[QuestionResult]:
        """The results of the questions that expect a refusal."""
        return [
            r for r in self.results if r.outcome in {REFUSED, MISSED_REFUSAL}
        ]

    def refusal_correctness(self) -> float | None:
        """The share of expected refusals the understanding step made.

        Returns:
            The share, or None without such a question.
        """
        rows = self.refusals()
        if not rows:
            return None
        return sum(1 for r in rows if r.outcome == REFUSED) / len(rows)

    def gate_values(self) -> dict[str, float | None]:
        """The values the gates read; the answer metrics stay pending.

        Returns:
            The values by gate key.
        """
        main = self.summary(self.variants[0].name) if self.variants else {}
        return {
            "recall_at_25": main.get("recall_at_25"),
            "mrr": main.get("mrr"),
            "refusal_correctness": self.refusal_correctness(),
        }

    def gates(self) -> tuple[gates.GateResult, ...]:
        """Evaluate the 10 gates of chapter 18.8.

        Returns:
            1 result per gate.
        """
        return gates.evaluate(self.gate_values())


@dataclasses.dataclass(frozen=True)
class Harness:
    """What a run needs: the index, the understanding step, the variants.

    Attributes:
        conn: The read-only chunk store.
        understander: The understanding step over the index catalog.
        retrievers: 1 retriever per variant, the main one first.
    """

    conn: sqlite3.Connection
    understander: understanding.Understander
    retrievers: Mapping[Variant, retriever.Retriever]


def open_harness(
    settings: config.Settings,
    index_dir: pathlib.Path | None,
    variants: Sequence[Variant],
) -> Harness:
    """Open the index and load the 2 models once for every variant.

    Args:
        settings: The loaded settings.
        index_dir: The index directory, or None for `index.dir`.
        variants: The variants, the main one first.

    Returns:
        The harness.

    Raises:
        IndexMissingError: No published index.
    """
    base = retriever.Retriever.open(settings, index_dir)
    retrievers = {
        v: retriever.Retriever(
            base.conn,
            base.vectors,
            base.embedder,
            base.reranker if v.rerank else None,
            settings,
            degraded=base.degraded,
            mode=v.mode,
        )
        for v in variants
    }
    return Harness(
        conn=base.conn,
        understander=understanding.Understander.from_settings(
            settings, base.catalog
        ),
        retrievers=retrievers,
    )


def run_info(
    settings: config.Settings,
    golden_set: golden.GoldenSet,
    build_dir: pathlib.Path,
    subset: str | None,
    now: datetime.datetime | None = None,
) -> RunInfo:
    """Name a run and record what it ran against.

    Args:
        settings: The loaded settings.
        golden_set: The golden set.
        build_dir: The index build directory.
        subset: The subset, or None.
        now: The start time, or None for the clock.

    Returns:
        The run identity.
    """
    started = now or datetime.datetime.now(datetime.UTC)
    manifest = indexer.load_manifest(build_dir)
    return RunInfo(
        run_id="eval-" + started.strftime("%Y%m%dT%H%M%SZ"),
        started_at=started.isoformat(timespec="seconds"),
        golden_version=golden_set.version,
        index_version=manifest.index_version,
        build_id=manifest.build.build_id,
        chunks_sha256=manifest.chunks_sha256,
        prompt_version=settings.llm.prompt_version,
        model=settings.llm.model,
        subset=subset or "",
    )


def _score(
    question: golden.GoldenQuestion,
    judged: golden.Judgments,
    variant: Variant,
    result: retriever.RetrievalResult | None,
    *,
    outcome: str,
    detail: str = "",
) -> QuestionResult:
    ranked: list[str] = []
    elapsed = 0.0
    sections: dict[str, int] = {}
    if result is not None:
        sections = result.context.sections()
        chunks = sorted(
            (c.candidate for c in result.context.chunks),
            key=lambda c: c.rank_key,
        )
        ranked = [c.chunk_id for c in chunks]
        elapsed = result.timings.total_ms
    return QuestionResult(
        question_id=question.id,
        type=question.type,
        variant=variant.name,
        outcome=outcome,
        detail=detail or judged.note,
        label_level=judged.level,
        metrics=metrics.question_metrics(
            ranked,
            judged.grades,
            judged.relevant,
            judged.tickers,
            question.tickers,
        ),
        chunks=len(ranked),
        relevant=len(judged.relevant),
        retrieval_ms=elapsed,
        top=tuple(ranked[:TOP_SHOWN]),
        sections=sections,
    )


def _run_question(
    question: golden.GoldenQuestion,
    labels: golden.QuestionLabels | None,
    harness: Harness,
) -> list[QuestionResult]:
    if question.answer_only:
        return [QuestionResult(question.id, question.type, "", ANSWER_ONLY)]
    analysis: understanding.QuestionAnalysis | None = None
    try:
        analysis = harness.understander.analyze(question.question)
        detail = analysis.out_of_scope_reason or ""
    except errors.QuestionInputError as error:
        detail = f"{type(error).__name__}: {error}"
    refused = analysis is None or analysis.out_of_scope
    if question.expect_out_of_scope:
        outcome = (
            REFUSED if analysis is not None and refused else MISSED_REFUSAL
        )
        return [QuestionResult(question.id, question.type, "", outcome, detail)]
    judged = golden.judgments(question, labels, harness.conn)
    results = []
    for variant, step in harness.retrievers.items():
        if analysis is None or refused:
            outcome = INPUT_ERROR if analysis is None else WRONG_REFUSAL
            results.append(
                _score(
                    question,
                    judged,
                    variant,
                    None,
                    outcome=outcome,
                    detail=detail,
                )
            )
            continue
        result = step.retrieve(analysis)
        results.append(
            _score(question, judged, variant, result, outcome=SCORED)
        )
    return results


def run(
    questions: Sequence[golden.GoldenQuestion],
    labels: Mapping[str, golden.QuestionLabels],
    harness: Harness,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[QuestionResult]:
    """Run each question through understanding and every variant.

    Args:
        questions: The golden questions.
        labels: The labels by question ID.
        harness: The index, the understanding step, and the retrievers.
        progress: Called with 1 line per question, or None.

    Returns:
        The results, in question order and then variant order.
    """
    results: list[QuestionResult] = []
    for question in questions:
        started = time.perf_counter()
        rows = _run_question(question, labels.get(question.id), harness)
        results += rows
        if progress is not None:
            main = rows[0]
            recall = main.metrics.get("recall_at_25")
            shown = "n/a" if recall is None else f"{recall:.2f}"
            progress(
                f"{question.id} {main.outcome} recall@25 {shown} "
                f"({time.perf_counter() - started:.1f} s)"
            )
    return results


def stale_labels(
    labels: Mapping[str, golden.QuestionLabels], chunks_sha256: str
) -> tuple[str, ...]:
    """List the questions whose labels come from another index.

    Args:
        labels: The labels by question ID.
        chunks_sha256: The chunk digest of the open index.

    Returns:
        The question IDs, sorted.
    """
    return tuple(
        sorted(
            q
            for q, label in labels.items()
            if label.chunks_sha256 != chunks_sha256
        )
    )


def evaluate(  # pylint: disable=too-many-arguments
    settings: config.Settings,
    golden_path: pathlib.Path,
    labels_dir: pathlib.Path,
    *,
    subset: str | None = None,
    index_dir: pathlib.Path | None = None,
    variants: Sequence[Variant] = ABLATION,
    progress: Callable[[str], None] | None = None,
) -> tuple[EvalRun, tuple[golden.GoldenQuestion, ...]]:
    """Run the golden set end to end (the body of `keel eval`).

    Args:
        settings: The loaded settings.
        golden_path: The golden set file.
        labels_dir: The labels directory.
        subset: A subset tag or a comma list of IDs, or None for all.
        index_dir: The index directory, or None for `index.dir`.
        variants: The variants, the main one first.
        progress: Called with 1 line per question, or None.

    Returns:
        The run and the questions it ran.

    Raises:
        GoldenSetError: The golden set or a label file is not valid.
        IndexMissingError: No published index.
    """
    started = time.perf_counter()
    golden_set = golden.load_golden(golden_path)
    questions = golden_set.select(subset)
    labels = golden.load_labels(labels_dir, [q.id for q in questions])
    directory = index_dir or settings.index.dir
    build = indexer.current_build(directory)
    if build is None:
        raise errors.IndexMissingError(
            f"no index at {directory}/current; run keel index"
        )
    info = run_info(settings, golden_set, build, subset)
    harness = open_harness(settings, directory, variants)
    try:
        results = run(questions, labels, harness, progress=progress)
    finally:
        harness.conn.close()
    return (
        EvalRun(
            info=info,
            variants=tuple(variants),
            results=tuple(results),
            stale_labels=stale_labels(labels, info.chunks_sha256),
            seconds=time.perf_counter() - started,
        ),
        questions,
    )
