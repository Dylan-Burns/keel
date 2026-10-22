"""`keel warm-cache`: everything the demo touches, on disk (chapter 16.12).

The command runs 2 steps before a demo. First it pre-fetches the XBRL
company facts file of every corpus ticker and of the `demo.add_companies`
tickers into the EDGAR disk cache (chapter 26.1 step 2: 1 request per
company the night before, 0 on demo day), through `keel/edgar.py` with
its `User-Agent` and its 0.2 s pacing. Then it answers the 3 example
questions and the golden set through the real pipeline, so the answer
cache holds 1 entry per question under the D-29 key of the current index,
prompt, and model. A question that the pipeline refuses with no model
call (out of scope) stores that response, so `KEEL_OFFLINE=1` serves it
from the cache too. A question already in the cache is skipped unless
`--refresh` is given.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Sequence
import dataclasses
import logging
import pathlib
import time
from typing import Any

from keel import answer
from keel import cache
from keel import config
from keel import edgar
from keel import errors
from keel import understanding
from keel.evaluation import golden

logger = logging.getLogger(__name__)

DEFAULT_GOLDEN = pathlib.Path("eval/golden.yaml")
HELP = "pre-fetch the company facts and fill the demo answer cache"

Printer = Callable[[str], None]


@dataclasses.dataclass(frozen=True)
class FactsPrefetch:
    """The result of the company facts pre-fetch.

    Attributes:
        tickers: The tickers asked for, in order.
        fetched: The tickers whose file came from the network this run.
        cached: The tickers whose file was already in the cache.
        no_lines: The tickers whose file maps none of the 8 concepts.
        failed: `ticker: reason` per ticker with no file.
        requests: The HTTP requests sent (the ticker map included).
    """

    tickers: tuple[str, ...]
    fetched: tuple[str, ...]
    cached: tuple[str, ...]
    no_lines: tuple[str, ...]
    failed: tuple[str, ...]
    requests: int


@dataclasses.dataclass(frozen=True)
class DemoQuestion:
    """1 question the demo may ask.

    Attributes:
        label: `example 1` to `example 3`, or the golden ID.
        text: The question.
    """

    label: str
    text: str


@dataclasses.dataclass(frozen=True)
class WarmResult:
    """The outcome of 1 question.

    Attributes:
        label: The question label.
        status: `skipped` (already cached), `answered`, `refusal` (stored
            no-call response), or `failed`.
        outcome: The pipeline outcome, such as `answered` or
            `out_of_scope`; empty when skipped.
        cost_usd: The answer cost.
        model_requests: The model requests of the question.
        seconds: The wall time.
    """

    label: str
    status: str
    outcome: str = ""
    cost_usd: float = 0.0
    model_requests: int = 0
    seconds: float = 0.0


def corpus_tickers(
    catalog: understanding.Catalog, extra: Iterable[str]
) -> tuple[str, ...]:
    """List the corpus tickers (indexed or quarantined) and the extras.

    Args:
        catalog: The corpus facts of the index.
        extra: More tickers, such as `demo.add_companies`.

    Returns:
        The tickers, sorted, without repeats.
    """
    tickers = set(catalog.indexed_tickers)
    tickers.update(note.ticker for note in catalog.quarantined)
    tickers.update(edgar.normalize_ticker(t) for t in extra)
    return tuple(sorted(tickers))


def prefetch_facts(
    client: edgar.EdgarClient,
    facts_config: edgar.FactsConfig,
    tickers: Sequence[str],
    *,
    refresh: bool = False,
) -> FactsPrefetch:
    """Cache the company facts file of each ticker.

    A failed ticker (unknown to the ticker map, no facts file, a fetch
    error) is recorded and the rest continue.

    Args:
        client: The EDGAR client (its pacing and cache apply).
        facts_config: The mapped concepts, to count the lines per file.
        tickers: The tickers.
        refresh: Fetch every file again, even when cached.

    Returns:
        The counts per outcome.
    """
    fetched: list[str] = []
    cached: list[str] = []
    no_lines: list[str] = []
    failed: list[str] = []
    for ticker in tickers:
        before = client.requests
        try:
            cik = client.cik(ticker)
            before = client.requests
            document = client.company_facts(cik, refresh=refresh)
        except errors.EdgarError as error:
            logger.warning("no company facts for %s: %s", ticker, error)
            failed.append(f"{ticker}: {error}")
            continue
        (fetched if client.requests > before else cached).append(ticker)
        block = edgar.facts_lines(document.data, ticker, facts_config)
        if not block.lines:
            no_lines.append(ticker)
    return FactsPrefetch(
        tickers=tuple(tickers),
        fetched=tuple(fetched),
        cached=tuple(cached),
        no_lines=tuple(no_lines),
        failed=tuple(failed),
        requests=client.requests,
    )


def demo_questions(
    examples: Sequence[str], golden_set: golden.GoldenSet | None
) -> tuple[DemoQuestion, ...]:
    """The example questions, then the golden questions not yet listed.

    Args:
        examples: The `demo.example_questions`.
        golden_set: The golden set, or None.

    Returns:
        The questions; a golden question equal to an example (after the
        normalization of the cache key) is listed once, under its ID.
    """
    questions: dict[str, DemoQuestion] = {}
    norm = cache.normalize_question
    for number, text in enumerate(examples, start=1):
        questions[norm(text)] = DemoQuestion(f"example {number}", text)
    for item in golden_set.questions if golden_set else ():
        key = norm(item.question)
        if key in questions:
            questions[key] = DemoQuestion(item.id, questions[key].text)
        else:
            questions[key] = DemoQuestion(item.id, item.question)
    return tuple(questions.values())


async def _final(answerer: answer.Answerer, text: str) -> dict[str, Any]:
    record: dict[str, Any] = {}
    async for event in answerer.ask(text):
        if event.name == "final":
            record = event.data
    return record


async def warm_answers(
    answerer: answer.Answerer,
    questions: Sequence[DemoQuestion],
    *,
    refresh: bool = False,
    printer: Printer | None = None,
) -> tuple[WarmResult, ...]:
    """Answer each question that has no cache entry, through the pipeline.

    The pipeline writes an answered question into the cache itself (a
    primary-model answer of a real provider). An out-of-scope question
    makes no model call; its response is stored here, so offline mode
    serves it from the cache as well.

    Args:
        answerer: The opened pipeline.
        questions: The questions.
        refresh: Answer every question again, even when cached.
        printer: Called with 1 line per question, or None.

    Returns:
        1 result per question, in order.
    """
    results = []
    for number, item in enumerate(questions, start=1):
        key = answerer.cache_key(item.text)
        if not refresh and answerer.cache.get(key) is not None:
            result = WarmResult(item.label, "skipped")
        else:
            started = time.perf_counter()
            record = await _final(answerer, item.text)
            result = _store(answerer, key, item.label, record, started)
        results.append(result)
        if printer is not None:
            printer(_line(number, len(questions), result))
    return tuple(results)


def _store(
    answerer: answer.Answerer,
    key: str,
    label: str,
    record: dict[str, Any],
    started: float,
) -> WarmResult:
    """Classify 1 answered question and store a no-call refusal.

    An out-of-scope response with 0 model requests is written here; any
    other outcome counts as answered only when the cache entry now holds
    this request (the pipeline wrote it), so a failed `--refresh` does not
    pass for an old entry.

    Args:
        answerer: The pipeline that answered.
        key: The cache key of the question.
        label: The question label.
        record: The final record of the request.
        started: The `time.perf_counter` value at the start.

    Returns:
        The result.
    """
    meta = record.get("meta") or {}
    outcome = str(record.get("outcome") or "")
    requests = int(meta.get("model_requests") or 0)
    if outcome == "out_of_scope" and requests == 0:
        # The audit record belongs to the request, not to the entry.
        entry = {k: v for k, v in record.items() if k != "audit"}
        answerer.cache.put(key, entry)
        status = "refusal"
    else:
        # The entry must hold this request, not an older answer (refresh).
        stored = answerer.cache.get(key)
        fresh = stored is not None and stored.get("request_id") == (
            record.get("request_id")
        )
        status = "answered" if fresh else "failed"
        if not fresh:
            logger.warning("%s left no cache entry: %s", label, outcome)
    return WarmResult(
        label,
        status,
        outcome,
        float(meta.get("cost_usd") or 0.0),
        requests,
        round(time.perf_counter() - started, 1),
    )


def _line(number: int, total: int, result: WarmResult) -> str:
    if result.status == "skipped":
        return f"[{number}/{total}] {result.label}: cached already"
    return (
        f"[{number}/{total}] {result.label}: {result.status} "
        f"(outcome {result.outcome}, {result.model_requests} model "
        f"requests, ${result.cost_usd:.4f}, {result.seconds} s)"
    )


def add_arguments() -> argparse.ArgumentParser:
    """The arguments of `keel warm-cache`, as a parent parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--set",
        dest="golden",
        type=pathlib.Path,
        default=DEFAULT_GOLDEN,
        help="the golden set file (default: eval/golden.yaml)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="answer every question and fetch every facts file again",
    )
    parser.add_argument(
        "--facts-only",
        action="store_true",
        help="pre-fetch the company facts files and answer nothing",
    )
    parser.add_argument(
        "--index",
        type=pathlib.Path,
        default=None,
        help="the index directory with `current` (default: index.dir)",
    )
    return parser


def _print_facts(prefetch: FactsPrefetch, printer: Printer) -> None:
    printer(
        f"facts: {len(prefetch.tickers)} tickers, "
        f"{len(prefetch.fetched)} fetched, {len(prefetch.cached)} cached "
        f"already, {len(prefetch.failed)} failed, {prefetch.requests} "
        "requests to the SEC"
    )
    if prefetch.no_lines:
        printer("facts: no mapped concept for " + ", ".join(prefetch.no_lines))
    for failure in prefetch.failed:
        printer(f"facts: no file for {failure}")


def _print_summary(
    results: Sequence[WarmResult], entries: int, printer: Printer
) -> None:
    answered, refusals, skipped, failed = (
        sum(1 for r in results if r.status == status)
        for status in ("answered", "refusal", "skipped", "failed")
    )
    cost = sum(r.cost_usd for r in results)
    requests = sum(r.model_requests for r in results)
    printer(
        f"answer cache: {entries} of {len(results)} questions have an entry "
        f"({answered} answered, {refusals} refusals stored, {skipped} "
        f"cached already, {failed} failed); {requests} model requests, "
        f"${cost:.4f}"
    )


def run(
    settings: config.Settings,
    args: argparse.Namespace,
    printer: Printer = print,
) -> int:
    """Run `keel warm-cache`.

    Args:
        settings: The loaded settings.
        args: The arguments of `add_arguments`.
        printer: Prints 1 line of the report.

    Returns:
        0 when every question has a cache entry from this run or an
        earlier one, no answer failed, and every ticker has a facts file;
        else 1.

    Raises:
        ConfigError: Offline mode is on, or the prompt, the provider, or
            `config/facts.yaml` is invalid.
        IndexMissingError: No published index.
        GoldenSetError: The golden set file is invalid.
    """
    if settings.offline:
        raise errors.ConfigError(
            "warm-cache needs the provider and EDGAR; unset KEEL_OFFLINE"
        )
    answerer = answer.Answerer.open(
        settings, args.index, load_models=not args.facts_only
    )
    tickers = corpus_tickers(
        answerer.retriever.catalog, settings.demo.add_companies
    )
    facts_config = edgar.load_facts_config(settings.edgar.facts)
    with edgar.EdgarClient.from_settings(settings, offline=False) as client:
        prefetch = prefetch_facts(
            client, facts_config, tickers, refresh=args.refresh
        )
    _print_facts(prefetch, printer)
    if args.facts_only:
        return 1 if prefetch.failed else 0
    golden_set = golden.load_golden(args.golden)
    questions = demo_questions(settings.demo.example_questions, golden_set)
    printer(
        f"answer cache: {len(questions)} questions, index "
        f"{answerer.index_version}, prompt {answerer.files.version}, model "
        f"{answerer.model}, directory {settings.cache.answers_dir}"
    )
    results = asyncio.run(
        warm_answers(answerer, questions, refresh=args.refresh, printer=printer)
    )
    entries = sum(
        1
        for q in questions
        if answerer.cache.get(answerer.cache_key(q.text)) is not None
    )
    _print_summary(results, entries, printer)
    failed = any(r.status == "failed" for r in results)
    complete = entries == len(questions) and not prefetch.failed
    complete = complete and not failed
    return 0 if complete else 1
