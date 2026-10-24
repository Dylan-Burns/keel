"""The company browser of the admin companies page: sectors to companies.

The SEC assigns each registrant an industry (an SIC code), and each code
to the office of the Division of Corporation Finance that reviews its
filings. `config/sic_codes.yaml` (from the SEC SIC code list page, written
by `scripts/fetch_sic_codes.py`) holds the codes, their titles, and their
offices; each office is a sector here.

`industry_companies` lists the registrants of 1 industry that file a
10-K. It pages through the EDGAR company feed of the code
(`browse-edgar?action=getcompany&SIC=...&output=atom`, 100 companies per
request) through `keel.edgar.EdgarClient` (the allow list, the rate limit,
and the user agent), reads the CIKs, and caches them under
`<edgar.cache_dir>/sic/<code>.json` with the fetch time. A cached list is
fetched again after `edgar.directory_ttl_days`; offline, the cache serves
whatever its age. The company name field of that feed is broken (it reads
`ARRAY(0x...)`), so the names and tickers come from the SEC ticker map,
and a CIK without a ticker is left out: `keel add` takes a ticker.

No model request happens here (decision D-02).
"""

from __future__ import annotations

from collections.abc import Collection
from collections.abc import Iterable
import contextlib
import dataclasses
import datetime
import logging
import pathlib
import re
import sqlite3
from xml.etree import ElementTree

import pydantic

from keel import add
from keel import config
from keel import edgar
from keel import errors
from keel import indexer
from keel.stores import chunk_store

logger = logging.getLogger(__name__)

SIC_FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
    "&SIC={sic}&type=10-K&dateb=&owner=include&count={count}"
    "&start={start}&output=atom"
)
PAGE_SIZE = 100
# 30 pages are 3,000 registrants; the largest industries are cut there.
MAX_PAGES = 30
# A page of 100 entries is about 90 KB.
MAX_FEED_BYTES = 2_000_000
SIC_CODE = re.compile(r"^\d{4}$")
ATOM = "{http://www.w3.org/2005/Atom}"
_OFFICE_PREFIX = "Office of "
_FORBIDDEN_MARKUP = (b"<!doctype", b"<!entity")
# The encodings in which the byte check below sees every declaration.
_ENCODINGS = frozenset({"iso-8859-1", "latin-1", "utf-8", "us-ascii"})
_XML_ENCODING = re.compile(
    rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([^"']+)["']"""
)


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)


class Industry(_Model):
    """1 SEC industry.

    Attributes:
        code: The SIC code, 4 digits.
        title: The industry title as the SEC writes it.
        office: The SEC office that reviews the filings.
        sector: The sector of the browser: the first office named,
            without `Office of`.
    """

    code: str
    title: str
    office: str
    sector: str


class Company(_Model):
    """1 registrant of an industry, or 1 search result.

    Attributes:
        cik: The CIK, 10 digits.
        ticker: The main ticker in the SEC spelling (`BRK-B`): the one an
            Add sends.
        tickers: Every ticker of the company, the main one first.
        name: The company name from the ticker map.
        indexed: True when the index holds a filing of the company.
        watched: True when a user watches 1 of its tickers.
        addable: True when `keel add` takes the main ticker: the corpus
            file names allow letters and a share class dot only.
    """

    cik: str
    ticker: str
    tickers: tuple[str, ...]
    name: str
    indexed: bool
    watched: bool
    addable: bool


@dataclasses.dataclass(frozen=True)
class FeedPage:
    """The CIKs of 1 page of the EDGAR company feed.

    Attributes:
        ciks: The CIKs in feed order, 10 digits each.
        has_next: True when the feed links a next page.
    """

    ciks: tuple[str, ...]
    has_next: bool


@dataclasses.dataclass(frozen=True)
class IndustryList:
    """The registrants of 1 industry, from the cache or EDGAR.

    Attributes:
        sic: The SIC code.
        ciks: The CIKs of the registrants that file a 10-K.
        fetched_at: When EDGAR sent the list, in UTC.
        truncated: True when the list stopped at `MAX_PAGES`.
        stale: True when the list is older than the TTL and a fetch
            failed, so the old copy served.
        requests: The SEC requests this call sent.
    """

    sic: str
    ciks: tuple[str, ...]
    fetched_at: datetime.datetime
    truncated: bool
    stale: bool
    requests: int


@dataclasses.dataclass(frozen=True)
class Marks:
    """What the index and the watch list hold, to mark the companies.

    Attributes:
        indexed_ciks: The CIKs of the indexed filings, 10 digits.
        indexed_tickers: The tickers of the indexed filings, corpus
            spelling (`BRK.B`).
        watched: The watched tickers, corpus spelling.
    """

    indexed_ciks: frozenset[str] = frozenset()
    indexed_tickers: frozenset[str] = frozenset()
    watched: frozenset[str] = frozenset()


# --- The SIC codes ------------------------------------------------------------


def sector_of(office: str) -> str:
    """Name the sector of an SEC office.

    Args:
        office: The office as the SEC page writes it, such as `Office of
            Finance or Office of Crypto Assets`.

    Returns:
        The first office named, without `Office of`: `Finance`.
    """
    first = " ".join(office.split()).split(" or ", 1)[0]
    return first.removeprefix(_OFFICE_PREFIX)


def load_sic_codes(path: pathlib.Path) -> tuple[Industry, ...]:
    """Load `config/sic_codes.yaml`.

    Args:
        path: The YAML file with an `industries` list of code, office, and
            title.

    Returns:
        The industries in code order.

    Raises:
        ConfigError: The file is unreadable, a row is invalid, or a code
            repeats.
    """
    data = config.read_yaml(path)
    rows = data.get("industries")
    if not isinstance(rows, list) or not rows:
        raise errors.ConfigError(f"{path} has no industries list")
    industries: dict[str, Industry] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise errors.ConfigError(f"{path}: an industry is not a mapping")
        code = str(row.get("code", "")).zfill(4)
        office = " ".join(str(row.get("office", "")).split())
        title = " ".join(str(row.get("title", "")).split())
        if not SIC_CODE.match(code) or not office or not title:
            raise errors.ConfigError(f"{path}: invalid industry {code!r}")
        if code in industries:
            raise errors.ConfigError(f"{path}: SIC {code} repeats")
        industries[code] = Industry(
            code=code, title=title, office=office, sector=sector_of(office)
        )
    return tuple(sorted(industries.values(), key=lambda i: i.code))


def sectors(
    industries: Iterable[Industry],
) -> list[tuple[str, list[Industry]]]:
    """Group the industries by sector.

    Args:
        industries: The industries.

    Returns:
        (sector, industries) pairs, by sector name, each list by code.
    """
    groups: dict[str, list[Industry]] = {}
    for industry in industries:
        groups.setdefault(industry.sector, []).append(industry)
    return [
        (name, sorted(groups[name], key=lambda i: i.code))
        for name in sorted(groups)
    ]


# --- The EDGAR company feed ---------------------------------------------------


def feed_url(sic: str, start: int) -> str:
    """The URL of 1 page of the company feed of an industry.

    Args:
        sic: The SIC code, 4 digits.
        start: The offset of the first company.

    Returns:
        The URL.
    """
    return SIC_FEED_URL.format(sic=sic, count=PAGE_SIZE, start=start)


def parse_feed(body: bytes) -> FeedPage:
    """Read the CIKs of 1 page of the EDGAR company feed.

    The body comes from the network, so it is bounded before it is
    parsed, and a document type or an entity declaration is refused: the
    feed has neither, and they are how XML expands or reaches out.

    Args:
        body: The atom XML.

    Returns:
        The CIKs and whether a next page exists.

    Raises:
        EdgarFetchError: The body is too large, has an unexpected
            encoding, declares a document type or an entity, or is not XML.
    """
    if len(body) > MAX_FEED_BYTES:
        raise errors.EdgarFetchError(
            f"the company feed page has {len(body)} bytes, more than "
            f"{MAX_FEED_BYTES}"
        )
    # The byte check sees a declaration only in an ASCII-compatible
    # encoding: a NUL byte (UTF-16, UTF-32) or another declared encoding
    # (EBCDIC) is refused first. The feed is ISO-8859-1.
    declared = _XML_ENCODING.match(body)
    encoding = declared.group(1).decode("ascii", "replace") if declared else ""
    if b"\x00" in body or (encoding and encoding.lower() not in _ENCODINGS):
        raise errors.EdgarFetchError(
            "the company feed has an unexpected encoding"
        )
    lowered = body.lower()
    if any(m in lowered for m in _FORBIDDEN_MARKUP):
        raise errors.EdgarFetchError(
            "the company feed declares a document type or an entity"
        )
    try:
        # With no document type, no entity can be declared, so nothing
        # expands and nothing is fetched; the expat guard against entity
        # expansion stays the backstop.
        root = ElementTree.fromstring(body)  # noqa: S314
    except ElementTree.ParseError as error:
        raise errors.EdgarFetchError(
            f"the company feed is not XML: {error}"
        ) from error
    ciks: list[str] = []
    for entry in root.iter(f"{ATOM}entry"):
        node = entry.find(f".//{ATOM}cik")
        text = (node.text or "").strip() if node is not None else ""
        try:
            cik = edgar.cik10(text)
        except errors.EdgarError:
            logger.warning("company feed entry without a valid CIK skipped")
            continue
        if cik not in ciks:
            ciks.append(cik)
    has_next = any(
        link.get("rel") == "next" for link in root.findall(f"{ATOM}link")
    )
    return FeedPage(ciks=tuple(ciks), has_next=has_next)


def cache_path(cache_dir: pathlib.Path, sic: str) -> pathlib.Path:
    """The cache file of the company list of an industry.

    Args:
        cache_dir: The EDGAR cache directory.
        sic: The SIC code, 4 digits.

    Returns:
        `<cache_dir>/sic/<code>.json`.

    Raises:
        EdgarError: The code is not 4 digits.
    """
    if not SIC_CODE.match(sic):
        raise errors.EdgarError(f"not an SIC code: {sic!r}")
    return cache_dir / "sic" / f"{sic}.json"


def _list_of(
    document: edgar.CachedDocument, *, stale: bool, requests: int
) -> IndustryList:
    data = document.data
    if not isinstance(data, dict) or not isinstance(data.get("ciks"), list):
        raise errors.EdgarError("bad company list in the EDGAR cache")
    return IndustryList(
        sic=str(data.get("sic", "")),
        ciks=tuple(edgar.cik10(c) for c in data["ciks"]),
        fetched_at=document.fetched_at,
        truncated=bool(data.get("truncated", False)),
        stale=stale,
        requests=requests,
    )


def read_industry(cache_dir: pathlib.Path, sic: str) -> IndustryList | None:
    """Read the cached company list of an industry, without a request.

    Args:
        cache_dir: The EDGAR cache directory.
        sic: The SIC code, 4 digits.

    Returns:
        The list, or None when the cache has none or a bad one.
    """
    path = cache_path(cache_dir, sic)
    if not path.is_file():
        return None
    try:
        return _list_of(edgar.read_cached(path), stale=False, requests=0)
    except errors.EdgarError:
        logger.warning("bad company list cache file skipped")
        return None


def _fetch(client: edgar.EdgarClient, sic: str) -> edgar.CachedDocument:
    """Page through the company feed of an industry and cache the CIKs."""
    ciks: dict[str, None] = {}
    pages = 0
    truncated = False
    while True:
        body = client.fetch(
            feed_url(sic, pages * PAGE_SIZE), max_bytes=MAX_FEED_BYTES
        )
        page = parse_feed(body)
        pages += 1
        ciks.update(dict.fromkeys(page.ciks))
        if not page.has_next or not page.ciks:
            break
        if pages >= MAX_PAGES:
            truncated = True
            break
    document = edgar.CachedDocument(
        url=feed_url(sic, 0),
        fetched_at=datetime.datetime.now(datetime.UTC),
        data={
            "sic": sic,
            "ciks": list(ciks),
            "pages": pages,
            "truncated": truncated,
        },
    )
    edgar.write_cached(cache_path(client.cache_dir, sic), document)
    return document


def industry_ciks(
    client: edgar.EdgarClient,
    sic: str,
    *,
    ttl_days: int,
    now: datetime.datetime | None = None,
) -> IndustryList:
    """The CIKs of an industry: from the cache, else from EDGAR.

    Args:
        client: The EDGAR client; offline, only the cache serves.
        sic: The SIC code, 4 digits.
        ttl_days: The age after which a cached list is fetched again.
        now: The current time in UTC; tests pass a fixed one.

    Returns:
        The list with its fetch time and the requests sent.

    Raises:
        EdgarCacheMissError: The client is offline and the cache has no
            list.
        EdgarError: The fetch fails and the cache has no list, or the
            code is not 4 digits.
    """
    cached = read_industry(client.cache_dir, sic)
    moment = now or datetime.datetime.now(datetime.UTC)
    if cached is not None:
        fresh = moment - cached.fetched_at < datetime.timedelta(days=ttl_days)
        if fresh or client.offline:
            return cached
    elif client.offline:
        raise errors.EdgarCacheMissError(
            "offline and no cached company list of the industry"
        )
    before = client.requests
    try:
        document = _fetch(client, sic)
    except errors.EdgarError:
        if cached is None:
            raise
        logger.warning("company list refresh failed; the cached copy serves")
        return dataclasses.replace(
            cached, stale=True, requests=client.requests - before
        )
    return _list_of(document, stale=False, requests=client.requests - before)


# --- Companies ----------------------------------------------------------------


def _corpus_spelling(ticker: str) -> str | None:
    try:
        return add.corpus_ticker(ticker)
    except errors.EdgarError:
        return None


def company_of(
    rows: tuple[edgar.TickerEntry, ...], marks: Marks
) -> Company | None:
    """Build the company of the ticker map rows of 1 CIK.

    Args:
        rows: The rows of the CIK, the main ticker first.
        marks: The indexed and watched sets.

    Returns:
        The company, or None without a row.
    """
    if not rows:
        return None
    first = rows[0]
    spelled = {_corpus_spelling(r.ticker) for r in rows} - {None}
    return Company(
        cik=first.cik,
        ticker=first.ticker,
        tickers=tuple(r.ticker for r in rows),
        name=first.title,
        indexed=first.cik in marks.indexed_ciks
        or bool(spelled & marks.indexed_tickers),
        watched=bool(spelled & marks.watched),
        addable=_corpus_spelling(first.ticker) is not None,
    )


def join_companies(
    ciks: Iterable[str], tickers: edgar.TickerMap, marks: Marks
) -> list[Company]:
    """Join CIKs to the ticker map; a CIK without a ticker is left out.

    Args:
        ciks: The CIKs.
        tickers: The SEC ticker map.
        marks: The indexed and watched sets.

    Returns:
        The companies, by ticker.
    """
    companies = [
        company
        for cik in ciks
        if (company := company_of(tickers.by_cik(cik), marks)) is not None
    ]
    return sorted(companies, key=lambda c: c.ticker)


def search(
    tickers: edgar.TickerMap, query: str, marks: Marks, limit: int = 50
) -> list[Company]:
    """Find companies by ticker or name.

    The ranks: the exact ticker, a ticker that starts with the query, a
    name that starts with it, then a name that holds it. 1 row per
    company.

    Args:
        tickers: The SEC ticker map.
        query: The text; case and the `.` of a share class do not matter.
        marks: The indexed and watched sets.
        limit: The most companies returned.

    Returns:
        The companies, best first.
    """
    text = " ".join(query.split()).upper()
    key = edgar.normalize_ticker(text)
    if len(text) < 2:
        return []
    ranked: dict[str, tuple[int, str]] = {}
    for entry in tickers:
        name = entry.title.upper()
        if entry.ticker == key:
            rank = 0
        elif entry.ticker.startswith(key):
            rank = 1
        elif name.startswith(text):
            rank = 2
        elif text in name:
            rank = 3
        else:
            continue
        best = ranked.get(entry.cik)
        if best is None or (rank, entry.ticker) < best:
            ranked[entry.cik] = (rank, entry.ticker)
    order = sorted(ranked.items(), key=lambda item: item[1])[:limit]
    found = []
    for cik, _ in order:
        company = company_of(tickers.by_cik(cik), marks)
        if company is not None:
            found.append(company)
    return found


def indexed_marks(
    index_dir: pathlib.Path, watched: Collection[str] = ()
) -> Marks:
    """Read the CIKs and tickers of the current build.

    Args:
        index_dir: The index directory with the `current` build.
        watched: The watched tickers, corpus spelling.

    Returns:
        The marks; without a build or with an unreadable one, nothing is
        indexed.
    """
    ciks: set[str] = set()
    names: set[str] = set()
    current = indexer.current_build(index_dir)
    if current is not None:
        try:
            conn = chunk_store.open_read_only(current / chunk_store.FILE_NAME)
        except errors.IndexMissingError:
            conn = None
        if conn is not None:
            try:
                for ticker, cik in conn.execute(
                    "SELECT DISTINCT ticker, cik FROM filings"
                ):
                    names.add(str(ticker))
                    if cik:
                        with contextlib.suppress(errors.EdgarError):
                            ciks.add(edgar.cik10(str(cik)))
            except sqlite3.Error:
                logger.warning(
                    "the filings of the current build are unreadable"
                )
            finally:
                conn.close()
    return Marks(
        indexed_ciks=frozenset(ciks),
        indexed_tickers=frozenset(names),
        watched=frozenset(watched),
    )
