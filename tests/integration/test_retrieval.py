"""Retrieval over synthetic indexes with a fake embedder and reranker.

Each test writes a small published index (store, FTS5, vectors, pointer)
with `conftest.build_store`, so the SQL filters, the fusion, the cap, the
collapse, and the budget run as they do on the real index.
"""

import pathlib
import sqlite3

import pytest

import conftest
from keel import cli
from keel import config
from keel import context
from keel import errors
from keel import retriever
from keel import understanding
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

FakeFiling = conftest.FakeFiling
# Distinct words keep the chunks of 1 company apart in SimHash.
THEMES = ("pricing", "approval", "tariffs", "privacy", "antitrust", "export")
THEMES += ("licensing", "audits", "sanctions", "emissions", "labor", "taxes")


def open_retriever(
    index_dir: pathlib.Path, settings: config.Settings, *, dense: bool = True
) -> retriever.Retriever:
    build = index_dir / "current"
    conn = chunk_store.open_read_only(build / chunk_store.FILE_NAME)
    vectors = numpy_dense.load(build / numpy_dense.FILE_NAME) if dense else None
    return retriever.Retriever(
        conn,
        vectors,
        conftest.FakeEmbedder() if dense else None,
        conftest.FakeReranker(),
        settings,
    )


def analyze(step: retriever.Retriever, settings: config.Settings, text: str):
    understander = understanding.Understander.from_settings(
        settings, step.catalog
    )
    return understander.analyze(text)


class TopicReranker(conftest.FakeReranker):
    """Scores a passage by how often it names the topic word."""

    def score(self, pairs):
        self.pairs.extend(pairs)
        return [min(0.99, p.count("regulatory") / 10) for _, p in pairs]


def test_sector_cap(tmp_path: pathlib.Path, settings: config.Settings) -> None:
    tickers = [f"Q{chr(65 + n // 26)}{chr(65 + n % 26)}" for n in range(53)]
    filings = [
        FakeFiling(t, "10-K", "2024-12-31", "2025-02-14", 2024) for t in tickers
    ]
    chunks = [
        conftest.make_chunk(
            filing,
            "risk_factors",
            k,
            # Later tickers repeat the topic word more often, so their
            # reranker scores are higher; the themes keep chunks apart.
            "risk "
            + "regulatory " * (1 + n // 8)
            + " ".join(f"{word}{k}" for word in THEMES),
        )
        for n, filing in enumerate(filings)
        for k in range(5)
    ]
    step = open_retriever(
        conftest.build_store(tmp_path, filings, chunks), settings
    )
    step.reranker = TopicReranker()
    analysis = analyze(
        step, settings, "What regulatory risks do all companies face?"
    )
    assert analysis.primary_type == "sector"
    assert len(analysis.tickers) == 53
    result = step.retrieve(analysis)
    kept = [g.ticker for g in result.plan.groups]
    assert len(kept) == 12
    assert len(result.plan.sub_queries) == 12
    outside = [g for g in result.gaps if "outside the 12 companies" in g]
    assert len(outside) == 41
    assert {c.candidate.ticker for c in result.context.chunks} == set(kept)
    # The 12 highest summed scores are among the later tickers.
    assert set(kept) <= set(tickers[-16:])
    assert len(result.context.chunks) == 48
    assert {f.taken for f in result.context.fills} == {4}
    # 53 in the first round (1 each, so the summed scores compare), the
    # rest of the 80 for the 12 kept: 2 each, and the 3 left over go to
    # the companies with candidates left.
    assert result.reranked == 80
    assert {c.candidate.query for c in result.context.chunks} <= set(range(12))


def test_response_reserve_with_the_cap(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    # 14 companies with risk chunks and Item 1 chunks; the question asks
    # how they address the risks, so each kept company gets a response
    # group over the business, MD&A, and legal sections.
    tickers = [f"R{chr(65 + n)}" for n in range(14)]
    filings = [
        FakeFiling(t, "10-K", "2024-12-31", "2025-02-14", 2024) for t in tickers
    ]
    chunks = []
    for n, filing in enumerate(filings):
        for k in range(5):
            words = " ".join(f"{word}{k}" for word in THEMES)
            chunks.append(
                conftest.make_chunk(
                    filing,
                    "risk_factors",
                    k,
                    "risk " + "regulatory " * (1 + n // 4) + words,
                )
            )
            chunks.append(
                conftest.make_chunk(
                    filing,
                    "business",
                    k,
                    "we comply with regulatory approval programs " + words,
                )
            )
    step = open_retriever(
        conftest.build_store(tmp_path, filings, chunks), settings
    )
    step.reranker = TopicReranker()
    analysis = analyze(
        step,
        settings,
        "What regulatory risks do all companies face, and how are they "
        "addressing them?",
    )
    assert retriever.asks_for_response(analysis)
    result = step.retrieve(analysis)
    kept = {g.ticker for g in result.plan.groups}
    assert len(kept) == 12
    assert len(result.plan.groups) == 24
    # 1 risk and 1 response sub-query per kept company.
    assert len(result.plan.sub_queries) == 24
    response = [g for g in result.plan.groups if g.key.endswith(" response")]
    assert {g.quota for g in response} == {1}
    assert {g.quota for g in result.plan.groups if g not in response} == {3}
    sections = {
        (c.candidate.ticker, c.candidate.section) for c in result.context.chunks
    }
    for ticker in kept:
        assert (ticker, "business") in sections
        assert (ticker, "risk_factors") in sections
    queries = {c.candidate.query for c in result.context.chunks}
    assert queries <= set(range(24))


def risk_store(tmp_path: pathlib.Path) -> pathlib.Path:
    annual = FakeFiling("PFE", "10-K", "2024-12-31", "2025-02-27", 2024)
    q1 = FakeFiling("PFE", "10-Q", "2025-03-30", "2025-05-01", 2025, "Q1")
    q2 = FakeFiling("PFE", "10-Q", "2025-06-29", "2025-08-05", 2025, "Q2")
    chunks = [
        conftest.make_chunk(
            annual,
            "risk_factors",
            k,
            f"risks from drug pricing legislation number {k} adversely affect",
        )
        for k in range(6)
    ]
    chunks += [
        conftest.make_chunk(
            annual, "mdna", 0, "revenue discussion of the year and risks"
        ),
        conftest.make_chunk(
            q1,
            "risk_factors",
            0,
            "there were no material changes to the risk factors of the "
            "annual report except a new tariff risk",
            delta_only=True,
        ),
        conftest.make_chunk(
            q2,
            "risk_factors",
            0,
            "changes to the risks: a new risk on vaccine demand and risks",
            delta_only=True,
        ),
        conftest.make_chunk(q2, "mdna", 0, "quarterly revenue and risks"),
    ]
    return conftest.build_store(tmp_path, [annual, q1, q2], chunks)


def test_risk_10k_supplement(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    step = open_retriever(risk_store(tmp_path), settings)
    analysis = analyze(step, settings, "What risks did Pfizer report in 2025?")
    window = analysis.windows["PFE"]
    assert window is not None
    assert window.start.year == 2025
    result = step.retrieve(analysis)
    chunks = [c.candidate for c in result.context.chunks]
    annual = [c for c in chunks if c.form == "10-K"]
    # The window covers only 10-Qs, yet the latest 10-K risk chunks join.
    assert annual
    assert {c.section for c in annual} == {"risk_factors"}
    assert all(not c.in_window for c in annual)
    assert {c.form for c in chunks} == {"10-K", "10-Q"}
    # The order puts the latest period first.
    assert chunks[0].period_end_date == "2025-06-29"
    assert chunks[-1].form == "10-K"


def test_empty_context(
    tmp_path: pathlib.Path,
    settings: config.Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = open_retriever(risk_store(tmp_path), settings)
    reranker = step.reranker
    assert isinstance(reranker, conftest.FakeReranker)
    # A question about a fiscal year the company has no filing for: the
    # window filter matches no row.
    analysis = analyze(step, settings, "What risks did Pfizer report in 2019?")
    window = analysis.windows["PFE"]
    assert window is not None

    def no_model_request(*args: object, **kwargs: object) -> None:
        raise AssertionError("no model request without context")

    monkeypatch.setattr(reranker, "score", no_model_request)
    result = step.retrieve(analysis)
    assert result.context.empty
    assert result.candidates == 0
    assert result.context.token_estimate == 0
    assert result.gaps[-1] == "PFE: no filing text matched"


def test_empty_context_command(
    tmp_path: pathlib.Path,
    clean_env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del clean_env
    index_dir = risk_store(tmp_path)
    code = cli.main(
        [
            "--config",
            str(conftest.CONFIG_FILE),
            "retrieve",
            "What risks did Pfizer report in 2019?",
            "--index",
            str(index_dir),
        ]
    )
    assert code == 0
    assert context.NO_CONTEXT_MESSAGE in capsys.readouterr().out


def test_out_of_scope_retrieves_nothing(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    step = open_retriever(risk_store(tmp_path), settings)
    analysis = analyze(step, settings, "What is the weather in Paris?")
    result = step.retrieve(analysis)
    assert result.context.empty
    assert not result.plan.sub_queries


def test_lexical_only_fallback(
    tmp_path: pathlib.Path,
    settings: config.Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = risk_store(tmp_path)

    def unavailable(*args: object, **kwargs: object) -> None:
        raise errors.EmbeddingModelUnavailableError("not in the cache")

    def no_reranker(*args: object, **kwargs: object) -> None:
        raise errors.ModelMissingError("not in the cache")

    monkeypatch.setattr(
        numpy_dense.SentenceEmbedder, "from_settings", unavailable
    )
    monkeypatch.setattr(
        retriever.CrossEncoderReranker, "from_settings", no_reranker
    )
    step = retriever.Retriever.open(settings, index_dir)
    assert step.embedder is None
    assert step.reranker is None
    assert step.degraded == (
        retriever.DEGRADED_RETRIEVAL,
        retriever.RERANKER_UNAVAILABLE,
    )
    analysis = analyze(step, settings, "What risks did Pfizer report in 2025?")
    result = step.retrieve(analysis)
    assert not result.context.empty
    assert result.degraded[0] == "degraded_retrieval"
    assert result.reranked == 0
    assert result.timings.rerank_ms == 0.0


def test_open_without_index(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    with pytest.raises(errors.IndexMissingError, match="keel index"):
        retriever.Retriever.open(settings, tmp_path)


def test_open_with_models_skipped(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    step = retriever.Retriever.open(
        settings, risk_store(tmp_path), load_models=False
    )
    assert step.degraded == (retriever.DEGRADED_RETRIEVAL,)
    assert step.names == {"PFE": "PFE Inc"}


def test_comparison_collapse_and_quotas(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    filings = []
    chunks = []
    for ticker in ["AAPL", "TSLA", "JPM"]:
        annual = FakeFiling(ticker, "10-K", "2024-12-31", "2025-02-14", 2024)
        quarter = FakeFiling(
            ticker, "10-Q", "2025-03-31", "2025-05-01", 2025, "Q1"
        )
        filings += [annual, quarter]
        for k in range(20):
            body = (
                f"{ticker} risk factor {k}: competition and supply chain "
                f"could adversely affect results, theme {k} of many themes"
            )
            chunks.append(conftest.make_chunk(annual, "risk_factors", k, body))
            # The quarter repeats the 10-K text: a near-duplicate.
            chunks.append(conftest.make_chunk(quarter, "risk_factors", k, body))
    step = open_retriever(
        conftest.build_store(tmp_path, filings, chunks), settings
    )
    analysis = analyze(
        step,
        settings,
        "What are the primary risk factors facing Apple, Tesla, and "
        "JPMorgan, and how do they compare?",
    )
    result = step.retrieve(analysis)
    assert result.candidates == 120
    assert result.collapsed == 60
    fills = {f.key: f.taken for f in result.context.fills}
    assert fills == {"AAPL": 16, "TSLA": 16, "JPM": 16}
    # The later 10-Q copy stays; the 10-K copy collapses into it.
    assert {c.candidate.form for c in result.context.chunks} == {"10-Q"}
    # 6 sub-queries (each company and its latest 10-K) get 13 pairs each,
    # and the 2 left over go to the sub-queries with candidates left.
    assert result.reranked == 80
    assert result.context.token_estimate <= 32000


def test_risk_trend_10q_cells(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    annual = FakeFiling("PFE", "10-K", "2024-12-31", "2025-02-14", 2024)
    quarter = FakeFiling("PFE", "10-Q", "2025-03-30", "2025-05-01", 2025, "Q1")
    chunks = [
        conftest.make_chunk(
            annual, "risk_factors", k, f"risk factor {k} pricing changes"
        )
        for k in range(30)
    ]
    chunks += [
        conftest.make_chunk(
            quarter, "risk_factors", 0, "no material changes to risks"
        ),
        conftest.make_chunk(quarter, "mdna", 0, "quarterly risks and revenue"),
        conftest.make_chunk(quarter, "unknown", 0, "exhibit index risks"),
    ]
    step = open_retriever(
        conftest.build_store(tmp_path, [annual, quarter], chunks), settings
    )
    analysis = analyze(
        step, settings, "How have Pfizer's risk factors changed since 2024?"
    )
    result = step.retrieve(analysis)
    quarter_chunks = [
        c.candidate for c in result.context.chunks if c.candidate.form == "10-Q"
    ]
    # The 10-Q cell reads only its risk delta; its unused quota and
    # rerank pairs go to the 10-K risk chunks.
    assert [c.section for c in quarter_chunks] == ["risk_factors"]
    assert len(result.context.chunks) == 31
    assert result.reranked == 31


def test_catalog_from_store(tmp_path: pathlib.Path) -> None:
    index_dir = risk_store(tmp_path)
    writable = sqlite3.connect(index_dir / "current" / chunk_store.FILE_NAME)
    writable.execute(
        "INSERT INTO quarantine VALUES ('GE_10K_2015-02-27_full.txt', "
        '\'registrant_mismatch\', \'{"cover_registrant": "GE Capital", '
        '"header_company": "General Electric"}\')'
    )
    writable.execute(
        "INSERT INTO quarantine VALUES ('XX_10K_2020-01-01_full.txt', "
        "'header_error', '{\"field\": \"Filing Date\"}')"
    )
    writable.execute(
        "INSERT INTO filings (filing_id, ticker, company, form, "
        "period_end_date, filing_date, file_name, file_sha256, "
        "parser_version, chunker_version) VALUES ('BAD_10K_2024-01-01', "
        "'BAD', 'Bad', '10-K', 'not a date', '2024-02-01', 'b', '', '1', '1')"
    )
    writable.commit()
    catalog = understanding.Catalog.from_store(writable)
    writable.close()
    assert [f.label for f in catalog.for_ticker("PFE")] == [
        "fiscal 2024 10-K (ended 2024-12-31)",
        "Q1 fiscal 2025 10-Q (ended 2025-03-30)",
        "Q2 fiscal 2025 10-Q (ended 2025-06-29)",
    ]
    assert catalog.for_ticker("PFE")[0].filing_id == "PFE_10K_2024-12-31"
    assert catalog.year_end_month("PFE") == 12
    notes = {q.ticker: q for q in catalog.quarantined}
    assert notes["GE"].detail == (
        "cover registrant 'GE Capital', header company 'General Electric'"
    )
    assert notes["XX"].detail == "header_error: field Filing Date"
    assert len(catalog.filings) == 3
    assert "BAD" not in catalog.indexed_tickers
