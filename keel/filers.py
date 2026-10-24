"""The active 10-K and 10-Q filers of the company browser.

The browser shows a company only when its filings cover the years the
index can answer for: a 10-K or 10-Q in every calendar year from
`edgar.directory_since_year` through last year, and 1 in the last 365
days. The current calendar year is not required on its own, so the list
does not empty each January before the first 10-Ks arrive.

The source is the quarterly XBRL index of EDGAR
(`/Archives/edgar/full-index/<year>/QTR<n>/xbrl.idx`): 1 line per filing
with XBRL, with the CIK, the form, and the filing date, about 2 MB a
quarter. Every 10-K and 10-Q of an operating company carries XBRL, so the
index lists them all. The client caches 1 summary per quarter under
`<edgar.cache_dir>/xbrl_index/`: the latest 10-K or 10-Q filing date of
each CIK. A quarter that had ended when it was fetched never changes and
is not fetched again; the current quarter is fetched again after a day.
Offline, the cache serves whatever its age.

Only original forms count (`FORMS`); an amendment alone does not show
that a company still reports. No model request happens here (decision
D-02).
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
import dataclasses
import datetime
import logging
import pathlib
import threading

from keel import edgar
from keel import errors

logger = logging.getLogger(__name__)

INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/xbrl.idx"
)
FORMS = frozenset({"10-K", "10-Q", "10-KT", "10-QT"})
# A quarter of the XBRL index is about 2.3 MB; the cap leaves room.
MAX_INDEX_BYTES = 40_000_000
# The current quarter grows every business day.
CURRENT_TTL = datetime.timedelta(days=1)
RECENT = datetime.timedelta(days=365)

_memo: dict[tuple[pathlib.Path, int, datetime.date], frozenset[str]] = {}
_memo_lock = threading.Lock()


@dataclasses.dataclass(frozen=True)
class Quarter:
    """1 calendar quarter of the EDGAR full index.

    Attributes:
        year: The calendar year.
        quarter: The quarter, 1 to 4.
    """

    year: int
    quarter: int

    @property
    def end(self) -> datetime.date:
        """The last day of the quarter.

        Returns:
            The date.
        """
        if self.quarter == 4:
            return datetime.date(self.year, 12, 31)
        first_next = datetime.date(self.year, self.quarter * 3 + 1, 1)
        return first_next - datetime.timedelta(days=1)


def quarters(since_year: int, today: datetime.date) -> list[Quarter]:
    """The quarters from the first of `since_year` through today's.

    Args:
        since_year: The first calendar year.
        today: The current date.

    Returns:
        The quarters in order.
    """
    current = (today.month - 1) // 3 + 1
    return [
        Quarter(year, quarter)
        for year in range(since_year, today.year + 1)
        for quarter in range(1, 5)
        if (year, quarter) <= (today.year, current)
    ]


def index_url(quarter: Quarter) -> str:
    """The URL of the XBRL index of a quarter.

    Args:
        quarter: The quarter.

    Returns:
        The URL on www.sec.gov.
    """
    return INDEX_URL.format(year=quarter.year, quarter=quarter.quarter)


def cache_path(cache_dir: pathlib.Path, quarter: Quarter) -> pathlib.Path:
    """The cache file of the summary of a quarter.

    Args:
        cache_dir: The EDGAR cache directory.
        quarter: The quarter.

    Returns:
        `<cache_dir>/xbrl_index/<year>Q<n>.json`.
    """
    name = f"{quarter.year}Q{quarter.quarter}.json"
    return cache_dir / "xbrl_index" / name


def parse_index(body: bytes) -> dict[str, str]:
    """Read the latest 10-K or 10-Q filing date of each CIK.

    Args:
        body: The `xbrl.idx` file: a text header, then `CIK|Company
            Name|Form Type|Date Filed|Filename` lines.

    Returns:
        The latest filing date (ISO) of each CIK, 10 digits.

    Raises:
        EdgarError: The body has no line in the index format.
    """
    latest: dict[str, str] = {}
    rows = 0
    for line in body.decode("latin-1").splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[0].strip().isdigit():
            continue
        rows += 1
        form, filed = parts[2].strip(), parts[3].strip()
        if form not in FORMS:
            continue
        try:
            datetime.date.fromisoformat(filed)
            cik = edgar.cik10(parts[0])
        except (ValueError, errors.EdgarError):
            logger.warning("XBRL index line without a valid date or CIK")
            continue
        if filed > latest.get(cik, ""):
            latest[cik] = filed
    if rows == 0:
        raise errors.EdgarError("the XBRL index has no filing line")
    return latest


def _summary(document: edgar.CachedDocument) -> dict[str, str]:
    data = document.data
    latest = data.get("latest") if isinstance(data, dict) else None
    if not isinstance(latest, dict):
        raise errors.EdgarError("bad XBRL index summary in the EDGAR cache")
    return {str(cik): str(date) for cik, date in latest.items()}


def _complete(document: edgar.CachedDocument) -> bool:
    data = document.data
    return isinstance(data, dict) and bool(data.get("complete", False))


def quarter_filers(
    client: edgar.EdgarClient,
    quarter: Quarter,
    now: datetime.datetime,
) -> dict[str, str]:
    """The latest 10-K or 10-Q date of each CIK in a quarter.

    Args:
        client: The EDGAR client; offline, only the cache serves.
        quarter: The quarter.
        now: The current time in UTC.

    Returns:
        The latest filing date (ISO) of each CIK.

    Raises:
        EdgarCacheMissError: The client is offline and the cache has no
            summary of the quarter.
        EdgarError: The fetch fails and the cache has no summary.
    """
    path = cache_path(client.cache_dir, quarter)
    cached: edgar.CachedDocument | None = None
    summary: dict[str, str] = {}
    if path.is_file():
        try:
            cached = edgar.read_cached(path)
            summary = _summary(cached)
        except errors.EdgarError:
            logger.warning("bad XBRL index summary skipped")
            cached = None
    if cached is not None:
        fresh = now - cached.fetched_at < CURRENT_TTL
        if _complete(cached) or fresh or client.offline:
            return summary
    elif client.offline:
        raise errors.EdgarCacheMissError(
            "offline and no cached XBRL index of the quarter"
        )
    try:
        latest = parse_index(
            client.fetch(index_url(quarter), max_bytes=MAX_INDEX_BYTES)
        )
    except errors.EdgarError:
        if cached is None:
            raise
        logger.warning("XBRL index refresh failed; the cached copy serves")
        return summary
    edgar.write_cached(
        path,
        edgar.CachedDocument(
            url=index_url(quarter),
            fetched_at=now,
            data={
                "year": quarter.year,
                "quarter": quarter.quarter,
                "complete": now.date() > quarter.end,
                "latest": latest,
            },
        ),
    )
    return latest


def active(
    summaries: Iterable[tuple[Quarter, Mapping[str, str]]],
    since_year: int,
    today: datetime.date,
) -> frozenset[str]:
    """The CIKs that pass the coverage rule.

    Args:
        summaries: Each quarter with the latest filing date of each CIK.
        since_year: The first calendar year that needs a filing.
        today: The current date.

    Returns:
        The CIKs with a 10-K or 10-Q in every year from `since_year`
        through last year, and 1 in the last 365 days.
    """
    years: dict[str, set[int]] = {}
    latest: dict[str, str] = {}
    for quarter, summary in summaries:
        for cik, filed in summary.items():
            years.setdefault(cik, set()).add(quarter.year)
            if filed > latest.get(cik, ""):
                latest[cik] = filed
    needed = set(range(since_year, today.year))
    cutoff = (today - RECENT).isoformat()
    return frozenset(
        cik
        for cik, seen in years.items()
        if needed <= seen and latest[cik] >= cutoff
    )


def active_ciks(
    client: edgar.EdgarClient,
    since_year: int,
    now: datetime.datetime | None = None,
) -> frozenset[str]:
    """The CIKs the company browser shows, kept in memory for the day.

    Args:
        client: The EDGAR client; offline, only the cache serves.
        since_year: The first calendar year that needs a filing.
        now: The current time in UTC; tests pass a fixed one.

    Returns:
        The active CIKs, 10 digits.

    Raises:
        EdgarCacheMissError: Offline, and a quarter is not cached.
        EdgarError: A quarter cannot load.
    """
    moment = now or datetime.datetime.now(datetime.UTC)
    key = (client.cache_dir, since_year, moment.date())
    with _memo_lock:
        found = _memo.get(key)
    if found is not None:
        return found
    before = client.requests
    summaries = [
        (quarter, quarter_filers(client, quarter, moment))
        for quarter in quarters(since_year, moment.date())
    ]
    found = active(summaries, since_year, moment.date())
    logger.info(
        "active filers: %d CIKs from %d quarters, %d SEC requests",
        len(found),
        len(summaries),
        client.requests - before,
    )
    with _memo_lock:
        _memo.clear()
        _memo[key] = found
    return found


def clear_memo() -> None:
    """Forget the active CIKs kept in memory; tests call it."""
    with _memo_lock:
        _memo.clear()
