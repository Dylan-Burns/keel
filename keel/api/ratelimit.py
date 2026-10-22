"""The question rate limit per client (chapter 15, control S-05).

2 token buckets per client address: 10 questions per minute and 100 per
hour by default (`limits.rate_per_minute`, `limits.rate_per_hour`). A
question takes 1 token from each bucket. When either bucket is empty the
API answers HTTP 429 with `Retry-After`, the seconds until both buckets
hold a token again.
"""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
import math
import threading
import time

MINUTE = 60.0
HOUR = 3600.0
MAX_CLIENTS = 10_000  # idle clients are dropped past this many


@dataclasses.dataclass
class _Bucket:
    """The tokens of 1 bucket at 1 time; private and mutable."""

    tokens: float
    updated: float


@dataclasses.dataclass(frozen=True)
class Decision:
    """The result of 1 check.

    Attributes:
        allowed: True when the question may run.
        retry_after: Whole seconds to wait when not allowed, else 0.
    """

    allowed: bool
    retry_after: int = 0


class RateLimiter:
    """Token buckets per client.

    Args:
        per_minute: The questions per minute.
        per_hour: The questions per hour.
        clock: The monotonic clock in seconds (tests pass a fake one).
    """

    def __init__(
        self,
        per_minute: int,
        per_hour: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        per_minute, per_hour = max(1, per_minute), max(1, per_hour)
        # (capacity, refill per second) of each bucket.
        self.limits = (
            (float(per_minute), per_minute / MINUTE),
            (float(per_hour), per_hour / HOUR),
        )
        self.clock = clock
        self._clients: dict[str, list[_Bucket]] = {}
        self._lock = threading.Lock()

    def _buckets(self, client: str, now: float) -> list[_Bucket]:
        buckets = self._clients.get(client)
        if buckets is None:
            if len(self._clients) >= MAX_CLIENTS:
                self._drop_full(now)
            buckets = [_Bucket(cap, now) for cap, _ in self.limits]
            self._clients[client] = buckets
        for bucket, (capacity, rate) in zip(buckets, self.limits, strict=True):
            bucket.tokens = min(
                capacity, bucket.tokens + (now - bucket.updated) * rate
            )
            bucket.updated = now
        return buckets

    def _drop_full(self, now: float) -> None:
        """Forget the clients whose buckets have refilled."""
        for client in list(self._clients):
            buckets = self._clients[client]
            if all(
                b.tokens + (now - b.updated) * rate >= capacity
                for b, (capacity, rate) in zip(
                    buckets, self.limits, strict=True
                )
            ):
                del self._clients[client]

    def check(self, client: str) -> Decision:
        """Take 1 token from each bucket of a client when both have one.

        Args:
            client: The client address.

        Returns:
            The decision, with the wait when the client is over a limit.
        """
        with self._lock:
            now = self.clock()
            buckets = self._buckets(client, now)
            waits = [
                (1.0 - bucket.tokens) / rate
                for bucket, (_, rate) in zip(buckets, self.limits, strict=True)
                if bucket.tokens < 1.0
            ]
            if waits:
                return Decision(False, max(1, math.ceil(max(waits))))
            for bucket in buckets:
                bucket.tokens -= 1.0
            return Decision(True)
