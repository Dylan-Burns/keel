"""The admin routes: jobs, the cost preview, the backups, the audit trail.

Every route under `/api/admin` needs the admin role: a valid token of
another role gets HTTP 403 `forbidden`, no token HTTP 401. Each change an
admin makes (a job submitted or cancelled, a backup downloaded, a user
added or removed) writes 1 row to the admin audit table with the user,
the action, the target, and the parameters without secrets
(`keel.stores.admin_store`), including the refused attempts. The log
lines of these routes carry fixed words and job IDs, never a value that
the request supplied.

`docs/API_ADMIN.md` is the contract of these routes.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Annotated
from typing import Any
from typing import Literal

import fastapi
from fastapi import responses
import pydantic

from keel import backup
from keel import errors
from keel import warm_cache
from keel.api import auth
from keel.api import costs
from keel.api import job_kinds
from keel.api import jobs
from keel.api import routes
from keel.api import state
from keel.stores import admin_store
from keel.stores import state_store

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/api/admin")

JobKind = Literal[
    "add",
    "refresh",
    "warm_cache",
    "eval",
    "facts",
    "backup",
    "restore",
    "index",
]
JOB_ID = r"^[0-9a-f]{16}$"


def require_admin(caller: routes.Caller) -> auth.Principal:
    """The Principal of an admin, else HTTP 403.

    Args:
        caller: The Principal of the token (401 without one).

    Returns:
        The Principal.

    Raises:
        HTTPException: 403 when the user is not an admin.
    """
    if not caller.is_admin:
        raise routes.http_error(403, "forbidden", "this route is for admins")
    return caller


Admin = Annotated[auth.Principal, fastapi.Depends(require_admin)]


def api_error(
    status: int, code: str, message: str, **extra: object
) -> fastapi.HTTPException:
    """An HTTP error with the body of chapter 14.3 and more fields.

    Args:
        status: The HTTP status.
        code: The error code.
        message: The message; never a secret or a request value.
        **extra: More fields of the body, such as `job_id`.

    Returns:
        The exception.
    """
    return fastapi.HTTPException(
        status_code=status, detail={**routes.error_body(code, message), **extra}
    )


async def audit(
    services: state.Services,
    caller: auth.Principal,
    action: str,
    *,
    target: str | None = None,
    params: dict[str, Any] | None = None,
    outcome: str = "ok",
) -> None:
    """Write 1 admin action in a thread; a store failure is logged.

    Args:
        services: The shared services.
        caller: The admin.
        action: The action name.
        target: The object acted on.
        params: The parameters without secrets.
        outcome: `ok` or an error code.
    """
    try:
        await asyncio.to_thread(
            functools.partial(
                admin_store.record_audit,
                state_store.state_path(services.settings),
                caller.user.name,
                action,
                target=target,
                params=params,
                outcome=outcome,
            )
        )
    except errors.StateStoreError as error:
        logger.error("admin audit not written: %s", error)


class Progress(pydantic.BaseModel):
    """The progress of a job.

    Attributes:
        done: The steps done.
        total: The steps in all, or None when not known.
    """

    done: int
    total: int | None


class StepProgress(pydantic.BaseModel):
    """The counts of 1 step.

    Attributes:
        done: The units done.
        total: The units in all, or None when not known.
        unit: The plural noun of the unit, such as `chunks`, or empty.
    """

    done: int
    total: int | None
    unit: str = ""


class JobStep(pydantic.BaseModel):
    """1 step of a job, with its own log.

    Attributes:
        key: The stable step key, such as `embed`.
        name: The step name, such as `Embed`.
        status: pending, running, succeeded, failed, or skipped.
        started_at: When it started (UTC), or None.
        finished_at: When it ended (UTC), or None.
        progress: The counts the step reported, or None.
        log: The last log lines of the step (at most 200), oldest first.
    """

    key: str
    name: str
    status: Literal["pending", "running", "succeeded", "failed", "skipped"]
    started_at: str | None = None
    finished_at: str | None = None
    progress: StepProgress | None = None
    log: list[str] = pydantic.Field(default_factory=list)


class JobSummary(pydantic.BaseModel):  # pylint: disable=too-many-instance-attributes
    """1 job without its log.

    Attributes:
        id: The job ID (16 hex characters).
        kind: The job kind.
        params: The validated parameters.
        requested_by: The admin who asked.
        heavy: True when the job holds the maintenance slot.
        status: queued, running, succeeded, failed, or cancelled.
        progress: Done of total.
        phase: What the job does now.
        created_at: When it was asked for (UTC).
        started_at: When it started, or None.
        finished_at: When it ended, or None.
        result: The result summary, or None.
        error: The error of a failed job, or None.
        step_count: The steps of the plan; 0 for a job without steps.
        current_step: The index of the running step, or None.
    """

    id: str
    kind: str
    params: dict[str, Any]
    requested_by: str
    heavy: bool
    status: str
    progress: Progress
    phase: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    result: dict[str, Any] | None
    error: str | None
    step_count: int = 0
    current_step: int | None = None


class JobDetail(JobSummary):
    """1 job with its log tail and its steps.

    Attributes:
        log: The last log lines of the job (at most 200), oldest first.
        steps: The steps in order, each with its own log; empty for a
            job kind without steps or a job recorded before them.
    """

    log: list[str]
    steps: list[JobStep] = pydantic.Field(default_factory=list)


class JobList(pydantic.BaseModel):
    """The body of `GET /api/admin/jobs`.

    Attributes:
        items: The jobs, newest first.
        active: The heavy job that holds the slot, or None.
    """

    items: list[JobSummary]
    active: JobSummary | None


class JobRequest(pydantic.BaseModel):
    """The body of `POST /api/admin/jobs`.

    Attributes:
        kind: The job kind.
        params: The parameters of the kind.
        confirm: The typed confirmation, when the kind needs one.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    kind: JobKind
    params: dict[str, Any] = pydantic.Field(default_factory=dict)
    confirm: str | None = pydantic.Field(default=None, max_length=200)


class JobSubmitted(pydantic.BaseModel):
    """The body of a queued job (HTTP 202).

    Attributes:
        job: The job.
        warnings: What the admin should know, such as the memory need.
        estimate: The cost estimate of a job that calls the model.
    """

    job: JobDetail
    warnings: list[str]
    estimate: costs.CostEstimate | None


class BackupItem(pydantic.BaseModel):
    """1 archive of the backup directory.

    Attributes:
        name: The file name; the restore job and the download take it.
        size_bytes: The size.
        created_at: The UTC time of its stamp.
        sha256: The hash of its `.sha256` file, or None without one.
    """

    name: str
    size_bytes: int
    created_at: str
    sha256: str | None


class BackupList(pydantic.BaseModel):
    """The body of `GET /api/admin/backups`.

    Attributes:
        directory: The backup directory.
        items: The archives, newest first.
    """

    directory: str
    items: list[BackupItem]


class AuditItem(pydantic.BaseModel):
    """1 admin action.

    Attributes:
        at: When (UTC).
        user: The admin.
        action: The action, such as `job.submit`.
        target: The object, such as a job ID.
        params: The parameters without secrets.
        outcome: `ok` or an error code.
    """

    at: str
    user: str
    action: str
    target: str | None
    params: dict[str, Any]
    outcome: str


class AuditList(pydantic.BaseModel):
    """The body of `GET /api/admin/audit`.

    Attributes:
        items: The actions, newest first.
    """

    items: list[AuditItem]


def summary_of(job: admin_store.JobRecord) -> JobSummary:
    """The API view of a job without its log.

    Args:
        job: The record.

    Returns:
        The summary.
    """
    views = steps_of(job)
    return JobSummary(
        id=job.id,
        kind=job.kind,
        params=job.params,
        requested_by=job.requested_by,
        heavy=job.heavy,
        status=job.status,
        progress=Progress(done=job.done, total=job.total),
        phase=job.phase,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        result=job.result,
        error=job.error,
        step_count=len(views),
        current_step=next(
            (
                index
                for index, step in enumerate(views)
                if step.status == "running"
            ),
            None,
        ),
    )


def steps_of(job: admin_store.JobRecord) -> list[JobStep]:
    """The API view of the steps of a job; a malformed step is dropped.

    Args:
        job: The record.

    Returns:
        The steps.
    """
    views: list[JobStep] = []
    for step in job.steps:
        try:
            views.append(JobStep.model_validate(step))
        except pydantic.ValidationError:
            logger.warning("job %s has a malformed step", job.id)
    return views


def detail_of(job: admin_store.JobRecord) -> JobDetail:
    """The API view of a job with its log.

    Args:
        job: The record.

    Returns:
        The detail.
    """
    return JobDetail(
        **summary_of(job).model_dump(),
        log=list(job.log),
        steps=steps_of(job),
    )


def runner_of(services: state.Services) -> jobs.JobRunner:
    """The job runner, or HTTP 503 before the app started it.

    Args:
        services: The shared services.

    Returns:
        The runner.

    Raises:
        HTTPException: 503 `jobs_unavailable`.
    """
    runner = services.jobs
    if not isinstance(runner, jobs.JobRunner):
        raise routes.http_error(
            503, "jobs_unavailable", "the job runner is not running"
        )
    return runner


def _store_error(error: errors.StateStoreError) -> fastapi.HTTPException:
    logger.error("state store: %s", error)
    return routes.http_error(503, "store_unavailable", "the job store failed")


def _invalid_params(error: pydantic.ValidationError) -> fastapi.HTTPException:
    # Only the locations and the error types: never the input values.
    fields = [
        ".".join(str(part) for part in item["loc"]) or "params"
        for item in error.errors()
    ]
    return api_error(
        400,
        "invalid_params",
        "the parameters do not fit the job kind",
        fields=fields,
    )


def _estimate(
    services: state.Services, kind: str, params: pydantic.BaseModel
) -> costs.CostEstimate | None:
    settings = services.settings
    if isinstance(params, job_kinds.EvalParams):
        return costs.eval_estimate(
            settings,
            warm_cache.DEFAULT_GOLDEN,
            answers=params.answers,
            judge=params.judge,
            subset=params.subset,
        )
    if isinstance(params, job_kinds.WarmCacheParams):
        answerer = services.answerer
        return costs.warm_cache_estimate(
            settings,
            answerer.cache if answerer else None,
            answerer.cache_key if answerer else None,
            refresh=params.refresh,
            facts_only=params.facts_only,
        )
    del kind
    return None


def confirmation(
    services: state.Services, kind: str, params: pydantic.BaseModel
) -> tuple[str | None, costs.CostEstimate | None, list[str]]:
    """The confirm value, the estimate, and the warnings of a job.

    Args:
        services: The shared services.
        kind: The job kind.
        params: The validated parameters.

    Returns:
        (confirm, estimate, warnings): confirm is None when the job runs
        without one.

    Raises:
        HTTPException: 404 `archive_not_found` for a restore of an
            archive outside the listing.
        GoldenSetError: The golden set or the subset is not valid.
        ConfigError: The prices file is absent or invalid.
    """
    estimate = _estimate(services, kind, params)
    warnings: list[str] = []
    confirm = estimate.confirm if estimate else None
    if isinstance(params, job_kinds.EvalParams) and params.answers:
        warnings.append(job_kinds.EVAL_WARNING)
    if isinstance(params, job_kinds.RestoreParams):
        if job_kinds.find_archive(services.settings, params.archive) is None:
            raise routes.http_error(
                404, "archive_not_found", "no archive by that name"
            )
        confirm = params.archive
        warnings.append(
            "the restored build replaces the current build; the current "
            "build stays as `previous`"
        )
    if isinstance(params, job_kinds.IndexParams):
        confirm = job_kinds.REBUILD_CONFIRM
        warnings.append(job_kinds.INDEX_WARNING)
    return confirm, estimate, warnings


def _check_confirm(
    expected: str | None,
    given: str | None,
    estimate: costs.CostEstimate | None,
) -> None:
    if expected is None:
        return
    extra: dict[str, Any] = {"confirm": expected}
    if estimate is not None:
        extra["estimate"] = estimate.model_dump(mode="json")
    if given is None:
        raise api_error(
            400,
            "confirm_required",
            "this job needs a typed confirmation",
            **extra,
        )
    if given != expected:
        raise api_error(
            400,
            "confirm_mismatch",
            "the confirmation does not match",
            **extra,
        )


@router.get("/jobs")
async def list_jobs(
    services: routes.Services,
    caller: Admin,
    limit: Annotated[int, fastapi.Query(ge=1, le=200)] = 50,
) -> JobList:
    """The admin jobs, newest first.

    Args:
        services: The shared services.
        caller: The admin.
        limit: The most jobs returned.

    Returns:
        The jobs and the heavy job that holds the slot.

    Raises:
        HTTPException: 503 when the store fails.
    """
    del caller
    path = state_store.state_path(services.settings)
    try:
        items = await asyncio.to_thread(
            functools.partial(admin_store.list_jobs, path, limit=limit)
        )
        active = await asyncio.to_thread(
            functools.partial(
                admin_store.list_jobs, path, statuses=admin_store.ACTIVE
            )
        )
    except errors.StateStoreError as error:
        raise _store_error(error) from error
    holder = next((job for job in active if job.heavy), None)
    return JobList(
        items=[summary_of(job) for job in items],
        active=summary_of(holder) if holder else None,
    )


@router.post("/jobs", status_code=202)
async def submit_job(
    body: JobRequest, services: routes.Services, caller: Admin
) -> JobSubmitted:
    """Queue an admin job.

    Args:
        body: The kind, the parameters, and the confirmation.
        services: The shared services.
        caller: The admin.

    Returns:
        The queued job, its warnings, and its cost estimate.

    Raises:
        HTTPException: 400 `invalid_params`, `confirm_required`, or
            `confirm_mismatch`; 404 `archive_not_found`; 409 `job_running`
            with the `job_id` that holds the slot; 503 when the runner or
            the store is not available.
    """
    runner = runner_of(services)
    spec = runner.specs[body.kind]
    action = f"job.{body.kind}"
    try:
        params = spec.params.model_validate(body.params)
    except pydantic.ValidationError as error:
        await audit(services, caller, action, outcome="invalid_params")
        raise _invalid_params(error) from None
    shown = params.model_dump(mode="json")
    try:
        expected, estimate, warnings = await asyncio.to_thread(
            confirmation, services, body.kind, params
        )
        _check_confirm(expected, body.confirm, estimate)
    except fastapi.HTTPException as error:
        detail: object = error.detail
        code = detail.get("code") if isinstance(detail, dict) else "refused"
        await audit(services, caller, action, params=shown, outcome=str(code))
        raise
    except errors.GoldenSetError as error:
        await audit(
            services, caller, action, params=shown, outcome="invalid_params"
        )
        raise routes.http_error(400, "invalid_params", str(error)) from None
    except errors.ConfigError as error:
        logger.error("cost estimate failed: %s", error)
        raise routes.http_error(
            503, "prices_unavailable", "the prices file failed"
        ) from None
    try:
        job = await asyncio.to_thread(
            runner.submit, body.kind, params, caller.user.name
        )
    except errors.JobBusyError as error:
        await audit(
            services, caller, action, params=shown, outcome="job_running"
        )
        raise api_error(
            409, "job_running", str(error), job_id=error.job_id
        ) from None
    except errors.StateStoreError as error:
        raise _store_error(error) from error
    await audit(services, caller, action, target=job.id, params=shown)
    logger.info("admin job %s queued", job.id)
    return JobSubmitted(
        job=detail_of(job), warnings=warnings, estimate=estimate
    )


JobId = Annotated[str, fastapi.Path(pattern=JOB_ID)]


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: JobId, services: routes.Services, caller: Admin
) -> JobDetail:
    """1 job with its log tail; the admin pages poll it.

    Args:
        job_id: The job ID.
        services: The shared services.
        caller: The admin.

    Returns:
        The job.

    Raises:
        HTTPException: 404 for an unknown ID, 503 when the store fails.
    """
    del caller
    try:
        job = await asyncio.to_thread(
            admin_store.get_job,
            state_store.state_path(services.settings),
            job_id,
        )
    except errors.StateStoreError as error:
        raise _store_error(error) from error
    if job is None:
        raise routes.http_error(404, "not_found", "no job with this ID")
    return detail_of(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: JobId, services: routes.Services, caller: Admin
) -> JobDetail:
    """Cancel a queued job; a running job runs to its end.

    Args:
        job_id: The job ID.
        services: The shared services.
        caller: The admin.

    Returns:
        The cancelled job.

    Raises:
        HTTPException: 404 for an unknown ID, 409 `not_cancellable` for a
            job that is not queued, 503 when the store fails.
    """
    runner = runner_of(services)
    try:
        job = await asyncio.to_thread(runner.cancel, job_id)
    except KeyError:
        raise routes.http_error(
            404, "not_found", "no job with this ID"
        ) from None
    except errors.JobStateError as error:
        await audit(
            services, caller, "job.cancel", target=job_id, outcome="busy"
        )
        raise routes.http_error(409, "not_cancellable", str(error)) from None
    except errors.StateStoreError as error:
        raise _store_error(error) from error
    await audit(services, caller, "job.cancel", target=job_id)
    return detail_of(job)


@router.get("/costs/preview")
async def cost_preview(  # pylint: disable=too-many-arguments
    *,
    services: routes.Services,
    caller: Admin,
    kind: Annotated[Literal["eval", "warm_cache"], fastapi.Query()],
    answers: bool = True,
    judge: bool = True,
    subset: Annotated[
        str | None, fastapi.Query(pattern=r"^[A-Za-z0-9_,-]{1,200}$")
    ] = None,
    refresh: bool = False,
    facts_only: bool = False,
) -> costs.CostEstimate:
    """The model requests and the USD of a job before it runs.

    Args:
        services: The shared services.
        caller: The admin.
        kind: `eval` or `warm_cache`.
        answers: eval: answer each question.
        judge: eval: judge each answer.
        subset: eval: a subset tag or a comma list of IDs.
        refresh: warm_cache: answer every question again.
        facts_only: warm_cache: answer nothing.

    Returns:
        The estimate, with the `confirm` value the job needs.

    Raises:
        HTTPException: 400 for a bad subset, 503 when the prices fail.
    """
    del caller
    params: pydantic.BaseModel = (
        job_kinds.EvalParams(answers=answers, judge=judge, subset=subset)
        if kind == "eval"
        else job_kinds.WarmCacheParams(refresh=refresh, facts_only=facts_only)
    )
    try:
        estimate = await asyncio.to_thread(_estimate, services, kind, params)
    except errors.GoldenSetError as error:
        raise routes.http_error(400, "invalid_params", str(error)) from None
    except errors.ConfigError as error:
        logger.error("cost estimate failed: %s", error)
        raise routes.http_error(
            503, "prices_unavailable", "the prices file failed"
        ) from None
    if estimate is None:  # pragma: no cover  # both kinds estimate
        raise routes.http_error(400, "invalid_params", "no estimate")
    return estimate


def _sha256_of(item: backup.BackupInfo) -> str | None:
    path = item.path.with_name(item.name + backup.CHECKSUM_SUFFIX)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    digest = text.strip().partition("  ")[0]
    return digest if len(digest) == 64 else None


def backup_items(services: state.Services) -> list[BackupItem]:
    """The archives of the backup directory with their hashes.

    Args:
        services: The shared services.

    Returns:
        The archives, newest first.
    """
    return [
        BackupItem(
            name=item.name,
            size_bytes=item.size_bytes,
            created_at=item.created_at,
            sha256=_sha256_of(item),
        )
        for item in backup.list_backups(services.settings.scheduler.backup_dir)
    ]


@router.get("/backups")
async def list_backups(services: routes.Services, caller: Admin) -> BackupList:
    """The local archives that a restore or a download can take.

    Args:
        services: The shared services.
        caller: The admin.

    Returns:
        The backup directory and the archives, newest first.
    """
    del caller
    items = await asyncio.to_thread(backup_items, services)
    return BackupList(
        directory=str(services.settings.scheduler.backup_dir), items=items
    )


@router.get("/backups/{name}")
async def download_backup(
    name: str, services: routes.Services, caller: Admin
) -> responses.FileResponse:
    """Stream 1 archive of the listing as a download.

    The name must equal a name of the listing exactly, so no path, link,
    or other file of the directory is reachable.

    Args:
        name: The archive name.
        services: The shared services.
        caller: The admin.

    Returns:
        The archive, streamed.

    Raises:
        HTTPException: 404 for a name outside the listing.
    """
    found = None
    if backup.is_archive_name(name):
        found = await asyncio.to_thread(
            job_kinds.find_archive, services.settings, name
        )
    if found is None:
        raise routes.http_error(404, "not_found", "no archive by that name")
    await audit(services, caller, "backups.download", target=found.name)
    return responses.FileResponse(
        found.path,
        media_type="application/gzip",
        filename=found.name,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/audit")
async def list_audit(
    services: routes.Services,
    caller: Admin,
    limit: Annotated[int, fastapi.Query(ge=1, le=500)] = 100,
) -> AuditList:
    """The admin actions, newest first.

    Args:
        services: The shared services.
        caller: The admin.
        limit: The most entries returned.

    Returns:
        The actions.

    Raises:
        HTTPException: 503 when the store fails.
    """
    del caller
    try:
        entries = await asyncio.to_thread(
            admin_store.list_audit,
            state_store.state_path(services.settings),
            limit,
        )
    except errors.StateStoreError as error:
        raise _store_error(error) from error
    return AuditList(
        items=[
            AuditItem(
                at=e.at,
                user=e.user,
                action=e.action,
                target=e.target,
                params=e.params,
                outcome=e.outcome,
            )
            for e in entries
        ]
    )
