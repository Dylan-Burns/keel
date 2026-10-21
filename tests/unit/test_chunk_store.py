"""Chunk store and FTS5 tests (chapters 9.2 and 9.3)."""

import datetime
import pathlib
import sqlite3

import pytest

from keel import chunker
from keel import errors
from keel.parsers import base
from keel.stores import chunk_store
from keel.stores import sqlite_fts

pytestmark = pytest.mark.unit


def make_chunk(
    filing_id: str, section: str, sequence: int, text: str, ticker: str
) -> chunker.Chunk:
    return chunker.Chunk(
        chunk_id=base.chunk_id(filing_id, section, sequence),
        filing_id=filing_id,
        ticker=ticker,
        company=f"{ticker} Inc.",
        cik="0000000001",
        form="10-K",
        fiscal_year=2024,
        fiscal_period="FY",
        period_end_date="2024-12-31",
        filing_date="2025-02-01",
        section=section,
        item_label="Item 1A",
        section_confidence=1.0,
        sequence=sequence,
        text=text,
        token_count=len(text.split()),
        char_start=0,
        char_end=len(text),
        is_table=False,
        chunk_hash=base.chunk_hash(text),
        simhash=chunker.simhash(text),
    )


def make_filing(ticker: str, quarantine: bool = False) -> base.ParsedFiling:
    meta = base.FilingMetadata(
        file_name=f"{ticker}_10K_2025-02-01_full.txt",
        file_sha256="a" * 64,
        parser_version="1.0.0",
        ticker=ticker,
        company=f"{ticker} Inc.",
        cik="0000000001",
        form="10-K",
        filing_date=datetime.date(2025, 2, 1),
        url="https://www.sec.gov/x.htm",
        url_trusted=True,
        period_end_date=datetime.date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period="FY",
        fiscal_year_end_month=12,
    )
    record = (
        base.QuarantineRecord(
            file_name=meta.file_name,
            reason="registrant_mismatch",
            detail="cover",
            evidence={"cover": "Other Corp"},
        )
        if quarantine
        else None
    )
    return base.ParsedFiling(
        metadata=meta, text="", warnings=("w1",), quarantine=record
    )


CHUNKS = sorted(
    [
        make_chunk(
            "AAA_10K_2024-12-31",
            "risk_factors",
            0,
            "Supply chain disruption could adversely affect our results.",
            "AAA",
        ),
        make_chunk(
            "AAA_10K_2024-12-31",
            "risk_factors",
            1,
            "Changes in antitrust law and regulation in Johnson & Johnson's "
            "markets.",
            "AAA",
        ),
        make_chunk(
            "BBB_10K_2024-12-31",
            "mdna",
            0,
            "Net sales increased due to BRK.B holdings and pre-tax gains.",
            "BBB",
        ),
    ],
    key=lambda c: c.chunk_id,
)


@pytest.fixture
def store(tmp_path: pathlib.Path) -> sqlite3.Connection:
    conn = chunk_store.create(tmp_path / chunk_store.FILE_NAME)
    chunk_store.write_filings(
        conn,
        [make_filing("BBB"), make_filing("AAA"), make_filing("GEX", True)],
        "1.0.0",
    )
    chunk_store.write_quarantine(
        conn,
        [make_filing("GEX", True).quarantine],  # type: ignore[list-item]
    )
    chunk_store.write_chunks(conn, CHUNKS)
    sqlite_fts.create(conn)
    sqlite_fts.rebuild(conn)
    conn.commit()
    return conn


def test_schema_rows(store: sqlite3.Connection) -> None:
    filings = [r[0] for r in store.execute("SELECT filing_id FROM filings")]
    assert filings == ["AAA_10K_2024-12-31", "BBB_10K_2024-12-31"]
    (reason,) = store.execute("SELECT reason FROM quarantine").fetchone()
    assert reason == "registrant_mismatch"
    rows = store.execute(
        "SELECT chunk_id, vector_row, id FROM chunks ORDER BY id"
    ).fetchall()
    assert [r[0] for r in rows] == [c.chunk_id for c in CHUNKS]
    assert [r[1] for r in rows] == [0, 1, 2]
    assert [r[2] for r in rows] == [1, 2, 3]
    assert chunk_store.count_chunks(store) == len(CHUNKS)


def test_chunks_out_of_order(tmp_path: pathlib.Path) -> None:
    conn = chunk_store.create(tmp_path / "x.sqlite")
    with pytest.raises(errors.IndexWriteError):
        chunk_store.write_chunks(conn, list(reversed(CHUNKS)))


def test_create_existing_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "x.sqlite"
    path.write_bytes(b"")
    with pytest.raises(errors.IndexWriteError):
        chunk_store.create(path)


def test_open_read_only(
    store: sqlite3.Connection, tmp_path: pathlib.Path
) -> None:
    store.close()
    conn = chunk_store.open_read_only(tmp_path / chunk_store.FILE_NAME)
    assert chunk_store.count_chunks(conn) == len(CHUNKS)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM chunks")
    with pytest.raises(errors.IndexMissingError):
        chunk_store.open_read_only(tmp_path / "absent.sqlite")


def test_filing_states(store: sqlite3.Connection) -> None:
    states = chunk_store.filing_states(store)
    assert set(states) == {"AAA_10K_2024-12-31", "BBB_10K_2024-12-31"}
    aaa = states["AAA_10K_2024-12-31"]
    assert aaa.file_sha256 == "a" * 64
    assert aaa.chunker_version == "1.0.0"
    assert aaa.chunk_hashes == (CHUNKS[0].chunk_hash, CHUNKS[1].chunk_hash)


def test_fetch_chunks(store: sqlite3.Connection) -> None:
    wanted = [CHUNKS[2].chunk_id, "missing", CHUNKS[0].chunk_id]
    found = chunk_store.fetch_chunks(store, wanted)
    assert [c.chunk_id for c in found] == [wanted[0], wanted[2]]
    assert found[0].vector_row == 2
    assert found[0].text == CHUNKS[2].text


def test_quote_escapes_operators() -> None:
    assert sqlite_fts.quote('say "hi"') == '"say ""hi"""'
    assert sqlite_fts.match_expression(["BRK.B", " ", "pre-tax"]) == (
        '"BRK.B" OR "pre-tax"'
    )


def test_fts_phrase_and_operators(store: sqlite3.Connection) -> None:
    hits = sqlite_fts.search(store, ["supply chain disruption"], 3)
    assert hits[0].chunk_id == CHUNKS[0].chunk_id
    assert hits[0].vector_row == 0
    # Terms with FTS5 operator characters do not raise.
    for term in ["Johnson & Johnson", "BRK.B", "pre-tax", 'a "quoted" word']:
        sqlite_fts.search(store, [term], 3)
    assert sqlite_fts.search(store, ["BRK.B"], 3)[0].chunk_id == (
        CHUNKS[2].chunk_id
    )


def test_fts_ticker_filter(store: sqlite3.Connection) -> None:
    terms = ["adversely", "sales"]
    both = sqlite_fts.search(store, terms, 10)
    assert {h.chunk_id for h in both} == {
        CHUNKS[0].chunk_id,
        CHUNKS[2].chunk_id,
    }
    only = sqlite_fts.search(store, terms, 10, tickers=["BBB"])
    assert [h.chunk_id for h in only] == [CHUNKS[2].chunk_id]
    assert sqlite_fts.search(store, [], 10) == []
    assert sqlite_fts.search(store, terms, 0) == []
