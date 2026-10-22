"""The pilot store: comp sets and feedback in 1 SQLite file (chapter 27.2).

The file lives apart from the index (`pilot.db`, on the volume in the
pilot), so a new index build never drops a comp set or a vote. The table
`comp_sets` holds a name and its tickers; a question names a set as
`my <name> comps` (`keel.understanding`). The table `feedback` holds 1
thumbs vote and an optional note per answer and user; a later vote of the
same user on the same answer replaces the earlier one. A thumbs-down vote
flags the answer, and `keel feedback --flagged` lists the flagged
questions as candidate golden questions.

Each call opens its own connection, so the API threads share nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from collections.abc import Sequence
import contextlib
import dataclasses
import datetime
import json
import pathlib
import re
import sqlite3
from typing import Literal

from keel import errors

Vote = Literal["up", "down"]
VOTES: tuple[Vote, ...] = ("up", "down")
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 &-]{0,39}$")
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
MAX_TICKERS = 25
MAX_NOTE_CHARS = 2000
# A name typed with its suffix ("software comps") keeps the bare name.
_RESERVED = frozenset(
    {"comps", "comp set", "comparables", "peers", "peer set", "my", "our"}
)
_SUFFIX = re.compile(r"\s+(?:comps|comp set|comparables|peers|peer set)$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS comp_sets (
  name TEXT PRIMARY KEY,
  tickers TEXT NOT NULL,
  owner TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY,
  request_id TEXT NOT NULL,
  user_name TEXT NOT NULL,
  vote TEXT NOT NULL CHECK (vote IN ('up', 'down')),
  note TEXT,
  question TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (request_id, user_name)
);
"""


@dataclasses.dataclass(frozen=True)
class CompSet:
    """1 saved comp set.

    Attributes:
        name: The lower-case name a question uses.
        tickers: The tickers in the order the user gave them.
        owner: The user who saved it last, or None from the CLI.
        updated_at: The ISO 8601 time of the last save, in UTC.
    """

    name: str
    tickers: tuple[str, ...]
    owner: str | None
    updated_at: str


@dataclasses.dataclass(frozen=True)
class Feedback:
    """1 vote on 1 answer.

    Attributes:
        request_id: The request ID of the answer.
        user_name: The user who voted.
        vote: `up` or `down`.
        note: The note, or None.
        question: The question of the answer, from its audit record.
        created_at: The ISO 8601 time of the vote, in UTC.
    """

    request_id: str
    user_name: str
    vote: Vote
    note: str | None
    question: str | None
    created_at: str

    @property
    def flagged(self) -> bool:
        """True for a thumbs-down vote: a candidate golden question."""
        return self.vote == "down"


def normalize_name(name: str) -> str:
    """Normalize and check a comp set name.

    Args:
        name: The name as typed.

    Returns:
        The lower-case name with single spaces and no `comps` suffix.

    Raises:
        InvalidCompSetError: The name is empty, too long, only a suffix
            word, or has a character other than a letter, a digit, a
            space, `&`, or `-`.
    """
    text = " ".join(name.lower().split())
    text = _SUFFIX.sub("", text)
    text = re.sub(r"^(?:my|our|the)\s+", "", text)
    if not NAME_PATTERN.match(text) or text in _RESERVED:
        raise errors.InvalidCompSetError(
            "a comp set name has 1 to 40 letters, digits, spaces, & or -"
        )
    return text


def normalize_tickers(tickers: Sequence[str]) -> tuple[str, ...]:
    """Normalize and check the tickers of a comp set.

    Args:
        tickers: The tickers as typed; commas and spaces split them.

    Returns:
        The upper-case tickers without duplicates, in the given order.

    Raises:
        InvalidCompSetError: No ticker, more than 25, or a malformed one.
    """
    found: list[str] = []
    for item in tickers:
        for part in re.split(r"[\s,]+", item.strip().upper()):
            if part and part not in found:
                found.append(part)
    if not found or len(found) > MAX_TICKERS:
        raise errors.InvalidCompSetError(
            f"a comp set has 1 to {MAX_TICKERS} tickers"
        )
    bad = [t for t in found if not TICKER_PATTERN.match(t)]
    if bad:
        raise errors.InvalidCompSetError("not a ticker: " + ", ".join(bad[:3]))
    return tuple(found)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


class PilotStore:
    """The comp sets and the feedback of the pilot.

    Args:
        path: The SQLite file (`pilot.db`); created on the first write.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path

    @contextlib.contextmanager
    def _connect(self, write: bool) -> Iterator[sqlite3.Connection]:
        try:
            if write:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=5.0)
        except (OSError, sqlite3.Error) as error:
            raise errors.PilotStoreError(
                f"cannot open the pilot store {self.path}: {error}"
            ) from error
        try:
            with conn:
                conn.executescript(SCHEMA)
                yield conn
        except sqlite3.Error as error:
            raise errors.PilotStoreError(
                f"pilot store {self.path}: {error}"
            ) from error
        finally:
            conn.close()

    def comp_sets(self) -> dict[str, CompSet]:
        """Read every comp set.

        Returns:
            The comp sets keyed by name, in name order; empty when the
            file does not exist yet.

        Raises:
            PilotStoreError: The file cannot be read.
        """
        if not self.path.exists():
            return {}
        with self._connect(write=False) as conn:
            rows = conn.execute(
                "SELECT name, tickers, owner, updated_at FROM comp_sets "
                "ORDER BY name"
            ).fetchall()
        return {
            name: CompSet(name, tuple(json.loads(tickers)), owner, updated)
            for name, tickers, owner, updated in rows
        }

    def save_comp_set(
        self, name: str, tickers: Sequence[str], owner: str | None = None
    ) -> CompSet:
        """Create or replace a comp set.

        Args:
            name: The name as typed.
            tickers: The tickers as typed.
            owner: The user who saves it, or None from the CLI.

        Returns:
            The saved comp set.

        Raises:
            InvalidCompSetError: The name or the tickers fail validation.
            PilotStoreError: The write failed.
        """
        entry = CompSet(
            normalize_name(name), normalize_tickers(tickers), owner, _now()
        )
        with self._connect(write=True) as conn:
            conn.execute(
                "INSERT INTO comp_sets (name, tickers, owner, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (name) DO UPDATE SET "
                "tickers = excluded.tickers, owner = excluded.owner, "
                "updated_at = excluded.updated_at",
                (
                    entry.name,
                    json.dumps(list(entry.tickers)),
                    entry.owner,
                    entry.updated_at,
                ),
            )
        return entry

    def delete_comp_set(self, name: str) -> bool:
        """Delete a comp set.

        Args:
            name: The name as typed.

        Returns:
            True when the set existed.

        Raises:
            InvalidCompSetError: The name fails validation.
            PilotStoreError: The write failed.
        """
        key = normalize_name(name)
        if not self.path.exists():
            return False
        with self._connect(write=True) as conn:
            cursor = conn.execute(
                "DELETE FROM comp_sets WHERE name = ?", (key,)
            )
        return cursor.rowcount > 0

    def record_vote(  # pylint: disable=too-many-arguments
        self,
        *,
        request_id: str,
        user_name: str,
        vote: Vote,
        note: str | None = None,
        question: str | None = None,
    ) -> Feedback:
        """Store a vote; it replaces the user's earlier vote on the answer.

        Args:
            request_id: The request ID of the answer.
            user_name: The user who votes.
            vote: `up` or `down`.
            note: An optional note, at most 2,000 characters.
            question: The question of the answer, for the eval review.

        Returns:
            The stored vote.

        Raises:
            PilotStoreError: The vote or the note is not valid, or the
                write failed.
        """
        if vote not in VOTES:
            raise errors.PilotStoreError(f"a vote is up or down, not {vote}")
        text = (note or "").strip() or None
        if text is not None and len(text) > MAX_NOTE_CHARS:
            raise errors.PilotStoreError(
                f"a note has at most {MAX_NOTE_CHARS} characters"
            )
        entry = Feedback(request_id, user_name, vote, text, question, _now())
        with self._connect(write=True) as conn:
            conn.execute(
                "INSERT INTO feedback (request_id, user_name, vote, note, "
                "question, created_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (request_id, user_name) DO UPDATE SET "
                "vote = excluded.vote, note = excluded.note, "
                "question = excluded.question, "
                "created_at = excluded.created_at",
                dataclasses.astuple(entry),
            )
        return entry

    def feedback(self, *, flagged_only: bool = False) -> list[Feedback]:
        """Read the votes, newest first.

        Args:
            flagged_only: Only the thumbs-down votes.

        Returns:
            The votes; empty when the file does not exist yet.

        Raises:
            PilotStoreError: The file cannot be read.
        """
        if not self.path.exists():
            return []
        with self._connect(write=False) as conn:
            rows = conn.execute(
                "SELECT request_id, user_name, vote, note, question, "
                "created_at FROM feedback WHERE vote = 'down' OR NOT ? "
                "ORDER BY created_at DESC, id DESC",
                (flagged_only,),
            ).fetchall()
        return [Feedback(*row) for row in rows]
