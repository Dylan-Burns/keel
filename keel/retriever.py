"""Hybrid retrieval: filters, fusion, weights, rerank, collapse (chapter 11).

For each sub-query of the plan the retriever reads the top rows of the FTS5
index and of the dense index under 1 metadata filter, fuses the 2 lists
with reciprocal rank fusion, multiplies the fused score by the chapter 11.1
weights, reranks the top candidates of each sub-query with the pinned
cross-encoder, and collapses near-duplicate boilerplate by SimHash. The
context module then fills the quota groups within the budget.

No LLM call happens here (decision D-02). The 2 models load once per
process. Without the embedding model the retriever runs lexical only and
reports `degraded_retrieval` (E-F-11); without the reranker it ranks by the
weighted fused score.
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import datetime
import json
import logging
import math
import pathlib
import re
import sqlite3
import time
from typing import Any
from typing import Protocol

import numpy

from keel import chunker
from keel import config
from keel import context
from keel import errors
from keel import indexer
from keel import understanding
from keel.stores import chunk_store
from keel.stores import numpy_dense
from keel.stores import sqlite_fts

logger = logging.getLogger(__name__)

UNKNOWN_SECTION_WEIGHT = 0.7
BOILERPLATE_WEIGHT = 0.5
LATEST_FILING_WEIGHT = 1.0
OTHER_FILING_WEIGHT = 0.9
DELTA_ONLY_RISK_WEIGHT = 0.9
LATER_COMPARATIVE_WEIGHT = 1.05
SECTOR_MAX_COMPANIES = 12
SECTOR_MIN_QUOTA = 3
GENERIC_QUOTA = 4
TREND_MIN_QUOTA = 2
TREND_10K_MIN_QUOTA = 4
DEGRADED_RETRIEVAL = "degraded_retrieval"
RERANKER_UNAVAILABLE = "reranker_unavailable"
RISK_SECTION = "risk_factors"
UNKNOWN_SECTION = "unknown"

_FISCAL_YEAR = re.compile(r"(?i)\b(?:fiscal(?:\s+year)?|FY)\s*'?(20\d\d)\b")
_MONTH_TEXT = "jan feb mar apr may jun jul aug sep oct nov dec"
_MONTHS = _MONTH_TEXT.split()
_DATE = re.compile(
    r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2}),\s+(20\d\d)\b"
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
_STOP_TEXT = (
    "a an and are as at be by do does did for from has have how in is it "
    "its of on or over the their them they this to was what which who why "
    "with about between compare companies company face facing major "
    "primary last two years year been changed"
)
_STOP_WORDS = frozenset(_STOP_TEXT.split())

_ROW_COLUMNS = (
    "c.id, c.chunk_id, c.filing_id, c.ticker, c.company, c.form, "
    "c.fiscal_year, c.fiscal_period, c.period_end_date, c.filing_date, "
    "c.section, c.item_label, c.text, c.token_count, c.is_table, "
    "c.delta_only, c.boilerplate_flag, c.simhash, c.vector_row"
)


# --- Models -------------------------------------------------------------------


class Reranker(Protocol):
    """Scores (query, passage) pairs; higher is more relevant."""

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Score pairs.

        Args:
            pairs: (query, passage) pairs.

        Returns:
            1 probability in (0, 1) per pair.
        """


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


@dataclasses.dataclass(frozen=True)
class CrossEncoderReranker:
    """The pinned cross-encoder on the CPU (decision D-10).

    Attributes:
        model: The loaded `CrossEncoder`.
        batch_size: The predict batch size.
    """

    model: Any
    batch_size: int = 32

    @classmethod
    def from_settings(cls, settings: config.Settings) -> CrossEncoderReranker:
        """Load `reranker.model` at `reranker.revision` from the HF cache.

        Uses only `CrossEncoder(name, revision=..., device=...)` and
        `.predict(pairs)`, which sentence-transformers 3.4 and 6 share
        (decision D-37).

        Args:
            settings: The loaded settings.

        Returns:
            The reranker.

        Raises:
            ModelMissingError: The model cannot load.
        """
        # Heavy (torch), so imported only when a reranker is needed.
        import sentence_transformers  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

        reranker = settings.reranker
        try:
            model = sentence_transformers.CrossEncoder(
                reranker.model, revision=reranker.revision, device="cpu"
            )
        # The hub client and torch raise unrelated error types.
        except Exception as error:  # pylint: disable=broad-exception-caught
            raise errors.ModelMissingError(
                f"cannot load {reranker.model} at {reranker.revision}: "
                f"{error}; run keel doctor --download-models"
            ) from error
        return cls(model=model)

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Score pairs; the logits pass through a sigmoid.

        The weights multiply the score, so it must be positive; the model
        returns raw logits under both library versions.

        Args:
            pairs: (query, passage) pairs.

        Returns:
            1 probability per pair.
        """
        if not pairs:
            return []
        logits = self.model.predict(
            [list(pair) for pair in pairs],
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        return [_sigmoid(float(v)) for v in numpy.asarray(logits).ravel()]


# --- The plan -----------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Filter:
    """The metadata filter of 1 sub-query (chapter 11.2).

    Attributes:
        tickers: The tickers, or empty for all.
        filing_ids: The filings, or empty for all.
        sections: The weighted sections; `unknown` always joins them. Empty
            means no section filter.
        windows: (ticker, start, end) ISO period end windows.
    """

    tickers: tuple[str, ...] = ()
    filing_ids: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()
    windows: tuple[tuple[str, str, str], ...] = ()

    def where(self) -> tuple[str, list[object]]:
        """Render the SQL `WHERE` clause over `chunks AS c`.

        Every value is a parameter; lists pass as JSON (the SQL text holds
        only fixed column names).

        Returns:
            The clause and its parameters.
        """
        clauses: list[str] = []
        params: list[object] = []
        if self.tickers:
            clauses.append("c.ticker IN (SELECT value FROM json_each(?))")
            params.append(json.dumps(list(self.tickers)))
        if self.filing_ids:
            clauses.append("c.filing_id IN (SELECT value FROM json_each(?))")
            params.append(json.dumps(list(self.filing_ids)))
        if self.sections:
            clauses.append(
                "(c.section IN (SELECT value FROM json_each(?)) "
                "OR c.section = 'unknown')"
            )
            params.append(json.dumps(list(self.sections)))
        if self.windows:
            parts = []
            for ticker, start, end in self.windows:
                parts.append(
                    "(c.ticker = ? AND c.period_end_date BETWEEN ? AND ?)"
                )
                params += [ticker, start, end]
            clauses.append("(" + " OR ".join(parts) + ")")
        return (" AND ".join(clauses) or "1"), params


@dataclasses.dataclass(frozen=True)
class SubQuery:
    """1 sub-query: a lexical and a dense query under 1 filter.

    Attributes:
        group: The quota group of its candidates; empty for the generic
            plan, where the company of each hit names the group.
        label: A readable name.
        dense_text: The dense query and the reranker query.
        terms: The lexical terms, joined with OR.
        filter: The metadata filter.
        in_window: False for the 10-K risk supplement outside the window.
    """

    group: str
    label: str
    dense_text: str
    terms: tuple[str, ...]
    filter: Filter
    in_window: bool = True


@dataclasses.dataclass(frozen=True)
class Plan:
    """The retrieval plan of 1 question (chapter 11.3).

    Attributes:
        sub_queries: The sub-queries.
        groups: The quota groups, in turn order.
        gaps: The coverage limits the plan already knows.
        generic: True when the groups come from the companies of the hits.
        sector: True for a sector question (the 12-company cap applies).
    """

    sub_queries: tuple[SubQuery, ...]
    groups: tuple[context.QuotaGroup, ...]
    gaps: tuple[str, ...] = ()
    generic: bool = False
    sector: bool = False


def lexical_terms(
    topic_terms: Sequence[str],
    synonyms: Mapping[str, Sequence[str]],
    question: str,
) -> tuple[str, ...]:
    """Expand the topic terms with the synonyms (chapter 9.3).

    A synonym entry applies when its key starts the term or the term,
    without a plural `s`, starts the key. Without topic terms the content
    words of the question stand in.

    Args:
        topic_terms: The topic terms of the analysis.
        synonyms: The synonym dictionary.
        question: The question.

    Returns:
        The terms without duplicates, in order.
    """
    found: list[str] = []

    def add(term: str) -> None:
        if term and term.lower() not in (t.lower() for t in found):
            found.append(term)

    for term in topic_terms:
        add(term)
        stem = term.lower().rstrip("s")
        for key, values in synonyms.items():
            if term.lower().startswith(key) or key.startswith(stem):
                for value in values:
                    add(value)
    if not found:
        for word in _WORD.findall(question):
            if word.lower() not in _STOP_WORDS and len(word) > 2:
                add(word.lower())
    return tuple(found)


def _company_quota(total: int, companies: int) -> int:
    return max(1, total // max(1, companies))


def _window(
    analysis: understanding.QuestionAnalysis, ticker: str
) -> tuple[str, str] | None:
    window = analysis.windows.get(ticker)
    if window is None:
        return None
    return window.start.isoformat(), window.end.isoformat()


def is_risk_question(analysis: understanding.QuestionAnalysis) -> bool:
    """Tell whether the question is about risks (chapter 11.1, 11.2).

    Args:
        analysis: The question analysis.

    Returns:
        True when `risk_factors` has the top section weight above 1.0.
    """
    weights = analysis.section_weights
    risk = weights.get(RISK_SECTION, 0.0)
    return risk > 1.0 and risk >= max(weights.values())


def _filings_in(
    filings: Sequence[understanding.FilingRef], window: tuple[str, str] | None
) -> list[understanding.FilingRef]:
    if window is None:
        return list(filings)
    start, end = window
    return [f for f in filings if start <= f.period_end_date.isoformat() <= end]


def latest_10k(
    filings: Sequence[understanding.FilingRef], window: tuple[str, str] | None
) -> understanding.FilingRef | None:
    """Return the latest 10-K at or before the window end.

    Args:
        filings: The filings of 1 company.
        window: The (start, end) window, or None.

    Returns:
        The filing, or None.
    """
    end = window[1] if window else "9999-12-31"
    annual = [
        f
        for f in filings
        if f.form == "10-K" and f.period_end_date.isoformat() <= end
    ]
    return max(annual, key=lambda f: f.period_end_date, default=None)


def trend_cells(
    filings: Sequence[understanding.FilingRef], window: tuple[str, str] | None
) -> list[understanding.FilingRef]:
    """Return the period cells of 1 company for a trend (chapter 11.3).

    A cell is 1 filing: 1 fiscal year of a 10-K or 1 quarter of a 10-Q in
    the window. Without a window the cells are every 10-K plus the latest
    10-Q.

    Args:
        filings: The filings of 1 company, earliest first.
        window: The (start, end) window, or None.

    Returns:
        The cell filings, latest first.
    """
    if window is not None:
        cells = _filings_in(filings, window)
    else:
        cells = [f for f in filings if f.form == "10-K"]
        quarters = [f for f in filings if f.form == "10-Q"]
        if quarters:
            cells.append(max(quarters, key=lambda f: f.period_end_date))
    return sorted(cells, key=lambda f: f.period_end_date, reverse=True)


def _cell_label(filing: understanding.FilingRef) -> str:
    if filing.fiscal_period in {"FY", "unknown"}:
        return f"{filing.ticker} FY{filing.fiscal_year} {filing.form}"
    return (
        f"{filing.ticker} {filing.fiscal_period} FY{filing.fiscal_year} "
        f"{filing.form}"
    )


def _cell_quota(filing: understanding.FilingRef, base: int) -> int:
    quota = max(TREND_MIN_QUOTA, base)
    if filing.form == "10-K":
        quota = max(TREND_10K_MIN_QUOTA, quota)
    return quota


@dataclasses.dataclass(frozen=True)
class _PlanInput:
    """What the plan builders share for 1 question."""

    analysis: understanding.QuestionAnalysis
    catalog: understanding.Catalog
    names: Mapping[str, str]
    terms: tuple[str, ...]
    budget: context.Budget

    @property
    def sections(self) -> tuple[str, ...]:
        return tuple(self.analysis.section_weights)

    def dense_text(self, ticker: str, label: str = "") -> str:
        name = self.names.get(ticker, ticker)
        text = f"{name}: {self.analysis.question}"
        return f"{text} ({label})" if label else text

    def company_query(self, ticker: str, group: str) -> SubQuery:
        window = _window(self.analysis, ticker)
        return SubQuery(
            group=group,
            label=ticker,
            dense_text=self.dense_text(ticker),
            terms=self.terms,
            filter=Filter(
                tickers=(ticker,),
                sections=self.sections,
                windows=((ticker, *window),) if window else (),
            ),
        )

    def supplement(
        self, ticker: str, group: str
    ) -> tuple[SubQuery, understanding.FilingRef] | None:
        """The latest 10-K risk chunks when the window leaves them out."""
        if not is_risk_question(self.analysis):
            return None
        window = _window(self.analysis, ticker)
        filings = self.catalog.for_ticker(ticker)
        annual = latest_10k(filings, window)
        if (
            window is None
            or annual is None
            or annual.filing_id is None
            or annual in _filings_in(filings, window)
        ):
            return None
        query = SubQuery(
            group=group,
            label=f"{ticker} latest 10-K risk factors",
            dense_text=self.dense_text(ticker, "latest 10-K risk factors"),
            terms=self.terms,
            filter=Filter(
                filing_ids=(annual.filing_id,), sections=(RISK_SECTION,)
            ),
            in_window=False,
        )
        return query, annual


def _trend_plan(
    data: _PlanInput, tickers: Sequence[str], company_total: int
) -> tuple[list[SubQuery], list[context.QuotaGroup], list[str]]:
    queries: list[SubQuery] = []
    groups: list[context.QuotaGroup] = []
    gaps: list[str] = []
    for ticker in tickers:
        window = _window(data.analysis, ticker)
        filings = data.catalog.for_ticker(ticker)
        cells = [c for c in trend_cells(filings, window) if c.filing_id]
        annual = sum(
            1 for f in _filings_in(filings, window) if f.form == "10-K"
        )
        if annual < 2:
            gaps.append(
                f"{ticker} has {annual} 10-K in the window, so the filings "
                f"show no multi-year trend for it"
            )
        if not cells:
            gaps.append(f"{ticker} has no filing in the window")
            continue
        extra = data.supplement(ticker, "")
        base = company_total // (len(cells) + (1 if extra else 0))
        for cell in cells:
            key = f"{ticker}|{cell.filing_id}"
            label = _cell_label(cell)
            groups.append(
                context.QuotaGroup(key, ticker, label, _cell_quota(cell, base))
            )
            queries.append(
                SubQuery(
                    group=key,
                    label=label,
                    dense_text=data.dense_text(ticker, label),
                    terms=data.terms,
                    filter=Filter(
                        filing_ids=(str(cell.filing_id),),
                        sections=data.sections,
                    ),
                )
            )
        if extra is not None:
            query, filing = extra
            key = f"{ticker}|{filing.filing_id}"
            groups.append(
                context.QuotaGroup(
                    key, ticker, query.label, _cell_quota(filing, base)
                )
            )
            queries.append(dataclasses.replace(query, group=key))
    return queries, groups, gaps


def build_plan(
    analysis: understanding.QuestionAnalysis,
    catalog: understanding.Catalog,
    *,
    names: Mapping[str, str],
    synonyms: Mapping[str, Sequence[str]],
    budget: context.Budget,
) -> Plan:
    """Turn the analysis into sub-queries and quota groups (11.2, 11.3).

    Args:
        analysis: The question analysis.
        catalog: The corpus facts with filing IDs.
        names: The company name per ticker, for the dense query.
        synonyms: The synonym dictionary for the lexical terms.
        budget: The budget, for the quotas.

    Returns:
        The plan; empty for an out-of-scope question.
    """
    if analysis.out_of_scope:
        return Plan(sub_queries=(), groups=())
    data = _PlanInput(
        analysis=analysis,
        catalog=catalog,
        names=names,
        terms=lexical_terms(analysis.topic_terms, synonyms, analysis.question),
        budget=budget,
    )
    tickers = list(analysis.tickers)
    kind = analysis.primary_type
    total = budget.max_chunks
    if kind == "generic" or not tickers:
        windows = tuple(
            (t, *w) for t in tickers if (w := _window(analysis, t)) is not None
        )
        query = SubQuery(
            group="",
            label="all companies" if not tickers else ", ".join(tickers),
            dense_text=analysis.question,
            terms=data.terms,
            filter=Filter(
                tickers=tuple(tickers),
                sections=data.sections,
                windows=windows,
            ),
        )
        return Plan(sub_queries=(query,), groups=(), generic=True)
    if "trend" in analysis.types:
        company_total = _company_quota(total, len(tickers))
        queries, groups, gaps = _trend_plan(data, tickers, company_total)
        return Plan(tuple(queries), tuple(groups), tuple(gaps))
    queries = []
    groups = []
    if kind == "sector":
        shown = min(len(tickers), SECTOR_MAX_COMPANIES)
        quota = max(SECTOR_MIN_QUOTA, total // shown)
        token_quota = None
    else:
        quota = _company_quota(total, len(tickers))
        token_quota = (
            budget.max_tokens // len(tickers) if len(tickers) > 1 else None
        )
    for ticker in tickers:
        groups.append(
            context.QuotaGroup(ticker, ticker, ticker, quota, token_quota)
        )
        queries.append(data.company_query(ticker, ticker))
        extra = data.supplement(ticker, ticker)
        if extra is not None:
            queries.append(extra[0])
    return Plan(tuple(queries), tuple(groups), sector=kind == "sector")


# --- Scores -------------------------------------------------------------------


def fuse(rankings: Sequence[Sequence[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion (chapter 11.1).

    Args:
        rankings: Lists of row IDs, best first.
        k: The RRF constant.

    Returns:
        The fused score per row ID: the sum of `1 / (k + rank)`, rank from
        1, over the lists that hold the row.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking, start=1):
            scores[row] = scores.get(row, 0.0) + 1.0 / (k + rank)
    return scores


@dataclasses.dataclass(frozen=True)
class WeightRules:
    """The facts the chapter 11.1 weights need for 1 question.

    Attributes:
        section_weights: The weight per section.
        table_weight: The weight of a table chunk (1.3 for numeric).
        risk_question: True for a question about risks.
        latest_filings: The filing IDs that get the latest-filing weight.
        later_comparatives: The chunk IDs that get the 1.05 weight.
    """

    section_weights: Mapping[str, float]
    table_weight: float = 1.0
    risk_question: bool = False
    latest_filings: frozenset[str] = frozenset()
    later_comparatives: frozenset[str] = frozenset()


def weigh(candidate: context.Candidate, rules: WeightRules) -> float:
    """Multiply the weights of chapter 11.1 and 11.5 for 1 candidate.

    Args:
        candidate: The candidate.
        rules: The facts of the question.

    Returns:
        The weight.
    """
    weights = rules.section_weights
    if candidate.section in weights:
        weight = weights[candidate.section]
    elif candidate.section == UNKNOWN_SECTION and weights:
        weight = UNKNOWN_SECTION_WEIGHT
    else:
        weight = 1.0
    if candidate.boilerplate_flag == "forward_looking":
        weight *= BOILERPLATE_WEIGHT
    if candidate.is_table:
        weight *= rules.table_weight
    weight *= (
        LATEST_FILING_WEIGHT
        if candidate.filing_id in rules.latest_filings
        else OTHER_FILING_WEIGHT
    )
    if candidate.delta_only and rules.risk_question:
        weight *= DELTA_ONLY_RISK_WEIGHT
    if candidate.chunk_id in rules.later_comparatives:
        weight *= LATER_COMPARATIVE_WEIGHT
    return weight


def _mentions(text: str) -> tuple[frozenset[int], frozenset[datetime.date]]:
    years = frozenset(int(m) for m in _FISCAL_YEAR.findall(text))
    dates: set[datetime.date] = set()
    for month, day, year in _DATE.findall(text):
        try:
            dates.add(
                datetime.date(
                    int(year), _MONTHS.index(month.lower()[:3]) + 1, int(day)
                )
            )
        except ValueError:
            continue
    return years, frozenset(dates)


def later_comparatives(
    candidates: Iterable[context.Candidate],
) -> frozenset[str]:
    """Find the candidates that restate a period of an earlier candidate.

    A candidate covers the period of a candidate from an earlier filing of
    the same company when its text names that period end date, or names
    the fiscal year of that earlier 10-K (chapter 11.5, E-D-17).

    Args:
        candidates: The candidates.

    Returns:
        The chunk IDs that get the later-filing weight of 1.05.
    """
    pool = list(candidates)
    periods: dict[str, set[tuple[str, str, int | None, str]]] = {}
    for c in pool:
        periods.setdefault(c.ticker, set()).add(
            (c.filing_date, c.period_end_date, c.fiscal_year, c.form)
        )
    found: set[str] = set()
    for c in pool:
        years, dates = _mentions(c.text)
        if not years and not dates:
            continue
        for filed, period, fiscal_year, form in periods[c.ticker]:
            if filed >= c.filing_date or period >= c.period_end_date:
                continue
            named = datetime.date.fromisoformat(period) in dates or (
                form == "10-K" and fiscal_year in years
            )
            if named:
                found.add(c.chunk_id)
                break
    return frozenset(found)


def collapse(
    candidates: Sequence[context.Candidate], max_distance: int = 3
) -> tuple[list[context.Candidate], int]:
    """Collapse near-duplicates of 1 company and section (chapter 11.4).

    Of a pair within `max_distance` SimHash bits, the chunk of the later
    filing stays, unless only the earlier one is in the time window.

    Args:
        candidates: The candidates.
        max_distance: The Hamming distance limit.

    Returns:
        The kept candidates in their input order, and the collapsed count.
    """
    preferred = sorted(
        candidates,
        key=lambda c: (
            not c.in_window,
            _descending(c.filing_date),
            c.rank_key,
        ),
    )
    kept: dict[tuple[str, str], list[context.Candidate]] = {}
    dropped: set[str] = set()
    for c in preferred:
        bucket = kept.setdefault((c.ticker, c.section), [])
        if any(
            chunker.hamming(c.simhash, k.simhash) <= max_distance
            for k in bucket
        ):
            dropped.add(c.chunk_id)
        else:
            bucket.append(c)
    return [c for c in candidates if c.chunk_id not in dropped], len(dropped)


def _descending(iso_date: str) -> int:
    try:
        return -datetime.date.fromisoformat(iso_date).toordinal()
    except ValueError:
        return 0


def cap_companies(
    candidates: Sequence[context.Candidate],
    tickers: Sequence[str],
    limit: int,
    per_company: int,
) -> tuple[list[str], list[str]]:
    """Keep the `limit` companies with the highest summed scores (11.3).

    Args:
        candidates: The candidates, each scored.
        tickers: The companies in question order.
        limit: The number of companies to keep.
        per_company: The top candidates of a company that count.

    Returns:
        The kept tickers and the dropped tickers, each in question order.
    """
    if len(tickers) <= limit:
        return list(tickers), []
    scores: dict[str, list[float]] = {t: [] for t in tickers}
    for c in candidates:
        if c.ticker in scores:
            scores[c.ticker].append(c.score)
    totals = {
        t: sum(sorted(s, reverse=True)[:per_company]) for t, s in scores.items()
    }
    ranked = sorted(tickers, key=lambda t: (-totals[t], t))
    keep = set(ranked[:limit])
    return (
        [t for t in tickers if t in keep],
        [t for t in tickers if t not in keep],
    )


def rerank_share(top_n: int, sub_queries: int) -> int:
    """Split the reranker's top N evenly over the sub-queries (D-10).

    The reranker scores the top 80 candidates of a question (decision D-10,
    chapter 6.3 step 7); each sub-query gets an equal share, so every quota
    group starts from reranked candidates.

    Args:
        top_n: `reranker.top_n`.
        sub_queries: The sub-queries with candidates.

    Returns:
        The candidates to rerank per sub-query.
    """
    return max(1, math.ceil(top_n / max(1, sub_queries)))


# --- The retriever ------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Timings:
    """Milliseconds spent per step.

    Attributes:
        lexical_ms: The FTS5 queries.
        dense_ms: The query embeddings and the dot products.
        rerank_ms: The cross-encoder.
        total_ms: The whole retrieval with the context build.
    """

    lexical_ms: float
    dense_ms: float
    rerank_ms: float
    total_ms: float


@dataclasses.dataclass(frozen=True)
class RetrievalResult:
    """The result of 1 retrieval.

    Attributes:
        plan: The plan, with the sector cap applied.
        context: The context.
        candidates: The candidates before the collapse.
        collapsed: The near-duplicates collapsed.
        reranked: The candidates the reranker scored.
        gaps: The coverage limits for the gaps of the answer.
        degraded: `degraded_retrieval` and `reranker_unavailable` notes.
        timings: The time per step.
    """

    plan: Plan
    context: context.Context
    candidates: int
    collapsed: int
    reranked: int
    gaps: tuple[str, ...]
    degraded: tuple[str, ...]
    timings: Timings


@dataclasses.dataclass
class _Clock:
    lexical: float = 0.0
    dense: float = 0.0
    rerank: float = 0.0


def _candidate(
    row: Sequence[Any], query: int, sub: SubQuery
) -> context.Candidate:
    return context.Candidate(
        chunk_id=row[1],
        filing_id=row[2],
        ticker=row[3],
        company=row[4],
        form=row[5],
        fiscal_year=row[6],
        fiscal_period=row[7],
        period_end_date=row[8],
        filing_date=row[9],
        section=row[10],
        item_label=row[11],
        text=row[12],
        token_count=int(row[13]),
        is_table=bool(row[14]),
        delta_only=bool(row[15]),
        boilerplate_flag=row[16],
        simhash=int(row[17]),
        vector_row=int(row[18]),
        group=sub.group or row[3],
        query=query,
        in_window=sub.in_window,
    )


class Retriever:
    """Hybrid retrieval over 1 published index.

    Args:
        conn: The read-only chunk store.
        vectors: The dense matrix, or None for lexical only.
        embedder: The query embedder, or None for lexical only.
        reranker: The reranker, or None to rank by the fused score.
        settings: The loaded settings.
        degraded: The notes of the models that did not load.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        conn: sqlite3.Connection,
        vectors: numpy_dense.Vectors | None,
        embedder: numpy_dense.Embedder | None,
        reranker: Reranker | None,
        settings: config.Settings,
        *,
        degraded: Sequence[str] = (),
    ) -> None:
        self.conn = conn
        self.vectors = vectors
        self.embedder = embedder if vectors is not None else None
        self.reranker = reranker
        self.settings = settings
        self.catalog = understanding.Catalog.from_store(conn)
        self.names = dict(
            conn.execute(
                "SELECT ticker, company FROM filings ORDER BY filing_id"
            )
        )
        synonyms = config.read_yaml(settings.dictionaries.synonyms)
        self.synonyms = {
            str(k).lower(): [str(v) for v in values]
            for k, values in synonyms.items()
            if isinstance(values, list)
        }
        notes = list(degraded)
        if self.embedder is None and DEGRADED_RETRIEVAL not in notes:
            notes.append(DEGRADED_RETRIEVAL)
        self.degraded = tuple(notes)

    @classmethod
    def open(
        cls,
        settings: config.Settings,
        index_dir: pathlib.Path | None = None,
        *,
        load_models: bool = True,
    ) -> Retriever:
        """Open the current build and load the 2 models once.

        Args:
            settings: The loaded settings.
            index_dir: The index directory with `current`, or None for
                `index.dir`.
            load_models: False skips both models (lexical only).

        Returns:
            The retriever.

        Raises:
            IndexMissingError: No published build.
        """
        directory = index_dir or settings.index.dir
        build = indexer.current_build(directory)
        if build is None:
            raise errors.IndexMissingError(
                f"no index at {directory}/current; run keel index"
            )
        conn = chunk_store.open_read_only(build / chunk_store.FILE_NAME)
        degraded: list[str] = []
        vectors = None
        embedder: numpy_dense.Embedder | None = None
        reranker: Reranker | None = None
        if load_models:
            try:
                vectors = numpy_dense.load(build / numpy_dense.FILE_NAME)
                embedder = numpy_dense.SentenceEmbedder.from_settings(settings)
            except errors.KeelError as error:
                logger.warning("lexical retrieval only: %s", error)
                degraded.append(DEGRADED_RETRIEVAL)
            if settings.reranker.enabled:
                try:
                    reranker = CrossEncoderReranker.from_settings(settings)
                except errors.ModelMissingError as error:
                    logger.warning("no reranker: %s", error)
                    degraded.append(RERANKER_UNAVAILABLE)
        return cls(
            conn, vectors, embedder, reranker, settings, degraded=degraded
        )

    def plan(
        self,
        analysis: understanding.QuestionAnalysis,
        budget: context.Budget,
    ) -> Plan:
        """Build the plan of a question.

        Args:
            analysis: The question analysis.
            budget: The budget.

        Returns:
            The plan.
        """
        return build_plan(
            analysis,
            self.catalog,
            names=self.names,
            synonyms=self.synonyms,
            budget=budget,
        )

    def _lexical(self, sub: SubQuery) -> list[int]:
        expression = sqlite_fts.match_expression(sub.terms)
        if not expression:
            return []
        where, params = sub.filter.where()
        rows = self.conn.execute(
            # The clause holds fixed column names; the values are parameters.
            "SELECT c.id FROM chunks_fts JOIN chunks AS c "  # noqa: S608
            "ON c.id = chunks_fts.rowid WHERE chunks_fts MATCH ? AND "
            + where
            + " ORDER BY bm25(chunks_fts), c.chunk_id LIMIT ?",
            [expression, *params, self.settings.retrieval.lexical_k],
        )
        return [int(row[0]) for row in rows]

    def _dense(self, sub: SubQuery) -> list[int]:
        if self.embedder is None or self.vectors is None:
            return []
        where, params = sub.filter.where()
        rows = [
            int(row[0])
            for row in self.conn.execute(
                "SELECT c.vector_row FROM chunks AS c WHERE "  # noqa: S608
                + where,
                params,
            )
        ]
        if not rows:
            return []
        query = numpy_dense.embed_query(self.embedder, sub.dense_text)
        hits = numpy_dense.top_k(
            self.vectors, query, self.settings.retrieval.dense_k, rows
        )
        return [row + 1 for row, _ in hits]  # the row ID is vector_row + 1

    def _rows(self, ids: Sequence[int]) -> dict[int, Sequence[Any]]:
        rows = self.conn.execute(
            f"SELECT {_ROW_COLUMNS} FROM chunks AS c "  # noqa: S608
            "WHERE c.id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(ids)),),
        )
        return {int(row[0]): row for row in rows}

    def _gather(self, plan: Plan, clock: _Clock) -> list[context.Candidate]:
        """Run every sub-query and fuse its 2 lists."""
        found: dict[str, context.Candidate] = {}
        for index, sub in enumerate(plan.sub_queries):
            started = time.perf_counter()
            lexical = self._lexical(sub)
            clock.lexical += time.perf_counter() - started
            started = time.perf_counter()
            dense = self._dense(sub)
            clock.dense += time.perf_counter() - started
            fused = fuse([lexical, dense], self.settings.retrieval.rrf_k)
            rows = self._rows(list(fused))
            for row_id, score in fused.items():
                candidate = dataclasses.replace(
                    _candidate(rows[row_id], index, sub), fused=score
                )
                known = found.get(candidate.chunk_id)
                if known is None or known.fused < score:
                    found[candidate.chunk_id] = candidate
        return list(found.values())

    def _rules(
        self,
        analysis: understanding.QuestionAnalysis,
        candidates: Sequence[context.Candidate],
    ) -> WeightRules:
        latest: set[str] = set()
        for ticker in {c.ticker for c in candidates}:
            window = _window(analysis, ticker)
            filings = self.catalog.for_ticker(ticker)
            scoped = _filings_in(filings, window)
            if scoped and scoped[-1].filing_id:
                latest.add(scoped[-1].filing_id)
            annual = latest_10k(filings, window)
            if annual is not None and annual.filing_id:
                latest.add(annual.filing_id)
        numeric = {"numeric", "trend"} & set(analysis.types)
        return WeightRules(
            section_weights=analysis.section_weights,
            table_weight=analysis.table_weight,
            risk_question=is_risk_question(analysis),
            latest_filings=frozenset(latest),
            later_comparatives=(
                later_comparatives(candidates) if numeric else frozenset()
            ),
        )

    def _rerank(
        self,
        queries: Sequence[SubQuery],
        candidates: list[context.Candidate],
        clock: _Clock,
    ) -> tuple[list[context.Candidate], int]:
        """Rerank the top weighted candidates of each sub-query.

        A candidate that a first round scored keeps its score; the call
        returns the count of new scores.
        """
        chosen: list[context.Candidate] = []
        if self.reranker is not None:
            by_query: dict[int, list[context.Candidate]] = {}
            for c in candidates:
                by_query.setdefault(c.query, []).append(c)
            share = rerank_share(self.settings.reranker.top_n, len(by_query))
            for group in by_query.values():
                group.sort(key=lambda c: (-c.fused * c.weight, c.chunk_id))
                chosen += [c for c in group[:share] if c.rerank is None]
        started = time.perf_counter()
        scores = (
            self.reranker.score(
                [(queries[c.query].dense_text, c.text) for c in chosen]
            )
            if self.reranker is not None and chosen
            else []
        )
        clock.rerank += time.perf_counter() - started
        reranked = {c.chunk_id: s for c, s in zip(chosen, scores, strict=True)}
        result = [
            c
            if c.chunk_id not in reranked
            else dataclasses.replace(
                c,
                rerank=reranked[c.chunk_id],
                score=reranked[c.chunk_id] * c.weight,
            )
            for c in candidates
        ]
        return result, len(reranked)

    def _cap(
        self,
        plan: Plan,
        analysis: understanding.QuestionAnalysis,
        candidates: list[context.Candidate],
        budget: context.Budget,
    ) -> tuple[Plan, list[context.Candidate], list[str]]:
        """Apply the 12-company sector cap and the generic groups."""
        tickers = (
            list(analysis.tickers)
            if not plan.generic or analysis.tickers
            else sorted({c.ticker for c in candidates})
        )
        if not (plan.sector or plan.generic):
            return plan, candidates, []
        per_company = (
            GENERIC_QUOTA
            if plan.generic
            else max(
                SECTOR_MIN_QUOTA, budget.max_chunks // SECTOR_MAX_COMPANIES
            )
        )
        kept, dropped = cap_companies(
            candidates, tickers, SECTOR_MAX_COMPANIES, per_company
        )
        gaps = [
            f"{t} is outside the {SECTOR_MAX_COMPANIES} companies with the "
            f"highest retrieval scores"
            for t in dropped
            if plan.sector
        ]
        keep = set(kept)
        if plan.generic:
            groups = tuple(
                context.QuotaGroup(t, t, t, GENERIC_QUOTA) for t in kept
            )
            plan = dataclasses.replace(plan, groups=groups)
        else:
            plan = dataclasses.replace(
                plan,
                groups=tuple(g for g in plan.groups if g.ticker in keep),
                sub_queries=tuple(
                    s
                    for s in plan.sub_queries
                    if set(s.filter.tickers) & keep or not s.filter.tickers
                ),
            )
        return plan, [c for c in candidates if c.ticker in keep], gaps

    def retrieve(
        self,
        analysis: understanding.QuestionAnalysis,
        budget: context.Budget | None = None,
    ) -> RetrievalResult:
        """Retrieve the context of 1 question (chapter 11).

        Args:
            analysis: The question analysis.
            budget: The budget, or None for the config values.

        Returns:
            The result; its context is empty when nothing matched, and the
            caller then returns the no-context response without a model
            request.
        """
        started = time.perf_counter()
        retrieval = self.settings.retrieval
        budget = budget or context.Budget(
            max_tokens=retrieval.max_context_tokens,
            max_chunks=retrieval.max_chunks,
            calibration_factor=retrieval.calibration_factor,
        )
        clock = _Clock()
        plan = self.plan(analysis, budget)
        candidates = self._gather(plan, clock)
        queries = plan.sub_queries  # the candidates index these
        rules = self._rules(analysis, candidates)
        candidates = [
            dataclasses.replace(
                c, weight=(w := weigh(c, rules)), score=c.fused * w
            )
            for c in candidates
        ]
        reranked = 0
        if plan.sector or plan.generic:
            # Reranker scores compare across sub-queries, fused ranks do
            # not, so the 12-company cap sums the scores of a first round.
            candidates, reranked = self._rerank(queries, candidates, clock)
        plan, candidates, cap_gaps = self._cap(
            plan, analysis, candidates, budget
        )
        candidates, more = self._rerank(queries, candidates, clock)
        reranked += more
        gathered = len(candidates)
        kept, collapsed = collapse(candidates, retrieval.simhash_max_distance)
        built = context.build_context(
            kept,
            plan.groups,
            budget,
            company_order=analysis.tickers,
            section_weights=analysis.section_weights,
            collapsed=collapsed,
        )
        empty = [
            f"{fill.label}: no filing text matched"
            for fill in built.fills
            if fill.candidates == 0
        ]
        return RetrievalResult(
            plan=plan,
            context=built,
            candidates=gathered,
            collapsed=collapsed,
            reranked=reranked,
            gaps=(*plan.gaps, *cap_gaps, *empty),
            degraded=self.degraded,
            timings=Timings(
                lexical_ms=round(clock.lexical * 1000, 1),
                dense_ms=round(clock.dense * 1000, 1),
                rerank_ms=round(clock.rerank * 1000, 1),
                total_ms=round((time.perf_counter() - started) * 1000, 1),
            ),
        )
