"""The background work of `keel serve`: the bootstrap and the nightly jobs.

`keel serve --bootstrap` (chapter 29.9 step 6) starts the HTTP server
first, then runs the bootstrap of `keel.bootstrap` in a daemon thread. Once
the bootstrap reaches `ready`, the same thread opens the index through
`Services.reload`, so `/api/ready` turns `index_loaded` true without a
restart.

With `scheduler.enabled` on (Railway, chapter 29.9 step 7) the in-app
scheduler runs the refresh of chapter 26.3 at `scheduler.refresh_at` and the
backup at `scheduler.backup_at`. A refresh that added a filing published a
new build, so the server reloads the index after it.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import threading

from keel import bootstrap
from keel import errors
from keel import refresh
from keel import scheduler
from keel.api import state

logger = logging.getLogger(__name__)

RefreshRunner = Callable[[], refresh.RefreshReport]


def _bootstrap_then_load(
    services: state.Services,
    deps: bootstrap.Dependencies | None,
) -> None:
    """Run the bootstrap; open the index when it ends in `ready`."""
    if services.bootstrap is None:
        return
    status = bootstrap.run_bootstrap(
        services.settings, services.bootstrap, deps
    )
    if status.phase != bootstrap.Phase.READY:
        logger.error("bootstrap ended in %s: no index loaded", status.phase)
        return
    services.reload()


def start_bootstrap(
    services: state.Services,
    deps: bootstrap.Dependencies | None = None,
) -> threading.Thread | None:
    """Start the bootstrap thread of `keel serve --bootstrap`.

    Args:
        services: The shared services; `services.bootstrap` holds the state.
        deps: The outside world of the bootstrap; None uses the real one.

    Returns:
        The started daemon thread, or None when the services run without
        the bootstrap.
    """
    if services.bootstrap is None:
        return None
    thread = threading.Thread(
        target=_bootstrap_then_load,
        args=(services, deps),
        name="keel-bootstrap",
        daemon=True,
    )
    thread.start()
    return thread


def refresh_job(
    services: state.Services,
    runner: RefreshRunner | None = None,
) -> refresh.RefreshReport | None:
    """Run the nightly refresh and reload the index after a new build.

    Args:
        services: The shared services.
        runner: Runs the refresh; None runs `keel.refresh.run_refresh` with
            the service settings.

    Returns:
        The refresh report, or None when the run failed (logged).
    """
    run = runner or (lambda: refresh.run_refresh(services.settings))
    try:
        report = run()
    except errors.KeelError as error:
        logger.error("refresh failed: %s: %s", type(error).__name__, error)
        return None
    logger.info(
        "refresh: %d new, %d added", report.new_count, report.added_count
    )
    if report.added_count:
        services.reload()
    return report


def start_scheduler(
    services: state.Services,
    runner: RefreshRunner | None = None,
) -> scheduler.Scheduler | None:
    """Start the nightly refresh and backup when `scheduler.enabled` is on.

    Args:
        services: The shared services.
        runner: Runs the refresh; None runs `keel.refresh.run_refresh`.

    Returns:
        The started scheduler, or None when the scheduler is off (the
        default; the AWS host runs systemd timers instead).
    """
    jobs = scheduler.build_scheduler(
        services.settings, refresh=lambda: refresh_job(services, runner)
    )
    if jobs is not None:
        jobs.start()
    return jobs
