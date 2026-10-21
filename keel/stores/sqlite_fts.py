"""The FTS5 lexical index over the chunk store (chapter 9.3).

`chunks_fts` is an external-content FTS5 table over `chunks.text`. The build
fills it with the FTS5 `rebuild` command after the chunk rows are written.
Every query term is quoted before it reaches `MATCH`, because FTS5 reads
`-`, `.`, and quotes as operators (docs/GOTCHAS.md).
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import json
import sqlite3

SCHEMA = """
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text, content='chunks', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
"""

# The ticker filter is a JSON list parameter, so the SQL text never changes.
_SEARCH = (
    "SELECT c.chunk_id, c.vector_row, bm25(chunks_fts) AS rank "
    "FROM chunks_fts JOIN chunks AS c ON c.rowid = chunks_fts.rowid "
    "WHERE chunks_fts MATCH ? "
    "AND (c.ticker IN (SELECT value FROM json_each(?)) OR ?) "
    "ORDER BY rank, c.chunk_id LIMIT ?"
)


@dataclasses.dataclass(frozen=True)
class LexicalHit:
    """1 lexical result.

    Attributes:
        chunk_id: The chunk ID.
        vector_row: The row of the chunk in `vectors.npy`.
        score: The BM25 score, negated so that higher is better.
    """

    chunk_id: str
    vector_row: int
    score: float


def create(conn: sqlite3.Connection) -> None:
    """Create the empty FTS5 table.

    Args:
        conn: The open chunk store.
    """
    conn.executescript(SCHEMA)


def rebuild(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS5 index from the `chunks` table (chapter 9.7 step 5).

    Args:
        conn: The open chunk store with the `chunks_fts` table.
    """
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")


def quote(term: str) -> str:
    """Quote 1 term or phrase for `MATCH`.

    Args:
        term: A word or a multi-word phrase.

    Returns:
        The term in double quotes with any inner quote doubled; FTS5 reads
        a quoted multi-word term as a phrase.
    """
    return '"' + term.replace('"', '""') + '"'


def match_expression(terms: Sequence[str]) -> str:
    """Join quoted terms with OR (chapter 9.3).

    Args:
        terms: The words and phrases; blank ones are dropped.

    Returns:
        The `MATCH` expression, or an empty string without terms.
    """
    return " OR ".join(quote(t.strip()) for t in terms if t.strip())


def search(
    conn: sqlite3.Connection,
    terms: Sequence[str],
    k: int,
    tickers: Sequence[str] | None = None,
) -> list[LexicalHit]:
    """Return the top `k` chunks by BM25 for terms joined with OR.

    Args:
        conn: An open chunk store.
        terms: The words and phrases, unquoted.
        k: The number of results.
        tickers: Restrict to these tickers, or None for all.

    Returns:
        The hits, best first; ties break on chunk ID.
    """
    expression = match_expression(terms)
    if not expression or k <= 0:
        return []
    rows = conn.execute(
        _SEARCH,
        (
            expression,
            json.dumps(list(tickers or [])),
            int(not tickers),
            k,
        ),
    )
    return [
        LexicalHit(chunk_id=row[0], vector_row=row[1], score=-float(row[2]))
        for row in rows
    ]
