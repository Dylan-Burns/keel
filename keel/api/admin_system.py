"""The admin routes of the system page and the users (chapter 27.2).

`GET /api/admin/system` gathers what `keel doctor`, `keel inventory`, the
index manifest, the backup directory, the scheduler, and the daily budget
report, in 1 response for the system page. The doctor checks are the
local checks of `keel doctor` without the model download; they send no
request.

`GET`, `POST`, and `DELETE /api/admin/users` are `keel users list`, `add`,
and `remove`. `POST` returns the new token once, in that response only,
with `Cache-Control: no-store`; the users file keeps only its sha256, so
no later response and no log line holds it. An admin cannot remove their
own user, so the API never locks out the last admin by mistake.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Annotated
from typing import Any
from typing import Literal

import fastapi
import pydantic

from keel import doctor
from keel import errors
from keel import indexer
from keel import inventory
from keel import users
from keel.api import admin
from keel.api import routes
from keel.api import state

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/api/admin")

# The users file is read, changed, and replaced without a file lock
# (keel.users); 1 change at a time inside the server.
_USERS_LOCK = threading.Lock()
MAX_DISCREPANCIES = 20


class UserItem(pydantic.BaseModel):
    """1 user of the users file.

    Attributes:
        name: The user name.
        role: analyst, partner, or admin.
    """

    name: str
    role: str


class UserList(pydantic.BaseModel):
    """The body of `GET /api/admin/users`.

    Attributes:
        items: The users of the file, in file order.
        legacy_enabled: True when `KEEL_API_TOKEN` is set, which passes
            as the admin user `legacy`.
    """

    items: list[UserItem]
    legacy_enabled: bool


class UserCreate(pydantic.BaseModel):
    """The body of `POST /api/admin/users`.

    Attributes:
        name: The user name: lowercase letters, digits, dot, dash, and
            underscore, at most 64 characters, not `legacy`.
        role: analyst, partner, or admin.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    name: str = pydantic.Field(pattern=users.NAME_PATTERN.pattern)
    role: Literal["analyst", "partner", "admin"]


class UserCreated(pydantic.BaseModel):
    """The body of a new user: the only response that holds the token.

    Attributes:
        name: The user name.
        role: The role.
        token: The new token; shown once, stored only as its sha256.
    """

    name: str
    role: str
    token: str


def _users_error(error: errors.ConfigError) -> fastapi.HTTPException:
    logger.error("users file: %s", error)
    return routes.http_error(
        503, "users_unavailable", "the users file cannot be read or written"
    )


@router.get("/users")
async def list_users(
    services: routes.Services, caller: admin.Admin
) -> UserList:
    """The users and their roles, without any token or hash.

    Args:
        services: The shared services.
        caller: The admin.

    Returns:
        The users.

    Raises:
        HTTPException: 503 when the users file is invalid.
    """
    del caller
    try:
        loaded = await asyncio.to_thread(
            users.load_file, services.settings.auth.users_file
        )
    except errors.ConfigError as error:
        raise _users_error(error) from None
    return UserList(
        items=[UserItem(name=u.name, role=u.role) for u in loaded.users],
        legacy_enabled=services.users.legacy_token is not None,
    )


def _add(services: state.Services, body: UserCreate) -> str | None:
    path = services.settings.auth.users_file
    with _USERS_LOCK:
        if any(u.name == body.name for u in users.load_file(path).users):
            return None
        return users.add_user(path, body.name, body.role)


@router.post("/users", status_code=201)
async def add_user(
    body: UserCreate,
    services: routes.Services,
    caller: admin.Admin,
    response: fastapi.Response,
) -> UserCreated:
    """Add a user and return the new token once.

    Args:
        body: The name and the role.
        services: The shared services.
        caller: The admin.
        response: The response, for the no-store header.

    Returns:
        The user with the token.

    Raises:
        HTTPException: 400 `invalid_user` for the reserved name, 409
            `user_exists`, 503 when the file fails.
    """
    action = "users.add"
    shown = {"name": body.name, "role": body.role}
    if body.name == users.LEGACY_USER:
        await admin.audit(
            services, caller, action, params=shown, outcome="invalid"
        )
        raise routes.http_error(
            400, "invalid_user", f"the name {users.LEGACY_USER} is reserved"
        )
    try:
        token = await asyncio.to_thread(_add, services, body)
    except errors.ConfigError as error:
        raise _users_error(error) from None
    if token is None:
        await admin.audit(
            services, caller, action, params=shown, outcome="exists"
        )
        raise routes.http_error(409, "user_exists", "that user exists")
    await admin.audit(services, caller, action, target=body.name, params=shown)
    logger.info("admin added a user")
    response.headers["Cache-Control"] = "no-store"
    return UserCreated(name=body.name, role=body.role, token=token)


def _remove(services: state.Services, name: str) -> bool:
    path = services.settings.auth.users_file
    with _USERS_LOCK:
        if not any(u.name == name for u in users.load_file(path).users):
            return False
        users.remove_user(path, name)
        return True


UserName = Annotated[
    str, fastapi.Path(pattern=users.NAME_PATTERN.pattern, max_length=64)
]


@router.delete("/users/{name}", status_code=204)
async def remove_user(
    name: UserName, services: routes.Services, caller: admin.Admin
) -> fastapi.Response:
    """Remove a user, which revokes their token at the next request.

    Args:
        name: The user name.
        services: The shared services.
        caller: The admin.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 404 for an unknown user, 409 `self_delete` for the
            caller's own user, 503 when the file fails.
    """
    action = "users.remove"
    if name == caller.user.name:
        await admin.audit(services, caller, action, target=name, outcome="self")
        raise routes.http_error(
            409, "self_delete", "an admin cannot remove their own user"
        )
    try:
        removed = await asyncio.to_thread(_remove, services, name)
    except errors.ConfigError as error:
        raise _users_error(error) from None
    if not removed:
        raise routes.http_error(404, "not_found", "no user by that name")
    await admin.audit(services, caller, action, target=name)
    logger.info("admin removed a user")
    return fastapi.Response(status_code=204)


def _inventory(services: state.Services) -> dict[str, Any]:
    corpus = services.settings.corpus
    try:
        report = inventory.build_inventory(
            corpus.dir, corpus.manifest, corpus.date_filter
        )
    except errors.KeelError as error:
        return {"error": f"{type(error).__name__}: {error}"}
    first = report.first_filing
    last = report.last_filing
    return {
        "corpus_dir": report.corpus_dir,
        "file_count": report.file_count,
        "total_bytes": report.total_bytes,
        "ticker_count": report.ticker_count,
        "form_counts": report.form_counts,
        "first_filing": first[0].isoformat() if first else None,
        "last_filing": last[0].isoformat() if last else None,
        "manifest_present": report.manifest.present,
        "discrepancy_count": len(report.discrepancies),
        "discrepancies": report.discrepancies[:MAX_DISCREPANCIES],
    }


def _index(services: state.Services) -> dict[str, Any]:
    answerer = services.answerer
    build = indexer.current_build(services.settings.index.dir)
    manifest = services.manifest
    filings = quarantined = None
    if answerer is not None:
        row = answerer.retriever.conn.execute(
            "SELECT COUNT(*) FROM filings"
        ).fetchone()
        filings = int(row[0]) if row else 0
        quarantined = len(answerer.retriever.catalog.quarantined)
    return {
        "loaded": answerer is not None,
        "index_version": answerer.index_version if answerer else None,
        "build_id": build.name if build else None,
        "verified": services.index_verified,
        "error": services.index_error,
        "corpus_checksum_match": services.corpus_match,
        "corpus_note": services.corpus_note,
        "built_at": manifest.built_at if manifest else None,
        "counts": manifest.counts.model_dump(mode="json") if manifest else None,
        "filings": filings,
        "quarantined": quarantined,
    }


def _scheduler(services: state.Services) -> dict[str, Any]:
    config = services.settings.scheduler
    running = services.scheduler
    jobs = []
    if running is not None:
        jobs = [
            {
                "name": job.name,
                "next_run": running.due(job.name).isoformat(timespec="seconds"),
            }
            for job in running.jobs
        ]
    return {
        "enabled": config.enabled,
        "running": running is not None,
        "refresh_at": config.refresh_at,
        "backup_at": config.backup_at,
        "backup_keep": config.backup_keep,
        "backup_bucket_set": bool(config.backup_bucket),
        "jobs": jobs,
    }


def _budget(services: state.Services) -> dict[str, Any] | None:
    answerer = services.answerer
    if answerer is None:
        return None
    limit = answerer.budget.limit_usd
    spent = answerer.budget.spent()
    return {"daily_usd": limit, "spent_usd": spent, "stopped": spent >= limit}


def system_report(services: state.Services) -> dict[str, Any]:
    """Gather the system page in 1 pass (blocking; run it in a thread).

    Args:
        services: The shared services.

    Returns:
        The doctor checks, the inventory, the index, the backups, the
        scheduler, the budget, the active job, and the bootstrap.
    """
    settings = services.settings
    checks = doctor.run_doctor(settings)
    runner = services.jobs
    holder = runner.holder() if runner is not None else None
    boot = services.bootstrap
    return {
        "version": routes.VERSION,
        "offline": settings.offline,
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "doctor": [
            {"name": c.name, "status": c.status, "detail": c.detail}
            for c in checks
        ],
        "doctor_failed": any(c.status == doctor.FAIL for c in checks),
        "inventory": _inventory(services),
        "index": _index(services),
        "backups": {
            "directory": str(settings.scheduler.backup_dir),
            "items": [
                item.model_dump(mode="json")
                for item in admin.backup_items(services)
            ],
        },
        "scheduler": _scheduler(services),
        "budget": _budget(services),
        "active_job": (
            admin.summary_of(holder).model_dump(mode="json") if holder else None
        ),
        "bootstrap": (
            boot.snapshot().model_dump(mode="json") if boot else None
        ),
    }


@router.get("/system")
async def system(
    services: routes.Services, caller: admin.Admin
) -> dict[str, Any]:
    """The system page: doctor, inventory, index, backups, schedule.

    Args:
        services: The shared services.
        caller: The admin.

    Returns:
        The report of `system_report`.

    Raises:
        HTTPException: 503 when the job store fails.
    """
    del caller
    try:
        return await asyncio.to_thread(system_report, services)
    except errors.StateStoreError as error:
        logger.error("state store: %s", error)
        raise routes.http_error(
            503, "store_unavailable", "the job store failed"
        ) from None
