"""Log redaction and the secret checks of chapter 15 (S-01, S-14).

`redact` replaces every known secret value and every key pattern in a
text: an Anthropic key, a bearer token, and the value of any
`NAME_KEY=` or `NAME_TOKEN=` assignment. `RedactingFormatter` applies it
to every log line, and `install` puts it on the handlers of the root
logger with the secret values of the loaded settings and of every
environment variable whose name ends in `KEY` or `TOKEN`.
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
import logging
import os
import re

from keel import config

MASK = "[REDACTED]"
MIN_SECRET_CHARS = 8  # shorter values would mask ordinary words
SECRET_NAME = re.compile(r"(KEY|TOKEN)$", re.IGNORECASE)
_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=\-]{8,}"),
    # Query strings: ?token=...&, &api_key=...; the value stops at & or #.
    re.compile(r"(?i)([?&][A-Z0-9_\-]*(?:KEY|TOKEN)=)[^&#\s'\"]{8,}"),
    # key=..., token: ..., NAME_KEY=..., x-api-key: ..., "api_key": "..."
    # a value that the query pattern already masked is left as it is:
    # any name that ends in KEY or TOKEN, prefix optional; the value runs to
    # the next space, quote, comma, or semicolon.
    re.compile(
        r"(?i)(?<![A-Z0-9_\-])"
        r"(([A-Z0-9_\-]*)(?:KEY|TOKEN)['\"]?\s*[=:]\s*['\"]?)"
        r"[^\s'\",;]{8,}"
    ),
)
# The 1 benign phrase that the name pattern matches: "cache key: <hash>".
_BENIGN_PREFIX = "cache "


def secret_values(
    environ: Mapping[str, str], settings: config.Settings | None = None
) -> list[str]:
    """Collect the secret values to mask.

    Args:
        environ: The environment; a variable whose name ends in `KEY` or
            `TOKEN` counts as a secret.
        settings: The loaded settings, for the provider key and the API
            token read from the dotenv file.

    Returns:
        The values, longest first: environment values of at least 8
        characters, and the 2 service secrets at any length.
    """
    values = {
        v
        for k, v in environ.items()
        if SECRET_NAME.search(k) and len(v) >= MIN_SECRET_CHARS
    }
    if settings is not None:
        # The 2 secrets of the service are masked at any length.
        for secret in (settings.anthropic_api_key, settings.api_token):
            if secret is not None and secret.get_secret_value():
                values.add(secret.get_secret_value())
    return sorted(values, key=len, reverse=True)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Mask the secrets and the key patterns in a text.

    Args:
        text: The text, such as a formatted log line.
        secrets: The known secret values.

    Returns:
        The text with each secret replaced by `[REDACTED]`.
    """
    for value in secrets:
        if value:
            text = text.replace(value, MASK)
    text = _PATTERNS[0].sub(MASK, text)
    for pattern in _PATTERNS[1:3]:
        text = pattern.sub(lambda m: m.group(1) + MASK, text)
    return _PATTERNS[3].sub(_mask_named_value, text)


def _mask_named_value(match: re.Match[str]) -> str:
    """Mask 1 `name=value` match unless it is the phrase `cache key`.

    A query parameter (the name follows `?` or `&`) whose value is exactly
    the mask, ended by the text end, `&`, or `#`, was masked by the query
    pattern and stays as it is; every other value is masked again.
    """
    value = match.group(0)[len(match.group(1)) :]
    rest = value[len(MASK) :]
    start = match.start()
    in_query = start > 0 and match.string[start - 1] in "?&"
    if in_query and value.startswith(MASK) and (not rest or rest[0] in "&#"):
        # Keep the mask, then redact what follows it: the tail can hold
        # another parameter such as `&api_key=...`.
        return match.group(1) + MASK + redact(rest)
    bare_key = match.group(2) == "" and match.group(1)[:3].lower() == "key"
    if bare_key:
        start = match.start()
        window = match.string[max(0, start - len(_BENIGN_PREFIX)) : start]
        if window.lower() == _BENIGN_PREFIX:
            return match.group(0)
    return match.group(1) + MASK


class RedactingFormatter(logging.Formatter):
    """A log formatter that masks secrets in every line (S-01 step 3).

    Args:
        fmt: The format string.
        secrets: The known secret values.
    """

    def __init__(self, fmt: str | None, secrets: Iterable[str] = ()) -> None:
        super().__init__(fmt)
        self.secrets = tuple(secrets)

    def format(self, record: logging.LogRecord) -> str:
        """Format the record, then mask it.

        Args:
            record: The log record.

        Returns:
            The masked line, traceback included.
        """
        return redact(super().format(record), self.secrets)


LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"


def install(
    settings: config.Settings | None = None,
    environ: Mapping[str, str] | None = None,
) -> RedactingFormatter:
    """Put the redacting formatter on every handler of the root logger.

    Args:
        settings: The loaded settings, or None.
        environ: The environment, or None for `os.environ`.

    Returns:
        The formatter.
    """
    secrets = secret_values(
        os.environ if environ is None else environ, settings
    )
    formatter = RedactingFormatter(LOG_FORMAT, secrets)
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(formatter)
    return formatter
