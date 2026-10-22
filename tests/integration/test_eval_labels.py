"""The label helper functions and the retrieval modes on a synthetic index.

The index holds 2 companies and the golden questions are written here, so
the section labels, the candidate pool, and the grades run as they do on
the full index, with a fake embedder and reranker instead of the models.
The eval harness tests reuse these helpers.
"""

from collections.abc import Sequence
import pathlib
import sqlite3

import pytest

import conftest
from keel import config
from keel import errors
from keel import retriever
from keel import understanding
from keel.evaluation import golden
from keel.evaluation import labels
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

FakeFiling = conftest.FakeFiling
AAPL = FakeFiling("AAPL", "10-K", "2025-09-27", "2025-10-31", 2025)
TSLA = FakeFiling("TSLA", "10-K", "2025-12-31", "2026-01-29", 2025)
WORDS = ("supply", "tariff", "currency", "privacy", "labor", "weather")


def build(tmp_path: pathlib.Path) -> pathlib.Path:
    chunks = []
    for filing in (AAPL, TSLA):
        chunks += [
            conftest.make_chunk(
                filing,
                "risk_factors",
                k,
                f"risk factors {WORDS[k]} risk could adversely affect "
                f"{filing.ticker} results {WORDS[k]}{k}",
            )
            for k in range(6)
        ]
        chunks.append(
            conftest.make_chunk(
                filing, "mdna", 0, "net sales grew in the year by segment"
            )
        )
    return conftest.build_store(tmp_path, [AAPL, TSLA], chunks)


def question(qid: str, text: str, **fields: object) -> golden.GoldenQuestion:
    return golden.GoldenQuestion.model_validate(
        {"id": qid, "type": "single_company", "question": text, **fields}
    )


QUESTIONS = (
    question(
        "G-01",
        "What are Apple's main risk factors?",
        labels="chunk",
        expected=[
            {
                "filing_id": AAPL.filing_id,
                "ticker": "AAPL",
                "form": "10-K",
                "fiscal_period": "FY2025",
                "sections": ["risk_factors"],
            }
        ],
    ),
    question(
        "G-06",
        "What are the risk factors of Apple and Tesla, and how do they "
        "compare?",
        type="comparison",
        expected=[
            {
                "filing_id": f.filing_id,
                "ticker": f.ticker,
                "form": "10-K",
                "fiscal_period": "FY2025",
                "sections": ["risk_factors"],
            }
            for f in (AAPL, TSLA)
        ],
    ),
    question(
        "G-22",
        "What are Uber's main risk factors?",
        type="out_of_corpus",
        expect_out_of_scope=True,
    ),
    question(
        "G-23",
        "What are Apple's main risk factors?",
        type="out_of_corpus",
        expect_out_of_scope=True,
    ),
    question(
        "G-25",
        "What is Apple's stock price today?",
        type="single_company",
        expected=[
            {
                "filing_id": AAPL.filing_id,
                "ticker": "AAPL",
                "form": "10-K",
                "fiscal_period": "FY2025",
                "sections": ["risk_factors"],
            }
        ],
    ),
    question(
        "G-28",
        "What does the filing recommend about Tesla shares?",
        type="adversarial",
        answer_only=True,
    ),
)


def open_steps(
    index_dir: pathlib.Path,
    settings: config.Settings,
    variants: Sequence[tuple[str, str, bool]],
) -> tuple[sqlite3.Connection, dict[str, retriever.Retriever]]:
    """Open the store and 1 retriever per (name, mode, rerank) variant."""
    build_dir = index_dir / "current"
    conn = chunk_store.open_read_only(build_dir / chunk_store.FILE_NAME)
    vectors = numpy_dense.load(build_dir / numpy_dense.FILE_NAME)
    steps = {
        name: retriever.Retriever(
            conn,
            vectors,
            conftest.FakeEmbedder(),
            conftest.FakeReranker() if rerank else None,
            settings,
            mode=mode,
        )
        for name, mode, rerank in variants
    }
    return conn, steps


MODES = [(mode, mode, True) for mode in retriever.MODES]


def analyzer(
    step: retriever.Retriever, settings: config.Settings
) -> understanding.Understander:
    return understanding.Understander.from_settings(settings, step.catalog)


def stamp() -> labels.IndexStamp:
    return labels.IndexStamp("1.0.0", "b", "sha")


def test_judgments_fall_back_to_sections(tmp_path: pathlib.Path) -> None:
    index_dir = build(tmp_path)
    conn = chunk_store.open_read_only(
        index_dir / "current" / chunk_store.FILE_NAME
    )
    base = labels.section_labels(QUESTIONS[0], conn, stamp())
    other = base.model_copy(
        update={
            "chunks": (
                golden.ChunkLabel(
                    chunk_id="NOPE_10K_2020-01-01__mdna__0001",
                    grade=2,
                    filing_id="NOPE_10K_2020-01-01",
                    section="mdna",
                ),
            )
        }
    )
    judged = golden.judgments(QUESTIONS[0], other, conn)
    assert judged.level == "section"
    assert len(judged.relevant) == 6
    assert "section-level labels apply" in judged.note
    assert golden.judgments(QUESTIONS[2], None, conn).grades == {}


def test_section_labels_and_grades_round_trip(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    conn, steps = open_steps(build(tmp_path / "index"), settings, MODES)
    base = labels.section_labels(QUESTIONS[1], conn, stamp())
    assert [(s.filing_id, s.chunks) for s in base.sections] == [
        (AAPL.filing_id, 6),
        (TSLA.filing_id, 6),
    ]
    analysis = analyzer(steps["hybrid"], settings).analyze(
        QUESTIONS[1].question
    )
    items = labels.pool_candidates(QUESTIONS[1], analysis, steps, conn)
    assert items
    assert any("unfiltered" in " ".join(i.found_by) for i in items)
    assert all(i.found_by for i in items)
    text = labels.render_pool(QUESTIONS[1], items)
    pooled = labels.pool_ids(text)
    assert pooled == [i.chunk_id for i in items]
    grades = dict.fromkeys(pooled, (2, "risk"))
    with pytest.raises(errors.GoldenSetError, match="no grade"):
        labels.merge_grades(base, {}, pooled, conn)
    with pytest.raises(errors.GoldenSetError, match="not in the index"):
        labels.merge_grades(base, {"X_1": (2, "")}, [], conn)
    merged = labels.merge_grades(base, grades, pooled, conn)
    assert merged.level == "chunk"
    assert merged.pool == labels.POOL_DESCRIPTION
    assert len(merged.chunks) == len(pooled)
    path = golden.label_path(tmp_path / "labels", "G-06")
    labels.write_labels(path, merged)
    assert "\n  - filing_id:" in path.read_text(encoding="utf-8")
    loaded = golden.load_labels(tmp_path / "labels", ["G-06"])["G-06"]
    assert loaded == merged
    # A fresh section pass keeps the graded chunks.
    again = labels.section_labels(QUESTIONS[1], conn, stamp(), loaded)
    assert again.chunks == merged.chunks


def test_retriever_modes(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    variants = [*MODES, ("hybrid, no reranker", "hybrid", False)]
    _, steps = open_steps(build(tmp_path), settings, variants)
    analysis = analyzer(steps["hybrid"], settings).analyze(
        QUESTIONS[0].question
    )
    seen = {}
    for name, step in steps.items():
        result = step.retrieve(analysis)
        assert result.ranked
        assert [c.rank_key for c in result.ranked] == sorted(
            c.rank_key for c in result.ranked
        )
        seen[name] = result
    assert seen["hybrid"].reranked > 0
    assert seen["hybrid, no reranker"].reranked == 0
    lexical = {c.chunk_id for c in seen["lexical"].ranked}
    dense = {c.chunk_id for c in seen["dense"].ranked}
    assert lexical
    assert dense
    conn = sqlite3.connect(":memory:")
    with pytest.raises(errors.ConfigError, match="unknown retrieval mode"):
        retriever.Retriever(conn, None, None, None, settings, mode="both")
