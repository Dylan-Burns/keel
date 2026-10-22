"""Tests of the retrieval plan, fusion, weights, and collapse (11.1 to 11.5).

The corpus facts are a hand-written catalog; no index and no model loads.
"""

import datetime
from typing import Any

import pytest

from keel import config
from keel import context
from keel import errors
from keel import retriever
from keel import understanding
from keel.parsers import base

BUDGET = context.Budget()
SYNONYMS = {
    "revenue": ["net sales", "revenues"],
    "risk": ["risk factors", "adversely affect"],
    "regulatory": ["regulation", "FDA"],
}

# The NVDA filings of the corpus (A-15 false: no fiscal 2026 10-K).
NVDA = [
    ("10-K", "2022-01-30", "2022-03-18", 2022, "FY"),
    ("10-K", "2023-01-29", "2023-02-24", 2023, "FY"),
    ("10-K", "2024-01-28", "2024-02-21", 2024, "FY"),
    ("10-K", "2025-01-26", "2025-02-26", 2025, "FY"),
    ("10-Q", "2023-04-30", "2023-05-26", 2024, "Q1"),
    ("10-Q", "2023-07-30", "2023-08-28", 2024, "Q2"),
    ("10-Q", "2023-10-29", "2023-11-21", 2024, "Q3"),
    ("10-Q", "2024-04-28", "2024-05-29", 2025, "Q1"),
    ("10-Q", "2024-07-28", "2024-08-28", 2025, "Q2"),
    ("10-Q", "2024-10-27", "2024-11-20", 2025, "Q3"),
    ("10-Q", "2025-04-27", "2025-05-28", 2026, "Q1"),
    ("10-Q", "2025-07-27", "2025-08-27", 2026, "Q2"),
    ("10-Q", "2025-10-26", "2025-11-19", 2026, "Q3"),
]


def ref(
    ticker: str, form: str, period: str, filed: str, year: int, fiscal: str
) -> understanding.FilingRef:
    end = datetime.date.fromisoformat(period)
    return understanding.FilingRef(
        ticker=ticker,
        form=form,
        period_end_date=end,
        fiscal_year=year,
        fiscal_period=fiscal,
        filing_date=datetime.date.fromisoformat(filed),
        filing_id=base.filing_id(ticker, form, end),
    )


def catalog() -> understanding.Catalog:
    filings = [ref("NVDA", *row) for row in NVDA]
    for ticker in ["AAPL", "TSLA", "JPM", "PFE", "JNJ", "MRK", "LLY", "ABBV"]:
        filings.append(
            ref(ticker, "10-K", "2024-12-31", "2025-02-14", 2024, "FY")
        )
    filings += [
        ref("AAPL", "10-Q", "2025-06-28", "2025-08-01", 2025, "Q3"),
        ref("AAPL", "10-K", "2025-09-27", "2025-10-31", 2025, "FY"),
        ref("PFE", "10-Q", "2025-03-30", "2025-05-01", 2025, "Q1"),
        ref("PFE", "10-Q", "2025-06-29", "2025-08-01", 2025, "Q2"),
    ]
    return understanding.Catalog(
        filings=tuple(filings), year_end_months={"NVDA": 1, "AAPL": 9}
    )


@pytest.fixture
def understander(settings: config.Settings) -> understanding.Understander:
    return understanding.Understander.from_settings(settings, catalog())


def plan(
    understander: understanding.Understander,
    question: str,
    budget: context.Budget = BUDGET,
) -> retriever.Plan:
    return retriever.build_plan(
        understander.analyze(question),
        understander.catalog,
        names={"NVDA": "NVIDIA Corporation"},
        synonyms=SYNONYMS,
        budget=budget,
    )


def candidate(**fields: Any) -> context.Candidate:
    values: dict[str, Any] = {
        "chunk_id": "AAPL_10K_2025-09-27__risk_factors__0001",
        "filing_id": "AAPL_10K_2025-09-27",
        "ticker": "AAPL",
        "company": "Apple Inc",
        "form": "10-K",
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "period_end_date": "2025-09-27",
        "filing_date": "2025-10-31",
        "section": "risk_factors",
        "item_label": None,
        "text": "Apple | 10-K\nThe company faces risks.",
        "token_count": 100,
        "is_table": False,
        "delta_only": False,
        "boilerplate_flag": None,
        "simhash": 0,
        "vector_row": 0,
        "fused": 1 / 61,
    }
    values.update(fields)
    return context.Candidate(**values)


def test_rrf_fusion() -> None:
    scores = retriever.fuse([[7, 8], [7, 9]], k=60)
    assert scores[7] == pytest.approx(2 / 61)
    assert scores[8] == pytest.approx(1 / 62)
    assert scores[9] == pytest.approx(1 / 62)
    assert retriever.fuse([[], []]) == {}


def test_section_weights() -> None:
    rules = retriever.WeightRules(
        section_weights={"risk_factors": 1.5, "business": 0.8},
        latest_filings=frozenset({"AAPL_10K_2025-09-27"}),
    )
    risk = candidate()
    business = candidate(section="business")
    unknown = candidate(section="unknown")
    assert retriever.weigh(risk, rules) == pytest.approx(1.5)
    assert retriever.weigh(business, rules) == pytest.approx(0.8)
    assert retriever.weigh(unknown, rules) == pytest.approx(0.7)
    scores = {
        c.section: c.fused * retriever.weigh(c, rules)
        for c in [risk, business, unknown]
    }
    assert scores["risk_factors"] > scores["business"] > scores["unknown"]
    # A section outside the weights (the 10-K supplement) keeps 1.0, and
    # a filing other than the latest gets 0.9.
    other = candidate(section="controls", filing_id="AAPL_10Q_2025-06-28")
    assert retriever.weigh(other, rules) == pytest.approx(0.9)


def test_boilerplate_weight() -> None:
    rules = retriever.WeightRules(section_weights={"mdna": 1.0})
    prose = candidate(section="mdna")
    boiler = candidate(section="mdna", boilerplate_flag="forward_looking")
    assert retriever.weigh(boiler, rules) == pytest.approx(
        retriever.weigh(prose, rules) / 2
    )


def test_table_and_delta_weights() -> None:
    rules = retriever.WeightRules(
        section_weights={"risk_factors": 1.5},
        table_weight=1.3,
        risk_question=True,
    )
    table = candidate(is_table=True)
    delta = candidate(delta_only=True)
    assert retriever.weigh(table, rules) == pytest.approx(1.5 * 1.3 * 0.9)
    assert retriever.weigh(delta, rules) == pytest.approx(1.5 * 0.9 * 0.9)


def test_latest_filing_weight() -> None:
    original = candidate(
        chunk_id="NVDA_10K_2025-01-26__mdna__0003",
        filing_id="NVDA_10K_2025-01-26",
        ticker="NVDA",
        period_end_date="2025-01-26",
        filing_date="2025-02-26",
        section="mdna",
        text="NVIDIA | 10-K\nRevenue for fiscal year 2025 was $130,497.",
    )
    later = candidate(
        chunk_id="NVDA_10K_2026-01-25__mdna__0002",
        filing_id="NVDA_10K_2026-01-25",
        ticker="NVDA",
        fiscal_year=2026,
        period_end_date="2026-01-25",
        filing_date="2026-02-25",
        section="mdna",
        text="NVIDIA | 10-K\n| Revenue | Jan 25, 2026 | Jan 26, 2025 |",
    )
    found = retriever.later_comparatives([original, later])
    assert found == {later.chunk_id}
    rules = retriever.WeightRules(
        section_weights={"mdna": 1.5}, later_comparatives=found
    )
    assert retriever.weigh(later, rules) == pytest.approx(
        retriever.weigh(original, rules) * 1.05
    )
    # The fiscal year named in words counts as well.
    words = candidate(
        chunk_id="NVDA_10K_2026-01-25__mdna__0009",
        filing_id="NVDA_10K_2026-01-25",
        ticker="NVDA",
        period_end_date="2026-01-25",
        filing_date="2026-02-25",
        text="NVIDIA | 10-K\nRevenue grew from fiscal 2025 to fiscal 2026.",
    )
    assert retriever.later_comparatives([original, words]) == {words.chunk_id}
    assert retriever.later_comparatives([original]) == frozenset()


def test_simhash_collapse() -> None:
    earlier = candidate(
        chunk_id="AAPL_10Q_2025-06-28__risk_factors__0001",
        filing_id="AAPL_10Q_2025-06-28",
        filing_date="2025-08-01",
        simhash=0b1011,
    )
    later = candidate(simhash=0b1000)  # distance 2
    far = candidate(
        chunk_id="AAPL_10Q_2025-06-28__risk_factors__0002",
        filing_date="2025-08-01",
        simhash=0b1111_0000,  # distance 6 from both
    )
    other_section = candidate(
        chunk_id="AAPL_10K_2025-09-27__mdna__0001",
        section="mdna",
        simhash=0b1011,
    )
    kept, collapsed = retriever.collapse(
        [earlier, later, far, other_section], 3
    )
    assert collapsed == 1
    assert [c.chunk_id for c in kept] == [
        later.chunk_id,
        far.chunk_id,
        other_section.chunk_id,
    ]
    # A later chunk outside the window yields to the one in the window.
    outside = candidate(simhash=0b1000, in_window=False)
    kept, collapsed = retriever.collapse([earlier, outside], 3)
    assert [c.chunk_id for c in kept] == [earlier.chunk_id]


def test_comparison_plan(understander: understanding.Understander) -> None:
    result = plan(
        understander,
        "What are the primary risk factors facing Apple, Tesla, and "
        "JPMorgan, and how do they compare?",
    )
    assert [g.key for g in result.groups] == ["AAPL", "TSLA", "JPM"]
    assert {g.quota for g in result.groups} == {16}
    assert {g.token_quota for g in result.groups} == {32000 // 3}
    assert len(result.sub_queries) == 3
    query = result.sub_queries[0]
    assert query.filter.tickers == ("AAPL",)
    assert "risk factors" in query.terms
    assert "adversely affect" in query.terms
    assert query.dense_text.startswith("AAPL: What are the primary risk")
    clause, params = query.filter.where()
    assert "c.section = 'unknown'" in clause
    assert '"risk_factors"' in str(params[1])


def test_trend_cells(understander: understanding.Understander) -> None:
    question = (
        "How has NVIDIA's revenue and growth outlook changed over the last "
        "two years?"
    )
    result = plan(understander, question)
    labels = [g.label for g in result.groups]
    # Case B of chapter 11.8: 2 10-K cells and 6 10-Q cells, latest first.
    assert labels == [
        "NVDA Q3 FY2026 10-Q",
        "NVDA Q2 FY2026 10-Q",
        "NVDA Q1 FY2026 10-Q",
        "NVDA FY2025 10-K",
        "NVDA Q3 FY2025 10-Q",
        "NVDA Q2 FY2025 10-Q",
        "NVDA Q1 FY2025 10-Q",
        "NVDA FY2024 10-K",
    ]
    assert {g.quota for g in result.groups} == {6}
    assert all(len(q.filter.filing_ids) == 1 for q in result.sub_queries)
    assert "(NVDA FY2025 10-K)" in result.sub_queries[3].dense_text
    assert "NVIDIA Corporation" in result.sub_queries[3].dense_text
    assert not result.gaps
    # A small budget still gives each 10-K at least 4 chunks.
    small = plan(understander, question, context.Budget(max_chunks=16))
    quotas = {g.label: g.quota for g in small.groups}
    assert quotas["NVDA FY2025 10-K"] == 4
    assert quotas["NVDA FY2024 10-K"] == 4
    assert quotas["NVDA Q3 FY2026 10-Q"] == 2
    # Filled, each 10-K cell gets its 4 chunks within the 16.
    pool = [
        candidate(
            chunk_id=f"{g.key}__mdna__{k:04d}",
            ticker="NVDA",
            group=g.key,
            score=1 - k / 100,
        )
        for g in small.groups
        for k in range(10)
    ]
    built = context.build_context(
        pool,
        small.groups,
        context.Budget(max_chunks=16),
        company_order=["NVDA"],
        section_weights={"mdna": 1.5},
    )
    taken = {f.label: f.taken for f in built.fills}
    assert taken["NVDA FY2025 10-K"] == 4
    assert taken["NVDA FY2024 10-K"] == 4
    assert len(built.chunks) == 16


def test_trend_cells_without_window() -> None:
    filings = [ref("NVDA", *row) for row in NVDA]
    cells = retriever.trend_cells(filings, None)
    assert [c.form for c in cells] == ["10-Q", "10-K", "10-K", "10-K", "10-K"]
    assert cells[0].period_end_date == datetime.date(2025, 10, 26)


def test_single_10k_trend_gap(
    understander: understanding.Understander,
) -> None:
    result = plan(
        understander, "How has Merck's revenue trended over the last 3 years?"
    )
    assert [g.label for g in result.groups] == ["MRK FY2024 10-K"]
    assert result.groups[0].quota == 48
    assert result.gaps == (
        "MRK has 1 10-K in the window, so the filings show no multi-year "
        "trend for it",
    )


def test_sector_plan(understander: understanding.Understander) -> None:
    result = plan(
        understander,
        "What regulatory risks do the major pharmaceutical companies face, "
        "and how are they addressing them?",
    )
    assert result.sector
    # The question asks how the companies address the risks, so a third
    # of each quota of 9 goes to a response group (stage 8).
    tickers = ["PFE", "JNJ", "MRK", "LLY", "ABBV"]
    assert [g.key for g in result.groups] == [
        key for t in tickers for key in (t, f"{t} response")
    ]
    assert [g.quota for g in result.groups] == [6, 3] * 5
    assert {g.token_quota for g in result.groups} == {None}
    assert "FDA" in result.sub_queries[0].terms
    response = [q for q in result.sub_queries if q.label.endswith("response")]
    assert [q.group for q in response] == [f"{t} response" for t in tickers]
    assert {q.filter.sections for q in response} == {
        ("business", "mdna", "legal_proceedings")
    }
    assert {q.filter.tickers for q in response} == {(t,) for t in tickers}
    # Without a response word the company keeps 1 group of 9.
    risks = plan(
        understander,
        "What regulatory risks do the major pharmaceutical companies face?",
    )
    assert [g.quota for g in risks.groups] == [9] * 5
    assert len(risks.sub_queries) == 5


def test_response_reserve_on_a_comparison(
    understander: understanding.Understander,
) -> None:
    result = plan(
        understander,
        "What are the risk factors of Apple and Tesla, and how do they "
        "mitigate them?",
    )
    assert [g.key for g in result.groups] == [
        "AAPL",
        "AAPL response",
        "TSLA",
        "TSLA response",
    ]
    # 24 chunks and 16,000 tokens per company, a third reserved.
    assert [g.quota for g in result.groups] == [16, 8, 16, 8]
    assert [g.token_quota for g in result.groups] == [
        10_667,
        5_333,
        10_667,
        5_333,
    ]
    # A question that is not about risks never reserves.
    revenue = plan(
        understander,
        "How do Apple and Tesla revenues compare, and how did they respond?",
    )
    assert len(revenue.groups) == 2


def test_risk_supplement_plan(
    understander: understanding.Understander,
) -> None:
    # The window holds only the 2 PFE 10-Qs of 2025; the latest 10-K is
    # added for its risk factors.
    result = plan(understander, "What risks did Pfizer report in 2025?")
    labels = [q.label for q in result.sub_queries]
    assert labels == ["PFE", "PFE latest 10-K risk factors"]
    extra = result.sub_queries[1]
    assert not extra.in_window
    assert extra.group == "PFE"
    assert extra.filter.filing_ids == ("PFE_10K_2024-12-31",)
    assert extra.filter.sections == ("risk_factors",)
    # A question that is not about risks gets no supplement.
    revenue = plan(understander, "What was Pfizer's revenue in 2025?")
    assert len(revenue.sub_queries) == 1


def test_generic_and_out_of_scope_plans(
    understander: understanding.Understander,
) -> None:
    generic = plan(understander, "Which companies discuss supply chain?")
    assert generic.generic
    assert len(generic.sub_queries) == 1
    assert generic.sub_queries[0].filter.tickers == ()
    assert plan(understander, "What is the weather in Paris?") == (
        retriever.Plan(sub_queries=(), groups=())
    )


def test_cap_companies() -> None:
    tickers = [f"T{n:02d}" for n in range(20)]
    pool = [
        candidate(ticker=t, chunk_id=f"{t}_{k}", score=float(n + k))
        for n, t in enumerate(tickers)
        for k in range(5)
    ]
    kept, dropped = retriever.cap_companies(pool, tickers, 12, 4)
    assert kept == tickers[8:]
    assert dropped == tickers[:8]
    assert retriever.cap_companies(pool, tickers[:3], 12, 4) == (
        tickers[:3],
        [],
    )


def test_lexical_terms() -> None:
    terms = retriever.lexical_terms(["revenue", "risks"], SYNONYMS, "")
    assert terms == (
        "revenue",
        "net sales",
        "revenues",
        "risks",
        "risk factors",
        "adversely affect",
    )
    words = retriever.lexical_terms([], SYNONYMS, "What does Apple say?")
    assert words == ("apple", "say")


def test_is_risk_question(understander: understanding.Understander) -> None:
    assert retriever.is_risk_question(
        understander.analyze("What risks does Apple face?")
    )
    assert not retriever.is_risk_question(
        understander.analyze("What was Apple's revenue?")
    )


def test_rerank_share() -> None:
    assert retriever.rerank_share(80, 1) == 80
    assert retriever.rerank_share(80, 3) == 26
    assert retriever.rerank_share(80, 0) == 80
    assert retriever.rerank_share(27, 53) == 1


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def predict(self, pairs: Any, **kwargs: Any) -> list[float]:
        self.calls.append((pairs, kwargs))
        return [0.0, 2.0, -2.0][: len(pairs)]


def test_cross_encoder_scores_are_probabilities() -> None:
    model = FakeModel()
    reranker = retriever.CrossEncoderReranker(model=model)
    scores = reranker.score([("q", "a"), ("q", "b"), ("q", "c")])
    assert scores[0] == pytest.approx(0.5)
    assert scores[1] == pytest.approx(0.8808, abs=1e-4)
    assert scores[2] == pytest.approx(0.1192, abs=1e-4)
    assert reranker.score([]) == []
    assert model.calls[0][1]["show_progress_bar"] is False


def test_cross_encoder_load_failure(
    settings: config.Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("not in the cache")

    monkeypatch.setattr("sentence_transformers.CrossEncoder", fail)
    with pytest.raises(errors.ModelMissingError, match="download-models"):
        retriever.CrossEncoderReranker.from_settings(settings)


def test_superseded_standing_sections(
    understander: understanding.Understander,
) -> None:
    analysis = understander.analyze("What are Apple's main risks?")
    latest = candidate()
    older = candidate(
        chunk_id="AAPL_10K_2024-12-31__risk_factors__0001",
        filing_id="AAPL_10K_2024-12-31",
        period_end_date="2024-12-31",
    )
    older_mdna = candidate(
        chunk_id="AAPL_10K_2024-12-31__mdna__0001",
        filing_id="AAPL_10K_2024-12-31",
        period_end_date="2024-12-31",
        section="mdna",
    )
    quarter = candidate(
        chunk_id="AAPL_10Q_2025-06-28__risk_factors__0001",
        filing_id="AAPL_10Q_2025-06-28",
        form="10-Q",
        period_end_date="2025-06-28",
    )
    found = [latest, older, older_mdna, quarter]
    rules = retriever.weight_rules(analysis, understander.catalog, found)
    assert rules.superseded_filings == {
        "AAPL_10K_2024-12-31",
        "AAPL_10Q_2025-06-28",
    }
    risk = analysis.section_weights["risk_factors"]
    assert retriever.weigh(latest, rules) == pytest.approx(risk)
    assert retriever.weigh(older, rules) == pytest.approx(risk * 0.9 * 0.6)
    # MD&A of an earlier year is not restated, so it keeps the 0.9 only.
    mdna = analysis.section_weights["mdna"]
    assert retriever.weigh(older_mdna, rules) == pytest.approx(mdna * 0.9)
    # A time scope or a trend keeps the earlier filings at full weight.
    for question in [
        "What were Apple's risks in fiscal 2024?",
        "How have Apple's risk factors changed?",
    ]:
        scoped = understander.analyze(question)
        rules = retriever.weight_rules(scoped, understander.catalog, found)
        assert not rules.superseded_filings


def test_quarter_in_year_weight(
    understander: understanding.Understander,
) -> None:
    analysis = understander.analyze(
        "What was NVIDIA's total revenue in fiscal 2025?"
    )
    annual = candidate(
        chunk_id="NVDA_10K_2025-01-26__mdna__0001",
        filing_id="NVDA_10K_2025-01-26",
        ticker="NVDA",
        period_end_date="2025-01-26",
        section="mdna",
    )
    quarter = candidate(
        chunk_id="NVDA_10Q_2024-10-27__mdna__0001",
        filing_id="NVDA_10Q_2024-10-27",
        ticker="NVDA",
        form="10-Q",
        period_end_date="2024-10-27",
        section="mdna",
    )
    rules = retriever.weight_rules(
        analysis, understander.catalog, [annual, quarter]
    )
    assert rules.quarter_filings == {
        "NVDA_10Q_2024-04-28",
        "NVDA_10Q_2024-07-28",
        "NVDA_10Q_2024-10-27",
    }
    assert retriever.weigh(quarter, rules) == pytest.approx(
        retriever.weigh(annual, rules) * 0.9 * 0.6
    )
    # A calendar year over the January year end of NVDA holds the 10-K of
    # fiscal 2024 (ended 2024-01-28) and the 10-Qs of fiscal 2025, which
    # that 10-K does not cover: they keep their weight.
    calendar = understander.analyze("What was NVIDIA's revenue in 2024?")
    assert calendar.time_scope.kind == "calendar_year"
    rules = retriever.weight_rules(calendar, understander.catalog, [quarter])
    assert not rules.quarter_filings
    # A year with no 10-K in the corpus keeps its quarters.
    later = understander.analyze(
        "What was NVIDIA's total revenue in fiscal 2026?"
    )
    rules = retriever.weight_rules(later, understander.catalog, [quarter])
    assert not rules.quarter_filings
