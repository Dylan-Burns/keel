"""`keel refresh`: new filings of the watched tickers (chapter 26.3).

For each ticker on the watch list and each ticker that `keel add` brought
in (the `added` entries of the corpus manifest), the refresh reads the
submissions of the company again, picks the latest 10-K and the latest
10-Q, and compares their accession numbers with the ones the corpus and
the index already hold: the `added` entries of the manifest and the
archive URLs of the `filings` table of the current build. A filing with an
unknown accession number is new. A dry run lists the new filings; a real
run passes their forms to the `keel add` path, which writes the files and
runs the incremental build.

Every run appends JSON lines to `<logs.dir>/refresh.log`: 1 `start` line,
1 line per new, added, or quarantined filing and per error, and 1 `done`
line. `added_since` reads the `added` lines after a point in time; the
front-end banner of chapter 26.3, step 4, lists them.

`run_refresh` is the entry point of the CLI and of the in-app scheduler
(chapter 29.9, at `scheduler.refresh_at`). The requests go through the
EDGAR client, so the rate limit, the allow list, and the disk cache hold.
No model request happens here (decisions D-01 and D-02).
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import datetime
import json
import logging
import pathlib
import re
import sqlite3
from typing import Literal
from typing import Protocol

import pydantic

from keel import add
from keel import config
from keel import edgar
from keel import errors
from keel import indexer
from keel import inventory
from keel import steps
from keel.stores import chunk_store
from keel.stores import numpy_dense
from keel.stores import state_store

logger = logging.getLogger(__name__)

LOG_NAME = "refresh.log"
# The accession folder of an archive URL: `.../data/<cik>/<18 digits>/`.
_ARCHIVE_FOLDER = re.compile(
    r"/Archives/edgar/data/\d+/(\d{10})(\d{2})(\d{6})/"
)

Event = Literal["start", "new", "added", "quarantined", "error", "done"]
Clock = Callable[[], datetime.datetime]
# The steps of a refresh run, for the step list of an admin job.
STEPS = (
    steps.StepDef("watch", "Read the watch list"),
    steps.StepDef("check", "Check EDGAR for new filings"),
    steps.StepDef("add", "Add the new filings"),
)


class Adder(Protocol):  # pylint: disable=too-few-public-methods
    """The signature of `add.add_ticker`, which a test can wrap."""

    def __call__(
        self,
        settings: config.Settings,
        ticker: str,
        *,
        client: edgar.EdgarClient,
        corpus_dir: pathlib.Path,
        index_dir: pathlib.Path,
        embedder_factory: indexer.EmbedderFactory,
        forms: Sequence[str] = edgar.ADD_FORMS,
        reporter: steps.Reporter = steps.NULL,
    ) -> add.AddReport:
        """Add the latest filings of the forms for 1 ticker.

        Args:
            settings: The loaded settings.
            ticker: The ticker.
            client: The EDGAR client.
            corpus_dir: The corpus directory.
            index_dir: The index directory.
            embedder_factory: Loads the embedder.
            forms: The forms to add.
            reporter: Receives the add steps and their log lines;
                `run_refresh` always passes it, so a custom adder takes
                the keyword.

        Returns:
            The `keel add` report.
        """


class LogEntry(pydantic.BaseModel):
    """1 line of `refresh.log`.

    Attributes:
        time: When the line was written, UTC.
        event: `start`, `new`, `added`, `quarantined`, `error`, or `done`.
        dry_run: True when the run only listed new filings.
        ticker: The ticker, for a filing or an error line.
        form: `10-K` or `10-Q`.
        accession: The accession number.
        filing_date: The filing date.
        url: The archive URL of the primary document.
        file_name: The corpus file written.
        filing_id: The filing ID from the parse.
        detail: The error message, the quarantine reason, or the counts.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="ignore")

    time: datetime.datetime
    event: Event
    dry_run: bool = False
    ticker: str | None = None
    form: str | None = None
    accession: str | None = None
    filing_date: datetime.date | None = None
    url: str | None = None
    file_name: str | None = None
    filing_id: str | None = None
    detail: str | None = None

    @pydantic.field_validator("time")
    @classmethod
    def _utc(cls, value: datetime.datetime) -> datetime.datetime:
        # A naive time (an injected clock, a hand-edited line) reads as UTC,
        # so `added_since` always compares aware values.
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value


class TickerResult(pydantic.BaseModel):
    """What the refresh found and did for 1 ticker.

    Attributes:
        ticker: The ticker as the corpus spells it.
        new: The latest filings whose accession numbers were unknown.
        added: The `keel add` reports of the new filings (empty on a dry
            run).
        error: The error message, or None.
    """

    ticker: str
    new: list[edgar.FilingRef] = pydantic.Field(default_factory=list)
    added: list[add.FilingReport] = pydantic.Field(default_factory=list)
    error: str | None = None


class RefreshReport(pydantic.BaseModel):
    """The result of 1 `keel refresh` run.

    Attributes:
        dry_run: True when the run only listed new filings.
        tickers: 1 result per ticker checked, in ticker order.
        requests: The EDGAR requests of this run.
    """

    dry_run: bool
    tickers: list[TickerResult]
    requests: int = 0

    @property
    def new_count(self) -> int:
        """Count the new filings found.

        Returns:
            The number of new filings across the tickers.
        """
        return sum(len(result.new) for result in self.tickers)

    @property
    def added_count(self) -> int:
        """Count the filings added and indexed (not quarantined).

        Returns:
            The number of added filings across the tickers.
        """
        return sum(
            1
            for result in self.tickers
            for filing in result.added
            if filing.quarantine is None
        )

    @property
    def error_count(self) -> int:
        """Count the tickers that failed.

        Returns:
            The number of tickers with an error.
        """
        return sum(1 for result in self.tickers if result.error)


def log_path(settings: config.Settings) -> pathlib.Path:
    """Return the refresh log file of the settings.

    Args:
        settings: The loaded settings.

    Returns:
        `<logs.dir>/refresh.log`.
    """
    return settings.logs.dir / LOG_NAME


def _manifest_added(corpus_dir: pathlib.Path) -> dict[str, dict[str, str]]:
    """Read the `added` entries of the corpus manifest (absent is empty)."""
    path = corpus_dir / add.MANIFEST
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise errors.ManifestMissingError(
            f"manifest unusable at {path}: {error}"
        ) from error
    added = data.get("added") if isinstance(data, dict) else None
    if not isinstance(added, dict):
        return {}
    return {
        str(name): {str(k): str(v) for k, v in entry.items()}
        for name, entry in added.items()
        if isinstance(entry, dict)
    }


def refresh_tickers(
    settings: config.Settings, corpus_dir: pathlib.Path
) -> list[str]:
    """List the tickers a refresh checks: watched or added from EDGAR.

    Args:
        settings: The loaded settings (the app-state database path).
        corpus_dir: The corpus directory with `manifest.json`.

    Returns:
        The tickers as the corpus spells them, sorted, without repeats.

    Raises:
        StateStoreError: The watch list cannot be read.
        ManifestMissingError: The manifest is not JSON.
    """
    tickers = {
        entry.ticker
        for entry in state_store.list_watch(state_store.state_path(settings))
    }
    for entry in _manifest_added(corpus_dir).values():
        if entry.get("source") == "edgar" and entry.get("ticker"):
            tickers.add(entry["ticker"])
    return sorted(tickers)


def accession_of(url: str | None) -> str | None:
    """Read the accession number from an EDGAR archive URL.

    Args:
        url: A URL such as `.../Archives/edgar/data/19617/000162828026008131/
            jpm-20251231.htm`, or None.

    Returns:
        The accession number, `0001628280-26-008131`, or None.
    """
    match = _ARCHIVE_FOLDER.search(url or "")
    return "-".join(match.groups()) if match else None


def known_accessions(
    corpus_dir: pathlib.Path, index_dir: pathlib.Path
) -> dict[str, set[str]]:
    """Collect the accession numbers that the corpus and the index hold.

    The `added` entries of the manifest name the files `keel add` wrote,
    even a quarantined one, so a quarantined filing is not fetched again
    every night. The `filings` table of the current build covers the
    corpus files, through the archive URL of their header.

    Args:
        corpus_dir: The corpus directory with `manifest.json`.
        index_dir: The index directory; no current build is no rows.

    Returns:
        The accession numbers per corpus ticker.

    Raises:
        ManifestMissingError: The manifest is not JSON.
        IndexCorruptError: The chunk store of the current build is not a
            readable database.
    """
    known: dict[str, set[str]] = {}
    for name, entry in _manifest_added(corpus_dir).items():
        parsed = inventory.parse_filename(name)
        ticker = entry.get("ticker") or (parsed.ticker if parsed else None)
        if ticker and entry.get("accession"):
            known.setdefault(ticker, set()).add(entry["accession"])
    current = indexer.current_build(index_dir)
    if current is None:
        return known
    conn = chunk_store.open_read_only(current / chunk_store.FILE_NAME)
    try:
        rows = conn.execute("SELECT ticker, source_url FROM filings").fetchall()
    except sqlite3.Error as error:
        raise errors.IndexCorruptError(
            f"cannot read the filings of {current}: {error}"
        ) from error
    finally:
        conn.close()
    for ticker, url in rows:
        accession = accession_of(url)
        if accession:
            known.setdefault(str(ticker), set()).add(accession)
    return known


def new_filings(
    submissions: Mapping[str, object],
    known: Iterable[str],
    forms: Sequence[str] = edgar.ADD_FORMS,
) -> list[edgar.FilingRef]:
    """Pick the latest filing of each form whose accession is unknown.

    Args:
        submissions: The submissions JSON (`CachedDocument.data`).
        known: The accession numbers the corpus holds for the company.
        forms: The forms to check.

    Returns:
        The new filings, in `forms` order; empty when the company has none
        of the forms.

    Raises:
        EdgarError: The submissions body is malformed.
    """
    seen = set(known)
    latest: dict[str, edgar.FilingRef] = {}
    for ref in edgar.filings_of(submissions, forms):
        latest.setdefault(ref.form, ref)
    return [
        latest[form]
        for form in forms
        if form in latest and latest[form].accession not in seen
    ]


def append_log(path: pathlib.Path, entries: Iterable[LogEntry]) -> None:
    """Append lines to the refresh log.

    Args:
        path: The log file.
        entries: The lines.

    Raises:
        StateStoreError: The log cannot be written.
    """
    text = "".join(
        entry.model_dump_json(exclude_none=True) + "\n" for entry in entries
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as error:
        raise errors.StateStoreError(f"cannot write {path}: {error}") from error


def read_log(path: pathlib.Path) -> list[LogEntry]:
    """Read the refresh log; a bad line is skipped with a warning.

    Args:
        path: The log file; absent is an empty log.

    Returns:
        The lines in file order.

    Raises:
        StateStoreError: The log exists but cannot be read.
    """
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise errors.StateStoreError(f"cannot read {path}: {error}") from error
    entries: list[LogEntry] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entries.append(LogEntry.model_validate_json(line))
        except pydantic.ValidationError:
            logger.warning("%s:%d is not a refresh log line", path, number)
    return entries


def added_since(path: pathlib.Path, since: datetime.datetime) -> list[LogEntry]:
    """List the filings that a refresh added after a point in time.

    The front-end banner (chapter 26.3, step 4) calls this with the time
    of the user's last visit.

    Args:
        path: The refresh log (`log_path(settings)`).
        since: The point in time; a naive value is read as UTC.

    Returns:
        The `added` lines written after `since`, newest first.

    Raises:
        StateStoreError: The log cannot be read.
    """
    if since.tzinfo is None:
        since = since.replace(tzinfo=datetime.UTC)
    found = [
        entry
        for entry in read_log(path)
        if entry.event == "added" and entry.time > since
    ]
    return sorted(found, key=lambda entry: entry.time, reverse=True)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclasses.dataclass(frozen=True)
class _Run:
    """The state of 1 refresh run: the log file, the mode, the clock."""

    path: pathlib.Path
    dry_run: bool
    clock: Clock

    def log(self, event: Event, **fields: object) -> None:
        """Append 1 line to the refresh log.

        Args:
            event: The event of the line.
            **fields: The other `LogEntry` fields.

        Raises:
            StateStoreError: The log cannot be written.
        """
        entry = LogEntry.model_validate(
            {
                "time": self.clock(),
                "event": event,
                "dry_run": self.dry_run,
                **fields,
            }
        )
        append_log(self.path, [entry])


def _check_ticker(
    run: _Run,
    ticker: str,
    known: set[str],
    client: edgar.EdgarClient,
) -> TickerResult:
    """List the new filings of 1 ticker and log each one."""
    cik = client.cik(ticker)
    submissions = client.submissions(cik, refresh=not client.offline).data
    new = new_filings(submissions, known)
    for ref in new:
        logger.info(
            "%s: new %s filed %s, accession %s",
            ticker,
            ref.form,
            ref.filing_date,
            ref.accession,
        )
        run.log(
            "new",
            ticker=ticker,
            form=ref.form,
            accession=ref.accession,
            filing_date=ref.filing_date,
            url=ref.url,
        )
    return TickerResult(ticker=ticker, new=new)


@dataclasses.dataclass(frozen=True)
class _AddTarget:
    """Where the new filings of a run go."""

    settings: config.Settings
    client: edgar.EdgarClient
    corpus_dir: pathlib.Path
    index_dir: pathlib.Path
    embedder_factory: indexer.EmbedderFactory
    adder: Adder


def _add_new(
    run: _Run,
    found: TickerResult,
    target: _AddTarget,
    reporter: steps.Reporter,
) -> TickerResult:
    """Add the new filings of 1 ticker through `keel add`."""
    report = target.adder(
        target.settings,
        found.ticker,
        client=target.client,
        corpus_dir=target.corpus_dir,
        index_dir=target.index_dir,
        embedder_factory=target.embedder_factory,
        forms=tuple(ref.form for ref in found.new),
        reporter=steps.Prefixed(
            reporter, found.ticker, steps.names_of(add.STEPS)
        ),
    )
    for filing in report.filings:
        run.log(
            "quarantined" if filing.quarantine else "added",
            ticker=report.ticker,
            form=filing.form,
            accession=filing.accession,
            filing_date=filing.filing_date,
            url=filing.url,
            file_name=filing.file_name,
            filing_id=filing.filing_id,
            detail=filing.quarantine,
        )
    return TickerResult(
        ticker=found.ticker, new=found.new, added=report.filings
    )


_TICKER_ERRORS = (errors.KeelError, OSError, sqlite3.Error, ValueError)


def _failed(
    run: _Run, ticker: str, error: Exception, reporter: steps.Reporter
) -> TickerResult:
    """Log the failure of 1 ticker; the run goes on."""
    message = f"{type(error).__name__}: {error}"
    logger.error("refresh %s failed: %s", ticker, message)
    run.log("error", ticker=ticker, detail=message)
    reporter.log(f"{ticker}: error: {message}")
    return TickerResult(ticker=ticker, error=message)


def _check_all(
    run: _Run,
    tickers: Sequence[str],
    known: Mapping[str, set[str]],
    client: edgar.EdgarClient,
    reporter: steps.Reporter,
) -> list[TickerResult]:
    """Check each ticker; a failed ticker is an error result."""
    results: list[TickerResult] = []
    for number, ticker in enumerate(tickers, start=1):
        try:
            found = _check_ticker(run, ticker, known.get(ticker, set()), client)
        except errors.StateStoreError:
            raise
        except _TICKER_ERRORS as error:
            found = _failed(run, ticker, error, reporter)
        else:
            for ref in found.new:
                reporter.log(
                    f"{ticker}: new {ref.form} filed {ref.filing_date}"
                )
            if not found.new:
                reporter.log(f"{ticker}: up to date")
        results.append(found)
        reporter.progress(number, len(tickers), "tickers")
    return results


def _add_all(
    run: _Run,
    results: list[TickerResult],
    pending: Sequence[int],
    target: _AddTarget,
    reporter: steps.Reporter,
) -> None:
    """Add the new filings of each pending result, in place."""
    for number, place in enumerate(pending, start=1):
        reporter.progress(number - 1, len(pending), "tickers")
        found = results[place]
        try:
            results[place] = _add_new(run, found, target, reporter)
        except errors.StateStoreError:
            raise
        except _TICKER_ERRORS as error:
            results[place] = _failed(run, found.ticker, error, reporter)
        reporter.progress(number, len(pending), "tickers")


def run_refresh(  # pylint: disable=too-many-arguments
    settings: config.Settings,
    *,
    dry_run: bool = False,
    client: edgar.EdgarClient | None = None,
    corpus_dir: pathlib.Path | None = None,
    index_dir: pathlib.Path | None = None,
    embedder_factory: indexer.EmbedderFactory | None = None,
    adder: Adder = add.add_ticker,
    clock: Clock = _utc_now,
    reporter: steps.Reporter = steps.NULL,
) -> RefreshReport:
    """Check the watched and added tickers for new filings (26.3).

    A failure on 1 ticker (an unknown ticker, a fetch, a build error) is
    logged and the run goes on with the next ticker. A dry run still
    refreshes the cached submissions, so the list is current. The run
    checks every ticker first, then adds the new filings ticker by
    ticker.

    Args:
        settings: The loaded settings.
        dry_run: List the new filings; write no corpus file and no
            index.
        client: The EDGAR client; None builds one from the settings and
            closes it afterwards. An offline client compares against the
            cached submissions.
        corpus_dir: The corpus directory, or None for `corpus.dir`.
        index_dir: The index directory, or None for `index.dir`.
        embedder_factory: Loads the embedder for the new filings; None
            loads the pinned model from the settings when needed.
        adder: The `keel add` path (`add.add_ticker`).
        clock: The UTC clock of the log lines.
        reporter: Receives the steps of `STEPS`, the line of each ticker,
            and the tickers checked and added.

    Returns:
        The report.

    Raises:
        StateStoreError: The watch list or the log cannot be read or
            written.
        ManifestMissingError: The manifest is not JSON.
        IndexCorruptError: The current build cannot be read.
    """
    corpus = corpus_dir or settings.corpus.dir
    index = index_dir or settings.index.dir
    factory = embedder_factory or (
        lambda: numpy_dense.SentenceEmbedder.from_settings(settings)
    )
    run = _Run(log_path(settings), dry_run, clock)
    reporter.step("watch")
    tickers = refresh_tickers(settings, corpus)
    known = known_accessions(corpus, index)
    reporter.log(f"{len(tickers)} tickers: " + " ".join(tickers))
    run.log("start", detail=f"{len(tickers)} tickers: " + " ".join(tickers))
    owned = client is None
    active = client or edgar.EdgarClient.from_settings(settings)
    requests_before = active.requests
    target = _AddTarget(settings, active, corpus, index, factory, adder)
    try:
        reporter.step("check")
        results = _check_all(run, tickers, known, active, reporter)
        pending = [i for i, r in enumerate(results) if r.new and not r.error]
        if dry_run or not pending:
            reporter.skip(
                "add", "dry run" if dry_run else "no new filing to add"
            )
        else:
            reporter.step("add")
            _add_all(run, results, pending, target, reporter)
        report = RefreshReport(
            dry_run=dry_run,
            tickers=results,
            requests=active.requests - requests_before,
        )
        run.log(
            "done",
            detail=(
                f"{len(tickers)} tickers, {report.new_count} new, "
                f"{report.added_count} added, {report.error_count} errors, "
                f"{report.requests} requests"
            ),
        )
        return report
    finally:
        if owned:
            active.close()
