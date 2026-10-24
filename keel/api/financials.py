"""The financials routes: the statements of an indexed company.

`GET /api/financials` lists the indexed companies, the companies the page
can open. `GET /api/financials/{ticker}?period=annual|quarterly` returns
the 3 statements of 1 company for 1 period kind, from its cached SEC
company facts (`keel.financials`). Both routes are for any signed-in role.

The company facts come through `EdgarClient.company_facts`: the disk cache
first, then 1 allow-listed fetch on a miss; offline, a miss is HTTP 503.
The computed statements stay in memory per CIK and cache file stamp (its
modification time and size), so a new fetch of the facts, which rewrites
the file with a new fetch time, computes them again. No model request
happens here (decision D-02).
"""

from __future__ import annotations

import asyncio
import collections
import datetime
import functools
import logging
import pathlib
import threading
from typing import Annotated
from typing import Literal

import fastapi
import pydantic

from keel import config
from keel import edgar
from keel import errors
from keel import financials
from keel.api import routes

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/api")

TICKER_PATTERN = r"^[A-Za-z][A-Za-z0-9.-]{0,9}$"
MAX_CACHED = 32

PathTicker = Annotated[str, fastapi.Path(pattern=TICKER_PATTERN)]
PeriodQuery = Annotated[Literal["annual", "quarterly"], fastapi.Query()]


class FinancialsCompany(pydantic.BaseModel):
    """1 company the financials page can open.

    Attributes:
        ticker: The ticker as the index spells it.
        company: The company name of its latest indexed filing.
        cik: The CIK, 10 digits, or None when the index has none.
    """

    ticker: str
    company: str
    cik: str | None


class FinancialsCompanies(pydantic.BaseModel):
    """The body of `GET /api/financials`.

    Attributes:
        companies: The indexed companies, by ticker.
    """

    companies: list[FinancialsCompany]


class FilingSource(pydantic.BaseModel):
    """1 filing behind 1 or more values.

    Attributes:
        form: The form, such as `10-K`.
        accession: The accession number.
        filed: The filing date.
        url: The filing index page on www.sec.gov.
    """

    form: str
    accession: str
    filed: datetime.date
    url: str


class PointOut(pydantic.BaseModel):
    """1 value of a line item.

    Attributes:
        label: `FY2025` or `Q3 FY2025`.
        start: The first day of the period, None for a balance.
        end: The last day of the period, or the balance date.
        value: The value in the item's unit, signed for display.
        source: The index of the filing in `sources`.
        derived: True when no filing reports the value as is.
        note: How the value was computed or adjusted, or None.
    """

    label: str
    start: datetime.date | None
    end: datetime.date
    value: float
    source: int
    derived: bool
    note: str | None


class LineItemOut(pydantic.BaseModel):
    """1 row of a statement.

    Attributes:
        id: The item ID.
        label: The row label.
        parent: The parent row ID, or None.
        unit: `USD`, `USD/shares`, or `shares`.
        rule: The derivation note when the item is computed, or None.
        points: The values, oldest first.
    """

    id: str
    label: str
    parent: str | None
    unit: str
    rule: str | None
    points: list[PointOut]


class StatementOut(pydantic.BaseModel):
    """1 statement of the page.

    Attributes:
        id: The statement ID.
        label: The tab label.
        defaults: The rows charted when the tab opens.
        items: The rows with a value, in order.
    """

    id: str
    label: str
    defaults: list[str]
    items: list[LineItemOut]


class SplitOut(pydantic.BaseModel):
    """1 stock split the per-share values are adjusted for.

    Attributes:
        date: The first filing date with split-adjusted values.
        ratio: New shares per old share.
    """

    date: datetime.date
    ratio: float


class FinancialsResponse(pydantic.BaseModel):
    """The body of `GET /api/financials/{ticker}`.

    Attributes:
        ticker: The ticker.
        company: The company name.
        cik: The CIK, 10 digits.
        period: `annual` or `quarterly`.
        fetched_at: When the company facts were fetched from the SEC.
        fiscal_year_end_month: The month of the latest fiscal year end.
        splits: The stock splits applied to per-share values.
        sources: The filings the points refer to.
        statements: The statements in tab order.
    """

    ticker: str
    company: str
    cik: str
    period: Literal["annual", "quarterly"]
    fetched_at: datetime.datetime
    fiscal_year_end_month: int | None
    splits: list[SplitOut]
    sources: list[FilingSource]
    statements: list[StatementOut]


@functools.lru_cache(maxsize=4)
def _config(path: pathlib.Path) -> financials.FinancialsConfig:
    return financials.load_financials_config(path)


_Stamp = tuple[str, int, int]
_cache: collections.OrderedDict[
    _Stamp, tuple[datetime.datetime, financials.Statements]
] = collections.OrderedDict()
_cache_lock = threading.Lock()


def _stamp(cik: str, path: pathlib.Path) -> _Stamp | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return (cik, info.st_mtime_ns, info.st_size)


def load_statements(
    settings: config.Settings, cik: str
) -> tuple[datetime.datetime, financials.Statements]:
    """The statements of 1 company, from memory or its company facts.

    Args:
        settings: The loaded settings.
        cik: The 10-digit CIK.

    Returns:
        The fetch time of the company facts and the statements.

    Raises:
        EdgarError: The facts cannot load (offline and not cached, or the
            fetch failed).
        ConfigError: `config/financials.yaml` is invalid.
    """
    statements_config = _config(settings.edgar.financials)
    with edgar.EdgarClient.from_settings(settings) as client:
        path = client.company_facts_path(cik)
        stamp = _stamp(cik, path)
        with _cache_lock:
            if stamp is not None and stamp in _cache:
                _cache.move_to_end(stamp)
                return _cache[stamp]
        document = client.company_facts(cik)
        data = document.data if isinstance(document.data, dict) else {}
        built = financials.extract(data, statements_config, cik)
        stamp = _stamp(cik, path)
    entry = (document.fetched_at, built)
    if stamp is not None:
        with _cache_lock:
            _cache[stamp] = entry
            while len(_cache) > MAX_CACHED:
                _cache.popitem(last=False)
    return entry


def clear_cache() -> None:
    """Drop the computed statements (tests).

    Returns:
        None.
    """
    with _cache_lock:
        _cache.clear()


def _companies(services: routes.Services) -> list[FinancialsCompany]:
    """The indexed companies with the company name of the latest filing."""
    answerer = routes.require_answerer(services)
    rows = answerer.retriever.conn.execute(
        "SELECT ticker, company, cik FROM filings ORDER BY ticker, filing_date"
    ).fetchall()
    found: dict[str, FinancialsCompany] = {}
    for ticker, company, cik in rows:
        previous = found.get(ticker)
        found[ticker] = FinancialsCompany(
            ticker=ticker,
            company=company,
            cik=cik or (previous.cik if previous else None),
        )
    return list(found.values())


def _visible(
    statement: financials.StatementSeries, period: financials.Period
) -> list[financials.Series]:
    """The rows to show: not hidden, with a value or a child with one."""
    shown = [s for s in statement.series if not s.item.hidden]
    with_points = {s.item.id for s in shown if s.points(period)}
    keep: set[str] = set(with_points)
    parents = {s.item.id: s.item.parent for s in shown}
    for item_id in with_points:
        parent = parents.get(item_id)
        while parent is not None:
            keep.add(parent)
            parent = parents.get(parent)
    return [s for s in shown if s.item.id in keep]


def to_response(
    ticker: str,
    company: str,
    cik: str,
    period: financials.Period,
    loaded: tuple[datetime.datetime, financials.Statements],
) -> FinancialsResponse:
    """Build the response body of 1 period kind.

    Args:
        ticker: The ticker.
        company: The company name.
        cik: The 10-digit CIK.
        period: `annual` or `quarterly`.
        loaded: The fetch time and the statements.

    Returns:
        The body, with the filings hoisted into `sources`.
    """
    fetched_at, built = loaded
    sources: list[FilingSource] = []
    index: dict[str, int] = {}

    def source_of(point: financials.Point) -> int:
        found = index.get(point.source.accession)
        if found is None:
            found = index[point.source.accession] = len(sources)
            sources.append(
                FilingSource(
                    form=point.source.form,
                    accession=point.source.accession,
                    filed=point.source.filed,
                    url=edgar.FILING_INDEX_URL.format(
                        cik=int(cik),
                        folder=point.source.accession.replace("-", ""),
                        accession=point.source.accession,
                    ),
                )
            )
        return found

    statements: list[StatementOut] = []
    for statement in built.statements:
        rows = _visible(statement, period)
        ids = {s.item.id for s in rows}
        statements.append(
            StatementOut(
                id=statement.config.id,
                label=statement.config.label,
                defaults=[d for d in statement.config.defaults if d in ids],
                items=[
                    LineItemOut(
                        id=s.item.id,
                        label=s.item.label,
                        parent=s.item.parent,
                        unit=s.item.unit,
                        rule=s.item.derive.note if s.item.derive else None,
                        points=[
                            PointOut(
                                label=p.label,
                                start=p.start,
                                end=p.end,
                                value=p.value,
                                source=source_of(p),
                                derived=p.derived,
                                note=p.note,
                            )
                            for p in s.points(period)
                        ],
                    )
                    for s in rows
                ],
            )
        )
    return FinancialsResponse(
        ticker=ticker,
        company=company or built.company,
        cik=cik,
        period=period,
        fetched_at=fetched_at,
        fiscal_year_end_month=built.fiscal_year_end,
        splits=[SplitOut(date=s.date, ratio=s.ratio) for s in built.splits],
        sources=sources,
        statements=statements,
    )


@router.get("/financials")
async def list_companies(
    services: routes.Services, caller: routes.Caller
) -> FinancialsCompanies:
    """The companies the financials page can open: the indexed ones.

    Args:
        services: The shared services.
        caller: The Principal.

    Returns:
        The companies by ticker.

    Raises:
        HTTPException: 503 when no index is loaded.
    """
    del caller
    companies = await asyncio.to_thread(_companies, services)
    return FinancialsCompanies(companies=companies)


@router.get("/financials/{ticker}")
async def get_financials(
    ticker: PathTicker,
    services: routes.Services,
    caller: routes.Caller,
    period: PeriodQuery = "annual",
) -> FinancialsResponse:
    """The 3 statements of 1 indexed company for 1 period kind.

    Args:
        ticker: The ticker, any case.
        services: The shared services.
        caller: The Principal.
        period: `annual` or `quarterly`.

    Returns:
        The statements with their sources.

    Raises:
        HTTPException: 404 for a ticker outside the index, 503 when the
            facts are not cached and the service is offline, 502 when the
            SEC fetch fails.
    """
    del caller
    wanted = ticker.strip().upper()
    companies = await asyncio.to_thread(_companies, services)
    company = next(
        (c for c in companies if c.ticker.upper() == wanted),
        None,
    )
    if company is None:
        raise routes.http_error(
            404, "unknown_ticker", f"{wanted} is not in the index"
        )
    # From here on the index's spelling names the company: the request
    # text never reaches a log line.
    known = company.ticker
    settings = services.settings
    try:
        cik = company.cik
        if cik is None:
            with edgar.EdgarClient.from_settings(settings) as client:
                cik = await asyncio.to_thread(client.cik, company.ticker)
        cik = edgar.cik10(cik)
        loaded = await asyncio.to_thread(load_statements, settings, cik)
    except errors.EdgarCacheMissError as error:
        logger.warning("no company facts for %s: %s", known, error)
        raise routes.http_error(
            503,
            "facts_unavailable",
            f"the company facts of {known} are not cached and the "
            "service is offline",
        ) from None
    except errors.EdgarError as error:
        logger.warning("company facts of %s failed: %s", known, error)
        raise routes.http_error(
            502, "edgar_error", f"the SEC company facts of {known} failed"
        ) from None
    return to_response(company.ticker, company.company, cik, period, loaded)
