"""The bearer token check and the Principal (chapter 15, control S-06).

Every `/api/` route except health and ready needs `Authorization: Bearer
<token>`. The token is compared in constant time with the token hashes of
the users file (chapter 27.2) and with `KEEL_API_TOKEN`, which stays the
admin user `legacy`. A request that passes gets a `Principal` that names
the user and the role; the Principal permits every ticker and source, and
phase 1 of the roadmap replaces the tokens with OpenID Connect.
"""

from __future__ import annotations

import dataclasses

import fastapi

from keel import config
from keel import users

BEARER = "bearer"
DEFAULT_TENANT = "default"


@dataclasses.dataclass(frozen=True)
class Principal:
    """Who asks, and what they may read (S-06 step 3).

    Attributes:
        tenant_id: The tenant.
        allowed_tickers: The tickers the caller may read; None permits all.
        allowed_sources: The sources the caller may read.
        user: The user of the token; `legacy` for `KEEL_API_TOKEN`.
    """

    tenant_id: str = DEFAULT_TENANT
    allowed_tickers: frozenset[str] | None = None
    allowed_sources: frozenset[str] = frozenset({"edgar"})
    # No default: a Principal built without a user must not become admin.
    user: users.User = dataclasses.field(kw_only=True)

    @property
    def is_admin(self) -> bool:
        """True when the user has the admin role."""
        return self.user.is_admin


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


def bearer_token(header: str | None) -> str | None:
    """The token of a `Bearer` Authorization header.

    Args:
        header: The `Authorization` header value, or None.

    Returns:
        The token, or None for another scheme or an empty value.
    """
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != BEARER or not token.strip():
        return None
    return token.strip()


def directory_of(settings: config.Settings) -> users.UserDirectory:
    """The user directory of the settings.

    Args:
        settings: The loaded settings.

    Returns:
        The users file of `auth.users_file` plus `KEEL_API_TOKEN`.
    """
    legacy = (
        settings.api_token.get_secret_value() if settings.api_token else None
    )
    return users.UserDirectory(settings.auth.users_file, legacy)


def authenticate(
    settings: config.Settings,
    header: str | None,
    directory: users.UserDirectory | None = None,
) -> Principal:
    """Check the bearer token and build the Principal of the request.

    Args:
        settings: The loaded settings, with `api_token` and `auth`.
        header: The `Authorization` header value, or None.
        directory: The users, or None to read them from the settings.

    Returns:
        The Principal with the user of the token.

    Raises:
        HTTPException: HTTP 401 when the token is absent or wrong, or when
            neither `KEEL_API_TOKEN` nor a user is configured (no request
            passes without one).
    """
    known = directory or directory_of(settings)
    if not known.configured:
        raise unauthorized("the service has no KEEL_API_TOKEN and no users")
    token = bearer_token(header)
    user = known.find(token) if token else None
    if user is None:
        raise unauthorized("a valid bearer token is required")
    return Principal(user=user)
