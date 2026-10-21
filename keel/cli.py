"""Command line entry point for Keel.

Stage 1 ships `keel inventory` and `keel doctor`; stage 2 adds `keel parse`;
stage 3 adds `keel chunk` and `keel parse --sections-report`.
Later stages add the commands that CLAUDE.md lists (index, ask, serve, and
the rest).
"""

import argparse
from collections.abc import Sequence
import json
import logging
import pathlib
import sys
import time

import keel
from keel import chunker
from keel import config
from keel import doctor
from keel import errors
from keel import extractor
from keel import inventory
from keel import sections
from keel.parsers import base as parser_base
from keel.parsers import corpus as parser_corpus

logger = logging.getLogger("keel")

# Assumption A-15 asks whether the NVDA 10-K filed in February 2026 is in
# the corpus; the worked example of chapter 11 branches on it.
A15_TICKER = "NVDA"
A15_FILED_FROM = "2026-02-01"
A15_FILED_TO = "2026-02-28"


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

    doctor_parser = commands.add_parser(
        "doctor", help="check the environment: FTS5, models, keys, clock, ports"
    )
    doctor_parser.add_argument(
        "--download-models",
        action="store_true",
        help="download the 2 pinned Hugging Face models into the cache",
    )
    doctor_parser.add_argument(
        "--json", action="store_true", help="print the results as JSON"
    )
    return parser


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
    context = parser_base.ParseContext.from_settings(settings, manifest_files)
    return parser_corpus.finish_corpus(
        parser_corpus.parse_files(files, context), context
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
    summary = chunker.summarize(chunked, sizes, time.perf_counter() - started)
    if as_json:
        print(json.dumps(summary.model_dump(mode="json"), indent=2))
    else:
        _print_chunk_summary(summary)
    return 0


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
        if args.command == "inventory":
            return run_inventory(
                settings, args.corpus, args.manifest, args.json
            )
        if args.command == "parse":
            return run_parse(
                settings,
                args.files,
                parse_all=args.all,
                corpus_dir=args.corpus,
                show_summary=args.summary,
                as_json=args.json,
                sections_report=args.sections_report,
            )
        if args.command == "chunk":
            return run_chunk(
                settings,
                args.files,
                chunk_all=args.all,
                corpus_dir=args.corpus,
                as_json=args.json,
            )
        return run_doctor(settings, args.download_models, args.json)
    except errors.KeelError as error:
        logger.error("%s: %s", type(error).__name__, error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
