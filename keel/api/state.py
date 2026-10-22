"""Shared state of the API: the result store and the services object.

The routes and the app both use these types; keeping them here avoids an
import cycle between `keel.api.app` and `keel.api.routes`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Callable
import dataclasses
import logging
import pathlib
import threading
import time
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol

from keel import answer
from keel import bootstrap
from keel import config
from keel import errors
from keel import indexer
from keel import prompt
from keel import reliability
from keel.api import auth
from keel.api import ratelimit
from keel.providers import base
from keel.stores import admin_store

if TYPE_CHECKING:
    from keel import scheduler

logger = logging.getLogger(__name__)

RESULT_TTL_SECONDS = 600.0  # 10 minutes (chapter 14.1)
MAX_RESULTS = 1000


@dataclasses.dataclass(frozen=True)
class _Entry:
    """1 entry of the result store; None while the answer runs."""

    expires: float
    record: dict[str, Any] | None
    owner: str | None = None


class ResultStore:
    """The answers by request ID for 10 minutes (the idempotency store).

    Args:
        ttl: The seconds an entry lives.
        clock: The monotonic clock (tests pass a fake one).
        max_entries: The entries kept; the oldest go first.
    """

    def __init__(
        self,
        ttl: float = RESULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = MAX_RESULTS,
    ) -> None:
        self.ttl = ttl
        self.clock = clock
        self.max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def _live(self, request_id: str) -> _Entry | None:
        now = self.clock()
        for key in [k for k, e in self._entries.items() if e.expires <= now]:
            del self._entries[key]
        return self._entries.get(request_id)

    def start(self, request_id: str, owner: str | None = None) -> bool:
        """Claim a request ID for a new answer.

        Args:
            request_id: The Idempotency-Key or the server ID.
            owner: The user who asks; only they replay the key.

        Returns:
            False when the ID already has an answer or 1 in progress.
        """
        with self._lock:
            if self._live(request_id) is not None:
                return False
            if len(self._entries) >= self.max_entries:
                # Evict finished answers first, oldest first.
                order = sorted(
                    self._entries,
                    key=lambda k: self._entries[k].record is None,
                )
                for key in order[: len(self._entries) - self.max_entries + 1]:
                    del self._entries[key]
            self._entries[request_id] = _Entry(
                self.clock() + self.ttl, None, owner
            )
            return True

    def finish(self, request_id: str, record: dict[str, Any]) -> None:
        """Store the final answer of a request.

        Args:
            request_id: The request ID.
            record: The answer response of chapter 14.2.
        """
        with self._lock:
            current = self._entries.get(request_id)
            owner = current.owner if current else None
            self._entries[request_id] = _Entry(
                self.clock() + self.ttl, record, owner
            )

    def drop(self, request_id: str) -> None:
        """Forget a request that ended without an answer.

        Args:
            request_id: The request ID.
        """
        with self._lock:
            self._entries.pop(request_id, None)

    def finished_ids(self) -> frozenset[str]:
        """The request IDs with a stored answer.

        Returns:
            The IDs of the finished answers that have not expired.
        """
        with self._lock:
            now = self.clock()
            return frozenset(
                key
                for key, entry in self._entries.items()
                if entry.record is not None and entry.expires > now
            )

    def owner(self, request_id: str) -> str | None:
        """The user who claimed a request ID.

        Args:
            request_id: The request ID.

        Returns:
            The owner, or None for an unknown ID or an ID without one.
        """
        with self._lock:
            entry = self._live(request_id)
            return entry.owner if entry else None

    def state(self, request_id: str) -> tuple[bool, dict[str, Any] | None]:
        """Look up a request ID.

        Args:
            request_id: The request ID.

        Returns:
            (known, record): known is True while the ID is stored; record
            is None while the answer runs.
        """
        with self._lock:
            entry = self._live(request_id)
            if entry is None:
                return False, None
            return True, entry.record


class MissingKeyProvider:
    """The provider when `ANTHROPIC_API_KEY` is absent (E-F-07).

    Every request fails before any content with a non-retryable error, so
    the question gets the degraded mode and the answer cache (chapter 16).

    Args:
        model: The configured model, reported in the events.
    """

    name = "anthropic"

    def __init__(self, model: str) -> None:
        self.model = model

    async def answer(
        self, bundle: prompt.PromptBundle
    ) -> AsyncIterator[base.ProviderEvent]:
        """Fail at once: there is no key to send.

        Args:
            bundle: The prompt, unused.

        Yields:
            Nothing.

        Raises:
            ProviderRequestError: Always.
        """
        del bundle
        self.refuse()
        yield base.Finished(None, tool_called=False)  # pragma: no cover

    def refuse(self) -> None:
        """Raise the missing key error.

        Raises:
            ProviderRequestError: Always.
        """
        raise errors.ProviderRequestError("ANTHROPIC_API_KEY is not set")


class JobSlot(Protocol):  # pylint: disable=too-few-public-methods
    """The part of the admin job runner (`keel.api.jobs`) others read."""

    def holder(self) -> admin_store.JobRecord | None:
        """The heavy job that is queued or running, if any."""


class Services:  # pylint: disable=too-many-instance-attributes
    """What the routes share: the pipeline, the stores, and the checks.

    Args:
        settings: The loaded settings.
        answerer: An opened pipeline (tests), or None to open the index at
            startup.
        clock: The monotonic clock of the stores and the rate limiter.
        bootstrap_first: Run the first-start bootstrap of chapter 29.9 in
            a background thread and open the index when it is ready
            (`keel serve --bootstrap`), instead of opening it at startup.
    """

    def __init__(
        self,
        settings: config.Settings,
        answerer: answer.Answerer | None = None,
        clock: Callable[[], float] = time.monotonic,
        *,
        bootstrap_first: bool = False,
    ) -> None:
        self.settings = settings
        self.answerer = answerer
        self.bootstrap = bootstrap.BootstrapState() if bootstrap_first else None
        self._reload_lock = threading.Lock()
        self.loaded = answerer is not None
        self.index_error: str | None = None
        self.index_verified = answerer is not None
        self.manifest: indexer.Manifest | None = None
        self.corpus_match: bool | None = None
        self.corpus_note: str | None = None
        self.provider_key = settings.llm.provider == "mock" or (
            settings.anthropic_api_key is not None
        )
        self.results = ResultStore(clock=clock)
        self.limiter = ratelimit.RateLimiter(
            settings.limits.rate_per_minute,
            settings.limits.rate_per_hour,
            clock=clock,
        )
        self.tasks: set[asyncio.Task[Any]] = set()
        self.users = auth.directory_of(settings)
        # Held by a heavy admin job and by the nightly refresh and backup,
        # so only 1 of them writes the index or the backups at a time.
        self.maintenance = threading.Lock()
        self.jobs: JobSlot | None = None
        self.scheduler: scheduler.Scheduler | None = None

    @property
    def is_mock(self) -> bool:
        """True when `llm.provider` is `mock`: the fault header applies."""
        return self.settings.llm.provider == "mock"

    def load(self) -> None:
        """Open the index, load the models, and run the startup checks.

        A missing index or key is recorded, never raised, so the service
        starts and `/api/ready` reports it.
        """
        if self.loaded:
            return
        self.loaded = True
        self._open()

    def reload(self) -> None:
        """Open the current build again and swap it in.

        The bootstrap thread calls it when the first build is ready, and
        the nightly refresh after it published a new build. A request in
        flight keeps the pipeline it started with. When the new build
        cannot be opened, the old pipeline stays and the error is logged.
        """
        with self._reload_lock:
            self.loaded = True
            self._open()

    def _open(self) -> None:
        """Open the pipeline and check the build; assign only on success."""
        settings = self.settings
        provider: base.LLMProvider | None = None
        if not self.provider_key:
            logger.warning("ANTHROPIC_API_KEY is not set: degraded mode only")
            provider = MissingKeyProvider(settings.llm.model)
        previous = self.answerer
        try:
            opened = answer.Answerer.open(
                settings, provider=provider, load_models=previous is None
            )
        except (errors.IndexMissingError, errors.IndexCorruptError) as error:
            if self.answerer is None:
                self.index_error = str(error)
            logger.warning("no index loaded: %s", error)
            return
        build = indexer.current_build(settings.index.dir)
        if build is None:  # pragma: no cover  # removed after the open
            return
        manifest: indexer.Manifest | None = None
        try:
            manifest = reliability.check_index(build)
        except (errors.IndexMissingError, errors.IndexCorruptError) as error:
            logger.error("index check failed: %s", error)
            if previous is not None:
                # A reload keeps the verified build it serves.
                return
            self.index_error = str(error)
        else:
            self.index_error = None
        if previous is not None:
            # A reload reuses the loaded models, so the memory does not
            # double, and keeps the breaker, so an open breaker stays open.
            opened.retriever.embedder = previous.retriever.embedder
            opened.retriever.reranker = previous.retriever.reranker
            opened.breaker = previous.breaker
            # The shared models keep 1 lock across the old and new builds.
            opened.retrieval_lock = previous.retrieval_lock
        self.manifest = manifest
        self.index_verified = manifest is not None
        self.answerer = opened
        self.corpus_match, self.corpus_note = corpus_check(
            settings.corpus.dir, manifest
        )
        logger.info("index %s loaded from %s", opened.index_version, build)

    def keep(self, task: asyncio.Task[Any]) -> None:
        """Hold a pipeline task until it ends, so it outlives its client.

        Args:
            task: The task.
        """
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


def corpus_check(
    corpus_dir: pathlib.Path,
    manifest: indexer.Manifest | None,
) -> tuple[bool | None, str | None]:
    """Compare the corpus on disk with the corpus of the index (E-F-02).

    Args:
        corpus_dir: The corpus directory (`corpus.dir`).
        manifest: The manifest of the current build, or None.

    Returns:
        (match, note): match is None without a manifest; True with a note
        when the corpus directory is absent, because nothing changed that
        the service can see.
    """
    if manifest is None:
        return None, "the index has no valid manifest"
    files = sorted(corpus_dir.glob("*.txt")) if corpus_dir.is_dir() else []
    if not files:
        return True, f"no corpus at {corpus_dir}; the checksum was not compared"
    digest = indexer.corpus_sha256([indexer.file_sha256(f) for f in files])
    return digest == manifest.corpus_sha256, None
