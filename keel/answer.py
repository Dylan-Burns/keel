"""The question pipeline around the single call (chapter 6.3).

`Answerer.ask` runs 1 question: the answer cache when allowed, question
understanding, retrieval, the company facts of a numeric question (from
the EDGAR disk cache, chapter 26.1; never a blocker), the prompt, exactly 1
provider request (with up to 2 retries before any content, decision D-04),
the citation validator, the answer cache write, and 1 audit record. It
yields the events of chapter 14.3 (`meta`, `analysis`, `retrieval`,
`answer_delta`, `findings`, `final`, `error`, `done`), which `keel ask`
prints and the API of stage 9 streams. No other step calls a model (D-01,
D-02, D-28).

Chapter 16 wraps the call: the circuit breaker sends a question straight to
the fallback model while the primary model is down, the fallback gets its
own budget of 3 requests, a context overflow halves the context once, and
the daily budget stops every model request. When no model answers, the
question gets the degraded mode: the retrieved chunks with their SEC links.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
import copy
import dataclasses
import datetime
import logging
import operator
import pathlib
import random
import sqlite3
import threading
import time
from typing import Any
import uuid

from keel import audit
from keel import cache
from keel import citations
from keel import config
from keel import context
from keel import edgar
from keel import errors
from keel import indexer
from keel import partial_json
from keel import prompt
from keel import reliability
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
BUDGET_MESSAGE = (
    "The daily model budget is spent: this question is not in the answer "
    "cache, so only the retrieved filing text is shown."
)
REFUSED_MESSAGE = (
    "The model declined to answer; the retrieved filing text is shown."
)
OVERFLOW_RAISE = 0.05  # chapter 16.6 step 4: the calibration factor +5%
DEGRADED_OUTCOMES = frozenset({"provider_error", "offline", "budget_stop"})
CONNECT_DELAYS = (1.0, 3.0)
SERVER_DELAYS = (2.0, 6.0)
MAX_RETRY_WAIT = 30.0  # a longer Retry-After would pass the 120 s total

Sleep = Callable[[float], Awaitable[None]]
FactsLoader = Callable[[understanding.QuestionAnalysis], edgar.FactsResult]


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


def fallback_from_settings(
    settings: config.Settings,
) -> base.LLMProvider | None:
    """Build the fallback model provider of chapter 16.4.

    The fallback sends the same prompt with the same output mode; the
    adapter takes the thinking setting of the fallback model from
    `llm.thinking`.

    Args:
        settings: The loaded settings.

    Returns:
        The provider of `llm.fallback_model`, or None when no key is set
        or the fallback model is the primary model.
    """
    llm = settings.llm
    if not llm.fallback_model or llm.fallback_model == llm.model:
        return None
    if llm.provider == "mock":
        return mock.MockProvider(llm.fallback_model)
    if llm.provider != "anthropic" or settings.anthropic_api_key is None:
        return None
    return anthropic_provider.AnthropicProvider.from_settings(
        settings, model=llm.fallback_model
    )


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
    facts: edgar.FactsResult = dataclasses.field(
        default_factory=edgar.FactsResult
    )
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
    failed_before_content: int = 0
    content: bool = False
    succeeded: bool = False
    halved: bool = False
    model: str = ""
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
        fallback: The fallback model provider, or None for no fallback.
        breaker: The circuit breaker of the primary model, or None for a
            new one.
        facts_loader: Loads the company facts of a numeric question, or
            None for the EDGAR client of the settings.

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
        fallback: base.LLMProvider | None = None,
        breaker: reliability.CircuitBreaker | None = None,
        facts_loader: FactsLoader | None = None,
    ) -> None:
        self.settings = settings
        self.retriever = step
        self.provider = provider
        self.fallback = fallback
        self.breaker = breaker or reliability.CircuitBreaker()
        self.index_version = index_version
        self.sleep = sleep
        self.facts_loader = facts_loader or self.load_facts
        self._edgar: edgar.EdgarClient | None = None
        # 1 client per pipeline keeps the 0.2 s interval across questions.
        self._edgar_lock = threading.Lock()
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
        self.budget = reliability.BudgetGuard(
            self.audit.path, settings.limits.daily_budget_usd
        )
        self.calibration = context.Calibration(
            settings.retrieval.calibration_factor
        )
        # 1 retrieval at a time: the reranker and the store connection are
        # shared by the concurrent requests of the API (E-F-03).
        self.retrieval_lock = threading.Lock()

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
            provider: The provider, or None for the configured one. The
                fallback model always comes from the config.
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
            fallback=fallback_from_settings(settings),
        )

    def with_provider(
        self,
        provider: base.LLMProvider,
        *,
        sleep: Sleep | None = None,
        fallback: base.LLMProvider | None = None,
    ) -> Answerer:
        """A copy that sends its requests to another provider.

        The copy shares the index, the models, the caches, the audit log,
        the budget, and the calibration, so the API can serve 1 request
        with a mock fault (the `X-Keel-Mock` header) without reloading
        anything. It gets its own circuit breaker, so a drill never opens
        the breaker of the service.

        Args:
            provider: The provider of the copy.
            sleep: The wait between retries, or None to keep it.
            fallback: The fallback provider of the copy, or None for none.

        Returns:
            The copy.
        """
        twin = copy.copy(self)
        twin.provider = provider
        twin.fallback = fallback
        twin.breaker = reliability.CircuitBreaker()
        if sleep is not None:
            twin.sleep = sleep
        return twin

    def load_facts(
        self, analysis: understanding.QuestionAnalysis
    ) -> edgar.FactsResult:
        """Load the facts lines of each resolved company in its window.

        The EDGAR disk cache serves first; a missing file is fetched when
        the settings are online, through 1 client per pipeline so the
        minimum interval holds across questions. Any failure yields no
        lines and is recorded, so the facts never block an answer.

        Args:
            analysis: The question analysis.

        Returns:
            The facts blocks, their source, and the errors.
        """
        windows: dict[str, edgar.Window] = {}
        for ticker in analysis.tickers:
            window = analysis.windows.get(ticker)
            windows[ticker] = (
                (window.start, window.end) if window else (None, None)
            )
        try:
            facts_config = edgar.load_facts_config(self.settings.edgar.facts)
            with self._edgar_lock:
                if self._edgar is None:
                    self._edgar = edgar.EdgarClient.from_settings(self.settings)
                return edgar.collect_facts(self._edgar, facts_config, windows)
        except (errors.KeelError, OSError) as error:
            logger.warning("no company facts: %s", error)
            return edgar.FactsResult(errors=(str(error),))

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
        max_context_tokens: int | None = None,
        max_chunks: int | None = None,
    ) -> AsyncIterator[Event]:
        """Answer 1 question and yield the events of chapter 14.3.

        Args:
            question: The question.
            request_id: The request ID, or None for a new one.
            use_cache: Serve a cached answer when there is one. Offline
                mode and a spent daily budget always read the cache and
                never call the model.
            max_context_tokens: A lower context budget for this request,
                or None; never above `retrieval.max_context_tokens`.
            max_chunks: A lower chunk budget for this request, or None;
                never above `retrieval.max_chunks`.

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
        stopped = not offline and (
            await asyncio.to_thread(self.budget.exhausted)
        )
        if offline or use_cache or stopped:
            cached = self.cache.get(self.cache_key(question))
            if cached is not None:
                async for event in self._from_cache(run, cached):
                    yield event
                return
        budget = context.Budget(
            max_tokens=self.settings.retrieval.max_context_tokens,
            max_chunks=self.settings.retrieval.max_chunks,
            calibration_factor=self.calibration.factor,
        ).lowered(max_context_tokens, max_chunks)
        async for event in self._pipeline(
            run, budget, offline=offline, stopped=stopped
        ):
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
        # The cached record holds the context the answer used; a fresh
        # retrieval before a provider failure does not describe it.
        run.result = None
        run.bundle = None
        record["audit"] = self._audit(run, record)
        yield Event("final", record)
        yield Event("done", {})

    def _retrieve(
        self,
        analysis: understanding.QuestionAnalysis,
        budget: context.Budget,
    ) -> retriever.RetrievalResult:
        with self.retrieval_lock:
            return self.retriever.retrieve(analysis, budget)

    async def _pipeline(
        self,
        run: _Run,
        budget: context.Budget,
        *,
        offline: bool,
        stopped: bool,
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
        retrieval_started = time.perf_counter()
        run.result = await asyncio.to_thread(
            self._retrieve, run.analysis, budget
        )
        run.retrieval_ms = round(
            (time.perf_counter() - retrieval_started) * 1000, 1
        )
        yield Event("retrieval", self._retrieval(run.result))
        if run.result.context.empty or offline or stopped:
            run.outcome = "budget_stop" if stopped else "offline"
            if run.result.context.empty:
                run.outcome = "no_context"
            yield self._final(run, None)
            yield Event("done", {})
            return
        if self.files.takes_facts and prompt.wants_facts(run.analysis):
            run.facts = await self._facts(run.analysis)
        run.bundle = prompt.build_bundle(
            self.files,
            run.analysis,
            run.result.context,
            self.retriever.catalog.filings,
            run.facts.lines,
        )
        async for event in self._call(run):
            yield event
        async for event in self._finish(run):
            yield event

    async def _facts(
        self, analysis: understanding.QuestionAnalysis
    ) -> edgar.FactsResult:
        """Run the facts loader off the event loop; never raise."""
        try:
            return await asyncio.to_thread(self.facts_loader, analysis)
        except Exception as error:  # pylint: disable=broad-exception-caught
            # The facts are optional context: any failure leaves them out.
            logger.exception("company facts failed")
            return edgar.FactsResult(
                errors=(f"{type(error).__name__}: {error}",)
            )

    async def _call(self, run: _Run) -> AsyncIterator[Event]:
        """Ask the primary model, then the fallback (chapters 16.3, 16.4).

        The primary model gets up to 3 requests while the breaker lets
        them through; the fallback gets its own 3 when the primary model
        failed for availability before any content, or the breaker is
        open. No request follows content (D-04), and with `max_retries: 0`
        the fallback is off.
        """
        async for out in self._attempts(run, self.provider, primary=True):
            yield out
        primary_down = run.error is None or run.error.retryable
        # D-04 reversal: `max_retries: 0` allows 1 request, so no fallback.
        fallback = self.fallback if self.settings.llm.max_retries else None
        if (
            fallback is not None
            and not run.succeeded
            and not run.content
            and primary_down
        ):
            logger.warning("the fallback model %s answers", fallback.model)
            async for out in self._attempts(run, fallback, primary=False):
                yield out
        if not run.succeeded and run.error is None:
            run.error = errors.ProviderUnavailableError(
                "the circuit breaker is open and no fallback model is set"
            )

    async def _attempts(
        self, run: _Run, provider: base.LLMProvider, *, primary: bool
    ) -> AsyncIterator[Event]:
        """Send up to 3 requests to 1 model; retry only before content."""
        attempts = self.settings.llm.max_retries + 1
        for attempt in range(attempts):
            permit = self.breaker.allow() if primary else None
            if primary and permit is None:
                logger.warning("circuit breaker open: primary model skipped")
                return
            probe = permit == reliability.HALF_OPEN
            if run.bundle is None:  # pragma: no cover  # set by the caller
                return
            run.requests += 1
            run.model = provider.model
            run.stream = partial_json.AnswerStream()
            run.raw_text = ""
            settled = False
            try:
                async for event in provider.answer(run.bundle):
                    for out in self._on_event(run, event):
                        yield out
            except errors.ProviderError as error:
                settled = True
                if not run.content:
                    run.failed_before_content += 1
                last = attempt == attempts - 1
                if not await self._recover(
                    run,
                    provider,
                    error,
                    attempt,
                    primary=primary,
                    probe=probe,
                    last=last,
                ):
                    return
            else:
                settled = True
                if primary:
                    self.breaker.record_success()
                run.error = None
                run.succeeded = True
                return
            finally:
                if probe and not settled:
                    # Cancelled mid-request: free the probe this request holds.
                    self.breaker.release()

    async def _recover(  # pylint: disable=too-many-arguments
        self,
        run: _Run,
        provider: base.LLMProvider,
        error: errors.ProviderError,
        attempt: int,
        *,
        primary: bool,
        probe: bool,
        last: bool,
    ) -> bool:
        """Record a failed request and decide on the next one.

        Returns:
            True when another request to the same model may follow.
        """
        run.error = error
        if primary and reliability.counts_as_failure(error):
            self.breaker.record_failure()
        elif probe:
            self.breaker.release()
        opened = primary and not self.breaker.closed
        if run.content or last or (opened and error.retryable):
            logger.warning(
                "%s failed after %d request(s): %s",
                provider.model,
                run.requests,
                error,
            )
            return False
        if isinstance(error, errors.ContextOverflowError) and not run.halved:
            self._halve(run, error)
            return True
        if not error.retryable:
            logger.warning("%s rejected the request: %s", provider.model, error)
            return False
        delay = backoff(error, attempt)
        logger.warning(
            "provider failed before content (%s); retry %d in %.1f s",
            error,
            attempt + 1,
            delay,
        )
        await self.sleep(delay)
        return True

    def _halve(self, run: _Run, error: errors.ProviderError) -> None:
        """Halve the context and rebuild the prompt (chapter 16.6 step 3)."""
        if run.result is None or run.analysis is None or run.bundle is None:
            return  # pragma: no cover  # a request needs all 3
        estimate = run.bundle.estimated_tokens
        factor = self.calibration.raise_by(OVERFLOW_RAISE)
        halved = reliability.halve_context(run.result.context)
        logger.warning(
            "context_overflow: estimate %d tokens, provider: %s; context "
            "budget halved to %d tokens (%d chunks), calibration factor %.4f",
            estimate,
            error,
            halved.budget.max_tokens,
            len(halved.chunks),
            factor,
        )
        run.halved = True
        run.result = dataclasses.replace(run.result, context=halved)
        run.bundle = prompt.build_bundle(
            self.files,
            run.analysis,
            halved,
            self.retriever.catalog.filings,
            run.facts.lines,
        )

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
        # A mock answer never enters the cache of the real model's key,
        # and neither does a fallback answer (the key names the model).
        real = self.provider.name != mock.MockProvider.name
        primary = run.model == self.model
        answered = validated is not None and record.data["answer"]
        if real and primary and answered:
            # The audit record belongs to this request, not to the entry.
            entry = {k: v for k, v in record.data.items() if k != "audit"}
            self.cache.put(self.cache_key(run.question), entry)
        yield Event("done", {})

    def _validate(self, run: _Run) -> citations.ValidatedAnswer | None:
        if run.result is None:
            return None
        text = run.stream.text
        finished = run.finished
        if finished is not None and finished.stop_reason == "refusal":
            run.outcome = "refused"
            logger.warning("the model declined to answer")
            return None
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
        return citations.validate(
            answer, run.result.context, urls, run.facts.by_id()
        )

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
        # The trace drawer renders the audit record of the answer (25.1).
        record["audit"] = self._audit(run, record)
        return Event("final", record)

    def _meta(
        self, run: _Run, validated: citations.ValidatedAnswer | None
    ) -> dict[str, Any]:
        usage = run.usage
        model = run.model or self.model
        prices = self.prices.models.get(model)
        cost = base.cost_usd(usage, prices) if prices else 0.0
        if run.bundle is not None and usage.total_input:
            self.calibration.observe(
                run.bundle.estimated_tokens, usage.total_input
            )
        report = validated.report if validated else citations.ValidationReport()
        timings = run.result.timings if run.result else None
        analysis = run.analysis
        return {
            "model": model,
            "fallback": model != self.model,
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
            "facts": _facts_summary(run.facts),
            "degraded": run.outcome in DEGRADED_OUTCOMES,
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

    def _audit(
        self, run: _Run, record: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Write the audit record of chapter 15 S-07 (never the prompt).

        The record lists the pipeline in order: the entities and the
        question type, the filters, the candidates per company around the
        collapse, the quota fills, the context, the prompt, the model, the
        requests, the usage, the latency, and the flags.

        Args:
            run: The question.
            record: The `final` record, or None for a rejected question.

        Returns:
            The record, which the `final` event carries (chapter 25.1).
        """
        meta = record["meta"] if record else {}
        chunk_ids = list(run.bundle.chunk_ids) if run.bundle else []
        if not chunk_ids and run.result is not None:
            chunk_ids = [
                c.candidate.chunk_id for c in run.result.context.chunks
            ]
        flags = meta.get("flags", {})
        analysis = run.analysis
        trace = _retrieval_trace(run.result)
        stored = (record or {}).get("analysis") or {}
        if run.result is None and record is not None:
            chunks = (record.get("retrieval") or {}).get("chunks") or []
            chunk_ids = chunk_ids or [c["chunk_id"] for c in chunks]
            trace["chunk_count"] = len(chunks)
            trace["token_estimate"] = (record.get("retrieval") or {}).get(
                "token_estimate", 0
            )
        entry: dict[str, Any] = {
            "request_id": run.request_id,
            "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(
                timespec="seconds"
            ),
            "question": run.question,
            "tickers": list(analysis.tickers)
            if analysis
            else list(stored.get("tickers", [])),
            "question_type": analysis.primary_type
            if analysis
            else stored.get("primary_type"),
            "time_scope": analysis.time_scope.kind
            if analysis
            else (stored.get("time_scope") or {}).get("kind"),
            **trace,
            "outcome": run.outcome,
            "chunk_ids": chunk_ids,
            "prompt_hash": self.files.prompt_hash,
            "prompt_version": self.files.version,
            "index_version": self.index_version,
            "model": meta.get("model", run.model or self.model),
            "model_requests": meta.get("model_requests", run.requests),
            "failed_before_content": run.failed_before_content,
            "degraded": meta.get("degraded", False),
            "latency_ms": meta.get("latency_ms"),
            "usage": meta.get("usage"),
            "cost_usd": meta.get("cost_usd", 0.0),
            "citation_drift": flags.get("citation_drift", 0),
            "inline_drift": flags.get("inline_drift", 0),
            "quote_mismatch": flags.get("quote_mismatch", 0),
            "period_mismatch": flags.get("period_mismatch", []),
            "unverified": flags.get("unverified", 0),
            "facts_lines": len(run.facts.lines),
            "facts_source": run.facts.source,
            "fact_ids": list(run.bundle.fact_ids) if run.bundle else [],
            "facts_errors": list(run.facts.errors),
            "flags": {
                "injection_suspect": flags.get("injection_suspect", False),
                "schema_violation": flags.get("schema_violation", False),
                "confidence_lowered": flags.get("confidence_lowered", False),
                "degraded": meta.get("degraded", False),
                "from_cache": meta.get("from_cache", False),
            },
            "error": run.error.code if run.error else None,
        }
        self.audit.write(entry)
        return entry


def _retrieval_trace(
    result: retriever.RetrievalResult | None,
) -> dict[str, Any]:
    """The retrieval part of the audit record, in pipeline order (25.1)."""
    if result is None:
        return {
            "filters": [],
            "candidates": None,
            "quota_fills": [],
            "chunk_count": 0,
            "token_estimate": 0,
        }
    built = result.context
    return {
        "filters": [
            {
                "label": query.label,
                "tickers": list(query.filter.tickers),
                "sections": list(query.filter.sections),
                "filings": len(query.filter.filing_ids),
                "windows": [list(w) for w in query.filter.windows],
            }
            for query in result.plan.sub_queries
        ],
        "candidates": {
            "gathered": result.candidates,
            "collapsed": result.collapsed,
            "reranked": result.reranked,
            "per_company": [
                {"ticker": ticker, "before": before, "after": after}
                for ticker, before, after in result.per_company
            ],
        },
        "quota_fills": [
            {
                "label": fill.label,
                "taken": fill.taken,
                "quota": fill.quota,
                "candidates": fill.candidates,
                "tokens": fill.tokens,
            }
            for fill in built.fills
        ],
        "chunk_count": len(built.chunks),
        "token_estimate": built.token_estimate,
    }


_MESSAGES = {
    "no_context": context.NO_CONTEXT_MESSAGE,
    "offline": OFFLINE_MESSAGE,
    "budget_stop": BUDGET_MESSAGE,
    "refused": REFUSED_MESSAGE,
    "schema_violation": SCHEMA_WARNING,
}


def _facts_summary(facts: edgar.FactsResult) -> dict[str, Any]:
    """The facts line of the trace drawer (chapter 26.1, step 8)."""
    return {
        "lines": len(facts.lines),
        "source": facts.source,
        "files": facts.files,
        "errors": list(facts.errors),
    }


def _message(run: _Run) -> str | None:
    if run.outcome == "out_of_scope" and run.analysis is not None:
        return f"Out of scope: {run.analysis.out_of_scope_reason}."
    if run.outcome == "provider_error" and run.error is not None:
        return (
            f"The model is unavailable ({run.error.code}); the retrieved "
            "filing text is shown."
        )
    return _MESSAGES.get(run.outcome)


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
