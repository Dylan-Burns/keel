"""Command line entry point for Keel.

Stage 1 ships `keel inventory` and `keel doctor`. Later stages add the
commands that CLAUDE.md lists (parse, index, ask, serve, and the rest).
"""

import argparse
from collections.abc import Sequence
import json
import logging
import pathlib
import sys

import keel
from keel import config
from keel import doctor
from keel import errors
from keel import extractor
from keel import inventory

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
        return run_doctor(settings, args.download_models, args.json)
    except errors.KeelError as error:
        logger.error("%s: %s", type(error).__name__, error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
