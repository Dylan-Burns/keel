"""The app-state SQLite store: the watch list (chapter 26.3, step 1).

The app state lives in its own file, `state.sqlite`, under `logs.dir`, and
not in the index directory: a full index build publishes a new build
directory and moves `current`, so a table inside `chunks.sqlite` would be
lost at the next rebuild. `logs.dir` already holds what must survive a
rebuild (`audit.jsonl`, `refresh.log`) and sits on the persistent volume on
Railway (`KEEL_LOGS__DIR=/data/logs`, chapter 29.9), so no new config key
is needed.

The `watch_list` table holds 1 row per ticker and user, with the date the
user added it. `keel refresh` checks the union of the tickers of all users.
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import sqlite3

from keel import config
from keel import errors

FILE_NAME = "state.sqlite"
DEFAULT_USER = "cli"

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_list (
  ticker TEXT NOT NULL,
  user TEXT NOT NULL,
  added_date TEXT NOT NULL,
  PRIMARY KEY (ticker, user)
);
"""


@dataclasses.dataclass(frozen=True)
class WatchEntry:
    """1 row of the watch list.

    Attributes:
        ticker: The ticker as the corpus spells it (`BRK.B`).
        user: The user who watches it.
        added_date: The date the user added it.
    """

    ticker: str
    user: str
    added_date: datetime.date


def state_path(settings: config.Settings) -> pathlib.Path:
    """Return the app-state database file of the settings.

    Args:
        settings: The loaded settings.

    Returns:
        `<logs.dir>/state.sqlite`.
    """
    return settings.logs.dir / FILE_NAME


def connect(path: pathlib.Path) -> sqlite3.Connection:
    """Open the app-state database, creating the file and schema if absent.

    Args:
        path: The database file.

    Returns:
        An open connection; the caller closes it.

    Raises:
        StateStoreError: The file cannot be opened or initialized.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
    except (OSError, sqlite3.Error) as error:
        raise errors.StateStoreError(f"cannot open {path}: {error}") from error
    try:
        conn.executescript(SCHEMA)
    except sqlite3.Error as error:
        conn.close()
        raise errors.StateStoreError(
            f"cannot initialize {path}: {error}"
        ) from error
    return conn


def add_watch(
    path: pathlib.Path,
    ticker: str,
    user: str = DEFAULT_USER,
    today: datetime.date | None = None,
) -> bool:
    """Add a ticker to the watch list of a user.

    Args:
        path: The database file.
        ticker: The ticker as the corpus spells it.
        user: The user.
        today: The added date; None takes the local date.

    Returns:
        True when the row is new, False when the user already watched it.

    Raises:
        StateStoreError: The database fails.
    """
    added = today or datetime.date.today()
    conn = connect(path)
    try:
        with conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO watch_list (ticker, user, added_date)"
                " VALUES (?, ?, ?)",
                (ticker, user, added.isoformat()),
            )
        return cursor.rowcount == 1
    except sqlite3.Error as error:
        raise errors.StateStoreError(f"cannot write {path}: {error}") from error
    finally:
        conn.close()


def remove_watch(
    path: pathlib.Path, ticker: str, user: str = DEFAULT_USER
) -> bool:
    """Remove a ticker from the watch list of a user.

    Args:
        path: The database file.
        ticker: The ticker as the corpus spells it.
        user: The user.

    Returns:
        True when a row was removed.

    Raises:
        StateStoreError: The database fails.
    """
    conn = connect(path)
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM watch_list WHERE ticker = ? AND user = ?",
                (ticker, user),
            )
        return cursor.rowcount > 0
    except sqlite3.Error as error:
        raise errors.StateStoreError(f"cannot write {path}: {error}") from error
    finally:
        conn.close()


def list_watch(path: pathlib.Path, user: str | None = None) -> list[WatchEntry]:
    """List the watch list, for 1 user or for all users.

    A missing database file is an empty watch list; nothing is created.

    Args:
        path: The database file.
        user: The user, or None for every user.

    Returns:
        The rows, by ticker then user.

    Raises:
        StateStoreError: The database fails.
    """
    if not path.exists():
        return []
    conn = connect(path)
    try:
        query = "SELECT ticker, user, added_date FROM watch_list"
        params: tuple[str, ...] = ()
        if user is not None:
            query += " WHERE user = ?"
            params = (user,)
        rows = conn.execute(query + " ORDER BY ticker, user", params).fetchall()
    except sqlite3.Error as error:
        raise errors.StateStoreError(f"cannot read {path}: {error}") from error
    finally:
        conn.close()
    return [
        WatchEntry(
            ticker=str(ticker),
            user=str(name),
            added_date=datetime.date.fromisoformat(str(added)),
        )
        for ticker, name, added in rows
    ]
