"""Tests for the in-app scheduler of the nightly jobs."""

import datetime
import logging
import threading

import pytest

from keel import config
from keel import errors
from keel import scheduler

pytestmark = pytest.mark.unit

UTC = datetime.UTC


class FakeClock:
    def __init__(self, start: datetime.datetime) -> None:
        self.now = start

    def __call__(self) -> datetime.datetime:
        return self.now


def enabled(settings: config.Settings) -> config.Settings:
    return settings.model_copy(
        update={
            "scheduler": settings.scheduler.model_copy(update={"enabled": True})
        }
    )


def test_scheduler_disabled_by_default(settings: config.Settings) -> None:
    assert settings.scheduler.enabled is False
    assert scheduler.build_scheduler(settings, refresh=lambda: None) is None


def test_scheduler_registers_backup_and_the_refresh_hook(
    settings: config.Settings,
) -> None:
    clock = FakeClock(datetime.datetime(2026, 10, 22, 1, 0, tzinfo=UTC))

    plain = scheduler.build_scheduler(enabled(settings), clock=clock)
    assert plain is not None
    assert [job.name for job in plain.jobs] == ["backup"]
    assert plain.due("backup") == datetime.datetime(
        2026, 10, 22, 2, 30, tzinfo=UTC
    )

    hooked = scheduler.build_scheduler(
        enabled(settings), refresh=lambda: None, clock=clock
    )
    assert hooked is not None
    assert [job.name for job in hooked.jobs] == ["refresh", "backup"]
    assert hooked.due("refresh") == datetime.datetime(
        2026, 10, 22, 2, 0, tzinfo=UTC
    )


def test_parse_time_and_next_run() -> None:
    at = scheduler.parse_time("02:30")
    assert (at.hour, at.minute, at.tzinfo) == (2, 30, UTC)
    with pytest.raises(ValueError, match="unconverted data"):
        scheduler.parse_time("2:30pm")
    before = datetime.datetime(2026, 10, 22, 2, 29, tzinfo=UTC)
    after = datetime.datetime(2026, 10, 22, 2, 30, tzinfo=UTC)
    assert scheduler.next_run(at, before) == after
    assert scheduler.next_run(at, after) == after + datetime.timedelta(days=1)


def test_config_rejects_a_bad_time(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("KEEL_SCHEDULER__BACKUP_AT", "25:00")
    with pytest.raises(errors.ConfigError, match="backup_at"):
        config.load_settings(config.DEFAULT_CONFIG_PATH, env_file=None)


def test_run_due_runs_each_job_once_per_day(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FakeClock(datetime.datetime(2026, 10, 22, 1, 0, tzinfo=UTC))
    calls: list[str] = []

    def failing_refresh() -> None:
        calls.append("refresh")
        raise RuntimeError("EDGAR down")

    jobs = [
        scheduler.Job(
            "refresh", scheduler.parse_time("02:00"), failing_refresh
        ),
        scheduler.Job(
            "backup", scheduler.parse_time("02:30"), lambda: calls.append("b")
        ),
    ]
    planner = scheduler.Scheduler(jobs, clock)

    assert planner.run_due() == []
    clock.now = datetime.datetime(2026, 10, 22, 2, 45, tzinfo=UTC)
    with caplog.at_level(logging.ERROR):
        assert planner.run_due() == ["refresh", "backup"]
    assert "refresh failed" in caplog.text
    assert calls == ["refresh", "b"]
    assert planner.run_due() == []
    assert planner.due("refresh") == datetime.datetime(
        2026, 10, 23, 2, 0, tzinfo=UTC
    )
    clock.now = datetime.datetime(2026, 10, 23, 2, 30, tzinfo=UTC)
    assert planner.run_due() == ["refresh", "backup"]


def test_seconds_to_next() -> None:
    clock = FakeClock(datetime.datetime(2026, 10, 22, 2, 29, 30, tzinfo=UTC))
    planner = scheduler.Scheduler(
        [scheduler.Job("backup", scheduler.parse_time("02:30"), lambda: 0)],
        clock,
    )
    assert planner.seconds_to_next() == 30.0
    clock.now = datetime.datetime(2026, 10, 22, 1, 0, tzinfo=UTC)
    assert planner.seconds_to_next() == scheduler.MAX_SLEEP_SECONDS
    clock.now = datetime.datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
    assert planner.seconds_to_next() == 0.0
    assert (
        scheduler.Scheduler([], clock).seconds_to_next()
        == scheduler.MAX_SLEEP_SECONDS
    )


def test_start_and_stop_runs_a_due_job() -> None:
    ran = threading.Event()
    clock = FakeClock(datetime.datetime(2026, 10, 22, 2, 29, tzinfo=UTC))
    planner = scheduler.Scheduler(
        [scheduler.Job("backup", scheduler.parse_time("02:30"), ran.set)],
        clock,
    )
    clock.now = datetime.datetime(2026, 10, 22, 2, 31, tzinfo=UTC)

    planner.start()
    planner.start()
    try:
        assert ran.wait(timeout=10)
    finally:
        planner.stop()
    planner.stop()


def test_utc_now_is_aware() -> None:
    assert scheduler.utc_now().tzinfo is UTC
