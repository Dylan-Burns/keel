"""Shared fixtures: the repository paths and a settings loader."""

from collections.abc import Sequence
import dataclasses
import datetime
import hashlib
import os
import pathlib

import numpy
import pytest

from keel import chunker
from keel import config
from keel.parsers import base
from keel.stores import chunk_store
from keel.stores import numpy_dense
from keel.stores import sqlite_fts

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
MINI_CORPUS = FIXTURES / "mini_corpus"
SNIPPETS = FIXTURES / "snippets"
CONFIG_FILE = REPO_ROOT / "config" / "keel.yaml"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every KEEL_ variable and the provider key from the env."""
    for name in list(os.environ):
        if name.startswith("KEEL_") or name == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(name)
    return monkeypatch


@pytest.fixture
def settings(clean_env: pytest.MonkeyPatch) -> config.Settings:
    """The repository config, with no environment and no dotenv file."""
    del clean_env
    return config.load_settings(CONFIG_FILE, env_file=None)


class FakeEmbedder:
    """Deterministic unit vectors from a hash of each text."""

    def __init__(self, dimensions: int = numpy_dense.DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.seen: list[str] = []

    def encode(self, texts: Sequence[str]) -> numpy_dense.Vectors:
        self.seen.extend(texts)
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8])
            row = numpy.random.default_rng(seed).standard_normal(
                self.dimensions
            )
            rows.append(row / numpy.linalg.norm(row))
        return numpy.asarray(rows, dtype=numpy.float32).reshape(
            len(texts), self.dimensions
        )


@dataclasses.dataclass(frozen=True)
class FakeFiling:
    """The period facts of 1 synthetic filing."""

    ticker: str
    form: str
    period_end: str
    filing_date: str
    fiscal_year: int
    fiscal_period: str = "FY"

    @property
    def filing_id(self) -> str:
        return base.filing_id(
            self.ticker,
            self.form,
            datetime.date.fromisoformat(self.period_end),
        )


def make_chunk(
    filing: FakeFiling,
    section: str,
    sequence: int,
    body: str,
    **fields: object,
) -> chunker.Chunk:
    """A chunk of a synthetic filing, with the chapter 9.1 prefix line."""
    text = f"{filing.ticker} Inc | {filing.form} | FY{filing.fiscal_year}"
    text += f" | {section}\n{body}"
    values: dict[str, object] = {
        "chunk_id": base.chunk_id(filing.filing_id, section, sequence),
        "filing_id": filing.filing_id,
        "ticker": filing.ticker,
        "company": f"{filing.ticker} Inc",
        "cik": None,
        "form": filing.form,
        "fiscal_year": filing.fiscal_year,
        "fiscal_period": filing.fiscal_period,
        "period_end_date": filing.period_end,
        "filing_date": filing.filing_date,
        "section": section,
        "item_label": None,
        "section_confidence": 1.0,
        "sequence": sequence,
        "text": text,
        "token_count": max(1, len(text.split())),
        "char_start": 0,
        "char_end": len(body),
        "chunk_hash": hashlib.sha256(text.encode()).hexdigest()[:16],
        "simhash": chunker.simhash(body),
    }
    values.update(fields)
    return chunker.Chunk.model_validate(values)


def build_store(
    index_dir: pathlib.Path,
    filings: Sequence[FakeFiling],
    chunks: Sequence[chunker.Chunk],
    embedder: FakeEmbedder | None = None,
) -> pathlib.Path:
    """Write a synthetic published index: store, FTS5, vectors, pointer."""
    build = index_dir / "20260101T000000000000Z"
    build.mkdir(parents=True)
    conn = chunk_store.create(build / chunk_store.FILE_NAME)
    sqlite_fts.create(conn)
    conn.executemany(
        "INSERT INTO filings (filing_id, ticker, company, form, fiscal_year, "
        "fiscal_period, period_end_date, filing_date, fiscal_year_end_month, "
        "url_trusted, file_name, file_sha256, parser_version, "
        "chunker_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 12, 0, ?, '', "
        "'1.0.0', '1.0.0')",
        [
            (
                f.filing_id,
                f.ticker,
                f"{f.ticker} Inc",
                f.form,
                f.fiscal_year,
                f.fiscal_period,
                f.period_end,
                f.filing_date,
                f"{f.filing_id}.txt",
            )
            for f in filings
        ],
    )
    ordered = sorted(chunks, key=lambda c: c.chunk_id)
    chunk_store.write_chunks(conn, ordered)
    sqlite_fts.rebuild(conn)
    conn.commit()
    conn.close()
    vectors = (embedder or FakeEmbedder()).encode([c.text for c in ordered])
    numpy.save(build / numpy_dense.FILE_NAME, vectors)
    (index_dir / "current").symlink_to(build.name)
    return index_dir


class FakeReranker:
    """Scores a pair by the share of query words in the passage."""

    def __init__(self) -> None:
        self.pairs: list[tuple[str, str]] = []

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        self.pairs.extend(pairs)
        scores = []
        for query, passage in pairs:
            words = set(query.lower().split())
            found = words & set(passage.lower().split())
            scores.append(0.1 + 0.8 * len(found) / max(1, len(words)))
        return scores
