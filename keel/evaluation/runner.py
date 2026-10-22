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

A question in scope that the understanding step refuses or rejects as
input scores 0 on every variant. A question that expects a refusal and
fails an input check counts as a missed refusal: the input error is not
the out-of-scope response the golden set asks for.

With `answers` on, each question then goes through the answer pipeline
on the context of the hybrid run (1 model request), and the judge reads
the answer (`answers.py`, `judge.py`): the 8 answer gates of chapter 18.8
get their values. Without it the run makes no model request and those
gates stay pending.
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
import tempfile
import time
from typing import Any

from keel import answer
from keel import config
from keel import errors
from keel import indexer
from keel import retriever
from keel import understanding
from keel.evaluation import answers as answering
from keel.evaluation import gates
from keel.evaluation import golden
from keel.evaluation import judge as judging
from keel.evaluation import metrics
from keel.providers import base

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
        judge_model: The judge model, or empty when no judge ran.
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
    judge_model: str = ""


@dataclasses.dataclass(frozen=True)
class EvalRun:
    """The results of 1 run.

    Attributes:
        info: The run identity.
        variants: The variants that ran, the main one first.
        results: Every question result.
        stale_labels: Questions whose labels come from another index.
        seconds: The wall time of the run.
        answers: The answer results, empty without the answer step.
    """

    info: RunInfo
    variants: tuple[Variant, ...]
    results: tuple[QuestionResult, ...]
    stale_labels: tuple[str, ...] = ()
    seconds: float = 0.0
    answers: tuple[answering.AnswerResult, ...] = ()

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
            if r.variant == variant
            and r.outcome in {SCORED, WRONG_REFUSAL, INPUT_ERROR}
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

    def answer_values(self) -> dict[str, float | None]:
        """The answer metrics of chapter 18.4 and 18.6 over the run.

        Faithfulness and citation precision are means over the judged
        answers, and None when a judge request failed; coverage over the
        comparison and sector answers; numeric accuracy over the questions
        with gold values; schema validity over the answers with a model
        request; latency and cost over the questions with a model request.

        Returns:
            The values by gate key, plus the judge cost and latency p50;
            empty without the answer step.
        """
        rows = self.answers
        if not rows:
            return {}
        called = [r for r in rows if r.model_requests > 0]
        judged = [r.judge for r in rows if r.judge is not None]
        failures = sum(1 for j in judged if j.error)
        times = [r.latency_s for r in called if r.latency_s is not None]
        valid = [r.schema_valid for r in rows if r.schema_valid is not None]
        refusals = [
            r.refusal_correct for r in rows if r.refusal_correct is not None
        ]
        # A failed judge request leaves an answer unjudged; the 2 judge
        # gates stay pending rather than average over fewer answers.
        return {
            "faithfulness": None
            if failures
            else metrics.mean(j.faithfulness for j in judged),
            "citation_precision": None
            if failures
            else metrics.mean(j.citation_precision for j in judged),
            "judge_failures": float(failures),
            # The sample of the 2 judge gates (chapter 18.8 minimum).
            "judged_answers": float(
                sum(1 for j in judged if j.faithfulness is not None)
            ),
            "coverage_completeness": metrics.mean(
                r.coverage_complete for r in rows
            ),
            "numeric_accuracy": metrics.mean(r.numeric_correct for r in rows),
            "schema_validity": (sum(valid) / len(valid) if valid else None),
            "answer_refusal_correctness": (
                sum(refusals) / len(refusals) if refusals else None
            ),
            "latency_p95_s": metrics.percentile(times, 0.95),
            "latency_p50_s": metrics.percentile(times, 0.5),
            "mean_cost_usd": metrics.mean(r.cost_usd for r in called),
            "max_cost_usd": max((r.cost_usd for r in called), default=None),
            "judge_cost_usd": sum(j.cost_usd for j in judged),
        }

    def gate_values(self) -> dict[str, float | None]:
        """The values the gates read; the answer gates need the answer step.

        Refusal correctness takes the answer step's value when it ran (an
        out-of-scope response and no model request), else the value of the
        understanding step.

        Returns:
            The values by gate key.
        """
        main = self.summary(self.variants[0].name) if self.variants else {}
        values = {
            "recall_at_25": main.get("recall_at_25"),
            "mrr": main.get("mrr"),
            "refusal_correctness": self.refusal_correctness(),
        }
        found = self.answer_values()
        for gate in gates.GATES:
            if gate.key in found:
                values[gate.key] = found[gate.key]
        if found.get("answer_refusal_correctness") is not None:
            values["refusal_correctness"] = found["answer_refusal_correctness"]
        return values

    def gates(self) -> tuple[gates.GateResult, ...]:
        """Evaluate the 10 gates of chapter 18.8.

        The 2 judge gates carry the number of judged answers, so a run
        that judged fewer than `gates.MIN_JUDGED_ANSWERS` answers (the CI
        subset) reports them as pending instead of gating on a sample of 1.

        Returns:
            1 result per gate.
        """
        judged = self.answer_values().get("judged_answers")
        return gates.evaluate(
            self.gate_values(),
            judged=None if judged is None else int(judged),
        )


@dataclasses.dataclass(frozen=True)
class Harness:
    """What a run needs: the index, the understanding step, the variants.

    Attributes:
        conn: The read-only chunk store.
        understander: The understanding step over the index catalog.
        retrievers: 1 retriever per variant, the main one first.
        session: The answer pipeline on its event loop, or None without
            the answer step.
        replay: The retriever of the answer pipeline, or None.
        judge: The judge, or None.
    """

    conn: sqlite3.Connection
    understander: understanding.Understander
    retrievers: Mapping[Variant, retriever.Retriever]
    session: answering.AnswerSession | None = None
    replay: answering.ReplayRetriever | None = None
    judge: judging.Judge | None = None


@dataclasses.dataclass(frozen=True)
class AnswerSetup:
    """What the answer step needs besides the index.

    Attributes:
        provider: The answer provider, or None for the configured one.
        judge_client: The judge client, or None for `llm.judge_model`
            through the Anthropic API.
        judge: False to skip the judge (the code metrics still run).
    """

    provider: base.LLMProvider | None = None
    judge_client: judging.JudgeClient | None = None
    judge: bool = True


def _answer_parts(
    settings: config.Settings,
    base_step: retriever.Retriever,
    build: pathlib.Path,
    setup: AnswerSetup,
) -> tuple[
    answering.AnswerSession, answering.ReplayRetriever, judging.Judge | None
]:
    manifest = indexer.load_manifest(build)
    version = settings.llm.prompt_version
    if not answer.prompt_supported(
        version, manifest.compatible_prompt_versions
    ):
        raise errors.ConfigError(
            f"prompt version {version} is outside the index range "
            f"{manifest.compatible_prompt_versions}"
        )
    replay = answering.ReplayRetriever.from_retriever(base_step)
    # The eval answers never enter the demo answer cache (D-29), and no
    # cached answer stands in for a failed request of the run.
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="keel-eval-answers-"))
    answer_settings = settings.model_copy(
        update={"cache": config.CacheConfig(answers_dir=scratch)}
    )
    answerer = answer.Answerer(
        answer_settings,
        replay,
        setup.provider or answer.provider_from_settings(settings),
        manifest.index_version,
    )
    judge = None
    if setup.judge:
        prices = config.load_prices(settings.llm.prices)
        judge = judging.Judge(
            setup.judge_client
            or judging.AnthropicJudgeClient.from_settings(settings),
            judging.load_prompt(settings.llm.prompts_dir),
            prices.models.get(settings.llm.judge_model),
        )
    return answering.AnswerSession(answerer, scratch), replay, judge


def open_harness(
    settings: config.Settings,
    index_dir: pathlib.Path | None,
    variants: Sequence[Variant],
    answers: AnswerSetup | None = None,
) -> Harness:
    """Open the index and load the 2 models once for every variant.

    Args:
        settings: The loaded settings.
        index_dir: The index directory, or None for `index.dir`.
        variants: The variants, the main one first.
        answers: The answer step setup, or None without the answer step.

    Returns:
        The harness.

    Raises:
        IndexMissingError: No published index.
        ConfigError: The prompt version is outside the index range.
        ProviderRequestError: The answer step needs `ANTHROPIC_API_KEY`.
    """
    base_step = retriever.Retriever.open(settings, index_dir)
    retrievers = {
        v: retriever.Retriever(
            base_step.conn,
            base_step.vectors,
            base_step.embedder,
            base_step.reranker if v.rerank else None,
            settings,
            degraded=base_step.degraded,
            mode=v.mode,
        )
        for v in variants
    }
    harness = Harness(
        conn=base_step.conn,
        understander=understanding.Understander.from_settings(
            settings, base_step.catalog
        ),
        retrievers=retrievers,
    )
    if answers is None:
        return harness
    build = indexer.current_build(index_dir or settings.index.dir)
    if build is None:
        raise errors.IndexMissingError("no index build to answer from")
    session, replay, judge = _answer_parts(settings, base_step, build, answers)
    return dataclasses.replace(
        harness,
        session=session,
        replay=replay,
        judge=judge,
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


@dataclasses.dataclass(frozen=True)
class _Outcome:
    """The retrieval rows of 1 question and what the answer step needs."""

    rows: list[QuestionResult]
    analysis: understanding.QuestionAnalysis | None = None
    main: retriever.RetrievalResult | None = None


def _run_question(
    question: golden.GoldenQuestion,
    labels: golden.QuestionLabels | None,
    harness: Harness,
) -> _Outcome:
    if question.answer_only:
        return _Outcome(
            [QuestionResult(question.id, question.type, "", ANSWER_ONLY)]
        )
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
        return _Outcome(
            [QuestionResult(question.id, question.type, "", outcome, detail)],
            analysis,
        )
    judged = golden.judgments(question, labels, harness.conn)
    results = []
    main: retriever.RetrievalResult | None = None
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
        main = main or result
        results.append(
            _score(question, judged, variant, result, outcome=SCORED)
        )
    return _Outcome(results, analysis, main)


@dataclasses.dataclass(frozen=True)
class _Answered:
    """The answer record of 1 question and what scoring it needs."""

    question: golden.GoldenQuestion
    record: dict[str, Any]
    planted: str | None = None
    judged: judging.JudgeResult | None = None
    retrieval_ms: float = 0.0


def _answer(
    question: golden.GoldenQuestion,
    outcome: _Outcome,
    harness: Harness,
) -> _Answered:
    """Answer 1 question on the hybrid context, then judge the answer."""
    session, replay = harness.session, harness.replay
    if session is None or replay is None:
        return _Answered(question, {})
    planted: str | None = None
    if question.answer_only:
        analysis = harness.understander.analyze(question.question)
        result = answering.plant(replay.retrieve(analysis))
        retrieval_ms = result.timings.total_ms
        first = (
            result.context.chunks[0].candidate
            if result.context.chunks
            else None
        )
        if first is not None:
            planted = answering.planted_chunk_id(first.filing_id, first.section)
        replay.prepared = result
    else:
        replay.prepared = outcome.main
        retrieval_ms = outcome.main.timings.total_ms if outcome.main else 0.0
    record = session.ask(question.question)
    replay.prepared = None
    judged = None
    item = judging.judge_input(record) if harness.judge else None
    if harness.judge is not None and item is not None:
        # The judge reads each cited chunk as the answer model read it: the
        # rendered context element, else the fact line, else the store text.
        texts = judging.chunk_texts(harness.conn, item.chunk_ids)
        if planted is not None:
            texts[planted] = answering.PLANTED_TEXT
        for source in (session.facts, session.chunks):
            texts.update((i, source[i]) for i in item.chunk_ids if i in source)
        judged = harness.judge.judge(item, texts)
    return _Answered(question, record, planted, judged, retrieval_ms)


def run(
    questions: Sequence[golden.GoldenQuestion],
    labels: Mapping[str, golden.QuestionLabels],
    harness: Harness,
    *,
    progress: Callable[[str], None] | None = None,
    logs_dir: pathlib.Path | None = None,
) -> tuple[list[QuestionResult], list[answering.AnswerResult]]:
    """Run each question through understanding, every variant, the answer.

    Args:
        questions: The golden questions.
        labels: The labels by question ID.
        harness: The index, the understanding step, the retrievers, and
            the answer step when it is on.
        progress: Called with 1 line per question, or None.
        logs_dir: The audit log directory the answer step reads.

    Returns:
        The retrieval results in question and variant order, and the
        answer results in question order (empty without the answer step).
    """
    results: list[QuestionResult] = []
    answered: list[_Answered] = []
    for question in questions:
        started = time.perf_counter()
        outcome = _run_question(question, labels.get(question.id), harness)
        results += outcome.rows
        line = ""
        if harness.session is not None:
            done = _answer(question, outcome, harness)
            answered.append(done)
            line = "; answer " + str(done.record.get("outcome", "none"))
            faithfulness = done.judged.faithfulness if done.judged else None
            if faithfulness is not None:
                line += f", faithfulness {faithfulness:.2f}"
        if progress is not None:
            main = outcome.rows[0]
            recall = main.metrics.get("recall_at_25")
            shown = "n/a" if recall is None else f"{recall:.2f}"
            progress(
                f"{question.id} {main.outcome} recall@25 {shown}{line} "
                f"({time.perf_counter() - started:.1f} s)"
            )
    if not answered or logs_dir is None:
        return results, []
    audit_records = answering.read_audit(
        logs_dir, [str(a.record.get("request_id", "")) for a in answered]
    )
    scored = [
        answering.score(
            a.question,
            a.record,
            audit_records.get(str(a.record.get("request_id", ""))),
            a.judged,
            planted=a.planted,
            retrieval_ms=a.retrieval_ms,
        )
        for a in answered
    ]
    return results, scored


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
    answers: AnswerSetup | None = None,
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
        answers: The answer step setup, or None for retrieval only (no
            model request).

    Returns:
        The run and the questions it ran.

    Raises:
        GoldenSetError: The golden set or a label file is not valid.
        IndexMissingError: No published index.
        ConfigError: The prompt version is outside the index range.
        ProviderRequestError: The answer step needs `ANTHROPIC_API_KEY`.
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
    harness = open_harness(settings, directory, variants, answers)
    if harness.judge is not None:
        info = dataclasses.replace(info, judge_model=settings.llm.judge_model)
    try:
        results, answered = run(
            questions,
            labels,
            harness,
            progress=progress,
            logs_dir=settings.logs.dir,
        )
    finally:
        harness.conn.close()
        if harness.session is not None:
            harness.session.close()
    return (
        EvalRun(
            info=info,
            variants=tuple(variants),
            results=tuple(results),
            stale_labels=stale_labels(labels, info.chunks_sha256),
            seconds=time.perf_counter() - started,
            answers=tuple(answered),
        ),
        questions,
    )
