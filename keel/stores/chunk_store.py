"""The SQLite chunk store: filings, chunks, quarantine (chapter 9.2).

The store is 1 SQLite file, `chunks.sqlite`, that also holds the FTS5
table of `keel.stores.sqlite_fts`. Row `vector_row` of `vectors.npy` holds
the vector of the chunk with that `vector_row`. The build inserts the chunks
in chunk-ID order, so `vector_row` equals the chunk-ID rank and `id` minus
1. `id` is an INTEGER PRIMARY KEY, the stable rowid that the external-content
FTS5 table keys on (a hidden rowid may change on VACUUM); `chunk_id` is
UNIQUE instead of the chapter 9.2 TEXT PRIMARY KEY.
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import itertools
import json
import pathlib
import sqlite3

from keel import chunker
from keel import errors
from keel.parsers import base

FILE_NAME = "chunks.sqlite"

SCHEMA = """
CREATE TABLE filings (
  filing_id TEXT PRIMARY KEY,
  ticker TEXT NOT NULL,
  company TEXT NOT NULL,
  cik TEXT,
  form TEXT NOT NULL,
  fiscal_year INTEGER,
  fiscal_period TEXT,
  period_end_date TEXT NOT NULL,
  filing_date TEXT NOT NULL,
  fiscal_year_end_month INTEGER,
  source_url TEXT,
  url_trusted INTEGER NOT NULL DEFAULT 0,
  file_name TEXT NOT NULL,
  file_sha256 TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  chunker_version TEXT NOT NULL,
  xbrl_block_chars INTEGER,
  warnings TEXT,
  source TEXT NOT NULL DEFAULT 'corpus'
);

CREATE TABLE chunks (
  id INTEGER PRIMARY KEY,
  chunk_id TEXT NOT NULL UNIQUE,
  filing_id TEXT NOT NULL REFERENCES filings(filing_id),
  ticker TEXT NOT NULL,
  company TEXT NOT NULL,
  cik TEXT,
  form TEXT NOT NULL,
  fiscal_year INTEGER,
  fiscal_period TEXT,
  period_end_date TEXT NOT NULL,
  filing_date TEXT NOT NULL,
  section TEXT NOT NULL,
  item_label TEXT,
  section_confidence REAL,
  sequence INTEGER NOT NULL,
  text TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  is_table INTEGER NOT NULL DEFAULT 0,
  delta_only INTEGER NOT NULL DEFAULT 0,
  boilerplate_flag TEXT,
  source_url TEXT,
  chunk_hash TEXT NOT NULL,
  simhash INTEGER NOT NULL,
  vector_row INTEGER NOT NULL
);

CREATE INDEX idx_chunks_filter
  ON chunks(ticker, form, period_end_date, section);

CREATE TABLE quarantine (
  file_name TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  evidence TEXT
);
"""

_CHUNK_COLUMNS = (
    "chunk_id",
    "filing_id",
    "ticker",
    "company",
    "cik",
    "form",
    "fiscal_year",
    "fiscal_period",
    "period_end_date",
    "filing_date",
    "section",
    "item_label",
    "section_confidence",
    "sequence",
    "text",
    "token_count",
    "char_start",
    "char_end",
    "is_table",
    "delta_only",
    "boilerplate_flag",
    "source_url",
    "chunk_hash",
    "simhash",
)

_INSERT_FILING = (
    "INSERT INTO filings VALUES "
    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
# The source of a filing (chapter 26.2, step 6): `corpus` for the files of
# the zip, `edgar` for the files that `keel add` fetched.
DEFAULT_SOURCE = "corpus"
_INSERT_CHUNK = (
    "INSERT INTO chunks (id, chunk_id, filing_id, ticker, company, cik, form, "
    "fiscal_year, fiscal_period, period_end_date, filing_date, section, "
    "item_label, section_confidence, sequence, text, token_count, "
    "char_start, char_end, is_table, delta_only, boilerplate_flag, "
    "source_url, chunk_hash, simhash, vector_row) VALUES "
    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
    "?, ?, ?)"
)


@dataclasses.dataclass(frozen=True)
class FilingState:
    """What an incremental build compares for 1 indexed filing (7.12).

    Attributes:
        filing_id: The filing ID.
        file_sha256: The sha256 of the source file.
        parser_version: The parser version of the build.
        chunker_version: The chunker version of the build.
        chunk_hashes: The chunk hashes in chunk-ID order.
    """

    filing_id: str
    file_sha256: str
    parser_version: str
    chunker_version: str
    chunk_hashes: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class StoredChunk:
    """1 chunk row as the retriever reads it.

    Attributes:
        chunk_id: The chunk ID.
        filing_id: The filing ID.
        ticker: The ticker.
        form: `10-K` or `10-Q`.
        period_end_date: The ISO period end date.
        section: The canonical section.
        text: The chunk text with its prefix line.
        token_count: The tokens of `text`.
        chunk_hash: The chunk hash.
        simhash: The signed 64-bit SimHash.
        vector_row: The row of the chunk in `vectors.npy`.
    """

    chunk_id: str
    filing_id: str
    ticker: str
    form: str
    period_end_date: str
    section: str
    text: str
    token_count: int
    chunk_hash: str
    simhash: int
    vector_row: int


def create(path: pathlib.Path) -> sqlite3.Connection:
    """Create a new, empty store with the chapter 9.2 schema.

    Args:
        path: The new database file; it must not exist.

    Returns:
        An open connection.

    Raises:
        IndexWriteError: The file exists already or cannot be created.
    """
    if path.exists():
        raise errors.IndexWriteError(f"{path} exists; a build writes anew")
    try:
        conn = sqlite3.connect(path)
        # The build writes into a temporary directory that is published
        # only after it completes, so no rollback journal is needed.
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.executescript(SCHEMA)
    except sqlite3.Error as error:
        raise errors.IndexWriteError(
            f"cannot create {path}: {error}"
        ) from error
    return conn


def open_read_only(path: pathlib.Path) -> sqlite3.Connection:
    """Open a published store read-only.

    Args:
        path: The database file.

    Returns:
        A read-only connection.

    Raises:
        IndexMissingError: The file does not exist.
    """
    if not path.is_file():
        raise errors.IndexMissingError(f"no chunk store at {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


def _filing_row(
    filing: base.ParsedFiling, chunker_version: str, source: str
) -> tuple[object, ...]:
    meta = filing.metadata
    return (
        filing.filing_id,
        meta.ticker,
        meta.company or "",
        meta.cik,
        meta.form,
        meta.fiscal_year,
        meta.fiscal_period,
        meta.period_end_date.isoformat() if meta.period_end_date else "",
        meta.filing_date.isoformat() if meta.filing_date else "",
        meta.fiscal_year_end_month,
        meta.url,
        int(meta.url_trusted),
        meta.file_name,
        meta.file_sha256,
        meta.parser_version,
        chunker_version,
        meta.xbrl_block_chars,
        json.dumps(list(filing.warnings)),
        source,
    )


def write_filings(
    conn: sqlite3.Connection,
    filings: Iterable[base.ParsedFiling],
    chunker_version: str,
    sources: Mapping[str, str] | None = None,
) -> int:
    """Insert the indexable filings, in filing-ID order.

    Args:
        conn: The open store.
        filings: The parsed filings; quarantined ones are skipped.
        chunker_version: The chunker version of the build.
        sources: The source per file name (`edgar` for the files of `keel
            add`); a file without an entry is `corpus`.

    Returns:
        The number of rows written.
    """
    rows = sorted(
        (
            _filing_row(
                f,
                chunker_version,
                (sources or {}).get(f.metadata.file_name, DEFAULT_SOURCE),
            )
            for f in filings
            if not f.quarantined and f.filing_id is not None
        ),
        key=lambda row: str(row[0]),
    )
    conn.executemany(_INSERT_FILING, rows)
    return len(rows)


def write_quarantine(
    conn: sqlite3.Connection, records: Iterable[base.QuarantineRecord]
) -> int:
    """Insert the quarantine records, in file-name order.

    Args:
        conn: The open store.
        records: The quarantine records.

    Returns:
        The number of rows written.
    """
    rows = sorted(
        (r.file_name, r.reason, json.dumps(r.evidence, sort_keys=True))
        for r in records
    )
    conn.executemany("INSERT INTO quarantine VALUES (?, ?, ?)", rows)
    return len(rows)


def _chunk_row(chunk: chunker.Chunk, vector_row: int) -> tuple[object, ...]:
    values = [getattr(chunk, column) for column in _CHUNK_COLUMNS]
    return (vector_row + 1, *values, vector_row)


def write_chunks(
    conn: sqlite3.Connection, chunks: Sequence[chunker.Chunk]
) -> int:
    """Insert the chunks; `vector_row` is the position in `chunks`.

    Args:
        conn: The open store.
        chunks: The chunks in chunk-ID order, the order of `vectors.npy`.

    Returns:
        The number of rows written.

    Raises:
        IndexWriteError: The chunks are not in strict chunk-ID order.
    """
    ids = [c.chunk_id for c in chunks]
    if any(a >= b for a, b in itertools.pairwise(ids)):
        raise errors.IndexWriteError("chunks are not in chunk-ID order")
    conn.executemany(
        _INSERT_CHUNK,
        (_chunk_row(chunk, row) for row, chunk in enumerate(chunks)),
    )
    return len(chunks)


def filing_states(conn: sqlite3.Connection) -> dict[str, FilingState]:
    """Read what an incremental build compares, per indexed filing.

    Args:
        conn: An open store.

    Returns:
        The state of each filing, keyed by filing ID.
    """
    hashes: dict[str, list[str]] = {}
    for filing, digest in conn.execute(
        "SELECT filing_id, chunk_hash FROM chunks ORDER BY chunk_id"
    ):
        hashes.setdefault(filing, []).append(digest)
    return {
        row[0]: FilingState(
            filing_id=row[0],
            file_sha256=row[1],
            parser_version=row[2],
            chunker_version=row[3],
            chunk_hashes=tuple(hashes.get(row[0], ())),
        )
        for row in conn.execute(
            "SELECT filing_id, file_sha256, parser_version, chunker_version "
            "FROM filings ORDER BY filing_id"
        )
    }


def count_chunks(conn: sqlite3.Connection) -> int:
    """Count the chunk rows.

    Args:
        conn: An open store.

    Returns:
        The number of rows of `chunks`.
    """
    (count,) = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
    return int(count)


def fetch_chunks(
    conn: sqlite3.Connection, chunk_ids: Sequence[str]
) -> list[StoredChunk]:
    """Read chunks by ID, in the order asked; unknown IDs are skipped.

    Args:
        conn: An open store.
        chunk_ids: The chunk IDs.

    Returns:
        The stored chunks.
    """
    found: dict[str, StoredChunk] = {}
    query = (
        "SELECT chunk_id, filing_id, ticker, form, period_end_date, "
        "section, text, token_count, chunk_hash, simhash, vector_row "
        "FROM chunks WHERE chunk_id = ?"
    )
    for chunk_id in chunk_ids:
        row = conn.execute(query, (chunk_id,)).fetchone()
        if row is not None:
            found[chunk_id] = StoredChunk(*row)
    return [found[c] for c in chunk_ids if c in found]
