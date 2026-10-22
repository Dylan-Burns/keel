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
import contextlib
import logging
import os
import pathlib

import fastapi
from fastapi import responses
from fastapi import staticfiles
from starlette import types
import uvicorn

from keel import config
from keel import doctor
from keel import errors
from keel.api import export_routes
from keel.api import routes
from keel.api import state
from keel.api import workspace

logger = logging.getLogger(__name__)

ResultStore = state.ResultStore
MissingKeyProvider = state.MissingKeyProvider
Services = state.Services
RESULT_TTL_SECONDS = state.RESULT_TTL_SECONDS
MAX_RESULTS = state.MAX_RESULTS

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
    app.include_router(export_routes.router)
    app.include_router(workspace.router)
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
        # The root handlers with the redacting formatter (S-01), and no
        # access log, which would hold each client address (S-14).
        log_config=None,
        access_log=False,
    )
    return 0
