"""The bearer token check, the visitor key, and the Principal (S-06).

Every `/api/` route except health and ready needs `Authorization: Bearer
<token>`, unless `auth.public` is on. The token is compared in constant
time with the token hashes of the users file and with
`KEEL_API_TOKEN`, which stays the admin user `legacy`. A request that
passes gets a `Principal` that names the user and the role; the Principal
permits every ticker and source.

With `auth.public` on, a request without an `Authorization` header is a
visitor. A visitor may send their own Anthropic API key in the
`X-Anthropic-Api-Key` header: the service then answers with that key, and
the visitor's name is a short hash of the key, so their history stays
theirs. The key is never stored or logged. A visitor without a key reads
the answer cache only. A wrong bearer token is still HTTP 401, so a typo
never turns an admin into a visitor.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re

import fastapi
import pydantic

from keel import config
from keel import users

BEARER = "bearer"
DEFAULT_TENANT = "default"
KEY_HEADER = "x-anthropic-api-key"
ANONYMOUS = "visitor"
# Anthropic keys start with sk-ant- and hold URL-safe characters only.
KEY_PATTERN = re.compile(r"^sk-ant-[A-Za-z0-9_-]{16,250}$")
KEY_NAME_DIGITS = 16


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

    @property
    def is_visitor(self) -> bool:
        """True for a visitor of a public service (no token)."""
        return self.user.is_visitor


def unauthorized(message: str) -> fastapi.HTTPException:
    """Build the HTTP 401 of a missing or wrong token.

    Args:
        message: The reason, without the token.

    Returns:
        The exception with the error body.
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


def visitor_key(header: str | None) -> pydantic.SecretStr | None:
    """The visitor's Anthropic API key of the `X-Anthropic-Api-Key` header.

    Args:
        header: The header value, or None.

    Returns:
        The key, or None when the header is absent or blank.

    Raises:
        HTTPException: HTTP 400 `invalid_api_key` for a value that is not
            shaped like an Anthropic key; the body never echoes it.
    """
    if header is None or not header.strip():
        return None
    key = header.strip()
    if not KEY_PATTERN.match(key):
        raise fastapi.HTTPException(
            status_code=400,
            detail={
                "code": "invalid_api_key",
                "message": "the Anthropic API key must start with sk-ant-",
            },
        )
    return pydantic.SecretStr(key)


def visitor(key: pydantic.SecretStr | None) -> Principal:
    """The Principal of a visitor of a public service.

    Args:
        key: The visitor's key, or None.

    Returns:
        The visitor `visitor-<hash>` named by a hash of the key, or the
        shared visitor `visitor` without a key.
    """
    if key is None:
        return Principal(user=users.User(ANONYMOUS, users.VISITOR))
    digest = hashlib.sha256(key.get_secret_value().encode("utf-8"))
    name = f"{ANONYMOUS}-{digest.hexdigest()[:KEY_NAME_DIGITS]}"
    return Principal(user=users.User(name, users.VISITOR))


def authenticate(
    settings: config.Settings,
    header: str | None,
    directory: users.UserDirectory | None = None,
    key: pydantic.SecretStr | None = None,
) -> Principal:
    """Check the bearer token and build the Principal of the request.

    Args:
        settings: The loaded settings, with `api_token` and `auth`.
        header: The `Authorization` header value, or None.
        directory: The users, or None to read them from the settings.
        key: The visitor's Anthropic API key, or None; it names the
            visitor when `auth.public` is on and no token is sent.

    Returns:
        The Principal with the user of the token, or a visitor.

    Raises:
        HTTPException: HTTP 401 when the token is wrong, when it is absent
            and `auth.public` is off, or when neither `KEEL_API_TOKEN` nor
            a user is configured and `auth.public` is off.
    """
    if settings.auth.public and not (header or "").strip():
        return visitor(key)
    known = directory or directory_of(settings)
    if not known.configured:
        raise unauthorized("the service has no KEEL_API_TOKEN and no users")
    token = bearer_token(header)
    user = known.find(token) if token else None
    if user is None:
        raise unauthorized("a valid bearer token is required")
    return Principal(user=user)
