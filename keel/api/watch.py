"""The watch list routes (chapter 26.3): `keel watch` over the API.

`GET /api/watch` lists the watched tickers for any user: the watch list
is the firm's, and `keel refresh` checks the union of every user's
tickers. Only an admin sees which user watches a ticker other than the
caller. `POST /api/watch` and `DELETE /api/watch/{ticker}` change the
list and are for admins, like `keel watch add` and `remove` on the host.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import fastapi
import pydantic

from keel import add
from keel import errors
from keel import users
from keel.api import admin
from keel.api import routes
from keel.api import state
from keel.stores import state_store

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/api")

Ticker = Annotated[
    str,
    pydantic.StringConstraints(
        strip_whitespace=True, pattern=r"^[A-Za-z][A-Za-z0-9.-]{0,9}$"
    ),
]


class WatchItem(pydantic.BaseModel):
    """1 watched ticker of 1 user.

    Attributes:
        ticker: The ticker as the corpus spells it.
        user: The user who watches it; None for another user's row when
            the caller is not an admin.
        added_date: The date the user added it.
        mine: True when the caller watches it.
    """

    ticker: str
    user: str | None
    added_date: str
    mine: bool


class WatchList(pydantic.BaseModel):
    """The body of `GET /api/watch`.

    Attributes:
        items: The rows, by ticker then user.
        tickers: The distinct tickers that `keel refresh` checks.
    """

    items: list[WatchItem]
    tickers: list[str]


class WatchAdd(pydantic.BaseModel):
    """The body of `POST /api/watch`.

    Attributes:
        tickers: The tickers, 1 to 25.
        user: The user who watches them; None for the caller.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    tickers: list[Ticker] = pydantic.Field(min_length=1, max_length=25)
    user: str | None = pydantic.Field(
        default=None, pattern=users.NAME_PATTERN.pattern
    )


class WatchChanged(pydantic.BaseModel):
    """The body of a watch list change.

    Attributes:
        user: The user whose list changed.
        added: The tickers added.
        unchanged: The tickers the user already watched.
    """

    user: str
    added: list[str]
    unchanged: list[str]


def _unavailable(error: errors.StateStoreError) -> fastapi.HTTPException:
    logger.error("state store: %s", error)
    return routes.http_error(
        503, "store_unavailable", "the watch list store failed"
    )


def _spelled(ticker: str) -> str:
    try:
        return add.corpus_ticker(ticker)
    except errors.EdgarError as error:
        raise routes.http_error(400, "invalid_ticker", str(error)) from None


@router.get("/watch")
async def list_watch(
    services: routes.Services, caller: routes.Caller
) -> WatchList:
    """The watch list of the firm.

    Args:
        services: The shared services.
        caller: The Principal.

    Returns:
        The rows and the distinct tickers.

    Raises:
        HTTPException: 503 when the store fails.
    """
    try:
        entries = await asyncio.to_thread(
            state_store.list_watch, state_store.state_path(services.settings)
        )
    except errors.StateStoreError as error:
        raise _unavailable(error) from error
    me = caller.user.name
    items = [
        WatchItem(
            ticker=e.ticker,
            user=e.user if caller.is_admin or e.user == me else None,
            added_date=e.added_date.isoformat(),
            mine=e.user == me,
        )
        for e in entries
    ]
    return WatchList(items=items, tickers=sorted({e.ticker for e in entries}))


def _add_all(
    services: state.Services, tickers: list[str], user: str
) -> tuple[list[str], list[str]]:
    path = state_store.state_path(services.settings)
    added: list[str] = []
    unchanged: list[str] = []
    for ticker in tickers:
        if state_store.add_watch(path, ticker, user):
            added.append(ticker)
        else:
            unchanged.append(ticker)
    return added, unchanged


@router.post("/watch")
async def add_watch(
    body: WatchAdd, services: routes.Services, caller: admin.Admin
) -> WatchChanged:
    """Watch tickers (admin), like `keel watch add`.

    Args:
        body: The tickers and the user.
        services: The shared services.
        caller: The admin.

    Returns:
        The tickers added and the ones already watched.

    Raises:
        HTTPException: 400 `invalid_ticker`, 403 for a user who is not an
            admin, 503 when the store fails.
    """
    user = body.user or caller.user.name
    spelled = [_spelled(t) for t in body.tickers]
    try:
        added, unchanged = await asyncio.to_thread(
            _add_all, services, spelled, user
        )
    except errors.StateStoreError as error:
        raise _unavailable(error) from error
    await admin.audit(
        services,
        caller,
        "watch.add",
        target=user,
        params={"tickers": spelled},
    )
    return WatchChanged(user=user, added=added, unchanged=unchanged)


@router.delete("/watch/{ticker}", status_code=204)
async def remove_watch(
    ticker: str,
    services: routes.Services,
    caller: admin.Admin,
    user: Annotated[
        str | None, fastapi.Query(pattern=users.NAME_PATTERN.pattern)
    ] = None,
) -> fastapi.Response:
    """Stop watching a ticker (admin), like `keel watch remove`.

    Args:
        ticker: The ticker.
        services: The shared services.
        caller: The admin.
        user: The user whose row goes; None for the caller.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 400 `invalid_ticker`, 403 for a user who is not an
            admin, 404 when the user did not watch it, 503 when the store
            fails.
    """
    spelled = _spelled(ticker)
    owner = user or caller.user.name
    try:
        removed = await asyncio.to_thread(
            state_store.remove_watch,
            state_store.state_path(services.settings),
            spelled,
            owner,
        )
    except errors.StateStoreError as error:
        raise _unavailable(error) from error
    if not removed:
        raise routes.http_error(404, "not_found", "that user did not watch it")
    await admin.audit(
        services,
        caller,
        "watch.remove",
        target=owner,
        params={"tickers": [spelled]},
    )
    return fastapi.Response(status_code=204)
