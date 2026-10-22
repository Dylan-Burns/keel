"""Command line entry point for Keel.

Stage 1 ships `keel inventory` and `keel doctor`; stage 2 adds `keel parse`;
stage 3 adds `keel chunk` and `keel parse --sections-report`; stage 4 adds
`keel index`; stage 5 adds `keel understand`; stage 6 adds `keel retrieve`;
stage 7 adds `keel ask`; stage 8 adds `keel calibrate`; stage 9 adds
`keel serve`; stage 10 adds `keel eval`; stage 13 adds `keel facts`; stage
14 adds `keel add`; stage 15 adds `keel warm-cache`; stage 20 adds `keel watch`
and `keel refresh`. Later stages add the commands that CLAUDE.md lists.
"""

import argparse
import asyncio
from collections.abc import Callable
from collections.abc import Sequence
import datetime
import json
import logging
import pathlib
import signal
import sys
import time
from typing import Any

import anthropic

import keel
from keel import add
from keel import answer
from keel import calibrate
from keel import chunker
from keel import config
from keel import context
from keel import doctor
from keel import edgar
from keel import errors
from keel import export
from keel import extractor
from keel import indexer
from keel import inventory
from keel import pilot_cli
from keel import refresh
from keel import retriever
from keel import sections
from keel import security
from keel import understanding
from keel import users
from keel import warm_cache
from keel.api import app as api_app
from keel.evaluation import gates
from keel.evaluation import report as eval_report
from keel.evaluation import runner
from keel.parsers import base as parser_base
from keel.parsers import corpus as parser_corpus
from keel.stores import chunk_store
from keel.stores import numpy_dense
from keel.stores import state_store

logger = logging.getLogger("keel")

# Assumption A-15 asks whether the NVDA 10-K filed in February 2026 is in
# the corpus; the worked example of chapter 11 branches on it.
A15_TICKER = "NVDA"
A15_FILED_FROM = "2026-02-01"
A15_FILED_TO = "2026-02-28"


def _positive(value: str) -> int:
    """Parse a whole number of at least 1 for argparse.

    Args:
        value: The argument text.

    Returns:
        The number.

    Raises:
        ArgumentTypeError: The value is not a whole number of at least 1.
    """
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a number: {value}") from error
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {value}")
    return number


def _facts_arguments() -> argparse.ArgumentParser:
    """Build the arguments of `keel facts` as a parent parser.

    Returns:
        A parser without help that holds the `facts` arguments.
    """
    facts_parser = argparse.ArgumentParser(add_help=False)
    facts_parser.add_argument("ticker", help="the ticker, such as NVDA")
    facts_parser.add_argument(
        "--start",
        type=datetime.date.fromisoformat,
        default=None,
        help="the first period end date to keep (YYYY-MM-DD)",
    )
    facts_parser.add_argument(
        "--end",
        type=datetime.date.fromisoformat,
        default=None,
        help="the last period end date to keep (YYYY-MM-DD)",
    )
    facts_parser.add_argument(
        "--offline",
        action="store_true",
        help="read only the EDGAR cache, make no request",
    )
    return facts_parser


def _doctor_arguments() -> argparse.ArgumentParser:
    """Build the arguments of `keel doctor` as a parent parser.

    Returns:
        A parser without help that holds the `doctor` arguments.
    """
    doctor_parser = argparse.ArgumentParser(add_help=False)
    doctor_parser.add_argument(
        "--download-models",
        action="store_true",
        help="download the 2 pinned Hugging Face models into the cache",
    )
    doctor_parser.add_argument(
        "--json", action="store_true", help="print the results as JSON"
    )
    return doctor_parser


def _add_arguments() -> argparse.ArgumentParser:
    """Build the arguments of `keel add` as a parent parser.

    Returns:
        A parser without help that holds the `add` arguments.
    """
    add_parser = argparse.ArgumentParser(add_help=False)
    add_parser.add_argument("ticker", help="the ticker, such as ZTS")
    add_parser.add_argument(
        "--offline",
        action="store_true",
        help="read only the EDGAR cache, make no request",
    )
    add_parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=None,
        help="the directory of filings (default: corpus.dir)",
    )
    add_parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the index directory with `current` (default: index.dir)",
    )
    return add_parser


def _serve_arguments() -> argparse.ArgumentParser:
    """Build the arguments of `keel serve` as a parent parser.

    Returns:
        A parser without help that holds the `serve` arguments.
    """
    serve_parser = argparse.ArgumentParser(add_help=False)
    serve_parser.add_argument(
        "--host", default=None, help="the bind address (default: server.host)"
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="the port (default: server.port); a busy port moves up to +10",
    )
    return serve_parser


def _eval_arguments() -> argparse.ArgumentParser:
    """Build the arguments of `keel eval` as a parent parser.

    Returns:
        A parser without help that holds the `eval` arguments.
    """
    eval_parser = argparse.ArgumentParser(add_help=False)
    eval_parser.add_argument(
        "--set",
        dest="golden",
        type=pathlib.Path,
        default=pathlib.Path("eval/golden.yaml"),
        help="the golden set (default: eval/golden.yaml)",
    )
    eval_parser.add_argument(
        "--subset",
        default=None,
        help="a subset tag (ci, demo, chunk) or a comma list of IDs",
    )
    eval_parser.add_argument(
        "--gate",
        action="store_true",
        help="exit 1 when a regression gate fails",
    )
    eval_parser.add_argument(
        "--report",
        type=pathlib.Path,
        default=pathlib.Path("eval/report.md"),
        help="the report file; the JSON results go beside it",
    )
    eval_parser.add_argument(
        "--labels",
        type=pathlib.Path,
        default=None,
        help="the labels directory (default: labels/ beside the set)",
    )
    eval_parser.add_argument(
        "--index",
        type=pathlib.Path,
        default=None,
        help="the index directory with `current` (default: index.dir)",
    )
    eval_parser.add_argument(
        "--no-ablation",
        action="store_true",
        help="run the hybrid pipeline only, without the ablation variants",
    )
    eval_parser.add_argument(
        "--answers",
        action="store_true",
        help="also answer each question (1 model request each) and judge it",
    )
    eval_parser.add_argument(
        "--no-judge",
        action="store_true",
        help="with --answers, skip the judge (the code metrics still run)",
    )
    return eval_parser


def _add_pilot_commands(
    add_command: Callable[..., argparse.ArgumentParser],
) -> None:
    """Add the pilot commands of chapter 27.2.

    These are `keel users`, and the comp sets, feedback, and template
    commands of `keel.pilot_cli`.
    """
    _add_users_parser(
        add_command(
            "users", help="the pilot users and their tokens (chapter 27.2)"
        )
    )
    pilot_cli.add_parsers(add_command)


def _add_users_parser(users_parser: argparse.ArgumentParser) -> None:
    """Add `keel users add NAME --role R`, `remove NAME`, and `list`."""
    users_commands = users_parser.add_subparsers(
        dest="users_command", metavar="action", required=True
    )
    add_user_parser = users_commands.add_parser(
        "add", help="add a user and print the new token once"
    )
    add_user_parser.add_argument("name", help="the user name, lowercase")
    add_user_parser.add_argument(
        "--role", required=True, choices=users.ROLES, help="the role"
    )
    remove_user_parser = users_commands.add_parser(
        "remove", help="remove a user, which revokes their token"
    )
    remove_user_parser.add_argument("name", help="the user name")
    users_commands.add_parser("list", help="list the users and their roles")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the `keel` command.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="keel",
        description="Grounded answers to business questions about SEC filings.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"keel {keel.__version__}",
    )
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        default=None,
        help="the YAML config (default: KEEL_CONFIG_FILE or config/keel.yaml)",
    )
    commands = parser.add_subparsers(dest="command", metavar="command")

    inventory_parser = commands.add_parser(
        "inventory",
        help="extract the corpus zip when needed, count it, check the manifest",
    )
    inventory_parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=None,
        help="the corpus directory (default: corpus.dir)",
    )
    inventory_parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=None,
        help="the manifest (default: manifest.json in the corpus directory)",
    )
    inventory_parser.add_argument(
        "--json", action="store_true", help="print the report as JSON"
    )

    parse_parser = commands.add_parser(
        "parse", help="parse filings: header, XBRL cut, cover page, checks"
    )
    parse_parser.add_argument(
        "files", nargs="*", type=pathlib.Path, help="filing files to parse"
    )
    parse_parser.add_argument(
        "--all", action="store_true", help="parse every file of the corpus"
    )
    parse_parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=None,
        help="the corpus directory for --all (default: corpus.dir)",
    )
    parse_parser.add_argument(
        "--summary", action="store_true", help="print the corpus summary"
    )
    parse_parser.add_argument(
        "--json", action="store_true", help="print JSON with 1 row per file"
    )
    parse_parser.add_argument(
        "--sections-report",
        action="store_true",
        help="print the canonical section coverage (chapter 8.6)",
    )

    chunk_parser = commands.add_parser(
        "chunk", help="detect the sections and cut the token chunks"
    )
    chunk_parser.add_argument(
        "files", nargs="*", type=pathlib.Path, help="filing files to chunk"
    )
    chunk_parser.add_argument(
        "--all", action="store_true", help="chunk every file of the corpus"
    )
    chunk_parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=None,
        help="the corpus directory for --all (default: corpus.dir)",
    )
    chunk_parser.add_argument(
        "--summary", action="store_true", help="print the chunk summary"
    )
    chunk_parser.add_argument(
        "--json", action="store_true", help="print the summary as JSON"
    )

    index_parser = commands.add_parser(
        "index", help="build the chunk store, FTS5, vectors, and manifest"
    )
    index_parser.add_argument(
        "--incremental",
        action="store_true",
        help="embed only new or changed filings; reuse the other shards",
    )
    index_parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=None,
        help="the directory of filings (default: corpus.dir)",
    )
    index_parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the index directory with `current` (default: index.dir)",
    )

    understand_parser = commands.add_parser(
        "understand", help="resolve a question without a model call"
    )
    understand_parser.add_argument("question", help="the question")
    understand_parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=None,
        help="the corpus directory (default: corpus.dir)",
    )

    retrieve_parser = commands.add_parser(
        "retrieve", help="retrieve the context of a question, no model call"
    )
    retrieve_parser.add_argument(
        "text", nargs="?", default=None, help="the question"
    )
    retrieve_parser.add_argument(
        "--question",
        type=int,
        default=None,
        help="the number of an example question in demo.example_questions",
    )
    retrieve_parser.add_argument(
        "--summary", action="store_true", help="print the plan and the counts"
    )
    retrieve_parser.add_argument(
        "--index",
        type=pathlib.Path,
        default=None,
        help="the index directory with `current` (default: index.dir)",
    )

    ask_parser = commands.add_parser(
        "ask", help="answer a question with 1 model request"
    )
    ask_parser.add_argument("question", help="the question")
    ask_parser.add_argument(
        "--json", action="store_true", help="print the full answer record"
    )
    ask_parser.add_argument(
        "--cached",
        action="store_true",
        help="serve the answer cache when it holds the question",
    )
    ask_parser.add_argument(
        "--index",
        type=pathlib.Path,
        default=None,
        help="the index directory with `current` (default: index.dir)",
    )

    calibrate_parser = commands.add_parser(
        "calibrate",
        help="measure the token calibration factor with 1 count call",
    )
    calibrate_parser.add_argument(
        "--sample",
        type=_positive,
        default=calibrate.SAMPLE_SIZE,
        help="the chunks in the sample (default: 200, chapter 11.6)",
    )
    calibrate_parser.add_argument(
        "--index",
        type=pathlib.Path,
        default=None,
        help="the index directory with `current` (default: index.dir)",
    )

    commands.add_parser(
        "serve",
        parents=[_serve_arguments()],
        help="serve the API and the front-end (chapter 14)",
    )

    commands.add_parser(
        "eval",
        parents=[_eval_arguments()],
        help="run the golden set and write the eval report",
    )

    for name, parent, text in (
        ("facts", _facts_arguments(), "print the facts lines of 1 ticker"),
        ("warm-cache", warm_cache.add_arguments(), warm_cache.HELP),
    ):
        commands.add_parser(name, parents=[parent], help=text)

    commands.add_parser(
        "add",
        parents=[_add_arguments()],
        help="add the latest 10-K and 10-Q of 1 company from EDGAR",
    )

    _add_pilot_commands(commands.add_parser)

    _add_refresh_commands(commands)

    commands.add_parser(
        "doctor",
        parents=[_doctor_arguments()],
        help="check the environment: FTS5, models, keys, clock, ports",
    )
    export.add_arguments(
        commands.add_parser("export", help="write a stored answer as a memo")
    )
    return parser


def _add_refresh_commands(
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Add `keel watch` and `keel refresh` to the subcommands (26.3)."""
    watch_parser = commands.add_parser(
        "watch", help="add, remove, or list the watched tickers"
    )
    watch_parser.add_argument(
        "action", choices=("add", "remove", "list"), help="what to do"
    )
    watch_parser.add_argument(
        "tickers", nargs="*", help="the tickers, such as ZTS WDAY"
    )
    watch_parser.add_argument(
        "--user",
        default=None,
        help=f"the user (default: {state_store.DEFAULT_USER}; list: all users)",
    )

    refresh_parser = commands.add_parser(
        "refresh", help="add the new 10-K and 10-Q of the watched tickers"
    )
    refresh_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the new filings; write no corpus file and no index",
    )
    refresh_parser.add_argument(
        "--offline",
        action="store_true",
        help="compare against the cached submissions, make no request",
    )
    refresh_parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=None,
        help="the directory of filings (default: corpus.dir)",
    )
    refresh_parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the index directory with `current` (default: index.dir)",
    )


def _ensure_corpus(settings: config.Settings, corpus_dir: pathlib.Path) -> None:
    """Extract the corpus zip when the corpus directory holds no filings."""
    if corpus_dir.is_dir() and any(corpus_dir.glob("*.txt")):
        return
    if corpus_dir != settings.corpus.dir or not settings.corpus.zip.is_file():
        raise errors.CorpusMissingError(
            f"no filings in {corpus_dir} and no zip at {settings.corpus.zip}"
        )
    result = extractor.extract_zip(settings.corpus.zip, corpus_dir)
    print(f"extracted {result.file_count} files from {settings.corpus.zip}")


def _a15_line(report: inventory.InventoryReport) -> str:
    latest = report.latest(A15_TICKER, "10-K")
    if latest is None:
        return f"A-15: no {A15_TICKER} 10-K in the corpus"
    filed = latest.filing_date.isoformat()
    present = A15_FILED_FROM <= filed <= A15_FILED_TO
    verdict = "present" if present else "absent"
    return (
        f"A-15: {A15_TICKER} 10-K filed February 2026 is {verdict} "
        f"(latest {A15_TICKER} 10-K: {latest.name})"
    )


def _print_inventory(report: inventory.InventoryReport) -> None:
    forms = ", ".join(f"{k} {v}" for k, v in report.form_counts.items())
    years = ", ".join(f"{k} {v}" for k, v in report.year_counts.items())
    patterns = ", ".join(f"{k} {v}" for k, v in report.pattern_counts.items())
    print(f"corpus: {report.corpus_dir}")
    print(f"files: {report.file_count} ({report.total_bytes:,} bytes)")
    print(f"tickers: {report.ticker_count}")
    print(f"forms: {forms}")
    print(f"filing years: {years}")
    if report.first_filing and report.last_filing:
        print(
            f"filing dates: {report.first_filing[0]} ({report.first_filing[1]})"
            f" to {report.last_filing[0]} ({report.last_filing[1]})"
        )
    print(f"file name patterns: {patterns}")
    for shape, count in report.header_shapes.items():
        print(f"header keys ({count} files): {shape}")
    quarterly = ", ".join(report.quarterly_tickers)
    full = ", ".join(report.full_quarterly_tickers)
    print(f"tickers with 10-Qs: {len(report.quarterly_tickers)} ({quarterly})")
    print(
        "full quarterly coverage 2023-2025: "
        f"{len(report.full_quarterly_tickers)} ({full})"
    )
    largest = ", ".join(f"{n} {s:,}" for n, s in report.largest_files)
    print(f"largest files: {largest}")
    if report.date_filter_excluded:
        print(f"outside the date filter: {len(report.date_filter_excluded)}")
    manifest = report.manifest
    print("manifest: " + ("present" if manifest.present else "absent"))
    if manifest.present:
        print(f"manifest license: {manifest.license}")
    print(_a15_line(report))
    print(f"discrepancies: {len(report.discrepancies)}")
    for line in report.discrepancies:
        print(f"  - {line}")


def run_inventory(
    settings: config.Settings,
    corpus_dir: pathlib.Path | None,
    manifest_path: pathlib.Path | None,
    as_json: bool,
) -> int:
    """Run `keel inventory`.

    Args:
        settings: The loaded settings.
        corpus_dir: The corpus directory, or None for `corpus.dir`.
        manifest_path: The manifest, or None for the corpus manifest.
        as_json: Print JSON instead of text.

    Returns:
        The process exit code.
    """
    directory = corpus_dir or settings.corpus.dir
    _ensure_corpus(settings, directory)
    if manifest_path is None:
        manifest_path = (
            settings.corpus.manifest
            if corpus_dir is None
            else directory / "manifest.json"
        )
    report = inventory.build_inventory(
        directory, manifest_path, settings.corpus.date_filter
    )
    if as_json:
        payload = report.model_dump(mode="json", exclude={"files"})
        payload["a15"] = _a15_line(report)
        print(json.dumps(payload, indent=2))
    else:
        _print_inventory(report)
    return 0


def _file_row(filing: parser_base.ParsedFiling) -> dict[str, object]:
    meta = filing.metadata
    return {
        "file": meta.file_name,
        "filing_id": filing.filing_id,
        "fiscal": f"{meta.fiscal_period} {meta.fiscal_year}",
        "period_end": str(meta.period_end_date),
        "period_source": meta.period_source,
        "xbrl_block_chars": meta.xbrl_block_chars,
        "tables": len(filing.tables),
        "seconds": round(filing.parse_seconds, 3),
        "warnings": list(filing.warnings),
        "quarantine": filing.quarantine.reason if filing.quarantine else None,
    }


def _print_parse_summary(summary: parser_corpus.ParseSummary) -> None:
    print(f"files: {summary.files}")
    print(f"parsed: {summary.parsed}")
    print(f"quarantined: {len(summary.quarantined)}")
    for record in summary.quarantined:
        evidence = ", ".join(f"{k}={v}" for k, v in record.evidence.items())
        print(f"  - {record.file_name}: {record.reason} ({record.detail})")
        if evidence:
            print(f"    evidence: {evidence}")
    warnings = ", ".join(f"{k} {v}" for k, v in summary.warnings.items())
    print("warnings: " + (warnings or "none"))
    for check, counts in summary.check_status.items():
        line = ", ".join(f"{k} {v}" for k, v in counts.items())
        print(f"  {check}: {line}")
    if summary.xbrl_min and summary.xbrl_max:
        print(
            f"xbrl_block_chars: min {summary.xbrl_min[0]:,} "
            f"({summary.xbrl_min[1]}), median {summary.xbrl_median:,.0f}, "
            f"max {summary.xbrl_max[0]:,} ({summary.xbrl_max[1]})"
        )
    print(
        f"no XBRL block: {len(summary.no_xbrl_block)} "
        + "("
        + ", ".join(summary.no_xbrl_block)
        + ")"
    )
    print(
        "period_source=filename: "
        f"{len(summary.period_source_filename)} "
        + "("
        + ", ".join(summary.period_source_filename)
        + ")"
    )
    print(
        f"cover period from split cells: {len(summary.split_cover_layout)} "
        + "("
        + ", ".join(summary.split_cover_layout)
        + ")"
    )
    print(f"artifact removals: {summary.artifact_removals:,}")
    print(f"tables rebuilt: {summary.tables:,}")
    slowest = ", ".join(f"{n} {t:.2f} s" for n, t in summary.slowest)
    print(
        f"parse time: total {summary.parse_seconds_total:.1f} s, median "
        f"{summary.parse_seconds_median:.3f} s, slowest {slowest}"
    )
    print(f"files over 60 s: {len(summary.slow_files)}")
    months = ", ".join(
        f"{t} {m}" for t, m in summary.year_end_months.items() if m != 12
    )
    print(f"non-December fiscal year ends: {months}")
    for note in summary.notes:
        print(f"note: {note}")


def _parse(
    settings: config.Settings,
    files: list[pathlib.Path],
    parse_all: bool,
    corpus_dir: pathlib.Path | None,
) -> parser_corpus.CorpusParse:
    """Parse the named files, or the whole corpus with `parse_all`."""
    directory = corpus_dir or settings.corpus.dir
    if parse_all:
        _ensure_corpus(settings, directory)
        files = sorted(directory.glob("*.txt"))
    manifest_path = directory / "manifest.json"
    manifest_files = None
    try:
        manifest_files = inventory.load_manifest(manifest_path).files
    except errors.ManifestMissingError as error:
        logger.warning("%s", error)
    parse_context = parser_base.ParseContext.from_settings(
        settings, manifest_files
    )
    return parser_corpus.finish_corpus(
        parser_corpus.parse_files(files, parse_context), parse_context
    )


def _print_sections_report(report: sections.SectionsReport) -> None:
    for form, count in sorted(report.filings.items()):
        core = ", ".join(
            sections.CORE_10K if form == "10-K" else sections.CORE_10Q
        )
        print(
            f"{form}: {count} filings, {report.core_complete[form]} with "
            f"every core section ({core}): {report.core_share[form]:.1%}"
        )
        present = ", ".join(
            f"{name} {n}" for name, n in report.present[form].items()
        )
        print(f"  filings with the section: {present}")
        spans = ", ".join(
            f"{name} {n}" for name, n in report.spans[form].items() if n
        )
        print(f"  spans: {spans}")
    warnings = ", ".join(f"{k} {v}" for k, v in report.warnings.items())
    print("section warnings: " + (warnings or "none"))
    for file_name, absent in report.incomplete:
        absent_names = ", ".join(absent)
        print(f"  - {file_name}: no {absent_names}")


def _sections_report(
    result: parser_corpus.CorpusParse,
) -> sections.SectionsReport:
    rows = [
        (
            f.metadata.file_name,
            f.metadata.form or "",
            sections.detect(f.text, f.metadata.form or ""),
        )
        for f in result.filings
        if not f.quarantined
    ]
    return sections.coverage_report(rows)


def run_parse(
    settings: config.Settings,
    files: list[pathlib.Path],
    *,
    parse_all: bool,
    corpus_dir: pathlib.Path | None,
    show_summary: bool,
    as_json: bool,
    sections_report: bool = False,
) -> int:
    """Run `keel parse`.

    Args:
        settings: The loaded settings.
        files: The files to parse when `parse_all` is False.
        parse_all: Parse every file of the corpus directory.
        corpus_dir: The corpus directory, or None for `corpus.dir`.
        show_summary: Print the summary instead of 1 line per file.
        as_json: Print JSON instead of text.
        sections_report: Print the section coverage of chapter 8.6.

    Returns:
        The process exit code: 2 without files to parse, else 0.

    Raises:
        CorpusMissingError: `--all` finds no filings and no zip.
        ConfigError: A parser dictionary is absent or invalid.
    """
    if not parse_all and not files:
        logger.error("name files to parse, or pass --all")
        return 2
    result = _parse(settings, files, parse_all, corpus_dir)
    summary = parser_corpus.summarize(result)
    report = _sections_report(result) if sections_report else None
    if as_json:
        payload: dict[str, object] = {
            "files": [_file_row(f) for f in result.filings]
        }
        if show_summary:
            payload["summary"] = summary.model_dump(mode="json")
        if report is not None:
            payload["sections"] = report.model_dump(mode="json")
        print(json.dumps(payload, indent=2))
    elif show_summary or report is not None:
        if show_summary:
            _print_parse_summary(summary)
        if report is not None:
            _print_sections_report(report)
    else:
        for filing in result.filings:
            row = _file_row(filing)
            fields = (
                row["quarantine"] or "ok",
                row["filing_id"],
                row["fiscal"],
                str(row["seconds"]) + " s",
            )
            print(str(row["file"]) + ": " + ", ".join(str(f) for f in fields))
    return 0


def _print_chunk_summary(summary: chunker.ChunkSummary) -> None:
    print(f"filings chunked: {summary.filings}")
    print(f"chunks: {summary.chunks:,}")
    print(
        "by form: "
        + ", ".join(f"{k} {v:,}" for k, v in summary.by_form.items())
    )
    print(
        "by section: "
        + ", ".join(f"{k} {v:,}" for k, v in summary.by_section.items())
    )
    print(
        f"table chunks: {summary.tables:,}, split sentences: "
        f"{summary.split_sentences:,}, forward_looking: "
        f"{summary.forward_looking:,}, delta_only: {summary.delta_only:,}"
    )
    print(
        f"tokens per chunk: mean {summary.tokens_mean}, median "
        f"{summary.tokens_median}, p95 {summary.tokens_p95}, min "
        f"{summary.tokens_min}, max {summary.tokens_max}; over the limit: "
        f"{summary.over_limit}"
    )
    print(f"chunk time: {summary.seconds} s")


def run_chunk(
    settings: config.Settings,
    files: list[pathlib.Path],
    *,
    chunk_all: bool,
    corpus_dir: pathlib.Path | None,
    as_json: bool,
) -> int:
    """Run `keel chunk`: parse, detect the sections, cut the chunks.

    Args:
        settings: The loaded settings.
        files: The files to chunk when `chunk_all` is False.
        chunk_all: Chunk every file of the corpus directory.
        corpus_dir: The corpus directory, or None for `corpus.dir`.
        as_json: Print the summary as JSON.

    Returns:
        The process exit code: 2 without files to chunk, else 0.

    Raises:
        CorpusMissingError: `--all` finds no filings and no zip.
        ConfigError: A parser dictionary is absent or invalid.
        ModelMissingError: The embedding tokenizer is not cached.
    """
    if not chunk_all and not files:
        logger.error("name files to chunk, or pass --all")
        return 2
    counter = chunker.HFTokenCounter.from_settings(settings)
    sizes = chunker.ChunkSizes.from_settings(settings)
    result = _parse(settings, files, chunk_all, corpus_dir)
    started = time.perf_counter()
    chunked = chunker.chunk_filings(result.filings, counter, sizes)
    summary = chunker.summarize(chunked, time.perf_counter() - started)
    if as_json:
        print(json.dumps(summary.model_dump(mode="json"), indent=2))
    else:
        _print_chunk_summary(summary)
    return 0


def _exit_on_sigterm(signum: int, frame: object) -> None:
    del frame
    sys.exit(128 + signum)


def run_index(
    settings: config.Settings,
    *,
    corpus_dir: pathlib.Path | None,
    out_dir: pathlib.Path | None,
    incremental: bool,
) -> int:
    """Run `keel index`: build and publish an index (chapter 9).

    Args:
        settings: The loaded settings.
        corpus_dir: The directory of filings, or None for `corpus.dir`
            (extracted from the zip when empty).
        out_dir: The index directory, or None for `index.dir`.
        incremental: Reuse the shards of unchanged filings.

    Returns:
        The process exit code: 0 after a published build.

    Raises:
        CorpusMissingError: No filings and no zip.
        ModelMissingError: The tokenizer is not cached.
        EmbeddingModelUnavailableError: The embedding model cannot load.
        IndexWriteError: The build cannot be written or published.
    """
    directory = corpus_dir or settings.corpus.dir
    if corpus_dir is None:
        _ensure_corpus(settings, directory)
    # SIGTERM exits through SystemExit, so the build removes its staging
    # directory before the process ends.
    handler = signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        result = indexer.build_index(
            settings,
            directory,
            out_dir or settings.index.dir,
            lambda: numpy_dense.SentenceEmbedder.from_settings(settings),
            incremental=incremental,
        )
    finally:
        signal.signal(signal.SIGTERM, handler)
    manifest = result.manifest
    counts = manifest.counts
    build = manifest.build
    print(f"build: {result.build_dir}")
    print(f"index version: {manifest.index_version}")
    print(
        f"files {counts.files}, indexed {counts.indexed}, quarantined "
        f"{counts.quarantined}, chunks {counts.chunks:,}, table chunks "
        f"{counts.table_chunks:,}"
    )
    print(
        f"embedded filings {build.embedded_filings}, reused "
        f"{build.reused_filings}, embedded chunks {build.embedded_chunks:,}, "
        f"chunks/s {build.chunks_per_second}"
    )
    print("seconds: " + ", ".join(f"{k} {v}" for k, v in build.seconds.items()))
    for name, digest in manifest.files.items():
        print(f"sha256 {name}: {digest}")
    print(f"chunks_sha256: {manifest.chunks_sha256}")
    return 0


def _catalog(
    settings: config.Settings, corpus_dir: pathlib.Path | None
) -> understanding.Catalog:
    """Read the corpus facts from the index, or parse the corpus."""
    build = indexer.current_build(settings.index.dir)
    if corpus_dir is None and build is not None:
        conn = chunk_store.open_read_only(build / chunk_store.FILE_NAME)
        try:
            return understanding.Catalog.from_store(conn)
        finally:
            conn.close()
    corpus_dir = corpus_dir or settings.corpus.dir
    _ensure_corpus(settings, corpus_dir)
    parse_context = parser_base.ParseContext.from_settings(settings)
    return understanding.Catalog.from_parse(
        parser_corpus.parse_corpus(corpus_dir, parse_context)
    )


def run_understand(
    settings: config.Settings, question: str, corpus_dir: pathlib.Path | None
) -> int:
    """Run `keel understand`: print the `QuestionAnalysis` as JSON.

    The corpus facts come from the index when one is published and no
    corpus directory is named, else from the parse of the corpus.

    Args:
        settings: The loaded settings.
        question: The question.
        corpus_dir: The corpus directory, or None for `corpus.dir`.

    Returns:
        0, or 1 when the question fails an input check.

    Raises:
        CorpusMissingError: The corpus directory and the zip are absent.
    """
    catalog = _catalog(settings, corpus_dir)
    step = understanding.Understander.from_settings(settings, catalog)
    try:
        analysis = step.analyze(question)
    except errors.QuestionInputError as error:
        print(f"HTTP {error.http_status}: {error}")
        return 1
    print(analysis.model_dump_json(indent=2))
    return 0


def _print_retrieval(result: retriever.RetrievalResult) -> None:
    """Print the plan, the counts, and the timings of 1 retrieval."""
    built = result.context
    print(f"sub-queries: {len(result.plan.sub_queries)}")
    for sub in result.plan.sub_queries:
        print(f"  {sub.label}: dense {sub.dense_text!r}")
        print("    lexical: " + ", ".join(sub.terms))
    print(
        f"candidates: {result.candidates} before collapse, "
        f"{result.candidates - result.collapsed} after "
        f"({result.collapsed} collapsed), {result.reranked} reranked"
    )
    print("quota fills (taken/quota of candidates, tokens):")
    for fill in built.fills:
        print(
            f"  {fill.label}: {fill.taken}/{fill.quota} of "
            f"{fill.candidates}, {fill.tokens:,} tokens"
        )
    print(
        f"context: {len(built.chunks)} chunks, about "
        f"{built.token_estimate:,} tokens (budget "
        f"{built.budget.max_tokens:,} and {built.budget.max_chunks}), "
        f"{built.dropped} candidates dropped"
    )
    print(
        "sections: "
        + ", ".join(f"{k} {v}" for k, v in built.sections().items())
    )
    timings = result.timings
    print(
        f"time ms: lexical {timings.lexical_ms}, dense {timings.dense_ms}, "
        f"rerank {timings.rerank_ms}, total {timings.total_ms}"
    )
    for gap in result.gaps:
        print(f"gap: {gap}")
    if result.degraded:
        print("degraded: " + ", ".join(result.degraded))


def run_retrieve(
    settings: config.Settings,
    text: str | None,
    number: int | None,
    *,
    summary: bool,
    index_dir: pathlib.Path | None,
) -> int:
    """Run `keel retrieve`: the context of a question, without a model call.

    Args:
        settings: The loaded settings.
        text: The question, or None with `number`.
        number: The 1-based number of an example question, or None.
        summary: Print the plan and the counts instead of the context.
        index_dir: The index directory, or None for `index.dir`.

    Returns:
        0, or 1 for a bad question number, an input check failure, or an
        out-of-scope question.

    Raises:
        IndexMissingError: No published index.
    """
    examples = settings.demo.example_questions
    if number is not None:
        if not 1 <= number <= len(examples):
            print(f"--question takes 1 to {len(examples)}")
            return 1
        text = examples[number - 1]
    if not text:
        print("give a question or --question N")
        return 1
    started = time.perf_counter()
    step = retriever.Retriever.open(settings, index_dir)
    loaded = time.perf_counter() - started
    understander = understanding.Understander.from_settings(
        settings, step.catalog
    )
    try:
        analysis = understander.analyze(text)
    except errors.QuestionInputError as error:
        print(f"HTTP {error.http_status}: {error}")
        return 1
    if analysis.out_of_scope:
        print(f"out of scope: {analysis.out_of_scope_reason}")
        return 1
    result = step.retrieve(analysis)
    print(f"question: {text}")
    types = ", ".join(analysis.types)
    tickers = ", ".join(analysis.tickers)
    print(
        f"type: {analysis.primary_type} ({types}); tickers: {tickers}; "
        f"models loaded in {loaded:.1f} s"
    )
    if summary:
        _print_retrieval(result)
    elif result.context.empty:
        print(context.NO_CONTEXT_MESSAGE)
    else:
        print(context.render_index(result.context))
        print(context.render_chunks(result.context))
    return 0


def _print_findings(result: dict[str, Any]) -> None:
    """Print the findings of each company, marking the unverified ones."""
    for company in result["company_findings"]:
        ticker, name = company["ticker"], company["company"]
        print(f"\n{ticker} ({name})")
        for finding in company["findings"]:
            mark = " [unverified]" if finding["unverified"] else ""
            point = finding["point"]
            print(f"  - {point}{mark}")


def _print_citations(record: dict[str, Any]) -> None:
    """Print the resolved citations with their markers and quotes."""
    print("\ncitations:")
    for cited in record["citations_resolved"]:
        marks = [m for m in ("truncated", "quote_mismatch") if cited[m]]
        extra = " [" + ", ".join(marks) + "]" if marks else ""
        chunk_id, filing = cited["chunk_id"], cited["filing_name"]
        section, quote = cited["section_title"], cited["quote"]
        print(f"  [{chunk_id}] {filing}, {section}{extra}")
        print(f'      "{quote}"')


def _meta_line(record: dict[str, Any]) -> str:
    """Describe the request, the tokens, the cost, and the latency."""
    meta = record["meta"]
    usage = meta.get("usage") or {}
    latency = meta.get("latency_ms") or {}
    requests = meta.get("model_requests", 0)
    fresh = usage.get("input_tokens", 0)
    cached = usage.get("cached_input_tokens", 0)
    written = usage.get("cache_write_tokens", 0)
    output = usage.get("output_tokens", 0)
    cost = meta.get("cost_usd", 0.0)
    first, total = latency.get("first_token"), latency.get("total")
    parts = [
        "request " + str(record["request_id"]),
        str(meta["model"]),
        f"{requests} request(s)",
        f"input {fresh} + cached {cached} + cache write {written}, "
        f"output {output}",
        f"${cost:.4f}",
        f"first token {first} ms, total {total} ms",
    ]
    if meta.get("from_cache"):
        parts.append("from cache")
    return " | ".join(parts)


def _facts_line(facts: dict[str, Any]) -> str:
    """Describe the facts block as the trace drawer does (chapter 26.1)."""
    lines, files = facts.get("lines", 0), facts.get("files", 0)
    source = {"cache": "cached", "network": "fetched"}.get(
        facts.get("source", "none")
    )
    text = f"facts: {lines} lines"
    if files and source:
        text += f" from {files} {source} file" + ("s" if files > 1 else "")
    for problem in facts.get("errors", []):
        text += f"; facts error: {problem}"
    return text


def _print_answer(record: dict[str, Any], streamed: bool) -> None:
    """Print the findings, the citations, the gaps, and the meta line."""
    result = record.get("answer")
    if result is None:
        print(record.get("message") or "no answer")
        if record.get("raw_text"):
            print(record["raw_text"])
        retrieval = record.get("retrieval") or {}
        for chunk in retrieval.get("chunks", []):
            print("  " + chunk["chunk_id"] + " | " + chunk["filing_name"])
    else:
        if not streamed:
            print(result["direct_answer"])
        if result.get("refusal"):
            print("refusal: " + result["refusal"]["reason"])
        _print_findings(result)
        _print_citations(record)
        for gap in result["gaps"]:
            print("gap: " + gap)
    print("\n" + _meta_line(record))
    facts = record["meta"].get("facts") or {}
    if facts.get("lines") or facts.get("errors"):
        print(_facts_line(facts))
    flags = record["meta"].get("flags") or {}
    if flags:
        drift = flags.get("citation_drift", 0)
        unverified = flags.get("unverified", 0)
        mismatch = flags.get("quote_mismatch", 0)
        periods = flags.get("period_mismatch", [])
        print(
            f"citation drift {drift}, unverified {unverified}, quote "
            f"mismatch {mismatch}, period mismatch {periods}"
        )


async def _ask(
    answerer: answer.Answerer, question: str, as_json: bool, cached: bool
) -> int:
    """Stream 1 answer to the terminal and print the record."""
    record: dict[str, Any] | None = None
    streamed = False
    code = 0
    async for event in answerer.ask(question, use_cache=cached):
        if event.name == "answer_delta" and not as_json:
            print(event.data["text"], end="", flush=True)
            streamed = True
        elif event.name == "error":
            code = 1
            if not as_json:
                code_name = event.data["code"]
                message = event.data["message"]
                print(f"\nerror {code_name}: {message}")
        elif event.name == "final":
            record = event.data
    if streamed:
        print()
    if record is None:
        return 1
    if as_json:
        print(json.dumps(record, indent=2, ensure_ascii=False))
    else:
        _print_answer(record, streamed)
    return code


def run_ask(
    settings: config.Settings,
    question: str,
    *,
    as_json: bool,
    cached: bool,
    index_dir: pathlib.Path | None,
) -> int:
    """Run `keel ask`: stream the direct answer, then print the record.

    Args:
        settings: The loaded settings.
        question: The question.
        as_json: Print the full record as JSON instead of the text.
        cached: Serve the answer cache when it holds the question.
        index_dir: The index directory, or None for `index.dir`.

    Returns:
        0, or 1 after an error event or an input check failure.

    Raises:
        IndexMissingError: No published index.
        ConfigError: The prompt version is outside the index range, or the
            prompt files or the provider are invalid.
        ProviderRequestError: `ANTHROPIC_API_KEY` is not set.
    """
    answerer = answer.Answerer.open(settings, index_dir)
    return asyncio.run(_ask(answerer, question, as_json, cached))


def run_calibrate(
    settings: config.Settings,
    size: int,
    index_dir: pathlib.Path | None,
    counter: calibrate.TokenCounter | None = None,
) -> int:
    """Run `keel calibrate`: 1 token count call over a chunk sample.

    The command prints the measured factor; the engineer writes it into
    `retrieval.calibration_factor` (chapter 11.6 step 2).

    Args:
        settings: The loaded settings.
        size: The sample size.
        index_dir: The index directory, or None for `index.dir`.
        counter: The token counter, or None for the Anthropic endpoint.

    Returns:
        0.

    Raises:
        IndexMissingError: No published index.
        ProviderRequestError: `ANTHROPIC_API_KEY` is not set.
    """
    directory = index_dir or settings.index.dir
    build = indexer.current_build(directory)
    if build is None:
        raise errors.IndexMissingError(
            f"no index at {directory}/current; run keel index"
        )
    if counter is None:
        if settings.anthropic_api_key is None:
            raise errors.ProviderRequestError("ANTHROPIC_API_KEY is not set")
        # No SDK retries: the calibration is exactly 1 count call.
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            max_retries=0,
            timeout=settings.llm.timeout_seconds,
        )
        counter = calibrate.anthropic_counter(client)
    conn = chunk_store.open_read_only(build / chunk_store.FILE_NAME)
    try:
        result = calibrate.measure(
            conn,
            counter,
            settings.llm.model,
            factor_before=settings.retrieval.calibration_factor,
            size=size,
        )
    finally:
        conn.close()
    before = settings.retrieval.calibration_factor
    drift = (result.counted_tokens - result.estimate_before) / max(
        1, result.estimate_before
    )
    print(f"model: {settings.llm.model}; sample: {result.chunks} chunks")
    print(f"embedding tokens: {result.embedding_tokens:,}")
    print(f"counted tokens: {result.counted_tokens:,}")
    print(
        f"estimate with factor {before}: {result.estimate_before:,} "
        f"({drift:+.1%} against the count)"
    )
    print(f"calibration factor: {result.factor}")
    return 0


def run_eval(settings: config.Settings, args: argparse.Namespace) -> int:
    """Run `keel eval`: the golden set, the gates, and the report.

    Args:
        settings: The loaded settings.
        args: The parsed `eval` arguments.

    Returns:
        0, or 1 with `--gate` when a regression gate fails.

    Raises:
        GoldenSetError: The golden set or a label file is not valid.
        IndexMissingError: No published index.
        ProviderRequestError: `--answers` without `ANTHROPIC_API_KEY`.
    """
    variants = (runner.MAIN,) if args.no_ablation else runner.ABLATION
    setup = (
        runner.AnswerSetup(judge=not args.no_judge) if args.answers else None
    )
    run, questions = runner.evaluate(
        settings,
        args.golden,
        args.labels or args.golden.parent / "labels",
        subset=args.subset,
        index_dir=args.index,
        variants=variants,
        progress=print,
        answers=setup,
    )
    json_path = eval_report.write(run, questions, args.report)
    print(f"run {run.info.run_id}: {len(questions)} questions, ", end="")
    print(f"{run.seconds:.0f} s; report {args.report}, results {json_path}")
    results = run.gates()
    for result in results:
        value = "n/a" if result.value is None else f"{result.value:.2f}"
        print(f"  {result.gate.name}: {value} ({result.status})")
    if run.answers:
        values = run.answer_values()
        spend = sum(r.cost_usd for r in run.answers)
        judge_cost = values.get("judge_cost_usd") or 0.0
        print(f"spend: answers ${spend:.4f}, judge ${judge_cost:.4f}")
    if args.gate and gates.blocked(results):
        print("gate failed: the release stays blocked")
        return 1
    return 0


def run_facts(
    settings: config.Settings,
    ticker: str,
    window: tuple[datetime.date | None, datetime.date | None],
    offline: bool,
) -> int:
    """Run `keel facts`: print the facts lines of 1 ticker.

    Args:
        settings: The loaded settings.
        ticker: The ticker.
        window: The first and last period end dates, None for no bound.
        offline: Read only the EDGAR cache.

    Returns:
        0.

    Raises:
        EdgarError: The ticker is unknown or a fetch fails.
        ConfigError: `config/facts.yaml` is invalid.
    """
    facts_config = edgar.load_facts_config(settings.edgar.facts)
    with edgar.EdgarClient.from_settings(
        settings, offline=offline or None
    ) as client:
        cik = client.cik(ticker)
        document = client.company_facts(cik)
    block = edgar.facts_lines(
        document.data, ticker, facts_config, start=window[0], end=window[1]
    )
    print(block.text())
    print(
        f"facts: {len(block.lines)} lines ({block.dropped} over the limit) "
        f"from 1 file fetched {document.fetched_at:%Y-%m-%d %H:%M} UTC "
        f"({client.requests} requests this run)"
    )
    return 0


def run_add(
    settings: config.Settings,
    ticker: str,
    *,
    offline: bool,
    corpus_dir: pathlib.Path | None,
    out_dir: pathlib.Path | None,
) -> int:
    """Run `keel add`: 1 company from EDGAR into the index (26.2).

    Args:
        settings: The loaded settings.
        ticker: The ticker.
        offline: Read only the EDGAR cache.
        corpus_dir: The directory of filings, or None for `corpus.dir`
            (extracted from the zip when empty).
        out_dir: The index directory, or None for `index.dir`.

    Returns:
        0, or 1 when a picked filing is quarantined.

    Raises:
        EdgarError: The ticker is unknown, or a fetch or the conversion
            fails.
        IndexMissingError: The index has no current build.
        IndexWriteError: The incremental build cannot be published.
        ManifestMissingError: The corpus has no usable manifest.
        ConfigError: The dictionary cannot take the company.
        HeaderError: A header value from EDGAR is unusable.
    """
    directory = corpus_dir or settings.corpus.dir
    if corpus_dir is None:
        _ensure_corpus(settings, directory)
    handler = signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        with edgar.EdgarClient.from_settings(
            settings, offline=offline or None
        ) as client:
            report = add.add_ticker(
                settings,
                ticker,
                client=client,
                corpus_dir=directory,
                index_dir=out_dir or settings.index.dir,
                embedder_factory=lambda: (
                    numpy_dense.SentenceEmbedder.from_settings(settings)
                ),
            )
    finally:
        signal.signal(signal.SIGTERM, handler)
    print(f"{report.ticker} CIK {report.cik} {report.company}")
    for filing in report.filings:
        changed = "new or changed" if filing.changed else "unchanged"
        state = (
            f"quarantined: {filing.quarantine}"
            if filing.quarantine
            else f"{filing.chunks} chunks"
        )
        print(
            f"  {filing.form} filed {filing.filing_date} accession "
            f"{filing.accession}: {filing.file_name} ({changed})"
        )
        print(
            f"    {filing.filing_id}, {filing.fiscal_period} FY"
            f"{filing.fiscal_year}, period end {filing.period_end_date}, "
            f"{state}"
        )
        if filing.warnings:
            print("    warnings: " + ", ".join(filing.warnings))
    if report.dictionary_added:
        print(f"added {report.ticker} to {settings.dictionaries.companies}")
    print(
        f"index version {report.index_version}: "
        + (
            f"embedded {report.embedded_filings} filings, "
            f"{report.embedded_chunks} chunks"
            if report.index_built
            else "unchanged"
        )
        + f"; {report.requests} EDGAR requests"
    )
    return 1 if any(f.quarantine for f in report.filings) else 0


def run_watch(
    settings: config.Settings,
    action: str,
    tickers: Sequence[str],
    user: str | None,
) -> int:
    """Run `keel watch`: add, remove, or list watched tickers (26.3).

    Args:
        settings: The loaded settings.
        action: `add`, `remove`, or `list`.
        tickers: The tickers for `add` and `remove`.
        user: The user, or None (`cli` for a change, all users for a list).

    Returns:
        0, or 1 when `add` or `remove` gets no ticker.

    Raises:
        EdgarError: A ticker cannot name a corpus file.
        StateStoreError: The app-state database fails.
    """
    path = state_store.state_path(settings)
    if action == "list":
        entries = state_store.list_watch(path, user)
        for entry in entries:
            print(
                f"{entry.ticker:<8} {entry.user:<12} added {entry.added_date}"
            )
        print(f"{len(entries)} watched tickers in {path}")
        return 0
    if not tickers:
        print(f"keel watch {action} needs at least 1 ticker", file=sys.stderr)
        return 1
    name = user or state_store.DEFAULT_USER
    for ticker in tickers:
        spelled = add.corpus_ticker(ticker)
        if action == "add":
            changed = state_store.add_watch(path, spelled, name)
            verb = "watching" if changed else "already watching"
        else:
            changed = state_store.remove_watch(path, spelled, name)
            verb = "stopped watching" if changed else "was not watching"
        print(f"{name} {verb} {spelled}")
    return 0


def run_refresh(
    settings: config.Settings,
    *,
    dry_run: bool,
    offline: bool,
    corpus_dir: pathlib.Path | None,
    out_dir: pathlib.Path | None,
) -> int:
    """Run `keel refresh`: new filings of the watched tickers (26.3).

    Args:
        settings: The loaded settings.
        dry_run: List the new filings only.
        offline: Compare against the cached submissions only.
        corpus_dir: The directory of filings, or None for `corpus.dir`.
        out_dir: The index directory, or None for `index.dir`.

    Returns:
        0, or 1 when a ticker failed or a new filing was quarantined.

    Raises:
        StateStoreError: The watch list or the log fails.
        ManifestMissingError: The manifest is not JSON.
        IndexCorruptError: The current build cannot be read.
    """
    handler = signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        with edgar.EdgarClient.from_settings(
            settings, offline=offline or None
        ) as client:
            report = refresh.run_refresh(
                settings,
                dry_run=dry_run,
                client=client,
                corpus_dir=corpus_dir,
                index_dir=out_dir,
            )
    finally:
        signal.signal(signal.SIGTERM, handler)
    for result in report.tickers:
        if result.error:
            print(f"{result.ticker}: error: {result.error}")
            continue
        if not result.new:
            print(f"{result.ticker}: up to date")
        for ref in result.new:
            print(
                f"{result.ticker}: new {ref.form} filed {ref.filing_date} "
                f"accession {ref.accession} period {ref.report_date}"
            )
        for filing in result.added:
            state = (
                f"quarantined: {filing.quarantine}"
                if filing.quarantine
                else f"added as {filing.filing_id}, {filing.chunks} chunks"
            )
            print(f"  {filing.file_name}: {state}")
    mode = "dry run: " if dry_run else ""
    print(
        f"{mode}{len(report.tickers)} tickers, {report.new_count} new, "
        f"{report.added_count} added, {report.error_count} errors, "
        f"{report.requests} EDGAR requests; log {refresh.log_path(settings)}"
    )
    quarantined = any(f.quarantine for r in report.tickers for f in r.added)
    return 1 if report.error_count or quarantined else 0


def run_doctor(settings: config.Settings, download: bool, as_json: bool) -> int:
    """Run `keel doctor`.

    Args:
        settings: The loaded settings.
        download: Download the pinned models first.
        as_json: Print JSON instead of text.

    Returns:
        1 when a check fails, else 0.
    """
    results = doctor.run_doctor(settings, download=download)
    if as_json:
        print(json.dumps([vars(result) for result in results], indent=2))
    else:
        for result in results:
            print(f"{result.status:<5} {result.name}: {result.detail}")
    return 1 if any(r.status == doctor.FAIL for r in results) else 0


def run_users(settings: config.Settings, args: argparse.Namespace) -> int:
    """Run `keel users add`, `keel users remove`, or `keel users list`.

    Args:
        settings: The loaded settings, with `auth.users_file`.
        args: The parsed arguments.

    Returns:
        0.

    Raises:
        ConfigError: The users file is invalid, the name to add exists,
            or the name to remove does not.
    """
    path = settings.auth.users_file
    if args.users_command == "add":
        token = users.add_user(path, args.name, args.role)
        print(f"added {args.name} ({args.role}) to {path}")
        print("token (shown once; the file keeps only its sha256):")
        print(token)
        return 0
    if args.users_command == "remove":
        users.remove_user(path, args.name)
        print(f"removed {args.name} from {path}; the token no longer passes")
        return 0
    entries = users.load_file(path).users
    for entry in entries:
        print(f"{entry.name}\t{entry.role}")
    print(f"{users.LEGACY_USER}\tadmin (KEEL_API_TOKEN, when set)")
    return 0


def _dispatch_measure(
    settings: config.Settings, args: argparse.Namespace
) -> int:
    """Run `keel calibrate`, `keel eval`, or `keel warm-cache`."""
    if args.command == "calibrate":
        return run_calibrate(settings, args.sample, args.index)
    if args.command == "warm-cache":
        return warm_cache.run(settings, args)
    return run_eval(settings, args)


def _dispatch_questions(
    settings: config.Settings, args: argparse.Namespace
) -> int | None:
    """Run a question, facts, or add command; None for the others."""
    if args.command == "understand":
        return run_understand(settings, args.question, args.corpus)
    if args.command == "ask":
        return run_ask(
            settings,
            args.question,
            as_json=args.json,
            cached=args.cached,
            index_dir=args.index,
        )
    if args.command == "retrieve":
        return run_retrieve(
            settings,
            args.text,
            args.question,
            summary=args.summary,
            index_dir=args.index,
        )
    if args.command == "facts":
        return run_facts(
            settings, args.ticker, (args.start, args.end), args.offline
        )
    if args.command == "add":
        return run_add(
            settings,
            args.ticker,
            offline=args.offline,
            corpus_dir=args.corpus,
            out_dir=args.out,
        )
    return None


def _dispatch_refresh(
    settings: config.Settings, args: argparse.Namespace
) -> int:
    """Run `keel watch` or `keel refresh` with its arguments."""
    if args.command == "watch":
        return run_watch(settings, args.action, args.tickers, args.user)
    return run_refresh(
        settings,
        dry_run=args.dry_run,
        offline=args.offline,
        corpus_dir=args.corpus,
        out_dir=args.out,
    )


def _dispatch(settings: config.Settings, args: argparse.Namespace) -> int:
    """Run the chosen command with its arguments."""
    if args.command in ("watch", "refresh"):
        return _dispatch_refresh(settings, args)
    handlers: dict[str, Callable[[], int]] = {
        "inventory": lambda: run_inventory(
            settings, args.corpus, args.manifest, args.json
        ),
        "parse": lambda: run_parse(
            settings,
            args.files,
            parse_all=args.all,
            corpus_dir=args.corpus,
            show_summary=args.summary,
            as_json=args.json,
            sections_report=args.sections_report,
        ),
        "chunk": lambda: run_chunk(
            settings,
            args.files,
            chunk_all=args.all,
            corpus_dir=args.corpus,
            as_json=args.json,
        ),
        "serve": lambda: api_app.serve(settings, args.host, args.port),
        "export": lambda: export.run(settings, args),
        "index": lambda: run_index(
            settings,
            corpus_dir=args.corpus,
            out_dir=args.out,
            incremental=args.incremental,
        ),
    }
    if args.command in ("calibrate", "eval", "warm-cache"):
        return _dispatch_measure(settings, args)
    if args.command == "users":
        return run_users(settings, args)
    if args.command in pilot_cli.COMMANDS:
        code, lines = pilot_cli.run(settings, args)
        for line in lines:
            print(line)
        return code
    handler = handlers.get(args.command)
    if handler is not None:
        return handler()
    return run_doctor(settings, args.download_models, args.json)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `keel` command.

    Args:
        argv: The arguments without the program name. None reads sys.argv.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = config.load_settings(args.config)
        security.install(settings)
        code = _dispatch_questions(settings, args)
        return _dispatch(settings, args) if code is None else code
    except errors.KeelError as error:
        logger.error("%s: %s", type(error).__name__, error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
