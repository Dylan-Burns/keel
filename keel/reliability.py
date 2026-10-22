"""The reliability layer around the single call (chapter 16).

`CircuitBreaker` counts provider failures (16.3): 3 consecutive failures
within 60 seconds open it for 30 seconds; while it is open every question
goes to the fallback model (16.4); after 30 seconds 1 probe request goes to
the primary model, and its result closes or reopens the breaker.
`BudgetGuard` sums the cost of the day from the audit log and stops model
requests at `limits.daily_budget_usd` (16.10 step 5, control S-05 step 3).
`halve_context` drops the lowest-ranked chunks until the context fits half
its budget, for the 1 retry after a context overflow (16.6 step 3).
`check_index` adds the row count check of 16.7 step 2 to the checksums.
"""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
import datetime
import json
import logging
import pathlib
import sqlite3
import threading
import time
from typing import Any

from keel import context
from keel import errors
from keel import indexer
from keel.stores import chunk_store
from keel.stores import numpy_dense

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3
FAILURE_WINDOW_SECONDS = 60.0
OPEN_SECONDS = 30.0
CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


@dataclasses.dataclass(frozen=True)
class BreakerState:
    """A snapshot of the breaker for `/api/ready` (16.3 step 4).

    Attributes:
        state: `closed`, `open`, or `half_open`.
        failures: The consecutive failures in the window.
        retry_in: Seconds until the probe, while open; else 0.
    """

    state: str
    failures: int
    retry_in: float

    def as_dict(self) -> dict[str, Any]:
        """The JSON form.

        Returns:
            The fields as a dictionary.
        """
        return dataclasses.asdict(self)


class CircuitBreaker:
    """The circuit breaker of the primary model (chapter 16.3).

    A failure is a request that failed for availability (HTTP 429, 529,
    5xx, a timeout, a lost connection); a rejected request or a context
    overflow says nothing about the provider and is not counted. The class
    is thread-safe; concurrent questions share 1 breaker.

    Args:
        threshold: The consecutive failures that open the breaker.
        window: The seconds in which the failures must fall.
        open_seconds: The seconds the breaker stays open before the probe.
        clock: The monotonic clock (tests pass a fake one).
    """

    def __init__(
        self,
        threshold: int = FAILURE_THRESHOLD,
        window: float = FAILURE_WINDOW_SECONDS,
        open_seconds: float = OPEN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.window = window
        self.open_seconds = open_seconds
        self.clock = clock
        self._failures: list[float] = []
        self._opened_at: float | None = None
        self._probing = False
        self._lock = threading.Lock()

    def _state(self, now: float) -> str:
        if self._opened_at is None:
            return CLOSED
        if self._probing or now - self._opened_at >= self.open_seconds:
            return HALF_OPEN
        return OPEN

    def allow(self) -> bool:
        """Ask whether 1 request may go to the primary model.

        Returns:
            True while closed; once after the open period (the probe);
            False while open or while the probe runs.
        """
        with self._lock:
            now = self.clock()
            state = self._state(now)
            if state == CLOSED:
                return True
            if state == HALF_OPEN and not self._probing:
                self._probing = True
                logger.info("circuit breaker half open: 1 probe request")
                return True
            return False

    def record_success(self) -> None:
        """Close the breaker after a request that succeeded."""
        with self._lock:
            if self._opened_at is not None:
                logger.info("circuit breaker closed")
            self._failures.clear()
            self._opened_at = None
            self._probing = False

    def release(self) -> None:
        """End a probe that proved nothing (a rejected or cut request).

        The breaker stays half open, so the next request is the probe.
        """
        with self._lock:
            self._probing = False

    def record_failure(self) -> None:
        """Count 1 failure; open the breaker at the threshold."""
        with self._lock:
            now = self.clock()
            if self._probing or self._opened_at is not None:
                # The probe failed, or a request that started before the
                # breaker opened: another 30 seconds open.
                self._opened_at = now
                self._probing = False
                logger.warning(
                    "circuit breaker open for %.0f s", self.open_seconds
                )
                return
            self._failures = [
                t for t in self._failures if now - t < self.window
            ] + [now]
            if len(self._failures) >= self.threshold:
                self._opened_at = now
                logger.warning(
                    "circuit breaker open after %d failures in %.0f s",
                    len(self._failures),
                    self.window,
                )

    def snapshot(self) -> BreakerState:
        """Read the state without changing it.

        Returns:
            The state, the failure count, and the seconds to the probe.
        """
        with self._lock:
            now = self.clock()
            state = self._state(now)
            retry_in = 0.0
            if state == OPEN and self._opened_at is not None:
                retry_in = round(self.open_seconds - (now - self._opened_at), 1)
            recent = [t for t in self._failures if now - t < self.window]
            return BreakerState(state, len(recent), retry_in)


def counts_as_failure(error: errors.ProviderError) -> bool:
    """Tell whether a provider error is an availability failure.

    Args:
        error: The error.

    Returns:
        True for the retryable errors (rate limit, overload, 5xx, timeout,
        connection); False for a rejected request or a context overflow.
    """
    return error.retryable


def _today() -> datetime.date:
    return datetime.datetime.now(tz=datetime.UTC).date()


class BudgetGuard:
    """The daily provider budget (chapter 16.10 step 5, S-05 step 3).

    The spend of the day is the sum of `cost_usd` over the audit records
    with a timestamp of the current UTC day. The file is read again only
    when its size or modification time changed.

    Args:
        audit_path: The audit log (`<logs.dir>/audit.jsonl`).
        limit_usd: The daily budget; 0 stops every model request.
        today: The current UTC date (tests pass a fixed one).
    """

    def __init__(
        self,
        audit_path: pathlib.Path,
        limit_usd: float,
        today: Callable[[], datetime.date] = _today,
    ) -> None:
        self.audit_path = audit_path
        self.limit_usd = limit_usd
        self.today = today
        self._seen: tuple[str, int, int] | None = None
        self._spent = 0.0
        self._lock = threading.Lock()

    def spent(self) -> float:
        """The spend of the current UTC day.

        Returns:
            The sum of `cost_usd` in USD, rounded to 6 decimals.
        """
        day = self.today().isoformat()
        try:
            stat = self.audit_path.stat()
        except OSError:
            return 0.0
        mark = (day, stat.st_size, stat.st_mtime_ns)
        with self._lock:
            if mark != self._seen:
                self._spent = _sum_day(self.audit_path, day)
                self._seen = mark
            return self._spent

    def exhausted(self) -> bool:
        """Tell whether the spend reached the budget.

        Returns:
            True when no model request may go out today.
        """
        spent = self.spent()
        if spent >= self.limit_usd:
            logger.warning(
                "daily budget reached: $%.4f of $%.2f", spent, self.limit_usd
            )
            return True
        return False


def _sum_day(path: pathlib.Path, day: str) -> float:
    total = 0.0
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                stamp = str(record.get("timestamp", ""))
                cost = record.get("cost_usd")
                if stamp.startswith(day) and isinstance(cost, int | float):
                    total += float(cost)
    except OSError as error:
        logger.warning("audit log unreadable for the budget: %s", error)
    return round(total, 6)


def halve_context(built: context.Context) -> context.Context:
    """Halve the context budget and drop chunks from the lowest rank.

    The new budget is half the smaller of the budget and the estimate of
    the context, so a context that filled less than half its budget still
    shrinks (chapter 16.6 step 3). The chunks that stay keep their context
    order. At least 1 chunk stays.

    Args:
        built: The context of the request that overflowed.

    Returns:
        The context within half the token budget.
    """
    limit = max(1, min(built.budget.max_tokens, built.token_estimate) // 2)
    ranked = sorted(built.chunks, key=lambda c: c.candidate.rank_key)
    kept: set[str] = set()
    used = 0
    for chunk in ranked:
        if kept and used + chunk.estimated_tokens > limit:
            continue
        kept.add(chunk.candidate.chunk_id)
        used += chunk.estimated_tokens
    chunks = tuple(c for c in built.chunks if c.candidate.chunk_id in kept)
    return dataclasses.replace(
        built,
        chunks=chunks,
        token_estimate=used,
        dropped=built.dropped + len(built.chunks) - len(chunks),
        budget=dataclasses.replace(built.budget, max_tokens=limit),
    )


def check_index(build_dir: pathlib.Path) -> indexer.Manifest:
    """Check an index build before it serves (chapter 16.7 steps 1, 2).

    Args:
        build_dir: The build directory.

    Returns:
        The manifest when the checksums and the row counts match.

    Raises:
        IndexMissingError: The manifest or an index file is absent.
        IndexCorruptError: A checksum or the row counts do not match.
    """
    manifest = indexer.verify(build_dir)
    store = build_dir / chunk_store.FILE_NAME
    vectors = build_dir / numpy_dense.FILE_NAME
    if not vectors.is_file():
        return manifest  # a lexical-only build has no vectors to count
    try:
        conn = chunk_store.open_read_only(store)
        try:
            chunks = int(
                conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            )
        finally:
            conn.close()
        rows = int(numpy_dense.load(vectors).shape[0])
    except (sqlite3.Error, OSError, ValueError, errors.KeelError) as error:
        raise errors.IndexCorruptError(
            f"index in {build_dir} unreadable: {error}"
        ) from error
    if chunks != rows:
        raise errors.IndexCorruptError(
            f"{chunks} chunks but {rows} vectors in {build_dir}"
        )
    return manifest
