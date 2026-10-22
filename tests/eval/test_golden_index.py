"""The golden set against the full index (needs index/current).

PR runs exclude the `eval` marker. Run with
`uv run pytest -m eval tests/eval/test_golden_index.py` after `keel index`.
"""

from collections.abc import Iterator
import sqlite3

import pytest

import conftest
from keel import indexer
from keel.evaluation import golden
from keel.stores import chunk_store

pytestmark = pytest.mark.eval

INDEX = conftest.REPO_ROOT / "index"
GOLDEN = conftest.REPO_ROOT / "eval" / "golden.yaml"
LABELS = conftest.REPO_ROOT / "eval" / "labels"


@pytest.fixture(scope="module")
def conn() -> Iterator[sqlite3.Connection]:
    build = indexer.current_build(INDEX)
    if build is None:
        pytest.skip("the full index is not built; run keel index")
    connection = chunk_store.open_read_only(build / chunk_store.FILE_NAME)
    yield connection
    connection.close()


def test_expected_filings_exist(conn: sqlite3.Connection) -> None:
    golden_set = golden.load_golden(GOLDEN)
    filings = {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT filing_id, ticker, form, fiscal_year FROM filings"
        )
    }
    for question in golden_set.questions:
        for source in question.expected:
            ticker, form, year = filings[source.filing_id]
            assert (ticker, form) == (source.ticker, source.form)
            assert source.fiscal_period.endswith(f"FY{year}"), source


def test_gold_values_in_their_chunks(conn: sqlite3.Connection) -> None:
    golden_set = golden.load_golden(GOLDEN)
    golds = [g for q in golden_set.questions for g in q.gold]
    assert {q.id for q in golden_set.questions if q.gold} == {
        "G-15",
        "G-16",
        "G-17",
        "G-18",
    }
    for gold in golds:
        row = conn.execute(
            "SELECT text FROM chunks WHERE chunk_id = ?", (gold.chunk_id,)
        ).fetchone()
        assert row is not None, gold.chunk_id
        assert f"{gold.value:,.0f}" in row[0], gold


def test_chunk_labels_exist_in_the_index(conn: sqlite3.Connection) -> None:
    golden_set = golden.load_golden(GOLDEN)
    chunk_level = [q.id for q in golden_set.questions if q.labels == "chunk"]
    found = golden.load_labels(LABELS, chunk_level)
    for question_id in chunk_level:
        graded = found[question_id].chunks
        assert graded, question_id
        assert any(c.grade == golden.RELEVANT for c in graded), question_id
        ids = golden.chunk_tickers(conn, [c.chunk_id for c in graded])
        assert len(ids) == len(graded), question_id
