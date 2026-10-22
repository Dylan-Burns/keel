"""The pilot routes of chapter 27.2: comp sets, templates, and feedback.

`GET /api/compsets` lists the saved comp sets of the firm; `PUT` saves 1
and `DELETE` removes 1. Any user creates a set; replacing or deleting a
set is for the user who saved it and the admins. `GET /api/templates`
serves the 5 question templates. `POST /api/feedback` stores a thumbs
vote and a note on an answer that the audit log knows: any token holder
who can open the answer (its asker or a shareable link) can vote, and a
second vote of the same user replaces the first. None of these routes
calls the model.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from typing import Literal

import fastapi
import pydantic

from keel import errors
from keel import templates as question_templates
from keel.api import auth
from keel.api import history as history_log
from keel.api import routes
from keel.api import state
from keel.stores import pilot

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/api")

CompSetName = Annotated[
    str, fastapi.Path(min_length=1, max_length=60, pattern=r"^[\w &-]+$")
]


class CompSetBody(pydantic.BaseModel):
    """The body of `PUT /api/compsets/{name}`.

    Attributes:
        tickers: The tickers, 1 to 25.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    tickers: list[Annotated[str, pydantic.StringConstraints(max_length=12)]] = (
        pydantic.Field(min_length=1, max_length=pilot.MAX_TICKERS)
    )


class CompSetItem(pydantic.BaseModel):
    """1 comp set as the API returns it.

    Attributes:
        name: The name a question uses (`my <name> comps`).
        tickers: The tickers.
        owner: The user who saved it last, or None from the CLI.
        updated_at: The time of the last save.
        missing: The tickers without an indexed filing; `keel add` adds
            them (chapter 26).
        editable: True when the caller may replace or delete the set.
    """

    name: str
    tickers: list[str]
    owner: str | None
    updated_at: str
    missing: list[str]
    editable: bool


class CompSetList(pydantic.BaseModel):
    """The body of `GET /api/compsets`.

    Attributes:
        items: The comp sets in name order.
    """

    items: list[CompSetItem]


class TemplateList(pydantic.BaseModel):
    """The body of `GET /api/templates`.

    Attributes:
        items: The templates in file order.
    """

    items: list[question_templates.Template]


class FeedbackBody(pydantic.BaseModel):
    """The body of `POST /api/feedback`.

    Attributes:
        request_id: The request ID of the answer.
        vote: `up` or `down`.
        note: An optional note, at most 2,000 characters.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    request_id: str = pydantic.Field(pattern=routes.REQUEST_ID.pattern)
    vote: Literal["up", "down"]
    note: str | None = pydantic.Field(
        default=None, max_length=pilot.MAX_NOTE_CHARS
    )


class FeedbackSaved(pydantic.BaseModel):
    """The body of a stored vote.

    Attributes:
        request_id: The request ID.
        vote: The vote.
        note: The stored note, or None.
        user: The user who voted.
    """

    request_id: str
    vote: str
    note: str | None
    user: str


def _store(services: state.Services) -> pilot.PilotStore:
    return pilot.PilotStore(services.settings.pilot.db)


def _indexed(services: state.Services) -> frozenset[str] | None:
    answerer = services.answerer
    return answerer.understander.indexed if answerer is not None else None


def _may_edit(entry: pilot.CompSet | None, caller: auth.Principal) -> bool:
    if entry is None or caller.is_admin:
        return True
    return entry.owner is not None and entry.owner == caller.user.name


def _item(
    entry: pilot.CompSet,
    caller: auth.Principal,
    indexed: frozenset[str] | None,
) -> CompSetItem:
    missing = (
        []
        if indexed is None
        else [t for t in entry.tickers if t not in indexed]
    )
    return CompSetItem(
        name=entry.name,
        tickers=list(entry.tickers),
        owner=entry.owner,
        updated_at=entry.updated_at,
        missing=missing,
        editable=_may_edit(entry, caller),
    )


def _unavailable(error: errors.PilotStoreError) -> fastapi.HTTPException:
    logger.error("pilot store: %s", error)
    return routes.http_error(
        503, "store_unavailable", "the comp sets and feedback store failed"
    )


@router.get("/compsets")
async def list_comp_sets(
    services: routes.Services, caller: routes.Caller
) -> CompSetList:
    """The saved comp sets of the firm (chapter 27.2).

    Args:
        services: The shared services.
        caller: The Principal.

    Returns:
        The comp sets in name order.

    Raises:
        HTTPException: 503 when the store cannot be read.
    """
    try:
        sets = await asyncio.to_thread(_store(services).comp_sets)
    except errors.PilotStoreError as error:
        raise _unavailable(error) from error
    indexed = _indexed(services)
    return CompSetList(
        items=[_item(entry, caller, indexed) for entry in sets.values()]
    )


@router.put("/compsets/{name}")
async def save_comp_set(
    name: CompSetName,
    body: CompSetBody,
    services: routes.Services,
    caller: routes.Caller,
) -> CompSetItem:
    """Create or replace a comp set.

    Args:
        name: The name; `my <name> comps` in a question expands to it.
        body: The tickers.
        services: The shared services.
        caller: The Principal.

    Returns:
        The saved comp set.

    Raises:
        HTTPException: 400 for a bad name or ticker, 403 when another
            user saved the set and the caller is not an admin, 503 when
            the store fails.
    """
    store = _store(services)
    try:
        key = pilot.normalize_name(name)
        tickers = pilot.normalize_tickers(body.tickers)
        current = (await asyncio.to_thread(store.comp_sets)).get(key)
        if not _may_edit(current, caller):
            raise routes.http_error(
                403, "forbidden", "only its owner or an admin edits this set"
            )
        entry = await asyncio.to_thread(
            store.save_comp_set, key, tickers, caller.user.name
        )
    except errors.InvalidCompSetError as error:
        raise routes.http_error(400, "invalid_comp_set", str(error)) from error
    except errors.PilotStoreError as error:
        raise _unavailable(error) from error
    logger.info("comp set %s saved with %d tickers", key, len(tickers))
    return _item(entry, caller, _indexed(services))


@router.delete("/compsets/{name}", status_code=204)
async def delete_comp_set(
    name: CompSetName, services: routes.Services, caller: routes.Caller
) -> fastapi.Response:
    """Delete a comp set.

    Args:
        name: The name.
        services: The shared services.
        caller: The Principal.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 400 for a bad name, 403 when another user saved
            the set and the caller is not an admin, 404 for an unknown
            set, 503 when the store fails.
    """
    store = _store(services)
    try:
        key = pilot.normalize_name(name)
        current = (await asyncio.to_thread(store.comp_sets)).get(key)
        if current is None:
            raise routes.http_error(
                404, "not_found", "no comp set by that name"
            )
        if not _may_edit(current, caller):
            raise routes.http_error(
                403, "forbidden", "only its owner or an admin deletes this set"
            )
        await asyncio.to_thread(store.delete_comp_set, key)
    except errors.InvalidCompSetError as error:
        raise routes.http_error(400, "invalid_comp_set", str(error)) from error
    except errors.PilotStoreError as error:
        raise _unavailable(error) from error
    logger.info("comp set %s deleted", key)
    return fastapi.Response(status_code=204)


@router.get("/templates")
async def list_templates(
    services: routes.Services, caller: routes.Caller
) -> TemplateList:
    """The question templates of the picker (chapter 27.2).

    Args:
        services: The shared services.
        caller: The Principal.

    Returns:
        The templates in file order.

    Raises:
        HTTPException: 503 when the templates file is absent or invalid.
    """
    del caller
    try:
        items = await asyncio.to_thread(
            question_templates.load, services.settings.pilot.templates
        )
    except errors.ConfigError as error:
        logger.error("question templates: %s", error)
        raise routes.http_error(
            503, "templates_unavailable", "the question templates failed"
        ) from error
    return TemplateList(items=items)


@router.post("/feedback")
async def feedback(
    body: FeedbackBody, services: routes.Services, caller: routes.Caller
) -> FeedbackSaved:
    """Store a thumbs vote and a note on an answer (chapter 27.2).

    Args:
        body: The request ID, the vote, and the note.
        services: The shared services.
        caller: The Principal.

    Returns:
        The stored vote.

    Raises:
        HTTPException: 404 when the audit log has no such answer, 400
            for a bad note, 503 when the store fails.
    """
    record = await asyncio.to_thread(
        history_log.find_record, services.settings.logs.dir, body.request_id
    )
    if record is None:
        raise routes.http_error(404, "not_found", "no answer with that ID")
    question = record.get("question")
    try:
        saved = await asyncio.to_thread(
            _store(services).record_vote,
            request_id=body.request_id,
            user_name=caller.user.name,
            vote=body.vote,
            note=body.note,
            question=question if isinstance(question, str) else None,
        )
    except errors.PilotStoreError as error:
        raise _unavailable(error) from error
    logger.info("feedback %s on %s", saved.vote, saved.request_id)
    return FeedbackSaved(
        request_id=saved.request_id,
        vote=saved.vote,
        note=saved.note,
        user=saved.user_name,
    )
