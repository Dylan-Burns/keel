"""The SEC EDGAR client and the company facts lines (chapter 26).

The client fetches 4 documents: the ticker map and the primary document of
a filing from `www.sec.gov`, and the company facts and the submissions of 1
company from `data.sec.gov`. Every
request carries the `User-Agent` header from `edgar.user_agent`, waits for
the minimum interval since the previous request, and passes the outbound
allow list of control S-11: https only, the 2 SEC hosts only, no private,
loopback, or link-local address, every redirect target checked again, and
the address of the opened socket checked before the body is read (a DNS
rebinding answer between the 2 lookups). Every response lands in the disk
cache under `edgar.cache_dir` with its fetch time, so a repeat run makes no
request.

`filings_of` and `pick_latest` read the submissions of a company and pick
the filings that `keel add` ingests (chapter 26.2, step 2).

`facts_lines` is a pure function: from a company facts document, a ticker,
the concepts of `config/facts.yaml`, and a period window, it builds the
lines of the `<facts>` block (chapter 26.1, step 4). The prompt module
calls it; no model request happens here (decision D-01).
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import datetime
import decimal
import ipaddress
import json
import logging
import pathlib
import re
import socket
import tempfile
import time
from typing import Any
from typing import Literal
import urllib.parse

import httpx
import pydantic

from keel import config
from keel import errors
from keel import net

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}"
    "-index.htm"
)
LOOKUP_URL = "https://www.sec.gov/edgar/searchedgar/companysearch"
DOCUMENT_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{document}"
)
ADD_FORMS = ("10-K", "10-Q")
# The submissions JSON is data from the network: an accession number and a
# document name must have these shapes before they name a URL or a file.
ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
DOCUMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.html?$")
MAX_REDIRECTS = 3
MAX_FACT_LINES = 40
FACT_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})

# A fiscal year runs 52 or 53 weeks, a quarter 13 or 14 weeks. Durations
# outside both ranges (the 6- and 9-month year-to-date values of a 10-Q)
# get no fact line.
_ANNUAL_DAYS = range(350, 381)
_QUARTER_DAYS = range(84, 99)

Resolver = Callable[[str], Sequence[str]]
Clock = Callable[[], float]
Sleep = Callable[[float], None]
PeriodKind = Literal["annual", "quarter", "instant"]


# --- Outbound allow list (control S-11) ---------------------------------------


def resolve_host(host: str) -> list[str]:
    """Resolve a host name to its IP addresses through the system resolver.

    Args:
        host: The host name.

    Returns:
        The distinct addresses, in resolver order.

    Raises:
        OutboundBlockedError: The name does not resolve.
    """
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as error:
        raise errors.OutboundBlockedError(
            f"cannot resolve {host}: {error}"
        ) from error
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
    return addresses


def _is_public(address: str) -> bool:
    """Tell whether an IP address is a public unicast address."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # is_global rejects private, loopback, link-local, shared (100.64/10),
    # reserved, and unspecified addresses; multicast is never a server.
    return ip.is_global and not ip.is_multicast


def check_url(url: str, resolver: Resolver = resolve_host) -> str:
    """Check a URL against the outbound allow list of control S-11.

    Args:
        url: The URL to fetch.
        resolver: Resolves a host name to its IP addresses.

    Returns:
        The URL, unchanged.

    Raises:
        OutboundBlockedError: The scheme is not https, the host is not an
            allowed SEC host, the URL carries credentials or a port, or a
            resolved address is private, loopback, or link-local.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise errors.OutboundBlockedError(f"not https: {url}")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise errors.OutboundBlockedError(f"credentials or port in {url}")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise errors.OutboundBlockedError(f"host not allowed: {host or url}")
    addresses = list(resolver(host))
    if not addresses:
        raise errors.OutboundBlockedError(f"{host} resolves to no address")
    for address in addresses:
        if not _is_public(address):
            raise errors.OutboundBlockedError(
                f"{host} resolves to a non-public address {address}"
            )
    return url


# --- Documents and the ticker map ---------------------------------------------


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)


class CachedDocument(_Model):
    """1 JSON document from EDGAR, as the disk cache stores it.

    Attributes:
        url: The URL the document came from.
        fetched_at: When the client fetched it, in UTC.
        data: The parsed JSON body.
    """

    url: str
    fetched_at: datetime.datetime
    data: Any


class TickerEntry(_Model):
    """1 row of the SEC ticker map.

    Attributes:
        ticker: The ticker in the SEC spelling (upper case, `-` for `.`).
        cik: The CIK, 10 digits with leading zeros.
        title: The company name as the SEC lists it.
    """

    ticker: str
    cik: str
    title: str


def cik10(cik: int | str) -> str:
    """Format a CIK as the 10 digits with leading zeros of the EDGAR URLs.

    Args:
        cik: The CIK as a number or a digit string.

    Returns:
        The CIK, zero padded to 10 digits.

    Raises:
        EdgarError: The value is not a CIK of at most 10 digits.
    """
    text = str(cik).strip()
    if not text.isdigit() or len(text) > 10 or int(text) == 0:
        raise errors.EdgarError(f"not a CIK: {cik!r}")
    return text.zfill(10)


def normalize_ticker(ticker: str) -> str:
    """Spell a ticker the way the SEC ticker map does (`BRK.B` is `BRK-B`).

    Args:
        ticker: The ticker as typed.

    Returns:
        The ticker, trimmed, upper case, with `-` for `.` and `/`.
    """
    return ticker.strip().upper().replace(".", "-").replace("/", "-")


class TickerMap:
    """The SEC ticker map: ticker to CIK and company name.

    Args:
        entries: The rows of the map. The first row of a ticker wins.
    """

    def __init__(self, entries: Iterable[TickerEntry]) -> None:
        self._entries: dict[str, TickerEntry] = {}
        for entry in entries:
            self._entries.setdefault(entry.ticker, entry)

    @classmethod
    def from_json(cls, data: object) -> TickerMap:
        """Read the body of `company_tickers.json`.

        Args:
            data: The parsed JSON: a mapping of row numbers to rows with
                `cik_str`, `ticker`, and `title`.

        Returns:
            The ticker map.

        Raises:
            EdgarError: The body does not have that shape.
        """
        if not isinstance(data, Mapping):
            raise errors.EdgarError("the ticker map is not a JSON object")
        entries = []
        for row in data.values():
            try:
                entries.append(
                    TickerEntry(
                        ticker=normalize_ticker(str(row["ticker"])),
                        cik=cik10(row["cik_str"]),
                        title=str(row["title"]),
                    )
                )
            except (KeyError, TypeError) as error:
                raise errors.EdgarError(
                    f"bad ticker map row: {row!r}"
                ) from error
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, ticker: object) -> bool:
        return (
            isinstance(ticker, str)
            and normalize_ticker(ticker) in self._entries
        )

    def lookup(self, ticker: str) -> TickerEntry:
        """Find the row of a ticker.

        Args:
            ticker: The ticker, in any case, with `.` or `-`, or the root
                of share classes that all belong to 1 company.

        Returns:
            The row.

        Raises:
            UnknownTickerError: The map has no such ticker. The message
                names the SEC company lookup page.
        """
        key = normalize_ticker(ticker)
        entry = self._entries.get(key)
        if entry is None:
            # A share class root (the corpus writes `BRK`, the map `BRK-B`)
            # resolves when every class of it belongs to 1 CIK.
            classes = [
                e for t, e in self._entries.items() if t.startswith(key + "-")
            ]
            if classes and len({e.cik for e in classes}) == 1:
                entry = classes[0]
        if entry is None:
            raise errors.UnknownTickerError(
                f"unknown ticker {ticker!r}: the SEC ticker map has no "
                f"entry; look the company up at {LOOKUP_URL}"
            )
        return entry

    def cik(self, ticker: str) -> str:
        """Map a ticker to its 10-digit CIK.

        Args:
            ticker: The ticker.

        Returns:
            The CIK, zero padded to 10 digits.

        Raises:
            UnknownTickerError: The map has no such ticker.
        """
        return self.lookup(ticker).cik


# --- Submissions (chapter 26.2, step 2) ---------------------------------------


class FilingRef(_Model):
    """1 filing of the submissions JSON that `keel add` can ingest.

    Attributes:
        cik: The CIK of the filer, 10 digits.
        form: `10-K` or `10-Q`.
        accession: The accession number, `0001555280-26-000011`.
        filing_date: The filing date.
        report_date: The period end date the submissions JSON states.
        primary_document: The file name of the primary document.
    """

    cik: str
    form: str
    accession: str
    filing_date: datetime.date
    report_date: datetime.date
    primary_document: str

    @pydantic.field_validator("cik")
    @classmethod
    def _check_cik(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 10:
            raise ValueError(f"not a 10-digit CIK: {value!r}")
        return value

    @pydantic.field_validator("accession")
    @classmethod
    def _check_accession(cls, value: str) -> str:
        if not ACCESSION.match(value):
            raise ValueError(f"not an accession number: {value!r}")
        return value

    @pydantic.field_validator("primary_document")
    @classmethod
    def _check_document(cls, value: str) -> str:
        # The name joins a URL and a cache path, so no `/` or `..` passes.
        if not DOCUMENT_NAME.match(value) or ".." in value:
            raise ValueError(f"not a document name: {value!r}")
        return value

    @property
    def url(self) -> str:
        """The https URL of the primary document on www.sec.gov.

        Returns:
            The archive URL.
        """
        return DOCUMENT_URL.format(
            cik=int(self.cik),
            folder=self.accession.replace("-", ""),
            document=self.primary_document,
        )


def filings_of(
    submissions: Mapping[str, Any], forms: Sequence[str] = ADD_FORMS
) -> list[FilingRef]:
    """List the filings of the given forms in a submissions body.

    Only the forms named count: a `10-K/A` is not a `10-K`. A row with a
    malformed accession number, document name, or date is skipped with a
    warning, because the values name a URL and a cache file (the
    `FilingRef` validators check them).

    Args:
        submissions: The submissions JSON (`CachedDocument.data`).
        forms: The forms to keep.

    Returns:
        The filings, newest filing date first (the accession number breaks
        a tie).

    Raises:
        EdgarError: The body has no `filings.recent` arrays of 1 length,
            or no CIK.
    """
    try:
        cik = cik10(submissions["cik"])
        recent = submissions["filings"]["recent"]
        columns = [
            recent[key]
            for key in (
                "form",
                "accessionNumber",
                "filingDate",
                "reportDate",
                "primaryDocument",
            )
        ]
    except (KeyError, TypeError) as error:
        raise errors.EdgarError(
            "the submissions body has no filings.recent arrays"
        ) from error
    if len({len(column) for column in columns}) != 1:
        raise errors.EdgarError("the filings.recent arrays differ in length")
    found: list[FilingRef] = []
    for form, accession, filed, report, document in zip(*columns, strict=True):
        if form not in forms:
            continue
        try:
            found.append(
                FilingRef(
                    cik=cik,
                    form=form,
                    accession=accession,
                    filing_date=datetime.date.fromisoformat(filed),
                    report_date=datetime.date.fromisoformat(report),
                    primary_document=document,
                )
            )
        except (TypeError, ValueError):
            # pydantic.ValidationError is a ValueError: a malformed
            # accession number or document name never names a path.
            logger.warning("skipping a bad %s row: %s", form, accession)
    found.sort(key=lambda ref: (ref.filing_date, ref.accession), reverse=True)
    return found


def pick_latest(
    submissions: Mapping[str, Any], forms: Sequence[str] = ADD_FORMS
) -> list[FilingRef]:
    """Pick the latest filing of each form (chapter 26.2, step 2).

    Args:
        submissions: The submissions JSON (`CachedDocument.data`).
        forms: The forms, in output order.

    Returns:
        1 filing per form that the company has filed, in `forms` order.

    Raises:
        EdgarError: The body is malformed, or it holds none of the forms.
    """
    latest: dict[str, FilingRef] = {}
    for ref in filings_of(submissions, forms):
        latest.setdefault(ref.form, ref)
    if not latest:
        raise errors.EdgarError(
            "the submissions list no " + " or ".join(forms) + " filing"
        )
    return [latest[form] for form in forms if form in latest]


# --- The client ---------------------------------------------------------------


class EdgarClient:
    """A rate-limited, cached, allow-listed client for SEC EDGAR.

    Args:
        user_agent: The `User-Agent` header (a name and an email address).
        cache_dir: The disk cache directory.
        min_interval: The minimum seconds between 2 requests.
        offline: Serve only from the cache; a cache miss raises.
        transport: The httpx transport; tests pass a mock transport.
        resolver: Resolves a host to its addresses for the S-11 check.
        clock: A monotonic clock in seconds.
        sleep: Sleeps for a number of seconds.
        timeout: The request timeout in seconds.

    Raises:
        EdgarError: The user agent is empty.
    """

    def __init__(
        self,
        user_agent: str,
        cache_dir: pathlib.Path,
        *,
        min_interval: float = 0.2,
        offline: bool = False,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = resolve_host,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        timeout: float = 30.0,
    ) -> None:
        if not user_agent.strip():
            raise errors.EdgarError("edgar.user_agent is empty")
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.offline = offline
        self.requests = 0
        self._resolver = resolver
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None
        self._ticker_map: TickerMap | None = None
        self._http = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=False,
            # No proxy from the environment: S-11 checks the direct route.
            trust_env=False,
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls,
        settings: config.Settings,
        *,
        offline: bool | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> EdgarClient:
        """Build the client from the `edgar` config section.

        Args:
            settings: The loaded settings.
            offline: Serve only from the cache. None reads the top-level
                `offline` setting.
            transport: The httpx transport; tests pass a mock transport.

        Returns:
            The client.
        """
        return cls(
            settings.edgar.user_agent,
            settings.edgar.cache_dir,
            min_interval=settings.edgar.min_request_interval_seconds,
            offline=settings.offline if offline is None else offline,
            transport=transport,
        )

    def __enter__(self) -> EdgarClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP connection pool.

        Returns:
            None.
        """
        self._http.close()

    # The cache paths mirror the URL paths of the 3 documents.

    def ticker_map_path(self) -> pathlib.Path:
        """Return the cache file of the ticker map.

        Returns:
            The path under the cache directory.
        """
        return self.cache_dir / "company_tickers.json"

    def company_facts_path(self, cik: str) -> pathlib.Path:
        """Return the cache file of the company facts of a CIK.

        Args:
            cik: The CIK (any zero padding).

        Returns:
            The path under the cache directory.
        """
        return self.cache_dir / "companyfacts" / f"CIK{cik10(cik)}.json"

    def submissions_path(self, cik: str) -> pathlib.Path:
        """Return the cache file of the submissions of a CIK.

        Args:
            cik: The CIK (any zero padding).

        Returns:
            The path under the cache directory.
        """
        return self.cache_dir / "submissions" / f"CIK{cik10(cik)}.json"

    def ticker_map(self, refresh: bool = False) -> TickerMap:
        """Load the ticker map, from the cache when it holds a copy.

        Args:
            refresh: Fetch a new copy even when the cache holds one.

        Returns:
            The ticker map.

        Raises:
            EdgarError: The fetch, the cache, or the body fails.
        """
        if self._ticker_map is None or refresh:
            document = self._document(
                TICKER_MAP_URL, self.ticker_map_path(), refresh
            )
            self._ticker_map = TickerMap.from_json(document.data)
        return self._ticker_map

    def cik(self, ticker: str) -> str:
        """Map a ticker to its 10-digit CIK through the ticker map.

        Args:
            ticker: The ticker.

        Returns:
            The CIK, zero padded to 10 digits.

        Raises:
            UnknownTickerError: The map has no such ticker.
            EdgarError: The ticker map cannot load.
        """
        return self.ticker_map().cik(ticker)

    def company_facts(self, cik: str, refresh: bool = False) -> CachedDocument:
        """Load the XBRL company facts of 1 company.

        Args:
            cik: The CIK (any zero padding); `cik(ticker)` gives it.
            refresh: Fetch a new copy even when the cache holds one.

        Returns:
            The document with its fetch time.

        Raises:
            EdgarError: The fetch, the cache, or the body fails.
        """
        url = COMPANY_FACTS_URL.format(cik=cik10(cik))
        return self._document(url, self.company_facts_path(cik), refresh)

    def submissions(self, cik: str, refresh: bool = False) -> CachedDocument:
        """Load the submissions (the filing history) of 1 company.

        Args:
            cik: The CIK (any zero padding).
            refresh: Fetch a new copy even when the cache holds one; `keel
                refresh` passes True.

        Returns:
            The document with its fetch time.

        Raises:
            EdgarError: The fetch, the cache, or the body fails.
        """
        url = SUBMISSIONS_URL.format(cik=cik10(cik))
        return self._document(url, self.submissions_path(cik), refresh)

    def document_path(self, ref: FilingRef) -> pathlib.Path:
        """Return the cache file of the primary document of a filing.

        The path mirrors the archive URL: `Archives/<cik>/<accession
        without dashes>/<document>`. A sidecar `<document>.json` holds the
        URL and the fetch time.

        Args:
            ref: The filing.

        Returns:
            The path under the cache directory.
        """
        return (
            self.cache_dir
            / "Archives"
            / str(int(ref.cik))
            / ref.accession.replace("-", "")
            / ref.primary_document
        )

    def filing_document(self, ref: FilingRef) -> bytes:
        """Load the primary document of a filing (chapter 26.2, step 3).

        Args:
            ref: The filing, from `pick_latest` or `filings_of`.

        Returns:
            The document bytes (inline XBRL HTML).

        Raises:
            EdgarCacheMissError: The client is offline and the cache holds
                no copy.
            EdgarError: The fetch or the cache write fails.
        """
        path = self.document_path(ref)
        sidecar = path.with_name(path.name + ".json")
        if path.is_file() and sidecar.is_file():
            return path.read_bytes()
        if self.offline:
            raise errors.EdgarCacheMissError(
                f"offline and no cached copy of {ref.url} at {path}"
            )
        body = self.fetch(ref.url)
        _write_bytes(path, body)
        write_cached(
            sidecar,
            CachedDocument(
                url=ref.url,
                fetched_at=datetime.datetime.now(datetime.UTC),
                data={"bytes": len(body), "form": ref.form},
            ),
        )
        return body

    def _document(
        self, url: str, path: pathlib.Path, refresh: bool
    ) -> CachedDocument:
        """Serve a JSON document from the cache, or fetch and cache it."""
        if not refresh and path.exists():
            return read_cached(path)
        if self.offline:
            raise errors.EdgarCacheMissError(
                f"offline and no cached copy of {url} at {path}"
            )
        body = self.fetch(url)
        try:
            data = json.loads(body)
        except ValueError as error:
            raise errors.EdgarFetchError(f"{url} is not JSON") from error
        document = CachedDocument(
            url=url,
            fetched_at=datetime.datetime.now(datetime.UTC),
            data=data,
        )
        write_cached(path, document)
        return document

    def fetch(self, url: str) -> bytes:
        """GET 1 allow-listed URL with the rate limit and redirect checks.

        Args:
            url: The URL.

        Returns:
            The response body.

        Raises:
            OutboundBlockedError: The URL or a redirect target fails S-11.
            EdgarFetchError: The request fails, a redirect has no target,
                there are too many redirects, or the status is not 200.
        """
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url, self._resolver)
            response = self._get(url)
            if not response.is_redirect:
                if response.status_code != httpx.codes.OK:
                    raise errors.EdgarFetchError(
                        f"HTTP {response.status_code} from {url}"
                    )
                return response.content
            location = response.headers.get("location")
            if not location:
                raise errors.EdgarFetchError(f"redirect without target: {url}")
            url = urllib.parse.urljoin(url, location)
            logger.info("EDGAR redirect to %s", url)
        raise errors.EdgarFetchError(f"more than {MAX_REDIRECTS} redirects")

    def _get(self, url: str) -> httpx.Response:
        """Send 1 GET after the minimum interval since the last request."""
        if self._last_request is not None:
            wait = self.min_interval - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        try:
            logger.info("EDGAR GET %s", url)
            with self._http.stream("GET", url) as response:
                # DNS rebinding (S-11): the connect resolves the name again,
                # so the address of the open socket is checked too, before
                # the body is read.
                net.check_peer(response, host)
                response.read()
                return response
        except errors.HostNotAllowedError as error:
            raise errors.OutboundBlockedError(str(error)) from error
        except httpx.HTTPError as error:
            raise errors.EdgarFetchError(f"GET {url}: {error}") from error
        finally:
            self._last_request = self._clock()
            self.requests += 1


def read_cached(path: pathlib.Path) -> CachedDocument:
    """Read 1 cached EDGAR document.

    Args:
        path: The cache file.

    Returns:
        The document.

    Raises:
        EdgarError: The file is unreadable or not a cached document.
    """
    try:
        return CachedDocument.model_validate_json(path.read_bytes())
    except (OSError, pydantic.ValidationError) as error:
        raise errors.EdgarError(f"bad EDGAR cache file {path}") from error


def write_cached(path: pathlib.Path, document: CachedDocument) -> None:
    """Write 1 EDGAR document to the cache through a temporary file.

    Args:
        path: The cache file.
        document: The document.

    Raises:
        EdgarError: The file cannot be written.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name,
            suffix=".tmp",
            delete=False,
        ) as stream:
            stream.write(document.model_dump_json())
        pathlib.Path(stream.name).replace(path)
    except OSError as error:
        raise errors.EdgarError(f"cannot write {path}: {error}") from error


def _write_bytes(path: pathlib.Path, body: bytes) -> None:
    """Write bytes to a cache file through a temporary file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=path.name, suffix=".tmp", delete=False
        ) as stream:
            stream.write(body)
        pathlib.Path(stream.name).replace(path)
    except OSError as error:
        raise errors.EdgarError(f"cannot write {path}: {error}") from error


# --- Facts config (config/facts.yaml) -----------------------------------------


class FactConcept(_Model):
    """1 mapped concept of `config/facts.yaml`.

    Attributes:
        key: The concept key, such as `revenue`.
        label: The display name, such as `Revenue`.
        unit: The XBRL unit to read, such as `USD` or `USD/shares`.
        names: The XBRL concept names (`taxonomy:Name`) in priority order.
    """

    key: str
    label: str
    unit: str
    names: tuple[str, ...] = pydantic.Field(min_length=1)

    @pydantic.field_validator("names")
    @classmethod
    def _check_names(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        for name in names:
            taxonomy, _, local = name.partition(":")
            if not taxonomy or not local:
                raise ValueError(f"{name!r} is not taxonomy:Name")
        return names


class FactsConfig(_Model):
    """The concepts of `config/facts.yaml`, in block order.

    Attributes:
        concepts: The mapped concepts.
    """

    concepts: tuple[FactConcept, ...] = pydantic.Field(min_length=1)


def load_facts_config(path: pathlib.Path) -> FactsConfig:
    """Load `config/facts.yaml`.

    Args:
        path: The YAML file: a `concepts` mapping of key to label, unit,
            and names.

    Returns:
        The validated config.

    Raises:
        ConfigError: The file is unreadable or fails validation.
    """
    data = config.read_yaml(path)
    concepts = data.get("concepts")
    if not isinstance(concepts, Mapping):
        raise errors.ConfigError(f"{path} has no concepts mapping")
    try:
        return FactsConfig(
            concepts=tuple(
                FactConcept(key=str(key), **dict(entry))
                for key, entry in concepts.items()
            )
        )
    except (TypeError, ValueError) as error:
        raise errors.ConfigError(f"invalid {path}: {error}") from error


# --- Facts lines (chapter 26.1, step 4) ---------------------------------------


class FactLine(_Model):
    """1 line of the `<facts>` block.

    Attributes:
        fact_id: The citable ID, `facts:<TICKER>:<XBRL name>:<label>`.
        ticker: The ticker.
        cik: The CIK, 10 digits.
        concept: The concept key of `config/facts.yaml`.
        xbrl_name: The XBRL concept name that held the value.
        value: The value as reported, in the XBRL unit.
        unit: The XBRL unit, such as `USD`.
        display_value: The value in the display unit, with thousands
            separators.
        display_unit: The display unit, such as `USD millions`.
        fiscal_label: `FY2025`, `Q3 FY2026`, and so on.
        period_kind: `annual`, `quarter`, or `instant`.
        period_start: The first day of a duration, None for an instant.
        period_end: The last day of the period, or the instant.
        form: The form of the filing that reported the value.
        filed: The filing date.
        accession: The accession number.
    """

    fact_id: str
    ticker: str
    cik: str
    concept: str
    xbrl_name: str
    value: decimal.Decimal
    unit: str
    display_value: str
    display_unit: str
    fiscal_label: str
    period_kind: PeriodKind
    period_start: datetime.date | None
    period_end: datetime.date
    form: str
    filed: datetime.date
    accession: str

    @property
    def filing_index_url(self) -> str:
        """The EDGAR filing index page of the filing behind the value.

        Returns:
            The https URL of the filing index on www.sec.gov.
        """
        return FILING_INDEX_URL.format(
            cik=int(self.cik),
            folder=self.accession.replace("-", ""),
            accession=self.accession,
        )

    def text(self) -> str:
        """Render the line in the chapter 26.1 format.

        Returns:
            `<fact id> | <value> | <unit> | <label> | period end <date> |
            <form> filed <date> | accession <number>`.
        """
        return (
            f"{self.fact_id} | {self.display_value} | {self.display_unit} | "
            f"{self.fiscal_label} | period end {self.period_end.isoformat()} "
            f"| {self.form} filed {self.filed.isoformat()} | accession "
            f"{self.accession}"
        )


class FactsBlock(_Model):
    """The facts lines of 1 company for 1 window.

    Attributes:
        ticker: The ticker.
        cik: The CIK, 10 digits, or empty when the document has none.
        entity_name: The company name in the document.
        lines: The lines in block order: by concept, newest period first.
        dropped: The lines in the window that the line limit dropped.
    """

    ticker: str
    cik: str
    entity_name: str
    lines: tuple[FactLine, ...]
    dropped: int = 0

    def text(self) -> str:
        """Render the lines, 1 per row, without the enclosing tags.

        Returns:
            The lines joined by newlines; empty when there is no line.
        """
        return "\n".join(line.text() for line in self.lines)

    def fact_ids(self) -> frozenset[str]:
        """Return the fact IDs of the block, for the citation validator.

        Returns:
            The fact IDs.
        """
        return frozenset(line.fact_id for line in self.lines)


@dataclasses.dataclass(frozen=True)
class _Entry:
    """1 reported value of the company facts document."""

    concept: str
    priority: int
    xbrl_name: str
    unit: str
    value: decimal.Decimal
    kind: PeriodKind
    start: datetime.date | None
    end: datetime.date
    fiscal_year: int
    fiscal_period: str
    form: str
    filed: datetime.date
    accession: str

    @property
    def period(self) -> tuple[str, datetime.date | None, datetime.date]:
        return (self.concept, self.start, self.end)


def _kind(start: datetime.date | None, end: datetime.date) -> PeriodKind | None:
    """Classify a period: annual, quarter, instant, or None for other."""
    if start is None:
        return "instant"
    days = (end - start).days + 1
    if days in _ANNUAL_DAYS:
        return "annual"
    if days in _QUARTER_DAYS:
        return "quarter"
    return None


def _entries(
    document: Mapping[str, Any], concepts: Sequence[FactConcept]
) -> list[_Entry]:
    """Read the values of the mapped concepts from a company facts body."""
    facts = document.get("facts")
    if not isinstance(facts, Mapping):
        return []
    entries: list[_Entry] = []
    for concept in concepts:
        for priority, name in enumerate(concept.names):
            taxonomy, _, local = name.partition(":")
            items = facts.get(taxonomy)
            item = items.get(local) if isinstance(items, Mapping) else None
            units = item.get("units") if isinstance(item, Mapping) else None
            rows = (
                units.get(concept.unit) if isinstance(units, Mapping) else None
            )
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, Mapping):
                    continue
                entry = _entry(concept, priority, local, row)
                if entry is not None:
                    entries.append(entry)
    return entries


def _entry(
    concept: FactConcept, priority: int, local: str, row: Mapping[str, Any]
) -> _Entry | None:
    """Read 1 row of a concept, or None for a row outside the facts lines."""
    form = str(row.get("form", ""))
    if form not in FACT_FORMS:
        return None
    try:
        start = (
            datetime.date.fromisoformat(row["start"])
            if "start" in row
            else None
        )
        end = datetime.date.fromisoformat(row["end"])
        kind = _kind(start, end)
        if kind is None or row.get("fy") is None:
            return None
        return _Entry(
            concept=concept.key,
            priority=priority,
            xbrl_name=local,
            unit=concept.unit,
            value=decimal.Decimal(str(row["val"])),
            kind=kind,
            start=start,
            end=end,
            fiscal_year=int(row["fy"]),
            fiscal_period=str(row.get("fp") or "FY"),
            form=form,
            filed=datetime.date.fromisoformat(row["filed"]),
            accession=str(row["accn"]),
        )
    except (KeyError, TypeError, ValueError, decimal.InvalidOperation):
        logger.warning("skipping a bad %s row: %r", local, row)
        return None


def _current_labels(
    entries: Sequence[_Entry],
) -> dict[tuple[PeriodKind, datetime.date], tuple[int, str]]:
    """Map the current periods of each filing to the filing's fiscal label.

    The `fy` and `fp` of a value belong to the filing, not to the period:
    a 10-K for fiscal 2025 also reports fiscal 2024 and 2023 under `fy`
    2025. The current period of a filing is its latest duration of a kind,
    and only that period takes the filing's label.

    Args:
        entries: The values.

    Returns:
        (kind, period end) to (fiscal year, fiscal period). An instant at
        the end of a current duration takes the label of that duration.
    """
    latest: dict[tuple[str, PeriodKind], datetime.date] = {}
    for entry in entries:
        if entry.kind != "instant":
            key = (entry.accession, entry.kind)
            latest[key] = max(latest.get(key, entry.end), entry.end)
    labels: dict[tuple[PeriodKind, datetime.date], tuple[int, str]] = {}
    for entry in sorted(entries, key=lambda item: item.filed):
        if entry.kind == "instant":
            continue
        if latest[(entry.accession, entry.kind)] != entry.end:
            continue
        label = (entry.fiscal_year, entry.fiscal_period)
        labels.setdefault((entry.kind, entry.end), label)
        if entry.kind == "annual" or entry.fiscal_period != "FY":
            labels.setdefault(("instant", entry.end), label)
    return labels


def _label(
    entry: _Entry,
    labels: Mapping[tuple[PeriodKind, datetime.date], tuple[int, str]],
    first_filing: Mapping[
        tuple[str, datetime.date | None, datetime.date], _Entry
    ],
) -> str:
    """Build the fiscal label of a value: `FY2025` or `Q3 FY2026`."""
    found = labels.get((entry.kind, entry.end))
    if found is None:
        # No filing reports this period as current (the history starts
        # later). Take the label of the first filing that reports it.
        origin = first_filing[entry.period]
        found = (origin.fiscal_year, origin.fiscal_period)
        if entry.kind != "instant":
            years = round((origin.filed - entry.end).days / 365.25)
            found = (origin.fiscal_year - max(years, 0), origin.fiscal_period)
    year, period = found
    if entry.kind == "annual":
        return f"FY{year}"
    if period == "FY":
        period = "Q4" if entry.kind == "quarter" else "FY"
    return f"FY{year}" if period == "FY" else f"{period} FY{year}"


def _display(value: decimal.Decimal, unit: str) -> tuple[str, str]:
    """Scale a value for the line: USD and shares in millions."""
    scales = {"USD": "USD millions", "shares": "shares millions"}
    if unit in scales:
        scaled = value / decimal.Decimal(1_000_000)
        return f"{scaled.normalize():,f}", scales[unit]
    if unit == "USD/shares":
        # Per-share values keep at least the 2 decimals of the filing.
        exponent = value.normalize().as_tuple().exponent
        places = max(2, -exponent) if isinstance(exponent, int) else 2
        return f"{value:,.{places}f}", "USD per share"
    return f"{value.normalize():,f}", unit


def facts_lines(
    document: Mapping[str, Any],
    ticker: str,
    facts_config: FactsConfig,
    *,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
    max_lines: int = MAX_FACT_LINES,
    cik: str | None = None,
) -> FactsBlock:
    """Build the facts lines of 1 company for a period window.

    For each concept and period, the highest priority XBRL name with a
    value wins, and among its values the latest filing wins (a restated
    value replaces the original). The priority comes first on purpose: a
    company that moves a number to a new name keeps the configured name,
    so a later value under a lower priority name does not replace it.
    Annual values and fiscal year end balances come before quarterly
    values when the line limit cuts.

    Args:
        document: The company facts JSON body (`CachedDocument.data`).
        ticker: The ticker for the fact IDs.
        facts_config: The mapped concepts.
        start: The first period end date to keep, or None for no bound.
        end: The last period end date to keep, or None for no bound.
        max_lines: The line limit (40 in chapter 26.1).
        cik: The CIK from the ticker map, or None to read the body's.

    Returns:
        The block. A company with no mapped concept yields no line.
    """
    ticker = normalize_ticker(ticker)
    cik = _document_cik(document) if cik is None else cik
    entries = _entries(document, facts_config.concepts)
    labels = _current_labels(entries)
    first_filing: dict[
        tuple[str, datetime.date | None, datetime.date], _Entry
    ] = {}
    best: dict[tuple[str, datetime.date | None, datetime.date], _Entry] = {}
    for entry in sorted(entries, key=lambda item: (item.filed, item.accession)):
        first_filing.setdefault(entry.period, entry)
        if (start and entry.end < start) or (end and entry.end > end):
            continue
        current = best.get(entry.period)
        if current is None or entry.priority <= current.priority:
            best[entry.period] = entry
    order = {
        concept.key: index
        for index, concept in enumerate(facts_config.concepts)
    }
    # 1 line per concept and fiscal label: a cover page share count and a
    # balance sheet count of the same quarter keep the higher priority name.
    lines: dict[tuple[str, str], FactLine] = {}
    for entry in sorted(
        best.values(), key=lambda item: (item.priority, -item.end.toordinal())
    ):
        label = _label(entry, labels, first_filing)
        if (entry.concept, label) in lines:
            continue
        compact = label.replace(" ", "")
        fact_id = f"facts:{ticker}:{entry.xbrl_name}:{compact}"
        value, unit = _display(entry.value, entry.unit)
        lines[(entry.concept, label)] = FactLine(
            fact_id=fact_id,
            ticker=ticker,
            cik=cik,
            concept=entry.concept,
            xbrl_name=entry.xbrl_name,
            value=entry.value,
            unit=entry.unit,
            display_value=value,
            display_unit=unit,
            fiscal_label=label,
            period_kind=entry.kind,
            period_start=entry.start,
            period_end=entry.end,
            form=entry.form,
            filed=entry.filed,
            accession=entry.accession,
        )

    def rank(line: FactLine) -> tuple[int, int, int]:
        quarterly = line.period_kind == "quarter" or " " in line.fiscal_label
        return (
            int(quarterly),
            -line.period_end.toordinal(),
            order[line.concept],
        )

    kept = sorted(lines.values(), key=rank)[: max(max_lines, 0)]
    kept.sort(
        key=lambda line: (order[line.concept], -line.period_end.toordinal())
    )
    return FactsBlock(
        ticker=ticker,
        cik=cik,
        entity_name=str(document.get("entityName", "")),
        lines=tuple(kept),
        dropped=len(lines) - len(kept),
    )


def _document_cik(document: Mapping[str, Any]) -> str:
    """Read the CIK of a company facts body, or empty when absent."""
    try:
        return cik10(document.get("cik", ""))
    except errors.EdgarError:
        return ""


# --- The facts of 1 question (chapter 26.1, steps 4 and 8) --------------------

FactsSource = Literal["cache", "network", "none"]
Window = tuple[datetime.date | None, datetime.date | None]


@dataclasses.dataclass(frozen=True)
class FactsResult:
    """The facts blocks of the resolved companies of 1 question.

    Attributes:
        blocks: 1 block per company with at least 1 line, in ticker order.
        source: `network` when a company facts file was fetched, `cache`
            when every file came from the disk cache, `none` when no line
            came back.
        files: The company facts files read.
        errors: 1 message per company whose facts failed; the answer goes
            on without those lines.
    """

    blocks: tuple[FactsBlock, ...] = ()
    source: FactsSource = "none"
    files: int = 0
    errors: tuple[str, ...] = ()

    @property
    def lines(self) -> tuple[FactLine, ...]:
        """All lines of the blocks, in block order."""
        return tuple(line for block in self.blocks for line in block.lines)

    def by_id(self) -> dict[str, FactLine]:
        """Map each fact ID to its line, for the citation validator.

        Returns:
            The lines by fact ID.
        """
        return {line.fact_id: line for line in self.lines}

    def text(self) -> str:
        """Render every line, 1 per row, without the enclosing tags.

        Returns:
            The lines joined by newlines; empty when there is no line.
        """
        return "\n".join(block.text() for block in self.blocks if block.lines)


def collect_facts(
    client: EdgarClient,
    facts_config: FactsConfig,
    windows: Mapping[str, Window],
    *,
    max_lines: int = MAX_FACT_LINES,
) -> FactsResult:
    """Build the facts blocks of several companies, each in its window.

    A failure of 1 company (an unknown ticker, a cache miss offline, a
    fetch error) drops that company's lines and is recorded; it never
    raises, because the facts never block an answer.

    Args:
        client: The EDGAR client; offline, it reads only the cache.
        facts_config: The mapped concepts.
        windows: The first and last period end dates per ticker, None for
            no bound.
        max_lines: The line limit per company.

    Returns:
        The blocks, the source, and the errors.
    """
    before = client.requests
    blocks = []
    problems = []
    files = 0
    for ticker, (start, end) in windows.items():
        try:
            cik = client.cik(ticker)
            document = client.company_facts(cik)
        except errors.EdgarError as error:
            logger.warning("no company facts for %s: %s", ticker, error)
            problems.append(f"{ticker}: {error}")
            continue
        files += 1
        block = facts_lines(
            document.data,
            ticker,
            facts_config,
            start=start,
            end=end,
            max_lines=max_lines,
            cik=cik10(cik),
        )
        if block.lines:
            blocks.append(block)
    source: FactsSource = "none"
    if blocks:
        source = "network" if client.requests > before else "cache"
    return FactsResult(
        blocks=tuple(blocks),
        source=source,
        files=files,
        errors=tuple(problems),
    )
