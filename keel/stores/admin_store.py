"""The admin jobs and the admin audit trail in the app-state database.

Both tables live in `state.sqlite` under `logs.dir`, next to the watch
list of `keel.stores.state_store`: the file sits on the persistent volume
and survives an index rebuild, and the nightly backup copies every SQLite
file of the logs directory.

The `jobs` table holds 1 row per background job of the admin API
(`keel.api.jobs`): the kind, the parameters, the user who asked, the
status, the progress, the phase, a bounded log tail, the steps with
their own logs (`keel.api.job_steps`), the result summary, and the error.
A job that was queued or running when the server stopped is marked
failed at the next start (`fail_interrupted`). A database written before
the steps existed gets the `steps` column on its first connection; its
old rows hold no steps.

The `admin_audit` table holds 1 row per admin action: who, what, the
target, and the parameters without any secret. A token never reaches
this table.
"""

from __future__ import annotations

from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
import contextlib
import dataclasses
import datetime
import json
import pathlib
import sqlite3
from typing import Any
from typing import Literal

from keel import errors
from keel.stores import state_store

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ACTIVE: tuple[JobStatus, ...] = ("queued", "running")
INTERRUPTED = "interrupted: the server stopped before the job finished"
SECRET_PARTS = ("token", "key", "password", "secret")
DEFAULT_LIMIT = 50
# The log lines a step keeps (keel.api.job_steps reads it too).
STEP_LOG_LINES = 200
MAX_LIMIT = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  params TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  heavy INTEGER NOT NULL,
  status TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0,
  total INTEGER,
  phase TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  log TEXT NOT NULL DEFAULT '[]',
  result TEXT,
  error TEXT,
  steps TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS jobs_created ON jobs (created_at);
CREATE TABLE IF NOT EXISTS admin_audit (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  user TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  params TEXT NOT NULL,
  outcome TEXT NOT NULL
);
"""

_COLUMNS = (
    "id, kind, params, requested_by, heavy, status, done, total, phase, "
    "created_at, started_at, finished_at, log, result, error, steps"
)
_MIGRATED: set[str] = set()


@dataclasses.dataclass(frozen=True)
class JobRecord:  # pylint: disable=too-many-instance-attributes
    """1 admin job.

    Attributes:
        id: The job ID.
        kind: The job kind, such as `add` or `index`.
        params: The validated parameters.
        requested_by: The user who asked for it.
        heavy: True when the job holds the maintenance slot.
        status: queued, running, succeeded, failed, or cancelled.
        done: The steps done.
        total: The steps in all, or None when not known.
        phase: What the job does now, in a few words.
        created_at: When it was asked for (UTC, ISO 8601).
        started_at: When it started, or None.
        finished_at: When it ended, or None.
        log: The last log lines, oldest first.
        result: The result summary, or None.
        error: The error of a failed job, or None.
        steps: The steps of the plan with their status, times, progress,
            and log (`keel.api.job_steps`); empty for a job kind without
            a plan or a row written before the steps existed.
    """

    id: str
    kind: str
    params: dict[str, Any]
    requested_by: str
    heavy: bool
    status: JobStatus
    done: int
    total: int | None
    phase: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    log: tuple[str, ...]
    result: dict[str, Any] | None
    error: str | None
    steps: tuple[dict[str, Any], ...] = ()

    @property
    def active(self) -> bool:
        """True while the job is queued or running."""
        return self.status in ACTIVE


@dataclasses.dataclass(frozen=True)
class AuditEntry:
    """1 admin action.

    Attributes:
        at: When it happened (UTC, ISO 8601).
        user: The admin who acted.
        action: The action, such as `job.submit` or `users.add`.
        target: The object acted on, such as a job ID, or None.
        params: The parameters without secrets.
        outcome: `ok`, or a short error code.
    """

    at: str
    user: str
    action: str
    target: str | None
    params: dict[str, Any]
    outcome: str


def now_text() -> str:
    """The UTC time as ISO 8601 with seconds.

    Returns:
        The time text.
    """
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


@contextlib.contextmanager
def _connect(path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    conn = state_store.connect(path)
    try:
        with conn:
            conn.executescript(SCHEMA)
            _migrate(conn, path)
            yield conn
    except sqlite3.Error as error:
        raise errors.StateStoreError(f"state store {path}: {error}") from error
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection, path: pathlib.Path) -> None:
    """Add the `steps` column to a jobs table written before it."""
    key = str(path)
    if key in _MIGRATED:
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "steps" not in columns:
        try:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN steps TEXT NOT NULL DEFAULT '[]'"
            )
        except sqlite3.OperationalError as error:
            # Another connection added it first.
            if "duplicate column" not in str(error):
                raise
    _MIGRATED.add(key)


def _loads(text: str | None) -> Any:  # noqa: ANN401
    return json.loads(text) if text else None


def _record(row: tuple[Any, ...]) -> JobRecord:
    (
        job_id,
        kind,
        params,
        requested_by,
        heavy,
        status,
        done,
        total,
        phase,
        created_at,
        started_at,
        finished_at,
        log,
        result,
        error,
        steps,
    ) = row
    return JobRecord(
        id=str(job_id),
        kind=str(kind),
        params=dict(_loads(params) or {}),
        requested_by=str(requested_by),
        heavy=bool(heavy),
        status=status,
        done=int(done),
        total=None if total is None else int(total),
        phase=str(phase),
        created_at=str(created_at),
        started_at=started_at,
        finished_at=finished_at,
        log=tuple(str(line) for line in _loads(log) or []),
        result=_loads(result),
        error=error,
        steps=tuple(
            dict(step) for step in _loads(steps) or [] if isinstance(step, dict)
        ),
    )


def insert_job(path: pathlib.Path, record: JobRecord) -> None:
    """Write a new job row.

    Args:
        path: The state database.
        record: The job.

    Raises:
        StateStoreError: The database fails.
    """
    with _connect(path) as conn:
        conn.execute(
            f"INSERT INTO jobs ({_COLUMNS}) "  # noqa: S608
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.kind,
                json.dumps(record.params, sort_keys=True),
                record.requested_by,
                int(record.heavy),
                record.status,
                record.done,
                record.total,
                record.phase,
                record.created_at,
                record.started_at,
                record.finished_at,
                json.dumps(list(record.log)),
                None if record.result is None else json.dumps(record.result),
                record.error,
                json.dumps(list(record.steps)),
            ),
        )


_UPDATABLE = frozenset(
    {
        "status",
        "done",
        "total",
        "phase",
        "started_at",
        "finished_at",
        "log",
        "result",
        "error",
        "steps",
    }
)


def update_job(
    path: pathlib.Path, job_id: str, **fields: object
) -> JobRecord | None:
    """Change fields of a job row.

    Args:
        path: The state database.
        job_id: The job ID.
        **fields: The new values; `log` takes a sequence of lines,
            `steps` a sequence of step mappings, and `result` a mapping.

    Returns:
        The job after the change, or None for an unknown ID.

    Raises:
        StateStoreError: The database fails.
        ValueError: A field name is not a job field that changes.
    """
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError("not a changeable job field: " + ", ".join(unknown))
    values: list[object] = []
    for name, value in fields.items():
        if name == "log":
            lines = value if isinstance(value, list | tuple) else ()
            values.append(json.dumps([str(line) for line in lines]))
        elif name == "steps":
            items = value if isinstance(value, list | tuple) else ()
            values.append(json.dumps(list(items)))
        elif name == "result":
            values.append(None if value is None else json.dumps(value))
        else:
            values.append(value)
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with _connect(path) as conn:
        if assignments:
            conn.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608
                (*values, job_id),
            )
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM jobs WHERE id = ?",  # noqa: S608
            (job_id,),
        ).fetchone()
    return _record(row) if row else None


def get_job(path: pathlib.Path, job_id: str) -> JobRecord | None:
    """Read 1 job.

    Args:
        path: The state database.
        job_id: The job ID.

    Returns:
        The job, or None for an unknown ID or a missing database.

    Raises:
        StateStoreError: The database fails.
    """
    if not path.exists():
        return None
    with _connect(path) as conn:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM jobs WHERE id = ?",  # noqa: S608
            (job_id,),
        ).fetchone()
    return _record(row) if row else None


def list_jobs(
    path: pathlib.Path,
    *,
    limit: int = DEFAULT_LIMIT,
    statuses: tuple[JobStatus, ...] | None = None,
) -> list[JobRecord]:
    """List the jobs, newest first.

    Args:
        path: The state database.
        limit: The most jobs returned.
        statuses: Only these statuses, or None for all.

    Returns:
        The jobs; empty for a missing database.

    Raises:
        StateStoreError: The database fails.
    """
    if not path.exists():
        return []
    query = f"SELECT {_COLUMNS} FROM jobs"  # noqa: S608
    params: list[object] = []
    if statuses:
        marks = ", ".join("?" for _ in statuses)
        query += f" WHERE status IN ({marks})"
        params.extend(statuses)
    query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(limit, MAX_LIMIT)))
    with _connect(path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_record(row) for row in rows]


def fail_interrupted(path: pathlib.Path, when: str | None = None) -> int:
    """Mark every queued or running job failed (a server start).

    Args:
        path: The state database.
        when: The finish time; None takes the clock.

    Returns:
        The jobs marked.

    Raises:
        StateStoreError: The database fails.
    """
    if not path.exists():
        return 0
    finished = when or now_text()
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT id, steps FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchall()
        for job_id, steps in rows:
            closed = close_steps(_loads(steps) or [], finished, INTERRUPTED)
            conn.execute(
                "UPDATE jobs SET status = 'failed', error = ?, "
                "finished_at = ?, phase = 'interrupted', steps = ? "
                "WHERE id = ?",
                (INTERRUPTED, finished, json.dumps(closed), job_id),
            )
    return len(rows)


def close_steps(
    steps: Sequence[Any], when: str, error: str | None = None
) -> list[dict[str, Any]]:
    """End the steps of a job that stops before its plan ends.

    The running step failed (with the error as its last log line) and
    every pending step is skipped.

    Args:
        steps: The step mappings of the record.
        when: The finish time.
        error: The error line of the running step, or None.

    Returns:
        The closed steps; a value that is not a mapping is dropped.
    """
    closed: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        item = dict(step)
        if item.get("status") == "running":
            item.update(status="failed", finished_at=when)
            if error:
                lines = [*(item.get("log") or []), f"error: {error}"]
                item["log"] = lines[-STEP_LOG_LINES:]
        elif item.get("status") == "pending":
            item["status"] = "skipped"
        closed.append(item)
    return closed


def clean_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """Drop the secret-looking keys of a parameter mapping.

    Args:
        params: The parameters.

    Returns:
        A copy without any key whose name holds `token`, `key`,
        `password`, or `secret`.
    """
    return {
        key: value
        for key, value in params.items()
        if not any(part in key.lower() for part in SECRET_PARTS)
    }


def record_audit(  # pylint: disable=too-many-arguments
    path: pathlib.Path,
    user: str,
    action: str,
    *,
    target: str | None = None,
    params: Mapping[str, Any] | None = None,
    outcome: str = "ok",
) -> AuditEntry:
    """Append 1 admin action to the audit table.

    Args:
        path: The state database.
        user: The admin who acted.
        action: The action name.
        target: The object acted on, or None.
        params: The parameters; secret-looking keys are dropped.
        outcome: `ok`, or a short error code.

    Returns:
        The stored entry.

    Raises:
        StateStoreError: The database fails.
    """
    entry = AuditEntry(
        at=now_text(),
        user=user,
        action=action,
        target=target,
        params=clean_params(params or {}),
        outcome=outcome,
    )
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO admin_audit (at, user, action, target, params, "
            "outcome) VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry.at,
                entry.user,
                entry.action,
                entry.target,
                json.dumps(entry.params, sort_keys=True, default=str),
                entry.outcome,
            ),
        )
    return entry


def list_audit(
    path: pathlib.Path, limit: int = DEFAULT_LIMIT
) -> list[AuditEntry]:
    """List the admin actions, newest first.

    Args:
        path: The state database.
        limit: The most entries returned.

    Returns:
        The entries; empty for a missing database.

    Raises:
        StateStoreError: The database fails.
    """
    if not path.exists():
        return []
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT at, user, action, target, params, outcome "
            "FROM admin_audit ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, MAX_LIMIT)),),
        ).fetchall()
    return [
        AuditEntry(
            at=str(at),
            user=str(user),
            action=str(action),
            target=target,
            params=dict(_loads(params) or {}),
            outcome=str(outcome),
        )
        for at, user, action, target, params, outcome in rows
    ]
