"""The pilot users and their tokens (chapter 27.2, `config/users.yaml`).

Each user has a name, a role (analyst, partner, or admin), and the sha256
of a token. The file never holds a token: `keel users add NAME --role R`
draws a random token of 256 bits, prints it once, and stores its hash.
A token of 256 random bits needs no slow key derivation; the hash only
keeps the file from being a list of working tokens. The single
`KEEL_API_TOKEN` keeps working as the user `legacy` with the admin role,
so CI and the demo need no users file. OpenID Connect replaces this file
in a paid engagement (chapter 27.2).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import logging
import os
import pathlib
import re
import secrets
import tempfile
import threading
from typing import Literal

import pydantic
import yaml

from keel import errors

logger = logging.getLogger(__name__)

Role = Literal["analyst", "partner", "admin"]
ROLES: tuple[Role, ...] = ("analyst", "partner", "admin")
ADMIN: Role = "admin"
LEGACY_USER = "legacy"
HASH_PREFIX = "sha256:"
TOKEN_BYTES = 32  # 256 random bits
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FILE_MODE = 0o600


class UserEntry(pydantic.BaseModel):
    """1 user of the users file.

    Attributes:
        name: The user name: lowercase letters, digits, dot, dash, and
            underscore, at most 64 characters.
        role: analyst, partner, or admin.
        token_hash: `sha256:` and the hex sha256 of the token.
    """

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    name: str = pydantic.Field(pattern=NAME_PATTERN.pattern)
    role: Role
    token_hash: str = pydantic.Field(pattern=r"^sha256:[0-9a-f]{64}$")


class UsersFile(pydantic.BaseModel):
    """The whole users file.

    Attributes:
        users: The users, in the order they were added.
    """

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    users: list[UserEntry] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _unique(self) -> UsersFile:
        names = [u.name for u in self.users]
        if len(names) != len(set(names)):
            raise ValueError("a user name appears twice")
        if LEGACY_USER in names:
            raise ValueError(f"the name {LEGACY_USER} is reserved")
        return self


@dataclasses.dataclass(frozen=True)
class User:
    """A user after authentication.

    Attributes:
        name: The user name.
        role: The role.
    """

    name: str
    role: Role

    @property
    def is_admin(self) -> bool:
        """True for the admin role."""
        return self.role == ADMIN


LEGACY = User(LEGACY_USER, ADMIN)


def hash_token(token: str) -> str:
    """Hash a token for the users file.

    Args:
        token: The token.

    Returns:
        `sha256:` and the hex digest.
    """
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return HASH_PREFIX + digest


def new_token() -> str:
    """Draw a new random token.

    Returns:
        A URL-safe token of 256 random bits.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def load_file(path: pathlib.Path) -> UsersFile:
    """Read the users file; an absent file has no users.

    Args:
        path: The users file.

    Returns:
        The parsed file.

    Raises:
        ConfigError: The file is unreadable or fails validation.
    """
    if not path.is_file():
        return UsersFile()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return UsersFile.model_validate(data)
    except (OSError, yaml.YAMLError, pydantic.ValidationError) as error:
        raise errors.ConfigError(
            f"the users file {path}: {describe_error(error)}"
        ) from None


def describe_error(error: Exception) -> str:
    """Describe a users file error without any value from the file.

    A pydantic or YAML message quotes the input, and a token pasted into
    the file by mistake would reach the log; only the locations and the
    error types are kept.

    Args:
        error: The read, parse, or validation error.

    Returns:
        The description.
    """
    if isinstance(error, pydantic.ValidationError):
        # A value_error message is written by this module, never input.
        parts = []
        for item in error.errors():
            where = ".".join(str(part) for part in item["loc"]) or "file"
            kind = item["type"]
            detail = item["msg"] if kind == "value_error" else kind
            parts.append(f"{where}: {detail}")
        return "invalid entries (" + "; ".join(parts) + ")"
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark:
        mark = error.problem_mark
        return (
            f"not valid YAML at line {mark.line + 1}, column {mark.column + 1}"
        )
    if isinstance(error, yaml.YAMLError):
        return "not valid YAML"
    return type(error).__name__


def save_file(path: pathlib.Path, users_file: UsersFile) -> None:
    """Write the users file atomically, readable by the owner only.

    Args:
        path: The users file.
        users_file: The content.

    Raises:
        ConfigError: The file could not be written.
    """
    text = (
        "# Keel pilot users (chapter 27.2). Token hashes only; "
        "`keel users add` writes this file.\n"
        + yaml.safe_dump(users_file.model_dump(mode="json"), sort_keys=False)
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=".tmp-", suffix=".yaml"
        )
        os.fchmod(handle, FILE_MODE)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(temporary, path)
        except OSError:
            pathlib.Path(temporary).unlink(missing_ok=True)
            raise
    except OSError as error:
        raise errors.ConfigError(f"cannot write {path}: {error}") from error


def add_user(path: pathlib.Path, name: str, role: str) -> str:
    """Add a user with a new token and return the token.

    The file is read, changed, and replaced without a lock: run 1 `keel
    users` command at a time.

    Args:
        path: The users file.
        name: The user name.
        role: analyst, partner, or admin.

    Returns:
        The new token; the file keeps only its hash.

    Raises:
        ConfigError: The name or role is invalid, the name exists, or the
            file cannot be read or written.
    """
    if role not in ROLES:
        choices = ", ".join(ROLES)
        raise errors.ConfigError(f"the role must be one of {choices}")
    if not NAME_PATTERN.match(name) or name == LEGACY_USER:
        raise errors.ConfigError(
            f"the name must match {NAME_PATTERN.pattern} and not be "
            f"{LEGACY_USER}"
        )
    current = load_file(path)
    if any(u.name == name for u in current.users):
        raise errors.ConfigError(f"the user {name} exists")
    token = new_token()
    entry = UserEntry(name=name, role=role, token_hash=hash_token(token))
    save_file(path, UsersFile(users=[*current.users, entry]))
    return token


def remove_user(path: pathlib.Path, name: str) -> None:
    """Remove a user, which revokes their token at the next request.

    Like `add_user`, run 1 `keel users` command at a time (no lock).

    Args:
        path: The users file.
        name: The user name.

    Raises:
        ConfigError: The user does not exist, or the file cannot be read
            or written.
    """
    current = load_file(path)
    kept = [u for u in current.users if u.name != name]
    if len(kept) == len(current.users):
        raise errors.ConfigError(f"no user {name} in {path}")
    save_file(path, UsersFile(users=kept))


class UserDirectory:
    """The users of the file plus the legacy token, read on change.

    The file is read again when its modification time in nanoseconds, its
    size, or its inode changes, so `keel users add` and `keel users
    remove` take effect without a restart. A file that fails to read or
    validate fails closed: no user of the file passes (the legacy token
    still does), and the next request reads the file again, so a fixed
    file restores access and a bad edit never keeps a removed user in.

    Args:
        path: The users file.
        legacy_token: The `KEEL_API_TOKEN` value, or None.
    """

    def __init__(self, path: pathlib.Path, legacy_token: str | None) -> None:
        self.path = path
        self.legacy_token = legacy_token or None
        self._lock = threading.Lock()
        self._stamp: tuple[int, int, int] | None = None
        self._loaded = False
        self._entries: tuple[UserEntry, ...] = ()

    def _refresh(self) -> tuple[UserEntry, ...]:
        stamp: tuple[int, int, int] | None = None
        try:
            info = self.path.stat()
            stamp = (info.st_mtime_ns, info.st_size, info.st_ino)
        except FileNotFoundError:
            stamp = None
        except OSError as error:
            logger.error("users file unreadable, no user passes: %s", error)
            with self._lock:
                self._entries, self._loaded = (), False
            return ()
        with self._lock:
            if self._loaded and stamp == self._stamp:
                return self._entries
            try:
                entries = tuple(load_file(self.path).users)
            except errors.ConfigError as error:
                # Fail closed and keep no stamp, so the next request retries.
                logger.error("users file invalid, no user passes: %s", error)
                self._entries, self._loaded = (), False
                return ()
            self._entries, self._stamp, self._loaded = entries, stamp, True
            return entries

    @property
    def configured(self) -> bool:
        """True when any token can pass: the legacy token or a user."""
        return self.legacy_token is not None or bool(self._refresh())

    def find(self, token: str) -> User | None:
        """Find the user of a token in constant time per user.

        Every stored hash is compared, so the time does not tell which
        user matched or how far a guess got.

        Args:
            token: The presented token.

        Returns:
            The user, or None when no token matches.
        """
        if not token:
            return None
        presented = hash_token(token).encode("ascii")
        found: User | None = None
        for entry in self._refresh():
            if hmac.compare_digest(presented, entry.token_hash.encode("ascii")):
                found = User(entry.name, entry.role)
        legacy = self.legacy_token or ""
        legacy_match = hmac.compare_digest(
            token.encode("utf-8"), legacy.encode("utf-8")
        )
        if legacy_match and self.legacy_token is not None and found is None:
            found = LEGACY
        return found

    def names(self) -> list[tuple[str, str]]:
        """List the users of the file.

        Returns:
            (name, role) per user, in file order.
        """
        return [(u.name, u.role) for u in self._refresh()]
