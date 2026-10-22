"""The in-app scheduler for the nightly jobs (chapter 29.9 step 7).

A Railway cron service cannot share the app's volume, so on Railway the
nightly refresh and backup run inside `keel serve` when `scheduler.enabled`
is on. The AWS host runs the same work from systemd timers instead, so the
flag is off by default.

The times in `scheduler.refresh_at` and `scheduler.backup_at` are UTC. The
jobs run 1 at a time in 1 daemon thread, so a long refresh delays the backup
instead of racing it. A job that fails is logged and runs again the next
night. Stage 21 registers the backup; the refresh job of stage 20 joins
through the `refresh` hook of `build_scheduler`.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
import dataclasses
import datetime
import functools
import logging
import threading

from keel import backup
from keel import config

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime.datetime]
# The longest sleep between checks, so a clock change is noticed.
MAX_SLEEP_SECONDS = 60.0


@dataclasses.dataclass(frozen=True)
class Job:
    """A job that runs once a day.

    Attributes:
        name: The job name in the logs.
        at: The UTC time of day.
        run: The work; its return value is ignored.
    """

    name: str
    at: datetime.time
    run: Callable[[], object]


def utc_now() -> datetime.datetime:
    """Return the current UTC time.

    Returns:
        An aware datetime in UTC.
    """
    return datetime.datetime.now(datetime.UTC)


def parse_time(text: str) -> datetime.time:
    """Parse an `HH:MM` time of day as UTC.

    Args:
        text: The time, for example `02:30`.

    Returns:
        The time with the UTC zone.

    Raises:
        ValueError: The text is not `HH:MM`.
    """
    parsed = datetime.datetime.strptime(text, "%H:%M")
    return parsed.time().replace(tzinfo=datetime.UTC)


def next_run(at: datetime.time, now: datetime.datetime) -> datetime.datetime:
    """Return the first time after `now` at the time of day `at`.

    Args:
        at: The UTC time of day.
        now: An aware datetime.

    Returns:
        Today at `at` when that is still ahead, else tomorrow at `at`.
    """
    today = now.astimezone(datetime.UTC).date()
    candidate = datetime.datetime.combine(today, at.replace(tzinfo=None))
    candidate = candidate.replace(tzinfo=datetime.UTC)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


class Scheduler:
    """Runs daily jobs in 1 background thread."""

    def __init__(self, jobs: Sequence[Job], clock: Clock = utc_now) -> None:
        """Plan the first run of each job after the current time.

        Args:
            jobs: The jobs.
            clock: Returns the current aware time.
        """
        self._jobs = tuple(jobs)
        self._clock = clock
        now = clock()
        self._due = {job.name: next_run(job.at, now) for job in self._jobs}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def jobs(self) -> tuple[Job, ...]:
        """The registered jobs."""
        return self._jobs

    def due(self, name: str) -> datetime.datetime:
        """Return the next run time of a job.

        Args:
            name: The job name.

        Returns:
            The next run time in UTC.
        """
        return self._due[name]

    def run_due(self) -> list[str]:
        """Run every job whose time has come, in registration order.

        Returns:
            The names of the jobs that ran.
        """
        ran = []
        for job in self._jobs:
            if self._clock() < self._due[job.name]:
                continue
            logger.info("scheduler: running %s", job.name)
            try:
                job.run()
            # A failed job must not stop the thread; it runs again tomorrow.
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("scheduler: %s failed", job.name)
            ran.append(job.name)
            self._due[job.name] = next_run(job.at, self._clock())
        return ran

    def seconds_to_next(self) -> float:
        """Return the seconds until the next job, at most a minute.

        Returns:
            The sleep before the next check.
        """
        if not self._due:
            return MAX_SLEEP_SECONDS
        now = self._clock()
        wait = min(due - now for due in self._due.values()).total_seconds()
        return min(MAX_SLEEP_SECONDS, max(0.0, wait))

    def _loop(self) -> None:
        while not self._stop.wait(self.seconds_to_next()):
            self.run_due()

    def start(self) -> None:
        """Start the background thread once."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="keel-scheduler", daemon=True
        )
        self._thread.start()
        logger.info(
            "scheduler: %s",
            ", ".join(f"{j.name} at {self._due[j.name]}" for j in self._jobs),
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the thread after the job it runs, if any.

        Args:
            timeout: The seconds to wait for the thread.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None


def build_scheduler(
    settings: config.Settings,
    *,
    refresh: Callable[[], object] | None = None,
    nightly_backup: Callable[[], object] | None = None,
    clock: Clock = utc_now,
) -> Scheduler | None:
    """Build the scheduler of `keel serve` from the config.

    Args:
        settings: The loaded settings.
        refresh: The nightly refresh (stage 20); None registers no refresh.
        nightly_backup: The backup job; None runs `run_nightly_backup`.
        clock: Returns the current aware time.

    Returns:
        The scheduler, not started, or None when `scheduler.enabled` is off.
    """
    if not settings.scheduler.enabled:
        return None
    jobs = []
    if refresh is not None:
        jobs.append(
            Job("refresh", parse_time(settings.scheduler.refresh_at), refresh)
        )
    jobs.append(
        Job(
            "backup",
            parse_time(settings.scheduler.backup_at),
            nightly_backup
            or functools.partial(backup.run_nightly_backup, settings),
        )
    )
    return Scheduler(jobs, clock)
