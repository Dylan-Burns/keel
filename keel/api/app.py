"""The FastAPI application: the services, the front-end, and `keel serve`.

`create_app` builds the app around 1 `Services` object. At startup the
lifespan opens the index, loads the embedding model and the reranker once,
builds the provider, and checks the index files and the corpus checksum;
a missing index or provider key does not stop the service (E-F-01,
E-F-07), `/api/ready` reports it. The `/api` routes are registered first;
then the hashed assets of `web/dist` and a fallback that returns
`index.html` for every other path, so the client routes work on a reload.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Callable
import contextlib
import dataclasses
import logging
import os
import pathlib
import threading
import time
from typing import Any

import fastapi
from fastapi import responses
from fastapi import staticfiles
from starlette import types
import uvicorn

from keel import answer
from keel import config
from keel import doctor
from keel import errors
from keel import indexer
from keel import prompt
from keel.api import ratelimit
from keel.api import routes
from keel.providers import base

logger = logging.getLogger(__name__)

RESULT_TTL_SECONDS = 600.0  # 10 minutes (chapter 14.1)
MAX_RESULTS = 1000
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)
SECURITY_HEADERS = (
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode("ascii")),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)


@dataclasses.dataclass(frozen=True)
class _Entry:
    """1 entry of the result store; None while the answer runs."""

    expires: float
    record: dict[str, Any] | None


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

    def start(self, request_id: str) -> bool:
        """Claim a request ID for a new answer.

        Args:
            request_id: The Idempotency-Key or the server ID.

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
            self._entries[request_id] = _Entry(self.clock() + self.ttl, None)
            return True

    def finish(self, request_id: str, record: dict[str, Any]) -> None:
        """Store the final answer of a request.

        Args:
            request_id: The request ID.
            record: The answer response of chapter 14.2.
        """
        with self._lock:
            self._entries[request_id] = _Entry(self.clock() + self.ttl, record)

    def drop(self, request_id: str) -> None:
        """Forget a request that ended without an answer.

        Args:
            request_id: The request ID.
        """
        with self._lock:
            self._entries.pop(request_id, None)

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


class Services:  # pylint: disable=too-many-instance-attributes
    """What the routes share: the pipeline, the stores, and the checks.

    Args:
        settings: The loaded settings.
        answerer: An opened pipeline (tests), or None to open the index at
            startup.
        clock: The monotonic clock of the stores and the rate limiter.
    """

    def __init__(
        self,
        settings: config.Settings,
        answerer: answer.Answerer | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.answerer = answerer
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
        settings = self.settings
        provider: base.LLMProvider | None = None
        if not self.provider_key:
            logger.warning("ANTHROPIC_API_KEY is not set: degraded mode only")
            provider = MissingKeyProvider(settings.llm.model)
        try:
            self.answerer = answer.Answerer.open(settings, provider=provider)
        except (errors.IndexMissingError, errors.IndexCorruptError) as error:
            self.index_error = str(error)
            logger.warning("no index loaded: %s", error)
            return
        build = indexer.current_build(settings.index.dir)
        if build is None:  # pragma: no cover  # removed after the open
            return
        try:
            self.manifest = indexer.verify(build)
            self.index_verified = True
        except (errors.IndexMissingError, errors.IndexCorruptError) as error:
            self.index_error = str(error)
            logger.error("index check failed: %s", error)
        self.corpus_match, self.corpus_note = routes.corpus_check(
            settings.corpus.dir, self.manifest
        )

    def keep(self, task: asyncio.Task[Any]) -> None:
        """Hold a pipeline task until it ends, so it outlives its client.

        Args:
            task: The task.
        """
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


class SecurityHeaders:
    """ASGI middleware that adds the CSP of control S-03 to each response.

    It wraps the send call only, so a streamed response is never buffered.
    No CORS header is set (control S-15).

    Args:
        app: The wrapped ASGI app.
    """

    def __init__(self, app: types.ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: types.Scope, receive: types.Receive, send: types.Send
    ) -> None:
        """Run the app and add the headers to the response start.

        Args:
            scope: The ASGI scope.
            receive: The receive channel.
            send: The send channel.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: types.Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _frontend(app: fastapi.FastAPI, dist: pathlib.Path) -> None:
    """Serve `web/dist`: the hashed assets and the index.html fallback."""
    assets = dist / "assets"
    if assets.is_dir():
        app.mount(
            "/assets", staticfiles.StaticFiles(directory=assets), name="assets"
        )
    root = dist.resolve()

    @app.api_route(
        "/{path:path}", methods=["GET", "HEAD"], include_in_schema=False
    )
    async def fallback(path: str) -> fastapi.Response:
        if path == "api" or path.startswith("api/"):
            return responses.JSONResponse(
                {"code": "not_found", "message": f"no route /{path}"},
                status_code=404,
            )
        index = root / "index.html"
        if not index.is_file():
            return responses.JSONResponse(
                {
                    "code": "frontend_not_built",
                    "message": "run npm run build --prefix web",
                },
                status_code=404,
            )
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return responses.FileResponse(candidate)
        return responses.FileResponse(
            index, headers={"Cache-Control": "no-cache"}
        )


def create_app(services: Services) -> fastapi.FastAPI:
    """Build the application.

    Args:
        services: The shared services; `load` runs at startup.

    Returns:
        The FastAPI app with the API routes, then the front-end.
    """

    @contextlib.asynccontextmanager
    async def lifespan(app: fastapi.FastAPI) -> AsyncIterator[None]:
        del app
        await asyncio.to_thread(services.load)
        yield
        pending = list(services.tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    app = fastapi.FastAPI(
        title="Keel",
        version=routes.VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.services = services
    app.include_router(routes.router)
    _frontend(app, services.settings.server.web_dist)
    app.add_middleware(SecurityHeaders)
    return app


def pick_port(host: str, port: int) -> int:
    """Find the first free port from `port` on (E-F-08).

    Args:
        host: The bind address.
        port: The configured port.

    Returns:
        The first free port of `port` to `port + 10`.

    Raises:
        ConfigError: Every port of the range is in use.
    """
    for candidate in range(port, port + doctor.PORT_SEARCH_SPAN + 1):
        if doctor.port_free(host, candidate):
            return candidate
    raise errors.ConfigError(
        f"{host}:{port} to {port + doctor.PORT_SEARCH_SPAN} are all in use"
    )


def serve(
    settings: config.Settings,
    host: str | None = None,
    port: int | None = None,
) -> int:
    """Run `keel serve`: the API and the front-end on 1 origin.

    Args:
        settings: The loaded settings.
        host: The bind address, or None for `server.host`.
        port: The port, or None for `server.port`; a busy port moves to the
            next free one up to 10 above it.

    Returns:
        0 after the server stops.

    Raises:
        ConfigError: No free port in the range.
    """
    # No request leaves for the Hugging Face Hub at serve time.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    bind_host = host or settings.server.host
    wanted = port or settings.server.port
    chosen = pick_port(bind_host, wanted)
    if chosen != wanted:
        logger.warning("port %d is in use; serving on %d", wanted, chosen)
    logger.info("Keel serves at http://%s:%d", bind_host, chosen)
    uvicorn.run(
        create_app(Services(settings)),
        host=bind_host,
        port=chosen,
        log_level="info",
        proxy_headers=False,
    )
    return 0
