"""The history per user and the stored answers of shareable links (27.2).

The history comes from the audit log (`audit.jsonl` and the rotated
`audit-<date>.jsonl` files): every record carries the user who asked
(`user_name`), so a user reads their own questions, newest first, and an
admin may read everyone's. A stored answer renders from the audit record
and the answer cache: the record holds the 4 parts of the cache key of
decision D-29 (question, index version, prompt version, model), so an
answer that the cache holds stays reachable by its request ID after the
10 minutes of the result store.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
import logging
import pathlib
from typing import Any

import pydantic

from keel import audit
from keel import cache

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
USER_KEY = "user_name"


class HistoryItem(pydantic.BaseModel):
    """1 question of the history.

    Attributes:
        request_id: The request ID; `/a/{request_id}` opens the answer.
        timestamp: When the question was asked (UTC, ISO 8601).
        question: The question.
        user: The user who asked, or None for a record before users.
        tickers: The resolved tickers.
        outcome: The pipeline outcome, such as `answered` or `cached`.
        model: The model that answered.
        cost_usd: The cost of the question.
        from_cache: True when the answer cache served it.
        degraded: True for the degraded mode.
        stored: True when the answer can still be opened by its link.
    """

    request_id: str
    timestamp: str
    question: str
    user: str | None
    tickers: list[str]
    outcome: str | None
    model: str | None
    cost_usd: float
    from_cache: bool
    degraded: bool
    stored: bool


class HistoryPage(pydantic.BaseModel):
    """The response of `GET /api/history`.

    Attributes:
        user: The caller.
        role: The role of the caller.
        scope: `own`, or `all` for an admin who asked for every user.
        items: The questions, newest first.
    """

    user: str
    role: str
    scope: str
    items: list[HistoryItem]


def audit_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """The audit files of a logs directory, oldest first.

    Args:
        directory: The logs directory.

    Returns:
        The rotated files by date, then the current file.
    """
    if not directory.is_dir():
        return []
    rotated = sorted(directory.glob("audit-*.jsonl"))
    current = directory / audit.FILE_NAME
    return [*rotated, current] if current.is_file() else rotated


def read_records(directory: pathlib.Path) -> Iterator[dict[str, Any]]:
    """Read every audit record; a broken line is skipped with a warning.

    Args:
        directory: The logs directory.

    Yields:
        The records, oldest file first, in line order.
    """
    for path in audit_files(directory):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            logger.warning("audit file %s unreadable: %s", path.name, error)
            continue
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                logger.warning("audit line %s:%d skipped", path.name, number)
                continue
            if isinstance(record, dict) and record.get("request_id"):
                yield record


def find_record(
    directory: pathlib.Path, request_id: str
) -> dict[str, Any] | None:
    """Find the audit record of a request ID.

    Args:
        directory: The logs directory.
        request_id: The request ID.

    Returns:
        The last record with the ID, or None.
    """
    found = None
    for record in read_records(directory):
        if record.get("request_id") == request_id:
            found = record
    return found


def cache_key_of(record: dict[str, Any]) -> str | None:
    """The answer cache key that an audit record names (decision D-29).

    Args:
        record: The audit record.

    Returns:
        The key, or None when a part is missing.
    """
    parts = [
        record.get(name)
        for name in ("question", "index_version", "prompt_version", "model")
    ]
    if not all(isinstance(part, str) and part for part in parts):
        return None
    question, index_version, prompt_version, model = (str(p) for p in parts)
    return cache.cache_key(question, index_version, prompt_version, model)


def stored_answer(
    directory: pathlib.Path, answers: cache.AnswerCache, request_id: str
) -> dict[str, Any] | None:
    """The stored answer of a request ID, from the audit log and the cache.

    Args:
        directory: The logs directory.
        answers: The answer cache.
        request_id: The request ID of the link.

    Returns:
        The cached answer with the request ID of the link and the audit
        record of that request, or None when the cache does not hold it.
    """
    record = find_record(directory, request_id)
    if record is None:
        return None
    key = cache_key_of(record)
    entry = answers.get(key) if key else None
    if entry is None:
        return None
    meta = dict(entry.get("meta") or {})
    meta.update(from_cache=record.get("outcome") == "cached")
    return {**entry, "request_id": request_id, "meta": meta, "audit": record}


def _item(record: dict[str, Any], stored: bool) -> HistoryItem:
    flags = record.get("flags") or {}
    tickers = record.get("tickers") or []
    cost = record.get("cost_usd")
    return HistoryItem(
        request_id=str(record["request_id"]),
        timestamp=str(record.get("timestamp") or ""),
        question=str(record.get("question") or ""),
        user=record.get(USER_KEY),
        tickers=[str(t) for t in tickers if isinstance(t, str)],
        outcome=record.get("outcome"),
        model=record.get("model"),
        cost_usd=float(cost) if isinstance(cost, int | float) else 0.0,
        from_cache=bool(flags.get("from_cache")),
        degraded=bool(record.get("degraded")),
        stored=stored,
    )


def history(
    directory: pathlib.Path,
    answers: cache.AnswerCache,
    user: str | None,
    *,
    limit: int = DEFAULT_LIMIT,
    live: frozenset[str] = frozenset(),
) -> list[HistoryItem]:
    """The questions of 1 user, or of every user, newest first.

    Args:
        directory: The logs directory.
        answers: The answer cache, to mark the answers a link can open.
        user: The user name, or None for every user (admin only).
        limit: The most items returned.
        live: The request IDs that the result store holds now.

    Returns:
        The items, newest first.
    """
    chosen = [
        r
        for r in read_records(directory)
        if user is None or r.get(USER_KEY) == user
    ]
    # The file order is the write order: reversed, a stable sort keeps the
    # newest first among records of the same second.
    chosen.reverse()
    chosen.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
    items = []
    for record in chosen[:limit]:
        key = cache_key_of(record)
        stored = record["request_id"] in live or (
            key is not None and answers.path(key).is_file()
        )
        items.append(_item(record, stored))
    return items
