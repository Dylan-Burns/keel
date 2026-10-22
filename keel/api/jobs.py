"""The background job runner of the admin API.

The admin pages start the operational commands of the CLI (`keel add`,
`keel refresh`, `keel warm-cache`, `keel eval`, `keel facts`, `keel
backup`, `keel restore`, `keel index`) as jobs. 1 worker thread runs the
jobs in the order they were asked for. A heavy job (every kind but
`facts`) holds the maintenance slot: while 1 is queued or running, a
second heavy job is refused with `JobBusyError` (HTTP 409 with the ID of
the job that holds the slot), and the nightly refresh and backup of the
in-app scheduler skip their run (`Services.maintenance`).

Every job is a row of the `jobs` table in `state.sqlite` under
`logs.dir` (`keel.stores.admin_store`), so the record survives a
restart: a job that was queued or running when the server stopped is
marked failed when the runner starts again. The worker writes the status,
the progress (done of total), the phase, a log tail of the last 200 lines
(each redacted and cut to 400 characters), the result summary, and the
error.

A job that changes the index (an add or a refresh that indexed a filing,
a restore, a rebuild) calls `Services.reload` at its end, so the server
serves the new build without a restart; a build that cannot be opened
leaves the old one in service.

The runner calls the library functions of the CLI commands in-process
(`keel.api.job_kinds`); it never starts a shell.
"""

from __future__ import annotations

import asyncio
import collections
from collections.abc import Callable
from collections.abc import Coroutine
from collections.abc import Mapping
import concurrent.futures
import dataclasses
import logging
import os
import queue
import re
import threading
import time
from typing import Any
from typing import TypeVar
import uuid

import pydantic

from keel import errors
from keel import security
from keel.api import state
from keel.stores import admin_store
from keel.stores import state_store

logger = logging.getLogger(__name__)

LOG_LINES = 200
LOG_LINE_CHARS = 400
FLUSH_SECONDS = 0.5
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_STOP = ""
T = TypeVar("T")


@dataclasses.dataclass(frozen=True)
class JobOutput:
    """What a job returns.

    Attributes:
        result: The result summary, JSON-ready.
        reload: True when the job published a new index build, so the
            server reloads the index.
    """

    result: dict[str, Any]
    reload: bool = False


class JobContext:
    """The handle a running job reports through.

    The log, the progress, and the phase are kept in memory and written to
    the job record from the worker thread only, at most every
    `FLUSH_SECONDS` and once more at the end, so a job that reports from
    the server's event loop (the warm-cache answers) never writes SQLite
    on that loop, and a build that reports every shard does not write a
    row per shard.

    Args:
        runner: The runner.
        job_id: The job ID.
        clock: The monotonic clock of the write throttle.
    """

    def __init__(
        self,
        runner: JobRunner,
        job_id: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.runner = runner
        self.job_id = job_id
        self.clock = clock
        self.worker = threading.get_ident()
        self._lines: collections.deque[str] = collections.deque(
            maxlen=LOG_LINES
        )
        self._fields: dict[str, object] = {}
        self._flushed = 0.0
        self._lock = threading.Lock()

    def _set(self, **fields: object) -> None:
        with self._lock:
            self._fields.update(fields)
        if threading.get_ident() == self.worker:
            self.flush(force=False)

    def flush(self, force: bool = True) -> None:
        """Write the pending fields to the job record (worker thread).

        Args:
            force: Write now; False writes only when `FLUSH_SECONDS`
                passed since the last write.
        """
        now = self.clock()
        with self._lock:
            if not self._fields or (
                not force and now - self._flushed < FLUSH_SECONDS
            ):
                return
            fields, self._fields = self._fields, {}
            self._flushed = now
        self.runner.update(self.job_id, **fields)

    def log(self, line: str) -> None:
        """Append 1 line to the log tail of the job.

        Args:
            line: The line; secrets are masked and control characters
                removed.
        """
        clean = self.runner.clean(line)
        with self._lock:
            self._lines.append(clean)
            lines = list(self._lines)
        self._set(log=lines)

    def progress(self, done: int, total: int | None) -> None:
        """Record the progress.

        Args:
            done: The steps done.
            total: The steps in all, or None when not known.
        """
        self._set(done=max(0, done), total=total)

    def phase(self, text: str) -> None:
        """Record what the job does now; written at once.

        Args:
            text: A few words, such as `embedding`.
        """
        self._set(phase=self.runner.clean(text)[:120])
        if threading.get_ident() == self.worker:
            self.flush()

    def run_async(self, coroutine: Coroutine[Any, Any, T]) -> T:
        """Run a coroutine on the server's event loop and wait for it.

        The pipeline's async provider client belongs to the server loop,
        so a job that answers questions runs them there. The worker
        thread waits and writes the job record while it waits.

        Args:
            coroutine: The coroutine.

        Returns:
            Its result.

        Raises:
            JobStateError: The server loop is not running, the call comes
                from the loop thread itself, or the runner stops.
        """
        loop = self.runner.loop
        if loop is None or not loop.is_running():
            coroutine.close()
            raise errors.JobStateError("the server event loop is not running")
        if threading.get_ident() != self.worker:
            coroutine.close()
            raise errors.JobStateError("run_async runs on the job worker only")
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        while True:
            try:
                return future.result(timeout=FLUSH_SECONDS)
            except concurrent.futures.TimeoutError:
                self.flush(force=False)
                if self.runner.stopping.is_set() or not loop.is_running():
                    future.cancel()
                    raise errors.JobStateError(
                        "the server stopped while the job ran"
                    ) from None


JobFunction = Callable[[state.Services, JobContext, Any], JobOutput]


@dataclasses.dataclass(frozen=True)
class JobSpec:
    """1 job kind.

    Attributes:
        kind: The kind, such as `add`.
        params: The pydantic model of the parameters.
        heavy: True when the job holds the maintenance slot.
        run: Runs the job with the validated parameters.
        title: A short description for the API reference.
    """

    kind: str
    params: type[pydantic.BaseModel]
    heavy: bool
    run: JobFunction
    title: str


class JobRunner:
    """1 worker thread over the persisted job records.

    Args:
        services: The shared services.
        specs: The job kinds by name.
        loop: The server's event loop, for the jobs that answer.
    """

    def __init__(
        self,
        services: state.Services,
        specs: Mapping[str, JobSpec],
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.services = services
        self.specs = dict(specs)
        self.loop = loop
        self.path = state_store.state_path(services.settings)
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.stopping = threading.Event()
        self._secrets = security.secret_values(os.environ, services.settings)

    def clean(self, text: str) -> str:
        """Mask the secrets of a text and cut it to 1 short line.

        Args:
            text: The text.

        Returns:
            The redacted line without control characters.
        """
        line = _CONTROL.sub(" ", security.redact(str(text), self._secrets))
        return line[:LOG_LINE_CHARS]

    def start(self) -> int:
        """Mark the interrupted jobs failed and start the worker.

        Returns:
            The jobs marked failed because the server stopped under them.

        Raises:
            StateStoreError: The state database cannot be read or written.
        """
        marked = admin_store.fail_interrupted(self.path)
        if marked:
            logger.warning("%d interrupted admin jobs marked failed", marked)
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._work, name="keel-jobs", daemon=True
            )
            self._thread.start()
        return marked

    def stop(self, timeout: float = 1.0) -> None:
        """Stop the worker after its current job; wait at most `timeout`.

        Args:
            timeout: The seconds to wait for the thread.
        """
        thread = self._thread
        if thread is None:
            return
        self.stopping.set()
        self._queue.put(_STOP)
        thread.join(timeout)
        if not thread.is_alive():
            self._thread = None

    def update(self, job_id: str, **fields: object) -> None:
        """Write fields of a job; a store failure is logged, never raised.

        Args:
            job_id: The job ID.
            **fields: The fields of `admin_store.update_job`.
        """
        try:
            admin_store.update_job(self.path, job_id, **fields)
        except errors.StateStoreError as error:
            logger.error("job record not written: %s", error)

    def holder(self) -> admin_store.JobRecord | None:
        """The heavy job that is queued or running, if any.

        Returns:
            The job, or None when the maintenance slot is free.
        """
        for job in admin_store.list_jobs(
            self.path, statuses=admin_store.ACTIVE
        ):
            if job.heavy:
                return job
        return None

    def submit(
        self, kind: str, params: pydantic.BaseModel, requested_by: str
    ) -> admin_store.JobRecord:
        """Queue a job.

        Args:
            kind: The job kind.
            params: The validated parameters.
            requested_by: The admin who asked.

        Returns:
            The queued job.

        Raises:
            JobBusyError: The job is heavy and a heavy job is queued or
                running, or the first-start bootstrap or a nightly job
                runs.
            StateStoreError: The record cannot be written.
            KeyError: The kind is unknown.
        """
        spec = self.specs[kind]
        with self._lock:
            if spec.heavy:
                boot = self.services.bootstrap
                if boot is not None and boot.active:
                    raise errors.JobBusyError(
                        "the first-start bootstrap is running"
                    )
                current = self.holder()
                if current is not None:
                    raise errors.JobBusyError(
                        f"the {current.kind} job {current.id} is "
                        f"{current.status}",
                        current.id,
                    )
                if self.services.maintenance.locked():
                    raise errors.JobBusyError(
                        "a nightly refresh or backup is running"
                    )
            record = admin_store.JobRecord(
                id=uuid.uuid4().hex[:16],
                kind=kind,
                params=params.model_dump(mode="json"),
                requested_by=requested_by,
                heavy=spec.heavy,
                status="queued",
                done=0,
                total=None,
                phase="queued",
                created_at=admin_store.now_text(),
                started_at=None,
                finished_at=None,
                log=(),
                result=None,
                error=None,
            )
            admin_store.insert_job(self.path, record)
        self._queue.put(record.id)
        return record

    def cancel(self, job_id: str) -> admin_store.JobRecord:
        """Cancel a queued job; a running job cannot stop safely.

        Args:
            job_id: The job ID.

        Returns:
            The cancelled job.

        Raises:
            JobStateError: The job is not queued.
            KeyError: The job ID is unknown.
        """
        with self._lock:
            job = admin_store.get_job(self.path, job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status != "queued":
                raise errors.JobStateError(
                    f"only a queued job can be cancelled; it is {job.status}"
                )
            updated = admin_store.update_job(
                self.path,
                job_id,
                status="cancelled",
                phase="cancelled",
                finished_at=admin_store.now_text(),
            )
        if updated is None:  # pragma: no cover  # deleted under the lock
            raise KeyError(job_id)
        return updated

    def _work(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id == _STOP:
                return
            try:
                self._run(job_id)
            except Exception as error:  # pylint: disable=broad-exception-caught
                # The worker outlives any failure; the record says so.
                logger.error(
                    "admin job %s crashed: %s", job_id, type(error).__name__
                )
                logger.debug("admin job crash", exc_info=True)
                self.update(
                    job_id,
                    status="failed",
                    phase="failed",
                    error=f"internal error: {type(error).__name__}",
                    finished_at=admin_store.now_text(),
                )

    def _claim(self, job_id: str) -> admin_store.JobRecord | None:
        with self._lock:
            job = admin_store.get_job(self.path, job_id)
            if job is None or job.status != "queued":
                return None
            return admin_store.update_job(
                self.path,
                job_id,
                status="running",
                phase="starting",
                started_at=admin_store.now_text(),
            )

    def _run(self, job_id: str) -> None:
        job = self._claim(job_id)
        if job is None:
            return
        context = JobContext(self, job.id)
        logger.info("admin job %s (%s) started", job.id, job.kind)
        try:
            output = self._execute(self.specs[job.kind], context, job)
        except errors.KeelError as error:
            context.flush()
            self.update(
                job.id,
                status="failed",
                phase="failed",
                error=self.clean(f"{type(error).__name__}: {error}"),
                finished_at=admin_store.now_text(),
            )
            logger.warning(
                "admin job %s failed: %s", job.id, type(error).__name__
            )
            return
        result = dict(output.result)
        if output.reload:
            context.phase("reloading the index")
            result["reloaded"] = self._reload()
        context.flush()
        self.update(
            job.id,
            status="succeeded",
            phase="done",
            result=result,
            finished_at=admin_store.now_text(),
        )
        logger.info("admin job %s succeeded", job.id)

    def _execute(
        self,
        spec: JobSpec,
        context: JobContext,
        job: admin_store.JobRecord,
    ) -> JobOutput:
        params = spec.params.model_validate(job.params)
        if not spec.heavy:
            return spec.run(self.services, context, params)
        maintenance = self.services.maintenance
        if not maintenance.acquire(blocking=False):
            context.phase("waiting for the nightly job")
            maintenance.acquire()
        try:
            context.phase("running")
            return spec.run(self.services, context, params)
        finally:
            maintenance.release()

    def _reload(self) -> bool:
        """Swap in the published build; True when the server serves it."""
        before = self.services.answerer
        try:
            self.services.reload()
        except Exception as error:  # pylint: disable=broad-exception-caught
            # The old build keeps serving; the job result says so.
            logger.error("index reload failed: %s", type(error).__name__)
            return False
        after = self.services.answerer
        return after is not None and after is not before
