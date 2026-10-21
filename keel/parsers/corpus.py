"""The corpus pass of the parser: per-ticker facts and the summary.

Some rules need more than 1 file. The fiscal-year-end month of a ticker
comes from its 10-K (chapter 7.9, step 4), and check CK-11 compares the
filing IDs of all files. This module parses every file, applies those 2
rules, and builds the summary that `keel parse --all --summary` prints and
the build report records.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable
import logging
import pathlib
import statistics

import pydantic

from keel import inventory
from keel import parsers
from keel.parsers import base
from keel.parsers import form_10k_10q

logger = logging.getLogger(__name__)

# E-D-21: a file that takes longer than 60 seconds gets a warning.
SLOW_PARSE_SECONDS = 60.0


class CorpusParse(pydantic.BaseModel):
    """The parse of a corpus directory.

    Attributes:
        filings: 1 parsed filing per file, in file name order.
        year_end_months: The fiscal-year-end month per ticker.
        year_end_sources: Where each month came from: `10-K` or `config`.
        notes: Corpus-level findings, 1 sentence each.
    """

    filings: list[base.ParsedFiling]
    year_end_months: dict[str, int]
    year_end_sources: dict[str, str]
    notes: list[str] = pydantic.Field(default_factory=list)


class ParseSummary(pydantic.BaseModel):
    """The numbers the build report records for the parse.

    Attributes:
        files: The files read.
        parsed: The files that pass to the index.
        quarantined: The quarantined files with reason and detail.
        warnings: The warning count per warning code.
        check_status: The count per check and status.
        xbrl_min: The smallest XBRL block and its file.
        xbrl_median: The median XBRL block length.
        xbrl_max: The largest XBRL block and its file.
        no_xbrl_block: The files without an XBRL block.
        period_source_filename: The files whose period comes from the name.
        split_cover_layout: The files whose cover period needed the
            split-cell pattern.
        artifact_removals: The page artifacts removed in all files.
        tables: The tables rebuilt in all files.
        parse_seconds_total: The sum of the parse times.
        parse_seconds_median: The median parse time.
        slowest: The 3 slowest files with their parse times.
        slow_files: Files over 60 seconds (E-D-21).
        year_end_months: The fiscal-year-end month per ticker.
        notes: The corpus-level findings.
    """

    files: int
    parsed: int
    quarantined: list[base.QuarantineRecord]
    warnings: dict[str, int]
    check_status: dict[str, dict[str, int]]
    xbrl_min: tuple[int, str] | None
    xbrl_median: float | None
    xbrl_max: tuple[int, str] | None
    no_xbrl_block: list[str]
    period_source_filename: list[str]
    split_cover_layout: list[str]
    artifact_removals: int
    tables: int
    parse_seconds_total: float
    parse_seconds_median: float
    slowest: list[tuple[str, float]]
    slow_files: list[str]
    year_end_months: dict[str, int]
    notes: list[str]


def parse_files(
    paths: Iterable[pathlib.Path], context: base.ParseContext
) -> list[base.ParsedFiling]:
    """Parse files one by one, each with its form's parser.

    Args:
        paths: The filing files.
        context: The dictionaries and corpus facts.

    Returns:
        1 parsed filing per path, in the given order.
    """
    found: list[base.ParsedFiling] = []
    for path in paths:
        name = inventory.parse_filename(path.name)
        parser = parsers.parser_for(name.form if name else None)
        found.append(parser.parse(path, context))
    return found


def year_end_months(
    filings: Iterable[base.ParsedFiling], fallback: dict[str, int]
) -> tuple[dict[str, int], dict[str, str], list[str]]:
    """Set the fiscal-year-end month per ticker from its latest 10-K.

    Args:
        filings: The parsed filings.
        fallback: The months of `config/fiscal_year_ends.yaml`.

    Returns:
        The month per ticker, the source per ticker (`10-K` or `config`),
        and a note per ticker whose 10-Ks disagree or whose 10-K month
        differs from the config file.
    """
    ten_ks: dict[str, list[base.FilingMetadata]] = collections.defaultdict(list)
    tickers: set[str] = set()
    for filing in filings:
        meta = filing.metadata
        if meta.ticker is None:
            continue
        tickers.add(meta.ticker)
        if (
            not filing.quarantined
            and meta.form == "10-K"
            and meta.period_source == "cover"
            and meta.fiscal_year_end_month is not None
        ):
            ten_ks[meta.ticker].append(meta)
    months: dict[str, int] = {}
    sources: dict[str, str] = {}
    notes: list[str] = []
    for ticker in sorted(tickers):
        reports = ten_ks.get(ticker)
        configured = fallback.get(ticker, base.DECEMBER)
        if not reports:
            months[ticker], sources[ticker] = configured, "config"
            continue
        latest = max(reports, key=lambda m: (m.filing_date, m.file_name))
        month = latest.fiscal_year_end_month or base.DECEMBER
        months[ticker], sources[ticker] = month, "10-K"
        seen = sorted({m.fiscal_year_end_month or 0 for m in reports})
        if len(seen) > 1:
            notes.append(f"{ticker}: 10-K year-end months differ: {seen}")
        if month != configured:
            notes.append(
                f"{ticker}: 10-K year-end month {month}, config {configured}"
            )
    return months, sources, notes


def _apply_fiscal(filing: base.ParsedFiling, month: int) -> base.ParsedFiling:
    meta = form_10k_10q.with_fiscal_period(filing.metadata, month)
    warnings = filing.warnings
    if meta.fiscal_period == "unknown":
        warnings = (*warnings, "fiscal_period_unknown")
    return filing.model_copy(update={"metadata": meta, "warnings": warnings})


def resolve_duplicates(
    filings: list[base.ParsedFiling],
) -> list[base.ParsedFiling]:
    """Apply check CK-11: 1 file per filing ID, the latest filing wins.

    Args:
        filings: The parsed filings.

    Returns:
        The filings in the same order. A duplicate that loses gets a
        quarantine record with the reason `duplicate_filing_id`; the kept
        file gets a CK-11 warning; the others pass.
    """
    groups: dict[str, list[int]] = collections.defaultdict(list)
    for index, filing in enumerate(filings):
        if not filing.quarantined and filing.filing_id:
            groups[filing.filing_id].append(index)
    result = list(filings)
    for identifier, members in groups.items():
        if len(members) == 1:
            result[members[0]] = _with_check(
                result[members[0]],
                base.CheckResult(check="CK-11", status="pass"),
            )
            continue
        ordered = sorted(
            members,
            key=lambda i: (
                filings[i].metadata.filing_date,
                filings[i].metadata.file_name,
            ),
        )
        kept = filings[ordered[-1]].metadata.file_name
        dropped = [filings[i].metadata.file_name for i in ordered[:-1]]
        detail = f"{identifier}: kept {kept}, dropped " + ", ".join(dropped)
        logger.warning("duplicate filing ID %s", detail)
        warning = base.CheckResult(
            check="CK-11", status="warning", detail=detail
        )
        result[ordered[-1]] = _with_check(
            result[ordered[-1]], warning, "duplicate_filing_id"
        )
        for index in ordered[:-1]:
            record = base.QuarantineRecord(
                file_name=filings[index].metadata.file_name,
                reason="duplicate_filing_id",
                detail=detail,
                evidence={"kept": kept},
            )
            result[index] = _with_check(
                result[index], warning, "duplicate_filing_id"
            ).model_copy(update={"quarantine": record})
    return result


def _with_check(
    filing: base.ParsedFiling,
    result: base.CheckResult,
    warning: str | None = None,
) -> base.ParsedFiling:
    warnings = filing.warnings + ((warning,) if warning else ())
    return filing.model_copy(
        update={"checks": (*filing.checks, result), "warnings": warnings}
    )


def parse_corpus(
    corpus_dir: pathlib.Path, context: base.ParseContext
) -> CorpusParse:
    """Parse every filing of a corpus directory.

    Args:
        corpus_dir: The directory with the `*.txt` filings.
        context: The dictionaries and corpus facts.

    Returns:
        The parse with the fiscal fields from the per-ticker months and
        check CK-11 applied.
    """
    return finish_corpus(
        parse_files(sorted(corpus_dir.glob("*.txt")), context), context
    )


def finish_corpus(
    filings: list[base.ParsedFiling], context: base.ParseContext
) -> CorpusParse:
    """Apply the corpus rules to filings parsed one by one.

    Args:
        filings: The parsed filings.
        context: The context of the parse.

    Returns:
        The corpus parse.
    """
    months, sources, notes = year_end_months(filings, context.fiscal_year_ends)
    filings = [
        _apply_fiscal(f, months.get(f.metadata.ticker or "", base.DECEMBER))
        for f in filings
    ]
    filings = resolve_duplicates(filings)
    filings = [
        _with_check(f, base.CheckResult(check="CK-11", status="skipped"))
        if f.check("CK-11") is None
        else f
        for f in filings
    ]
    filings = [
        f.model_copy(update={"warnings": (*f.warnings, "parse_slow")})
        if f.parse_seconds > SLOW_PARSE_SECONDS
        else f
        for f in filings
    ]
    return CorpusParse(
        filings=filings,
        year_end_months=months,
        year_end_sources=sources,
        notes=notes,
    )


def summarize(result: CorpusParse) -> ParseSummary:
    """Build the parse summary of the build report.

    Args:
        result: The corpus parse.

    Returns:
        The summary.
    """
    filings = result.filings
    warnings: collections.Counter[str] = collections.Counter()
    status: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for filing in filings:
        warnings.update(filing.warnings)
        for check in filing.checks:
            status[check.check][check.status] += 1
    blocks = sorted(
        (f.metadata.xbrl_block_chars, f.metadata.file_name)
        for f in filings
        if f.metadata.xbrl_present
    )
    times = sorted(
        ((f.metadata.file_name, f.parse_seconds) for f in filings),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return ParseSummary(
        files=len(filings),
        parsed=sum(not f.quarantined for f in filings),
        quarantined=[f.quarantine for f in filings if f.quarantine],
        warnings=dict(sorted(warnings.items())),
        check_status={
            k: dict(sorted(v.items())) for k, v in sorted(status.items())
        },
        xbrl_min=blocks[0] if blocks else None,
        xbrl_median=statistics.median(b for b, _ in blocks) if blocks else None,
        xbrl_max=blocks[-1] if blocks else None,
        no_xbrl_block=sorted(
            f.metadata.file_name
            for f in filings
            if "no_xbrl_block" in f.warnings
        ),
        period_source_filename=sorted(
            f.metadata.file_name
            for f in filings
            if f.metadata.period_source == "filename"
        ),
        split_cover_layout=sorted(
            f.metadata.file_name
            for f in filings
            if "cover_period_split_layout" in f.warnings
        ),
        artifact_removals=sum(f.metadata.artifact_removals for f in filings),
        tables=sum(len(f.tables) for f in filings),
        parse_seconds_total=sum(t for _, t in times),
        parse_seconds_median=statistics.median(t for _, t in times)
        if times
        else 0.0,
        slowest=times[:3],
        slow_files=sorted(n for n, t in times if t > SLOW_PARSE_SECONDS),
        year_end_months=result.year_end_months,
        notes=result.notes,
    )
