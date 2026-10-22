"""The admin job kinds: the CLI commands behind the admin pages.

Each kind validates its parameters with a pydantic model and calls the
library functions that the CLI command calls, in-process:

- `add`: `keel add TICKER`; heavy.
- `refresh`: `keel refresh [--dry-run]`; heavy.
- `warm_cache`: `keel warm-cache [--refresh] [--facts-only]`; heavy;
  `confirm: "cost"` unless `facts_only`.
- `eval`: `keel eval [--answers] [--subset S]`; heavy; `confirm: "cost"`
  with the answers.
- `facts`: `keel facts TICKER`; light.
- `backup`: `keel backup [--index-only]`; heavy.
- `restore`: `keel restore ARCHIVE`; heavy; `confirm` is the archive name.
- `index`: `keel index [--incremental]`; heavy; `confirm: "rebuild"`.

A job that embeds new filings reuses the embedding model the server
loaded, behind the pipeline's retrieval lock per batch, so the memory
does not double; a rebuild without a loaded pipeline loads its own.
"""

from __future__ import annotations

import collections
from collections.abc import Sequence
import pathlib
import threading
from typing import Annotated
from typing import Any

import numpy
import pydantic

from keel import add
from keel import backup
from keel import config
from keel import edgar
from keel import errors
from keel import extractor
from keel import indexer
from keel import refresh
from keel import warm_cache
from keel.api import jobs
from keel.api import state
from keel.evaluation import golden
from keel.evaluation import report as eval_report
from keel.evaluation import runner
from keel.stores import numpy_dense

Ticker = Annotated[
    str,
    pydantic.StringConstraints(
        strip_whitespace=True, pattern=r"^[A-Za-z][A-Za-z0-9.-]{0,9}$"
    ),
]
ArchiveName = Annotated[
    str,
    pydantic.StringConstraints(
        pattern=r"^keel-\d{4}-\d{2}-\d{2}T\d{6}Z\.tar\.gz$"
    ),
]
Subset = Annotated[
    str, pydantic.StringConstraints(pattern=r"^[A-Za-z0-9_,-]{1,200}$")
]
REBUILD_CONFIRM = "rebuild"
INDEX_WARNING = (
    "a full index build needs about 6.6 GB of memory and runs for more "
    "than an hour on the pilot host; questions keep the current build "
    "until the new one is published"
)
EVAL_WARNING = (
    "keel eval with answers makes 2 model requests per golden question "
    "(the answer and the judge)"
)


class _Params(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)


class TickerParams(_Params):
    """The parameters of `add` and `facts`.

    Attributes:
        ticker: The ticker, such as ZTS.
    """

    ticker: Ticker


class RefreshParams(_Params):
    """The parameters of `refresh`.

    Attributes:
        dry_run: List the new filings only.
    """

    dry_run: bool = False


class WarmCacheParams(_Params):
    """The parameters of `warm_cache`.

    Attributes:
        refresh: Answer every question and fetch every facts file again.
        facts_only: Pre-fetch the facts files and answer nothing.
    """

    refresh: bool = False
    facts_only: bool = False


class EvalParams(_Params):
    """The parameters of `eval`.

    Attributes:
        answers: Answer and judge each question (about 4 USD in all).
        judge: With answers, judge each answer.
        subset: A subset tag or a comma list of IDs, or None for all.
        ablation: Also run the lexical, dense, and no-reranker variants.
    """

    answers: bool = False
    judge: bool = True
    subset: Subset | None = None
    ablation: bool = True


class BackupParams(_Params):
    """The parameters of `backup`.

    Attributes:
        index_only: Leave the logs out of the archive.
    """

    index_only: bool = False


class RestoreParams(_Params):
    """The parameters of `restore`.

    Attributes:
        archive: The archive name, as `GET /api/admin/backups` lists it.
    """

    archive: ArchiveName


class IndexParams(_Params):
    """The parameters of `index`.

    Attributes:
        incremental: Reuse the shards of unchanged filings.
    """

    incremental: bool = False


class _LockedEmbedder:
    """The server's embedder, taken under the retrieval lock per batch."""

    def __init__(
        self,
        inner: numpy_dense.Embedder,
        lock: threading.Lock,
        batch: int,
    ) -> None:
        self.inner = inner
        self.lock = lock
        self.batch = max(1, batch)

    @property
    def dimensions(self) -> int:
        """The vector width."""
        return self.inner.dimensions

    def encode(self, texts: Sequence[str]) -> numpy_dense.Vectors:
        """Embed texts batch by batch, so questions run in between.

        Args:
            texts: The texts.

        Returns:
            The unit vectors, 1 row per text.
        """
        parts = []
        for start in range(0, len(texts), self.batch):
            with self.lock:
                parts.append(
                    self.inner.encode(texts[start : start + self.batch])
                )
        if not parts:
            with self.lock:
                return self.inner.encode([])
        return numpy.vstack(parts).astype(numpy.float32, copy=False)


def embedder_factory(services: state.Services) -> indexer.EmbedderFactory:
    """The embedder of a job: the loaded one when the server has it.

    Args:
        services: The shared services.

    Returns:
        A factory for `indexer.build_index` and `add.add_ticker`.
    """
    settings = services.settings
    answerer = services.answerer
    loaded = answerer.retriever.embedder if answerer is not None else None
    if answerer is None or loaded is None:
        return lambda: numpy_dense.SentenceEmbedder.from_settings(settings)
    lock = answerer.retrieval_lock
    batch = settings.embedding.batch_size * 8
    return lambda: _LockedEmbedder(loaded, lock, batch)


def ensure_corpus(settings: config.Settings, context: jobs.JobContext) -> None:
    """Extract the corpus zip when the corpus directory holds no filings.

    Args:
        settings: The loaded settings.
        context: The job, for the log line.

    Raises:
        CorpusMissingError: No filings and no zip.
    """
    corpus_dir = settings.corpus.dir
    if corpus_dir.is_dir() and any(corpus_dir.glob("*.txt")):
        return
    if not settings.corpus.zip.is_file():
        raise errors.CorpusMissingError(
            f"no filings in {corpus_dir} and no zip at {settings.corpus.zip}"
        )
    context.phase("extracting the corpus")
    result = extractor.extract_zip(settings.corpus.zip, corpus_dir)
    context.log(f"extracted {result.file_count} files")


def run_add(
    services: state.Services, context: jobs.JobContext, params: TickerParams
) -> jobs.JobOutput:
    """The `add` job: 1 company from EDGAR into the index (26.2).

    Args:
        services: The shared services.
        context: The job.
        params: The ticker.

    Returns:
        The add report; the index reloads when a build was published.
    """
    settings = services.settings
    ensure_corpus(settings, context)
    context.phase("fetching from EDGAR")
    with edgar.EdgarClient.from_settings(settings) as client:
        report = add.add_ticker(
            settings,
            params.ticker,
            client=client,
            corpus_dir=settings.corpus.dir,
            index_dir=settings.index.dir,
            embedder_factory=embedder_factory(services),
        )
    for filing in report.filings:
        state_word = (
            f"quarantined: {filing.quarantine}"
            if filing.quarantine
            else f"{filing.chunks} chunks"
        )
        context.log(
            f"{filing.form} filed {filing.filing_date}: {filing.file_name}, "
            f"{state_word}"
        )
    context.progress(len(report.filings), len(report.filings))
    return jobs.JobOutput(
        report.model_dump(mode="json"), reload=report.index_built
    )


def run_refresh(
    services: state.Services, context: jobs.JobContext, params: RefreshParams
) -> jobs.JobOutput:
    """The `refresh` job: new filings of the watched tickers (26.3).

    Args:
        services: The shared services.
        context: The job.
        params: The dry run flag.

    Returns:
        The refresh report with its counts; the index reloads when a
        filing was added.
    """
    context.phase("checking EDGAR")
    report = refresh.run_refresh(
        services.settings,
        dry_run=params.dry_run,
        embedder_factory=embedder_factory(services),
    )
    for result in report.tickers:
        if result.error:
            context.log(f"{result.ticker}: error: {result.error}")
        elif not result.new:
            context.log(f"{result.ticker}: up to date")
        for ref in result.new:
            context.log(
                f"{result.ticker}: new {ref.form} filed {ref.filing_date}"
            )
    context.progress(len(report.tickers), len(report.tickers))
    summary = report.model_dump(mode="json")
    summary.update(
        new_count=report.new_count,
        added_count=report.added_count,
        error_count=report.error_count,
    )
    reload = not params.dry_run and report.added_count > 0
    return jobs.JobOutput(summary, reload=reload)


def _counted(context: jobs.JobContext, total: int) -> warm_cache.Printer:
    seen = [0]

    def printer(line: str) -> None:
        seen[0] += 1
        context.log(line)
        context.progress(seen[0], total)

    return printer


def run_warm_cache(
    services: state.Services,
    context: jobs.JobContext,
    params: WarmCacheParams,
) -> jobs.JobOutput:
    """The `warm_cache` job: the facts pre-fetch and the demo answers.

    It answers through the server's pipeline on the server's event loop,
    so the budget, the breaker, and the audit log apply as for any
    question.

    Args:
        services: The shared services.
        context: The job.
        params: The refresh and facts-only flags.

    Returns:
        The counts of the facts files and of the answers.

    Raises:
        ConfigError: Offline mode is on.
        IndexMissingError: No index is loaded.
    """
    settings = services.settings
    if settings.offline:
        raise errors.ConfigError(
            "warm-cache needs the provider and EDGAR; unset KEEL_OFFLINE"
        )
    answerer = services.answerer
    if answerer is None:
        raise errors.IndexMissingError("no index is loaded")
    context.phase("fetching the company facts")
    tickers = warm_cache.corpus_tickers(
        answerer.retriever.catalog, settings.demo.add_companies
    )
    facts_config = edgar.load_facts_config(settings.edgar.facts)
    with edgar.EdgarClient.from_settings(settings, offline=False) as client:
        prefetch = warm_cache.prefetch_facts(
            client, facts_config, tickers, refresh=params.refresh
        )
    context.log(
        f"facts: {len(prefetch.tickers)} tickers, {len(prefetch.fetched)} "
        f"fetched, {len(prefetch.cached)} cached, {len(prefetch.failed)} "
        f"failed, {prefetch.requests} requests"
    )
    result: dict[str, Any] = {
        "facts": {
            "tickers": len(prefetch.tickers),
            "fetched": len(prefetch.fetched),
            "cached": len(prefetch.cached),
            "failed": list(prefetch.failed),
            "requests": prefetch.requests,
        }
    }
    if params.facts_only:
        result["ok"] = not prefetch.failed
        return jobs.JobOutput(result)
    context.phase("answering the demo questions")
    golden_set = golden.load_golden(warm_cache.DEFAULT_GOLDEN)
    questions = warm_cache.demo_questions(
        settings.demo.example_questions, golden_set
    )
    results = context.run_async(
        warm_cache.warm_answers(
            answerer,
            questions,
            refresh=params.refresh,
            printer=_counted(context, len(questions)),
        )
    )
    counts = collections.Counter(r.status for r in results)
    result["answers"] = {
        "questions": len(questions),
        **{s: counts[s] for s in ("answered", "refusal", "skipped", "failed")},
        "model_requests": sum(r.model_requests for r in results),
        "cost_usd": round(sum(r.cost_usd for r in results), 4),
    }
    result["ok"] = not prefetch.failed and not counts["failed"]
    return jobs.JobOutput(result)


def run_eval(
    services: state.Services, context: jobs.JobContext, params: EvalParams
) -> jobs.JobOutput:
    """The `eval` job: the golden set, the gates, and the report.

    The report replaces `server.eval_report`, which the eval page shows.

    Args:
        services: The shared services.
        context: The job.
        params: The answers, judge, subset, and ablation flags.

    Returns:
        The run ID, the gates, and the spend.
    """
    settings = services.settings
    golden_path = warm_cache.DEFAULT_GOLDEN
    total = len(golden.load_golden(golden_path).select(params.subset))
    context.progress(0, total)
    variants = runner.ABLATION if params.ablation else (runner.MAIN,)
    setup = runner.AnswerSetup(judge=params.judge) if params.answers else None
    context.phase("running the golden set")
    run, questions = runner.evaluate(
        settings,
        golden_path,
        golden_path.parent / "labels",
        subset=params.subset,
        variants=variants,
        progress=_counted(context, total),
        answers=setup,
    )
    report_path = eval_report.write(run, questions, settings.server.eval_report)
    gate_rows = [
        {
            "name": result.gate.name,
            "value": result.value,
            "status": result.status,
        }
        for result in run.gates()
    ]
    spend = sum(r.cost_usd for r in run.answers)
    judge_cost = run.answer_values().get("judge_cost_usd") if run.answers else 0
    return jobs.JobOutput(
        {
            "run_id": run.info.run_id,
            "questions": len(questions),
            "seconds": round(run.seconds, 1),
            "report": str(settings.server.eval_report),
            "results": report_path.name,
            "gates": gate_rows,
            "answers_usd": round(spend, 4),
            "judge_usd": round(float(judge_cost or 0.0), 4),
        }
    )


def run_facts(
    services: state.Services, context: jobs.JobContext, params: TickerParams
) -> jobs.JobOutput:
    """The `facts` job: the company facts lines of 1 ticker.

    Args:
        services: The shared services.
        context: The job.
        params: The ticker.

    Returns:
        The facts lines and their counts.
    """
    settings = services.settings
    context.phase("fetching the company facts")
    facts_config = edgar.load_facts_config(settings.edgar.facts)
    with edgar.EdgarClient.from_settings(settings) as client:
        cik = client.cik(params.ticker)
        document = client.company_facts(cik)
        requests = client.requests
    block = edgar.facts_lines(document.data, params.ticker, facts_config)
    lines = block.text().splitlines()
    context.progress(1, 1)
    return jobs.JobOutput(
        {
            "ticker": params.ticker.upper(),
            "cik": cik,
            "lines": lines,
            "line_count": len(block.lines),
            "dropped": block.dropped,
            "fetched_at": document.fetched_at.isoformat(timespec="seconds"),
            "requests": requests,
        }
    )


def run_backup(
    services: state.Services, context: jobs.JobContext, params: BackupParams
) -> jobs.JobOutput:
    """The `backup` job: the checksummed archive in the backup directory.

    Args:
        services: The shared services.
        context: The job.
        params: The index-only flag.

    Returns:
        The archive name, its sha256, and its members.
    """
    settings = services.settings
    context.phase("writing the archive")
    result = backup.create_backup(
        settings.index.dir,
        None if params.index_only else settings.logs.dir,
        settings.scheduler.backup_dir,
    )
    context.progress(1, 1)
    return jobs.JobOutput(
        {
            "archive": result.archive.name,
            "sha256": result.sha256,
            "members": list(result.members),
            "size_bytes": result.archive.stat().st_size,
        }
    )


def find_archive(
    settings: config.Settings, name: str
) -> backup.BackupInfo | None:
    """Find an archive of the backup directory by its exact name.

    Args:
        settings: The loaded settings.
        name: The archive name.

    Returns:
        The archive, or None when the listing has no such name.
    """
    for item in backup.list_backups(settings.scheduler.backup_dir):
        if item.name == name:
            return item
    return None


def run_restore(
    services: state.Services, context: jobs.JobContext, params: RestoreParams
) -> jobs.JobOutput:
    """The `restore` job: an archive as the current build.

    Args:
        services: The shared services.
        context: The job.
        params: The archive name.

    Returns:
        The restored build; the index reloads.

    Raises:
        BackupError: The archive is no longer in the listing.
    """
    settings = services.settings
    found = find_archive(settings, params.archive)
    if found is None:
        raise errors.BackupError("the archive is not in the backup directory")
    context.phase("checking and extracting the archive")
    result = backup.restore_backup(
        found.path, settings.index.dir, settings.logs.dir
    )
    context.progress(1, 1)
    return jobs.JobOutput(
        {
            "archive": found.name,
            "build": result.build_dir.name,
            "previous": result.previous.name if result.previous else None,
            "index_version": result.manifest.index_version,
            "restored_logs": (
                result.extra_dir.name if result.extra_dir else None
            ),
        },
        reload=True,
    )


def run_index(
    services: state.Services, context: jobs.JobContext, params: IndexParams
) -> jobs.JobOutput:
    """The `index` job: build and publish an index (chapter 9).

    Args:
        services: The shared services.
        context: The job.
        params: The incremental flag.

    Returns:
        The build, its version, and its counts; the index reloads.
    """
    settings = services.settings
    ensure_corpus(settings, context)
    context.phase("building the index")
    result = indexer.build_index(
        settings,
        settings.corpus.dir,
        settings.index.dir,
        embedder_factory(services),
        incremental=params.incremental,
        progress=context.progress,
    )
    manifest = result.manifest
    counts = manifest.counts
    context.log(
        f"files {counts.files}, indexed {counts.indexed}, quarantined "
        f"{counts.quarantined}, chunks {counts.chunks}"
    )
    return jobs.JobOutput(
        {
            "build": pathlib.Path(result.build_dir).name,
            "index_version": manifest.index_version,
            "counts": counts.model_dump(mode="json"),
            "seconds": manifest.build.seconds,
        },
        reload=True,
    )


SPECS: dict[str, jobs.JobSpec] = {
    spec.kind: spec
    for spec in (
        jobs.JobSpec("add", TickerParams, True, run_add, "keel add"),
        jobs.JobSpec(
            "refresh", RefreshParams, True, run_refresh, "keel refresh"
        ),
        jobs.JobSpec(
            "warm_cache",
            WarmCacheParams,
            True,
            run_warm_cache,
            "keel warm-cache",
        ),
        jobs.JobSpec("eval", EvalParams, True, run_eval, "keel eval"),
        jobs.JobSpec("facts", TickerParams, False, run_facts, "keel facts"),
        jobs.JobSpec("backup", BackupParams, True, run_backup, "keel backup"),
        jobs.JobSpec(
            "restore", RestoreParams, True, run_restore, "keel restore"
        ),
        jobs.JobSpec("index", IndexParams, True, run_index, "keel index"),
    )
}
