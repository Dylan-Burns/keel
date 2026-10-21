"""The corpus inventory: counts, the manifest check, and the discrepancies.

The inventory reads the file names, the header keys, and the manifest. It
never parses a filing body; the parser (chapter 7) owns the cover page. The
report states every difference between the directory, the manifest, and the
corpus facts so the build report can record it (E-D-24, E-D-25).
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import json
import logging
import pathlib
import re

import pydantic

from keel import config
from keel import errors

logger = logging.getLogger(__name__)

# 2 file-name patterns (E-D-03, E-D-04). The period code is the calendar
# quarter in the file name; the parser reads the real period from the cover.
FILENAME_WITH_PERIOD = re.compile(
    r"^(?P<ticker>[A-Z][A-Z.]{0,9})_(?P<form>10K|10Q)_"
    r"(?P<period>\d{4}Q[1-4])_(?P<date>\d{4}-\d{2}-\d{2})_full\.txt$"
)
FILENAME_NO_PERIOD = re.compile(
    r"^(?P<ticker>[A-Z][A-Z.]{0,9})_(?P<form>10K|10Q)_"
    r"(?P<date>\d{4}-\d{2}-\d{2})_full\.txt$"
)
FORM_CODES = {"10K": "10-K", "10Q": "10-Q"}
HEADER_KEY = re.compile(r"^(?P<key>[A-Za-z][A-Za-z ]*?)\s*:\s*(?P<value>.*)$")
SEPARATOR = re.compile(r"^={60}$")
HEADER_SCAN_LINES = 20
HEADER_SCAN_BYTES = 4096
QUARTERLY_CLAIM = re.compile(
    r"(?P<count>\d+)\s+companies\s+have\s+full\s+quarterly\s+coverage",
    re.IGNORECASE,
)
# A ticker has full quarterly coverage with 3 10-Qs filed in each of the
# calendar years 2023, 2024, and 2025 (the manifest claim covers 2023-2025).
COVERAGE_YEARS = (2023, 2024, 2025)
COVERAGE_PER_YEAR = 3


@dataclasses.dataclass(frozen=True)
class FileName:
    """The metadata that 1 corpus file name carries.

    Attributes:
        name: The file name.
        ticker: The ticker.
        form: `10-K` or `10-Q`.
        period_code: The calendar quarter code such as `2022Q4`, or None.
        filing_date: The filing date.
        pattern: `with_period` or `no_period`.
    """

    name: str
    ticker: str
    form: str
    period_code: str | None
    filing_date: datetime.date
    pattern: str


def parse_filename(name: str) -> FileName | None:
    """Read the ticker, form, period code, and filing date of a file name.

    Args:
        name: A file name such as `AAPL_10Q_2022Q4_2023-02-03_full.txt`.

    Returns:
        The parsed metadata, or None when neither pattern matches or the
        date is not a calendar date.
    """
    match = FILENAME_WITH_PERIOD.match(name)
    pattern = "with_period"
    if match is None:
        match = FILENAME_NO_PERIOD.match(name)
        pattern = "no_period"
    if match is None:
        return None
    try:
        filing_date = datetime.date.fromisoformat(match["date"])
    except ValueError:
        return None
    groups = match.groupdict()
    return FileName(
        name=name,
        ticker=match["ticker"],
        form=FORM_CODES[match["form"]],
        period_code=groups.get("period"),
        filing_date=filing_date,
        pattern=pattern,
    )


def header_keys(path: pathlib.Path) -> tuple[str, ...]:
    """Read the header keys of a filing, up to the separator line.

    Args:
        path: The filing.

    Returns:
        The keys in file order, or an empty tuple when no separator shows
        in the first 20 lines.
    """
    with path.open("rb") as stream:
        head = stream.read(HEADER_SCAN_BYTES).decode("utf-8", "replace")
    keys: list[str] = []
    for line in head.lstrip("﻿").splitlines()[:HEADER_SCAN_LINES]:
        if SEPARATOR.match(line):
            return tuple(keys)
        match = HEADER_KEY.match(line)
        if match:
            keys.append(match["key"])
    return ()


class Manifest(pydantic.BaseModel):
    """The corpus manifest. Unknown keys are kept.

    Attributes:
        files: The file names the manifest lists.
        file_count: The file count the manifest claims.
        filing_types: The count per form the manifest claims.
        description: The free-text description.
        license: The license statement (assumption A-05).
    """

    model_config = pydantic.ConfigDict(extra="allow", frozen=True)

    files: list[str]
    file_count: int | None = None
    filing_types: dict[str, int] = pydantic.Field(default_factory=dict)
    description: str | None = None
    license: str | None = None
    source: str | None = None
    corpus: str | None = None


def load_manifest(path: pathlib.Path) -> Manifest:
    """Load and validate the manifest.

    Args:
        path: The manifest JSON file.

    Returns:
        The manifest.

    Raises:
        ManifestMissingError: The file is absent, not JSON, or invalid.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Manifest.model_validate(raw)
    except (OSError, ValueError) as error:
        raise errors.ManifestMissingError(
            f"manifest unusable at {path}: {error}"
        ) from error


class TickerCount(pydantic.BaseModel):
    """The filings of 1 ticker.

    Attributes:
        ten_k: The number of 10-K files.
        ten_q: The number of 10-Q files.
        first_filing: The earliest filing date.
        last_filing: The latest filing date.
    """

    ten_k: int
    ten_q: int
    first_filing: datetime.date
    last_filing: datetime.date


class ManifestCheck(pydantic.BaseModel):
    """The comparison of the directory with the manifest (E-D-24).

    Attributes:
        present: False when the manifest is absent or unusable.
        absent_files: Files the manifest lists that are not on disk.
        unmanifested_files: Files on disk that the manifest omits.
        claimed_file_count: The manifest `file_count`.
        claimed_filing_types: The manifest `filing_types`.
        claimed_quarterly_companies: The count in the description claim.
        license: The manifest `license` key (A-05).
    """

    present: bool
    absent_files: list[str] = pydantic.Field(default_factory=list)
    unmanifested_files: list[str] = pydantic.Field(default_factory=list)
    claimed_file_count: int | None = None
    claimed_filing_types: dict[str, int] = pydantic.Field(default_factory=dict)
    claimed_quarterly_companies: int | None = None
    license: str | None = None


class InventoryReport(pydantic.BaseModel):
    """The inventory of a corpus directory.

    Attributes:
        corpus_dir: The directory read.
        file_count: The filing files (`*.txt`) on disk.
        total_bytes: Their total size.
        ticker_count: The distinct tickers.
        form_counts: The files per form.
        year_counts: The files per filing year.
        first_filing: The earliest filing date and its file.
        last_filing: The latest filing date and its file.
        pattern_counts: The files per file-name pattern.
        unmatched_files: Files that match neither file-name pattern.
        header_shapes: The files per header key list, joined by commas.
        tickers: The counts per ticker.
        quarterly_tickers: Tickers with at least 1 10-Q.
        full_quarterly_tickers: Tickers with full 10-Q coverage 2023-2025.
        largest_files: The 3 largest files with their sizes.
        date_filter_excluded: Files outside `corpus.date_filter`.
        manifest: The manifest comparison.
        discrepancies: Every difference, 1 sentence each.
        files: The file names on disk.
    """

    corpus_dir: str
    file_count: int
    total_bytes: int
    ticker_count: int
    form_counts: dict[str, int]
    year_counts: dict[int, int]
    first_filing: tuple[datetime.date, str] | None
    last_filing: tuple[datetime.date, str] | None
    pattern_counts: dict[str, int]
    unmatched_files: list[str]
    header_shapes: dict[str, int]
    tickers: dict[str, TickerCount]
    quarterly_tickers: list[str]
    full_quarterly_tickers: list[str]
    largest_files: list[tuple[str, int]]
    date_filter_excluded: list[str]
    manifest: ManifestCheck
    discrepancies: list[str]
    files: list[str] = pydantic.Field(default_factory=list, repr=False)

    def latest(self, ticker: str, form: str) -> FileName | None:
        """Return the latest file of a ticker and form by filing date.

        Args:
            ticker: The ticker.
            form: `10-K` or `10-Q`.

        Returns:
            The file name metadata, or None when the ticker has no such file.
        """
        return _latest(self.files, ticker, form)


def _latest(names: list[str], ticker: str, form: str) -> FileName | None:
    parsed = [parse_filename(name) for name in names]
    matches = [
        item
        for item in parsed
        if item and item.ticker == ticker and item.form == form
    ]
    return max(matches, key=lambda item: item.filing_date, default=None)


def full_quarterly_coverage(files: list[FileName]) -> list[str]:
    """List the tickers with 3 10-Qs filed in each year from 2023 to 2025.

    Args:
        files: The parsed file names.

    Returns:
        The tickers in sorted order.
    """
    per_year: dict[str, collections.Counter[int]] = collections.defaultdict(
        collections.Counter
    )
    for item in files:
        if item.form == "10-Q":
            per_year[item.ticker][item.filing_date.year] += 1
    return sorted(
        ticker
        for ticker, years in per_year.items()
        if all(years[year] >= COVERAGE_PER_YEAR for year in COVERAGE_YEARS)
    )


def _check_manifest(
    manifest_path: pathlib.Path, on_disk: list[str]
) -> ManifestCheck:
    try:
        manifest = load_manifest(manifest_path)
    except errors.ManifestMissingError as error:
        logger.warning("%s", error)
        return ManifestCheck(present=False)
    listed = set(manifest.files)
    disk = set(on_disk)
    claim = QUARTERLY_CLAIM.search(manifest.description or "")
    return ManifestCheck(
        present=True,
        absent_files=sorted(listed - disk),
        unmanifested_files=sorted(disk - listed),
        claimed_file_count=manifest.file_count,
        claimed_filing_types=dict(manifest.filing_types),
        claimed_quarterly_companies=int(claim["count"]) if claim else None,
        license=manifest.license,
    )


def _discrepancies(
    file_count: int,
    form_counts: dict[str, int],
    unmatched: list[str],
    full_quarterly: list[str],
    manifest: ManifestCheck,
) -> list[str]:
    found: list[str] = []
    if not manifest.present:
        found.append("manifest absent or unusable: no manifest comparison")
        return found + [f"file name matches no pattern: {n}" for n in unmatched]
    if manifest.absent_files:
        found.append(
            f"{len(manifest.absent_files)} manifest files absent on disk: "
            + ", ".join(manifest.absent_files)
        )
    if manifest.unmanifested_files:
        found.append(
            f"{len(manifest.unmanifested_files)} files on disk not in the "
            "manifest: " + ", ".join(manifest.unmanifested_files)
        )
    if (
        manifest.claimed_file_count is not None
        and manifest.claimed_file_count != file_count
    ):
        found.append(
            f"manifest file_count {manifest.claimed_file_count}, "
            f"directory {file_count}"
        )
    for form, claimed in sorted(manifest.claimed_filing_types.items()):
        actual = form_counts.get(form, 0)
        if claimed != actual:
            found.append(f"manifest {form} count {claimed}, directory {actual}")
    claimed_quarterly = manifest.claimed_quarterly_companies
    if claimed_quarterly is not None and claimed_quarterly != len(
        full_quarterly
    ):
        listed = ", ".join(full_quarterly)
        found.append(
            f"manifest claims {claimed_quarterly} companies with full "
            f"quarterly coverage, the files show {len(full_quarterly)}"
            + (f" ({listed})" if listed else "")
            + " (E-D-25)"
        )
    found.extend(f"file name matches no pattern: {n}" for n in unmatched)
    return found


def build_inventory(
    corpus_dir: pathlib.Path,
    manifest_path: pathlib.Path,
    date_filter: config.DateFilter | None = None,
) -> InventoryReport:
    """Count the corpus and compare it with the manifest.

    Args:
        corpus_dir: The extracted corpus directory.
        manifest_path: The manifest JSON file.
        date_filter: The optional filing date window of the config.

    Returns:
        The inventory report.

    Raises:
        CorpusMissingError: The corpus directory does not exist.
    """
    if not corpus_dir.is_dir():
        raise errors.CorpusMissingError(f"no corpus directory at {corpus_dir}")
    paths = sorted(corpus_dir.glob("*.txt"))
    names = [path.name for path in paths]
    parsed = [item for item in map(parse_filename, names) if item]
    unmatched = sorted(set(names) - {item.name for item in parsed})
    sizes = {path.name: path.stat().st_size for path in paths}
    shapes = collections.Counter(
        ", ".join(header_keys(path)) or "(no separator)" for path in paths
    )
    by_ticker: dict[str, list[FileName]] = collections.defaultdict(list)
    for item in parsed:
        by_ticker[item.ticker].append(item)
    tickers = {
        ticker: TickerCount(
            ten_k=sum(item.form == "10-K" for item in items),
            ten_q=sum(item.form == "10-Q" for item in items),
            first_filing=min(item.filing_date for item in items),
            last_filing=max(item.filing_date for item in items),
        )
        for ticker, items in sorted(by_ticker.items())
    }
    dated = sorted((item.filing_date, item.name) for item in parsed)
    form_counts = dict(
        sorted(collections.Counter(item.form for item in parsed).items())
    )
    full_quarterly = full_quarterly_coverage(parsed)
    manifest = _check_manifest(manifest_path, names)
    return InventoryReport(
        corpus_dir=str(corpus_dir),
        file_count=len(paths),
        total_bytes=sum(sizes.values()),
        ticker_count=len(tickers),
        form_counts=form_counts,
        year_counts=dict(
            sorted(
                collections.Counter(
                    item.filing_date.year for item in parsed
                ).items()
            )
        ),
        first_filing=dated[0] if dated else None,
        last_filing=dated[-1] if dated else None,
        pattern_counts=dict(
            sorted(collections.Counter(item.pattern for item in parsed).items())
        ),
        unmatched_files=unmatched,
        header_shapes=dict(shapes.most_common()),
        tickers=tickers,
        quarterly_tickers=sorted(t for t, c in tickers.items() if c.ten_q),
        full_quarterly_tickers=full_quarterly,
        largest_files=sorted(
            sizes.items(), key=lambda pair: (-pair[1], pair[0])
        )[:3],
        date_filter_excluded=sorted(
            item.name
            for item in parsed
            if date_filter and not date_filter.includes(item.filing_date)
        ),
        manifest=manifest,
        discrepancies=_discrepancies(
            len(paths), form_counts, unmatched, full_quarterly, manifest
        ),
        files=names,
    )
