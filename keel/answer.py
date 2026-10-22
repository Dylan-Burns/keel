"""The question pipeline around the single call (chapter 6.3).

`Answerer.ask` runs 1 question: the answer cache when allowed, question
understanding, retrieval, the prompt, exactly 1 provider request (with up
to 2 retries before any content, decision D-04), the citation validator,
the answer cache write, and 1 audit record. It yields the events of
chapter 14.3 (`meta`, `analysis`, `retrieval`, `answer_delta`, `findings`,
`final`, `error`, `done`), which `keel ask` prints and the API of stage 9
streams. No other step calls a model (D-01, D-02, D-28).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
import dataclasses
import datetime
import logging
import operator
import pathlib
import random
import sqlite3
import time
from typing import Any
import uuid

from keel import audit
from keel import cache
from keel import citations
from keel import config
from keel import context
from keel import errors
from keel import indexer
from keel import partial_json
from keel import prompt
from keel import retriever
from keel import understanding
from keel.providers import anthropic as anthropic_provider
from keel.providers import base
from keel.providers import mock

logger = logging.getLogger(__name__)

SEC_HOST = "https://www.sec.gov/"
SCHEMA_WARNING = (
    "The model output did not match the answer schema, so the raw text is "
    "shown as an unstructured answer and no citation is verified."
)
OFFLINE_MESSAGE = (
    "Offline mode: this question is not in the answer cache, so only the "
    "retrieved filing text is shown."
)
CONNECT_DELAYS = (1.0, 3.0)
SERVER_DELAYS = (2.0, 6.0)
MAX_RETRY_WAIT = 30.0  # a longer Retry-After would pass the 120 s total

Sleep = Callable[[float], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class Event:
    """1 event of chapter 14.3.

    Attributes:
        name: The event name, such as `answer_delta`.
        data: The payload.
    """

    name: str
    data: dict[str, Any]


def backoff(error: errors.ProviderError, attempt: int) -> float:
    """The wait before retry `attempt` (0 for the first), chapter 16.1.

    Args:
        error: The failure.
        attempt: The index of the retry.

    Returns:
        Seconds: `Retry-After` when the provider sent it (at most 30), else
        2 then 6 seconds, or 1 then 3 seconds with jitter after a timeout.
    """
    if error.retry_after is not None:
        return min(error.retry_after, MAX_RETRY_WAIT)
    if isinstance(error, errors.ProviderTimeoutError):
        base_delay = CONNECT_DELAYS[min(attempt, len(CONNECT_DELAYS) - 1)]
        return base_delay + random.uniform(0, 0.5)  # noqa: S311
    return SERVER_DELAYS[min(attempt, len(SERVER_DELAYS) - 1)]


def provider_from_settings(
    settings: config.Settings, fault: str = "none"
) -> base.LLMProvider:
    """Build the configured provider.

    Args:
        settings: The loaded settings.
        fault: The mock fault; read only when `llm.provider` is `mock`.

    Returns:
        The provider.

    Raises:
        ConfigError: An unknown provider name.
        ProviderRequestError: The Anthropic key is not set.
    """
    if settings.llm.provider == "mock":
        return mock.MockProvider(settings.llm.model, fault=fault)
    if settings.llm.provider == "anthropic":
        return anthropic_provider.AnthropicProvider.from_settings(settings)
    raise errors.ConfigError(f"unknown llm.provider {settings.llm.provider!r}")


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.strip().split("."))


_COMPARISONS: tuple[
    tuple[str, Callable[[tuple[int, ...], tuple[int, ...]], bool]], ...
] = (
    (">=", operator.ge),
    ("<=", operator.le),
    ("==", operator.eq),
    (">", operator.gt),
    ("<", operator.lt),
)


def prompt_supported(prompt_version: str, compatible: str) -> bool:
    """Check a prompt version against the manifest range (chapter 17.12).

    Args:
        prompt_version: Such as `1.0.0`.
        compatible: Such as `>=1.0.0,<2.0.0`.

    Returns:
        True when every clause holds.
    """
    version = _version(prompt_version)
    for clause in filter(None, (c.strip() for c in compatible.split(","))):
        for symbol, check in _COMPARISONS:
            if clause.startswith(symbol):
                if not check(version, _version(clause[len(symbol) :])):
                    return False
                break
    return True


def sec_urls(
    conn: sqlite3.Connection, filing_ids: Sequence[str]
) -> dict[str, str | None]:
    """Read the trusted SEC URL of each filing (control S-05, E-D-28).

    Args:
        conn: The chunk store.
        filing_ids: The filings of the context.

    Returns:
        The URL per filing ID, or None when the header URL is not trusted.
    """
    wanted = sorted(set(filing_ids))
    if not wanted:
        return {}
    marks = ",".join("?" * len(wanted))
    rows = conn.execute(
        "SELECT filing_id, source_url, url_trusted FROM filings "  # noqa: S608
        f"WHERE filing_id IN ({marks})",
        wanted,
    ).fetchall()
    return {
        row[0]: row[1]
        if row[2] and row[1] and str(row[1]).startswith(SEC_HOST)
        else None
        for row in rows
    }


@dataclasses.dataclass
class _Run:  # pylint: disable=too-many-instance-attributes
    """A private accumulator of 1 question, never returned."""

    request_id: str
    question: str
    started: float
    analysis: understanding.QuestionAnalysis | None = None
    result: retriever.RetrievalResult | None = None
    bundle: prompt.PromptBundle | None = None
    stream: partial_json.AnswerStream = dataclasses.field(
        default_factory=partial_json.AnswerStream
    )
    raw_text: str = ""
    usage: base.UsageReport = dataclasses.field(
        default_factory=base.UsageReport
    )
    finished: base.Finished | None = None
    requests: int = 0
    content: bool = False
    error: errors.ProviderError | None = None
    understanding_ms: float = 0.0
    retrieval_ms: float = 0.0
    first_token_ms: float | None = None
    outcome: str = "answered"


class Answerer:  # pylint: disable=too-many-instance-attributes
    """The question pipeline over 1 index and 1 provider.

    Args:
        settings: The loaded settings.
        step: The opened retriever.
        provider: The model provider.
        index_version: The index version of the manifest.
        sleep: The wait between retries (tests pass a no-op).

    Raises:
        ConfigError: The prompt version asks for another output mode than
            `llm.output_mode`.
    """

    def __init__(
        self,
        settings: config.Settings,
        step: retriever.Retriever,
        provider: base.LLMProvider,
        index_version: str,
        *,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.retriever = step
        self.provider = provider
        self.index_version = index_version
        self.sleep = sleep
        self.files = prompt.PromptFiles.load(
            settings.llm.prompt_version, settings.llm.prompts_dir
        )
        if self.files.output_mode != settings.llm.output_mode:
            raise errors.ConfigError(
                f"prompt version {self.files.version} asks for the "
                f"{self.files.output_mode} output mode; llm.output_mode is "
                f"{settings.llm.output_mode}"
            )
        self.prices = config.load_prices(settings.llm.prices)
        self.understander = understanding.Understander.from_settings(
            settings, step.catalog
        )
        self.cache = cache.AnswerCache(settings.cache.answers_dir)
        self.audit = audit.AuditLog(settings.logs.dir)
        self.calibration = context.Calibration(
            settings.retrieval.calibration_factor
        )

    @classmethod
    def open(
        cls,
        settings: config.Settings,
        index_dir: pathlib.Path | None = None,
        provider: base.LLMProvider | None = None,
        *,
        load_models: bool = True,
    ) -> Answerer:
        """Open the current index, the models, and the provider.

        Args:
            settings: The loaded settings.
            index_dir: The index directory, or None for `index.dir`.
            provider: The provider, or None for the configured one.
            load_models: False skips the embedding model and the reranker.

        Returns:
            The pipeline.

        Raises:
            IndexMissingError: No published index.
            ConfigError: The prompt version is outside the range the index
                supports or does not match `llm.output_mode`, or the
                provider is unknown.
        """
        directory = index_dir or settings.index.dir
        build = indexer.current_build(directory)
        if build is None:
            raise errors.IndexMissingError(
                f"no index at {directory}/current; run keel index"
            )
        manifest = indexer.load_manifest(build)
        version = settings.llm.prompt_version
        if not prompt_supported(version, manifest.compatible_prompt_versions):
            raise errors.ConfigError(
                f"prompt version {version} is outside the index range "
                f"{manifest.compatible_prompt_versions}"
            )
        step = retriever.Retriever.open(
            settings, directory, load_models=load_models
        )
        return cls(
            settings,
            step,
            provider or provider_from_settings(settings),
            manifest.index_version,
        )

    @property
    def model(self) -> str:
        """The model of the provider."""
        return self.provider.model

    def cache_key(self, question: str) -> str:
        """The answer cache key of a question (decision D-29).

        Args:
            question: The question.

        Returns:
            The key.
        """
        return cache.cache_key(
            question, self.index_version, self.files.version, self.model
        )

    def _elapsed(self, run: _Run) -> float:
        return round((time.perf_counter() - run.started) * 1000, 1)

    async def ask(
        self,
        question: str,
        *,
        request_id: str | None = None,
        use_cache: bool = False,
    ) -> AsyncIterator[Event]:
        """Answer 1 question and yield the events of chapter 14.3.

        Args:
            question: The question.
            request_id: The request ID, or None for a new one.
            use_cache: Serve a cached answer when there is one. Offline
                mode always reads the cache and never calls the model.

        Yields:
            The events, ending with `done`.
        """
        run = _Run(
            request_id=request_id or uuid.uuid4().hex,
            question=question,
            started=time.perf_counter(),
        )
        yield Event(
            "meta",
            {
                "request_id": run.request_id,
                "index_version": self.index_version,
                "prompt_version": self.files.version,
                "model": self.model,
            },
        )
        offline = self.settings.offline
        if offline or use_cache:
            cached = self.cache.get(self.cache_key(question))
            if cached is not None:
                async for event in self._from_cache(run, cached):
                    yield event
                return
        async for event in self._pipeline(run, offline=offline):
            yield event

    async def _from_cache(
        self, run: _Run, cached: dict[str, Any]
    ) -> AsyncIterator[Event]:
        run.outcome = "cached"
        record = dict(cached)
        meta = dict(record.get("meta", {}))
        meta.update(
            from_cache=True,
            # Requests that failed before content still count (D-01 audit).
            model_requests=run.requests,
            cost_usd=0.0,
            latency_ms={"total": self._elapsed(run)},
        )
        record.update(request_id=run.request_id, meta=meta)
        yield Event("final", record)
        self._audit(run, record)
        yield Event("done", {})

    async def _pipeline(
        self, run: _Run, *, offline: bool
    ) -> AsyncIterator[Event]:
        try:
            run.analysis = self.understander.analyze(run.question)
        except errors.QuestionInputError as error:
            run.outcome = "rejected"
            yield Event(
                "error",
                {
                    "code": "invalid_question",
                    "message": str(error),
                    "http_status": error.http_status,
                },
            )
            self._audit(run, None)
            yield Event("done", {})
            return
        run.understanding_ms = self._elapsed(run)
        yield Event("analysis", _analysis_summary(run.analysis))
        if run.analysis.out_of_scope:
            run.outcome = "out_of_scope"
            yield self._final(run, None)
            yield Event("done", {})
            return
        budget = context.Budget(
            max_tokens=self.settings.retrieval.max_context_tokens,
            max_chunks=self.settings.retrieval.max_chunks,
            calibration_factor=self.calibration.factor,
        )
        retrieval_started = time.perf_counter()
        run.result = await asyncio.to_thread(
            self.retriever.retrieve, run.analysis, budget
        )
        run.retrieval_ms = round(
            (time.perf_counter() - retrieval_started) * 1000, 1
        )
        yield Event("retrieval", self._retrieval(run.result))
        if run.result.context.empty or offline:
            run.outcome = (
                "no_context" if run.result.context.empty else "offline"
            )
            yield self._final(run, None)
            yield Event("done", {})
            return
        run.bundle = prompt.build_bundle(
            self.files,
            run.analysis,
            run.result.context,
            self.retriever.catalog.filings,
        )
        async for event in self._call(run, run.bundle):
            yield event
        async for event in self._finish(run):
            yield event

    async def _call(
        self, run: _Run, bundle: prompt.PromptBundle
    ) -> AsyncIterator[Event]:
        """Send the request; retry only before the first content (D-04)."""
        attempts = self.settings.llm.max_retries + 1
        for attempt in range(attempts):
            run.requests += 1
            run.stream = partial_json.AnswerStream()
            run.raw_text = ""
            try:
                async for event in self.provider.answer(bundle):
                    for out in self._on_event(run, event):
                        yield out
                run.error = None
                return
            except errors.ProviderError as error:
                run.error = error
                last = attempt == attempts - 1
                if run.content or not error.retryable or last:
                    logger.warning(
                        "provider failed after %d request(s): %s",
                        run.requests,
                        error,
                    )
                    return
                delay = backoff(error, attempt)
                logger.warning(
                    "provider failed before content (%s); retry %d in %.1f s",
                    error,
                    attempt + 1,
                    delay,
                )
                await self.sleep(delay)

    def _on_event(self, run: _Run, event: base.ProviderEvent) -> list[Event]:
        if isinstance(event, base.JsonDelta):
            update = run.stream.feed(event.text)
            out = []
            if update.answer_delta:
                out.append(Event("answer_delta", {"text": update.answer_delta}))
            out.extend(Event("findings", f) for f in update.findings)
            if out and not run.content:
                # Any event to the client is content: no retry after it.
                run.content = True
                run.first_token_ms = self._elapsed(run)
            return out
        if isinstance(event, base.TextDelta):
            run.raw_text += event.text
        elif isinstance(event, base.UsageReport):
            run.usage = event
        else:
            run.finished = event
        return []

    async def _finish(self, run: _Run) -> AsyncIterator[Event]:
        if run.error is not None:
            run.outcome = "provider_error"
            yield Event(
                "error",
                {
                    "code": run.error.code,
                    "message": str(run.error),
                    "retry_after": run.error.retry_after,
                    "partial": run.stream.answer,
                },
            )
            cached = None
            if (
                not run.content
            ):  # chapter 16.12 step 3: the cache after a failure
                cached = self.cache.get(self.cache_key(run.question))
            if cached is not None:
                async for event in self._from_cache(run, cached):
                    yield event
                return
            yield self._final(run, None)
            yield Event("done", {})
            return
        validated = self._validate(run)
        record = self._final(run, validated)
        yield record
        # A mock answer never enters the cache of the real model's key.
        real = self.provider.name != mock.MockProvider.name
        if real and validated is not None and record.data["answer"]:
            self.cache.put(self.cache_key(run.question), record.data)
        yield Event("done", {})

    def _validate(self, run: _Run) -> citations.ValidatedAnswer | None:
        if run.result is None:
            return None
        text = run.stream.text
        finished = run.finished
        try:
            if finished is not None and not finished.tool_called:
                raise errors.SchemaViolationError("no answer in the response")
            answer = citations.parse_answer(text)
        except errors.SchemaViolationError as error:
            run.outcome = "schema_violation"
            logger.warning("schema_violation: %s", error)
            return None
        urls = sec_urls(
            self.retriever.conn,
            [c.candidate.filing_id for c in run.result.context.chunks],
        )
        return citations.validate(answer, run.result.context, urls)

    def _retrieval(self, result: retriever.RetrievalResult) -> dict[str, Any]:
        built = result.context
        urls = sec_urls(
            self.retriever.conn, [c.candidate.filing_id for c in built.chunks]
        )
        chunks = [
            {
                "chunk_id": c.candidate.chunk_id,
                "ticker": c.candidate.ticker,
                "form": c.candidate.form,
                "fiscal_label": c.candidate.fiscal_label,
                "period_end": c.candidate.period_end_date,
                "section": c.candidate.section,
                "score": round(c.candidate.score, 4),
                "filing_name": citations.filing_name(c.candidate),
                "sec_url": urls.get(c.candidate.filing_id),
                "truncated": c.truncated,
            }
            for c in built.chunks
        ]
        return {
            "chunks": chunks,
            "collapsed_near_duplicates": built.collapsed,
            "dropped_candidates": built.dropped,
            "token_estimate": built.token_estimate,
            "gaps": list(result.gaps),
            "degraded": list(result.degraded),
        }

    def _final(
        self, run: _Run, validated: citations.ValidatedAnswer | None
    ) -> Event:
        meta = self._meta(run, validated)
        record: dict[str, Any] = {
            "request_id": run.request_id,
            "question": run.question,
            "analysis": _analysis_summary(run.analysis)
            if run.analysis
            else None,
            "retrieval": self._retrieval(run.result) if run.result else None,
            "answer": validated.answer.model_dump() if validated else None,
            "citations_resolved": [
                c.model_dump() for c in validated.citations_resolved
            ]
            if validated
            else [],
            "outcome": run.outcome,
            "message": _message(run),
            "raw_text": (run.stream.text or run.raw_text)
            if run.outcome == "schema_violation"
            else None,
            "meta": meta,
        }
        self._audit(run, record)
        return Event("final", record)

    def _meta(
        self, run: _Run, validated: citations.ValidatedAnswer | None
    ) -> dict[str, Any]:
        usage = run.usage
        prices = self.prices.models.get(self.model)
        cost = base.cost_usd(usage, prices) if prices else 0.0
        if run.bundle is not None and usage.total_input:
            self.calibration.observe(
                run.bundle.estimated_tokens, usage.total_input
            )
        report = validated.report if validated else citations.ValidationReport()
        timings = run.result.timings if run.result else None
        analysis = run.analysis
        return {
            "model": self.model,
            "prompt_version": self.files.version,
            "index_version": self.index_version,
            "prompt_hash": self.files.prompt_hash,
            "latency_ms": {
                "understanding": run.understanding_ms,
                "retrieval": run.retrieval_ms,
                "rerank": timings.rerank_ms if timings else 0.0,
                "first_token": run.first_token_ms,
                "total": self._elapsed(run),
            },
            "usage": {
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": usage.cache_read_tokens,
                "cache_write_tokens": usage.cache_write_tokens,
                "output_tokens": usage.output_tokens,
            },
            "estimated_input_tokens": (
                run.bundle.estimated_tokens if run.bundle else 0
            ),
            "cost_usd": cost,
            "model_requests": run.requests,
            "degraded": run.outcome in {"provider_error", "offline"},
            "from_cache": False,
            "flags": {
                "citation_drift": report.citation_drift,
                "inline_drift": report.inline_drift,
                "quote_mismatch": report.quote_mismatch,
                "period_mismatch": report.period_mismatch,
                "unverified": report.unverified,
                "confidence_lowered": report.confidence_lowered,
                "schema_violation": run.outcome == "schema_violation",
                "injection_suspect": bool(
                    analysis and analysis.flags.injection_suspect
                ),
                "stop_reason": run.finished.stop_reason
                if run.finished
                else None,
            },
        }

    def _audit(self, run: _Run, record: dict[str, Any] | None) -> None:
        """Write the audit record of chapter 15 S-07 (never the prompt)."""
        meta = record["meta"] if record else {}
        chunk_ids = list(run.bundle.chunk_ids) if run.bundle else []
        if not chunk_ids and run.result is not None:
            chunk_ids = [
                c.candidate.chunk_id for c in run.result.context.chunks
            ]
        flags = meta.get("flags", {})
        self.audit.write(
            {
                "request_id": run.request_id,
                "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(
                    timespec="seconds"
                ),
                "question": run.question,
                "tickers": list(run.analysis.tickers) if run.analysis else [],
                "outcome": run.outcome,
                "chunk_ids": chunk_ids,
                "prompt_hash": self.files.prompt_hash,
                "prompt_version": self.files.version,
                "index_version": self.index_version,
                "model": self.model,
                "model_requests": meta.get("model_requests", run.requests),
                "latency_ms": meta.get("latency_ms"),
                "usage": meta.get("usage"),
                "cost_usd": meta.get("cost_usd", 0.0),
                "citation_drift": flags.get("citation_drift", 0),
                "inline_drift": flags.get("inline_drift", 0),
                "quote_mismatch": flags.get("quote_mismatch", 0),
                "period_mismatch": flags.get("period_mismatch", []),
                "unverified": flags.get("unverified", 0),
                "flags": {
                    "injection_suspect": flags.get("injection_suspect", False),
                    "schema_violation": flags.get("schema_violation", False),
                    "confidence_lowered": flags.get(
                        "confidence_lowered", False
                    ),
                    "degraded": meta.get("degraded", False),
                    "from_cache": meta.get("from_cache", False),
                },
                "error": run.error.code if run.error else None,
            }
        )


def _message(run: _Run) -> str | None:
    if run.outcome == "out_of_scope" and run.analysis is not None:
        return f"Out of scope: {run.analysis.out_of_scope_reason}."
    if run.outcome == "no_context":
        return context.NO_CONTEXT_MESSAGE
    if run.outcome == "offline":
        return OFFLINE_MESSAGE
    if run.outcome == "schema_violation":
        return SCHEMA_WARNING
    if run.outcome == "provider_error" and run.error is not None:
        return (
            f"The model is unavailable ({run.error.code}); the retrieved "
            "filing text is shown."
        )
    return None


def _analysis_summary(
    analysis: understanding.QuestionAnalysis | None,
) -> dict[str, Any]:
    if analysis is None:
        return {}
    return {
        "tickers": list(analysis.tickers),
        "groups": list(analysis.groups),
        "primary_type": analysis.primary_type,
        "types": list(analysis.types),
        "time_scope": {"kind": analysis.time_scope.kind},
        "unknown_entities": list(analysis.unknown_entities),
        "not_indexed": [n.model_dump() for n in analysis.not_indexed],
        "out_of_scope_parts": list(analysis.out_of_scope_parts),
        "out_of_scope_reason": analysis.out_of_scope_reason,
        "flags": analysis.flags.model_dump(),
    }
