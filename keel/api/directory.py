"""The company browser routes of the admin companies page.

`GET /api/admin/directory` lists the sectors (the SEC offices) with their
industries (the SIC codes of `config/sic_codes.yaml`), and the company
count of each industry whose list is cached; it sends no request.
`GET /api/admin/directory/sic/{code}` lists the registrants of 1 industry
that have a ticker, fetched from EDGAR on the first call and cached for
`edgar.directory_ttl_days` (`keel.directory`). `GET
/api/admin/directory/search?q=` finds companies in the SEC ticker map by
ticker or name. Both show only the active filers of `keel.filers`: a
ticker, and a 10-K or 10-Q every year since `edgar.directory_since_year`
and in the last 365 days. Each company says whether the index holds its
filings and whether a user watches it; the Add button of the page starts
the `add` job with its ticker.

Every route needs the admin role. The log lines carry fixed words and
counts, never the query or a value of the request.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import threading
from typing import Annotated

import fastapi
import pydantic

from keel import config
from keel import directory
from keel import edgar
from keel import errors
from keel import filers
from keel.api import admin
from keel.api import routes
from keel.stores import state_store

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/api/admin/directory")

MAX_RESULTS = 50
# 1 EDGAR fetch at a time, so 2 admins never double the request rate.
_FETCH_LOCK = threading.Lock()


class DirectoryCompany(pydantic.BaseModel):
    """1 company of an industry or of a search.

    Attributes:
        cik: The CIK, 10 digits.
        ticker: The main ticker (the one Add sends), SEC spelling.
        tickers: Every ticker of the company, the main one first.
        name: The company name from the SEC ticker map.
        indexed: True when the index holds a filing of the company.
        watched: True when a user watches 1 of its tickers.
        addable: True when `keel add` takes the main ticker (letters and
            a share class only).
    """

    cik: str
    ticker: str
    tickers: list[str]
    name: str
    indexed: bool
    watched: bool
    addable: bool


class DirectoryIndustry(pydantic.BaseModel):
    """1 industry of a sector.

    Attributes:
        code: The SIC code, 4 digits.
        title: The industry title.
        office: The SEC office that reviews its filings.
        companies: The companies with a ticker, when the list is cached;
            None before the first expand.
    """

    code: str
    title: str
    office: str
    companies: int | None


class DirectorySector(pydantic.BaseModel):
    """1 sector: an SEC office and its industries.

    Attributes:
        name: The sector name.
        industries: The industries, by code.
    """

    name: str
    industries: list[DirectoryIndustry]


class DirectoryResponse(pydantic.BaseModel):
    """The body of `GET /api/admin/directory`.

    Attributes:
        sectors: The sectors, by name.
        industry_count: The industries in all.
    """

    sectors: list[DirectorySector]
    industry_count: int


class IndustryCompanies(pydantic.BaseModel):
    """The body of `GET /api/admin/directory/sic/{code}`.

    Attributes:
        code: The SIC code.
        title: The industry title.
        sector: The sector name.
        companies: The registrants with a ticker, by ticker.
        registrants: The registrants that file a 10-K, with or without a
            ticker.
        fetched_at: When EDGAR sent the list.
        stale: True when a refresh failed and an older copy served.
        truncated: True when the list stopped at the page limit.
        sec_requests: The SEC requests this call sent.
    """

    code: str
    title: str
    sector: str
    companies: list[DirectoryCompany]
    registrants: int
    fetched_at: datetime.datetime
    stale: bool
    truncated: bool
    sec_requests: int


class SearchResults(pydantic.BaseModel):
    """The body of `GET /api/admin/directory/search`.

    Attributes:
        items: The companies, best match first, at most 50.
    """

    items: list[DirectoryCompany]


def edgar_client(settings: config.Settings) -> edgar.EdgarClient:
    """The EDGAR client of the routes; tests replace it.

    Args:
        settings: The loaded settings.

    Returns:
        A client from the `edgar` settings.
    """
    return edgar.EdgarClient.from_settings(settings)


def _industries(settings: config.Settings) -> dict[str, directory.Industry]:
    try:
        rows = directory.load_sic_codes(settings.edgar.sic_codes)
    except errors.ConfigError as error:
        logger.error("SIC codes: %s", error)
        raise routes.http_error(
            503, "directory_unavailable", "the SIC code list cannot be read"
        ) from error
    return {row.code: row for row in rows}


def _marks(settings: config.Settings) -> directory.Marks:
    try:
        watched = {
            e.ticker
            for e in state_store.list_watch(state_store.state_path(settings))
        }
    except errors.StateStoreError as error:
        logger.warning("watch list unreadable for the directory: %s", error)
        watched = set()
    return directory.indexed_marks(settings.index.dir, watched)


def _company(company: directory.Company) -> DirectoryCompany:
    return DirectoryCompany(
        cik=company.cik,
        ticker=company.ticker,
        tickers=list(company.tickers),
        name=company.name,
        indexed=company.indexed,
        watched=company.watched,
        addable=company.addable,
    )


def _edgar_failure(error: errors.EdgarError) -> fastapi.HTTPException:
    if isinstance(error, errors.EdgarCacheMissError):
        logger.warning("directory: offline and not cached")
        return routes.http_error(
            503,
            "directory_offline",
            "the server is offline and has no cached copy of this list",
        )
    logger.error("directory: EDGAR request failed: %s", type(error).__name__)
    return routes.http_error(
        502, "sec_unavailable", "SEC EDGAR did not answer; try again later"
    )


def _cached_ticker_map(settings: config.Settings) -> edgar.TickerMap | None:
    """The ticker map when the cache holds it, without a request."""
    with edgar_client(settings.model_copy(update={"offline": True})) as c:
        try:
            return c.ticker_map()
        except errors.EdgarError:
            return None


def active_filers(
    settings: config.Settings, client: edgar.EdgarClient
) -> frozenset[str]:
    """The CIKs the browser shows; tests replace it.

    Args:
        settings: The loaded settings.
        client: The EDGAR client.

    Returns:
        The active 10-K and 10-Q filers (`keel.filers`).

    Raises:
        EdgarError: A quarter of the XBRL index cannot load.
    """
    return filers.active_ciks(client, settings.edgar.directory_since_year)


def _cached_active(settings: config.Settings) -> frozenset[str] | None:
    """The active filers when the cache holds them, without a request."""
    with edgar_client(settings.model_copy(update={"offline": True})) as c:
        try:
            return active_filers(settings, c)
        except errors.EdgarError:
            return None


def _overview(settings: config.Settings) -> DirectoryResponse:
    industries = _industries(settings)
    tickers = _cached_ticker_map(settings)
    allowed = _cached_active(settings)
    sectors = []
    for name, rows in directory.sectors(industries.values()):
        items = []
        for row in rows:
            count = None
            cached = directory.read_industry(settings.edgar.cache_dir, row.code)
            if (
                cached is not None
                and tickers is not None
                and allowed is not None
            ):
                count = sum(
                    1
                    for cik in cached.ciks
                    if cik in allowed and tickers.by_cik(cik)
                )
            items.append(
                DirectoryIndustry(
                    code=row.code,
                    title=row.title,
                    office=row.office,
                    companies=count,
                )
            )
        sectors.append(DirectorySector(name=name, industries=items))
    return DirectoryResponse(sectors=sectors, industry_count=len(industries))


@router.get("")
async def directory_overview(
    services: routes.Services, caller: admin.Admin
) -> DirectoryResponse:
    """The sectors and their industries, with the cached company counts.

    Args:
        services: The shared services.
        caller: The admin.

    Returns:
        The sectors.

    Raises:
        HTTPException: 503 when the SIC code list cannot be read.
    """
    del caller
    return await asyncio.to_thread(_overview, services.settings)


def _industry(settings: config.Settings, code: str) -> IndustryCompanies:
    industry = _industries(settings).get(code)
    if industry is None:
        raise routes.http_error(
            404, "unknown_industry", "no SEC industry has this SIC code"
        )
    with _FETCH_LOCK, edgar_client(settings) as client:
        try:
            listed = directory.industry_ciks(
                client, code, ttl_days=settings.edgar.directory_ttl_days
            )
            tickers = client.ticker_map()
            allowed = active_filers(settings, client)
        except errors.EdgarError as error:
            raise _edgar_failure(error) from error
        requests = client.requests
    companies = directory.join_companies(
        [cik for cik in listed.ciks if cik in allowed],
        tickers,
        _marks(settings),
    )
    logger.info(
        "directory industry: %d companies, %d SEC requests",
        len(companies),
        requests,
    )
    return IndustryCompanies(
        code=industry.code,
        title=industry.title,
        sector=industry.sector,
        companies=[_company(c) for c in companies],
        registrants=len(listed.ciks),
        fetched_at=listed.fetched_at,
        stale=listed.stale,
        truncated=listed.truncated,
        sec_requests=requests,
    )


@router.get("/sic/{code}")
async def industry_companies(
    code: Annotated[str, fastapi.Path(pattern=r"^\d{4}$")],
    services: routes.Services,
    caller: admin.Admin,
) -> IndustryCompanies:
    """The companies of 1 industry, from the cache or EDGAR.

    Args:
        code: The SIC code, 4 digits (422 otherwise).
        services: The shared services.
        caller: The admin.

    Returns:
        The companies with a ticker.

    Raises:
        HTTPException: 404 for a code the SEC list does not have, 502
            when EDGAR fails and nothing is cached, 503 offline without
            a cached list.
    """
    del caller
    return await asyncio.to_thread(_industry, services.settings, code)


def _search(settings: config.Settings, query: str) -> SearchResults:
    with _FETCH_LOCK, edgar_client(settings) as client:
        try:
            tickers = client.ticker_map()
            allowed = active_filers(settings, client)
        except errors.EdgarError as error:
            raise _edgar_failure(error) from error
    found = directory.search(
        tickers, query, _marks(settings), MAX_RESULTS, allowed
    )
    return SearchResults(items=[_company(c) for c in found])


@router.get("/search")
async def search_companies(
    q: Annotated[str, fastapi.Query(min_length=2, max_length=64)],
    services: routes.Services,
    caller: admin.Admin,
) -> SearchResults:
    """Companies of the SEC ticker map by ticker or name.

    Args:
        q: The text, 2 to 64 characters.
        services: The shared services.
        caller: The admin.

    Returns:
        At most 50 companies, best match first.

    Raises:
        HTTPException: 502 or 503 when the ticker map cannot load.
    """
    del caller
    return await asyncio.to_thread(_search, services.settings, q)
