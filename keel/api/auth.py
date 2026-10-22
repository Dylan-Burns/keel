"""The bearer token check and the Principal (chapter 15, control S-06).

Every `/api/` route except health and ready needs `Authorization: Bearer
<token>`. The token is compared in constant time with `KEEL_API_TOKEN`.
A request that passes gets a `Principal`; in this release the Principal
permits every ticker and source, and phase 1 of the roadmap replaces the
shared token with OpenID Connect.
"""

from __future__ import annotations

import dataclasses
import hmac

import fastapi

from keel import config

BEARER = "bearer"
DEFAULT_TENANT = "default"


@dataclasses.dataclass(frozen=True)
class Principal:
    """Who asks, and what they may read (S-06 step 3).

    Attributes:
        tenant_id: The tenant.
        allowed_tickers: The tickers the caller may read; None permits all.
        allowed_sources: The sources the caller may read.
    """

    tenant_id: str = DEFAULT_TENANT
    allowed_tickers: frozenset[str] | None = None
    allowed_sources: frozenset[str] = frozenset({"edgar"})


def unauthorized(message: str) -> fastapi.HTTPException:
    """Build the HTTP 401 of a missing or wrong token.

    Args:
        message: The reason, without the token.

    Returns:
        The exception with the error body of chapter 14.3.
    """
    return fastapi.HTTPException(
        status_code=401,
        detail={"code": "unauthorized", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def token_matches(header: str | None, expected: str) -> bool:
    """Check an Authorization header against the token in constant time.

    Args:
        header: The `Authorization` header value, or None.
        expected: The configured token.

    Returns:
        True when the header is `Bearer <expected>`.
    """
    if not header or not expected:
        return False
    scheme, _, token = header.partition(" ")
    if scheme.lower() != BEARER:
        return False
    return hmac.compare_digest(
        token.strip().encode("utf-8"), expected.encode("utf-8")
    )


def authenticate(settings: config.Settings, header: str | None) -> Principal:
    """Check the bearer token and build the Principal of the request.

    Args:
        settings: The loaded settings, with `api_token`.
        header: The `Authorization` header value, or None.

    Returns:
        The Principal.

    Raises:
        HTTPException: HTTP 401 when the token is absent or wrong, or when
            `KEEL_API_TOKEN` is not set (no request passes without it).
    """
    if settings.api_token is None:
        raise unauthorized("the service has no KEEL_API_TOKEN set")
    if not token_matches(header, settings.api_token.get_secret_value()):
        raise unauthorized("a valid bearer token is required")
    return Principal()
