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
import os
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

CGROUP_CPU_MAX = pathlib.Path("/sys/fs/cgroup/cpu.max")

UNKNOWN_SECTION_WEIGHT = 0.7
BOILERPLATE_WEIGHT = 0.5
LATEST_FILING_WEIGHT = 1.0
OTHER_FILING_WEIGHT = 0.9
DELTA_ONLY_RISK_WEIGHT = 0.9
LATER_COMPARATIVE_WEIGHT = 1.05
# Stage 10 (eval): a 10-K restates Item 1 and Item 1A in full each year,
# so without a time scope an earlier filing's copy of those sections is
# superseded by the latest 10-K (chapter 10.4: no scope prefers the latest
# 10-K through weights). A question about a whole fiscal or calendar year
# is answered by the 10-K of that year, not by the quarters inside it.
STANDING_SECTIONS = ("risk_factors", "business")
SUPERSEDED_WEIGHT = 0.6
QUARTER_IN_YEAR_WEIGHT = 0.6
YEAR_SCOPES = frozenset({"fiscal_year", "calendar_year"})
SECTOR_MAX_COMPANIES = 12
SECTOR_MIN_QUOTA = 3
GENERIC_QUOTA = 4
TREND_MIN_QUOTA = 2
TREND_10K_MIN_QUOTA = 4
DEGRADED_RETRIEVAL = "degraded_retrieval"
RERANKER_UNAVAILABLE = "reranker_unavailable"
HYBRID = "hybrid"
LEXICAL = "lexical"
DENSE = "dense"
MODES = (HYBRID, LEXICAL, DENSE)
RISK_SECTION = "risk_factors"
UNKNOWN_SECTION = "unknown"
# A risk question that also asks how the companies respond reserves a third
# of each company quota for the sections where filings state their
# responses: Item 1 (the regulation subsection), MD&A, and legal
# proceedings (stage 8; the risk factor weights alone leave them out).
RESPONSE_SECTIONS = ("business", "mdna", "legal_proceedings")
RESPONSE_SHARE = 3
RESPONSE_LABEL = "response"
LATEST_LABEL = "latest 10-K"
_RESPONSE_WORDS = re.compile(
    r"(?i)\b(?:address(?:es|ed|ing)?|mitigat\w*|respond(?:s|ed|ing)?|"
    r"responses?|handl(?:e|es|ed|ing)|deal(?:s|ing)? with|"
    r"doing about|tackl(?:e|es|ing))\b"
)

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

ROW_COLUMNS = (
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


def set_max_length(model: object, tokens: int) -> None:
    """Cut each (query, passage) pair of the cross-encoder to `tokens`.

    sentence-transformers 6 names the attribute `max_seq_length` (a
    property); 3.4 reads a plain `max_length` (decision D-37).

    Args:
        model: The loaded `CrossEncoder`.
        tokens: The most tokens per pair.
    """
    if hasattr(type(model), "max_seq_length"):
        name = "max_seq_length"
    elif hasattr(model, "max_length"):
        name = "max_length"
    else:
        logger.warning(
            "reranker.max_length %d ignored: the cross-encoder has no "
            "max_seq_length or max_length",
            tokens,
        )
        return
    setattr(model, name, tokens)


def cpu_budget() -> int:
    """Count the CPUs this process may use.

    The affinity mask (where the platform has one) capped by the cgroup v2
    CPU quota, so a container with a quota below the host's CPUs gets
    its quota, not the host count that `os.cpu_count()` reports.

    Returns:
        The CPU count, at least 1.
    """
    count = (
        len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else os.cpu_count() or 1
    )
    try:
        quota, period = CGROUP_CPU_MAX.read_text(encoding="utf-8").split()
        if quota != "max":
            count = min(count, max(1, math.ceil(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return max(1, count)


def set_threads(threads: int) -> None:
    """Set the torch CPU threads; 0 means 1 per CPU of `cpu_budget`.

    torch starts with 1 thread per physical core, which is 1 on a host
    with 2 vCPUs; the second hyperthread cuts the rerank time by a fifth.
    The setting is per process and also covers the query embedding.

    Args:
        threads: The thread count, or 0 for `cpu_budget()`.
    """
    # Heavy, so imported only when a reranker is needed.
    import torch  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    torch.set_num_threads(threads or cpu_budget())


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
        (decision D-37). `reranker.threads` sets the torch threads of the
        whole process, so it also covers the query embedding.

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
        if reranker.max_length is not None:
            set_max_length(model, reranker.max_length)
        if reranker.threads is not None:
            set_threads(reranker.threads)
        return cls(model=model, batch_size=reranker.batch_size)

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
        sections: The weighted sections; `unknown` joins them unless
            `unknown` is False. Empty means no section filter.
        windows: (ticker, start, end) ISO period end windows.
        superseded: Filings whose `STANDING_SECTIONS` the filter leaves
            out: the filings before the latest 10-K of a company, for a
            question with no time scope.
        unknown: False leaves the `unknown` section out of a section
            filter (the 10-Q cells of a risk trend).
    """

    tickers: tuple[str, ...] = ()
    filing_ids: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()
    windows: tuple[tuple[str, str, str], ...] = ()
    superseded: tuple[str, ...] = ()
    unknown: bool = True

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
        if self.sections and not self.unknown:
            clauses.append("c.section IN (SELECT value FROM json_each(?))")
            params.append(json.dumps(list(self.sections)))
        elif self.sections:
            clauses.append(
                "(c.section IN (SELECT value FROM json_each(?)) "
                "OR c.section = 'unknown')"
            )
            params.append(json.dumps(list(self.sections)))
        if self.superseded:
            clauses.append(
                "NOT (c.filing_id IN (SELECT value FROM json_each(?)) "
                "AND c.section IN (SELECT value FROM json_each(?)))"
            )
            params.append(json.dumps(list(self.superseded)))
            params.append(json.dumps(list(STANDING_SECTIONS)))
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


def asks_for_response(analysis: understanding.QuestionAnalysis) -> bool:
    """Tell whether a risk question also asks how the companies respond.

    Args:
        analysis: The question analysis.

    Returns:
        True for a risk question with a response word, such as `how are
        they addressing them`.
    """
    return is_risk_question(analysis) and bool(
        _RESPONSE_WORDS.search(analysis.question)
    )


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


def _cell_minimum(filing: understanding.FilingRef) -> int:
    return TREND_10K_MIN_QUOTA if filing.form == "10-K" else 0


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
                superseded=self.superseded(ticker),
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

    @property
    def latest_first(self) -> bool:
        """True when the plan reads the latest 10-K first.

        This holds for every plan with company groups and no time scope
        (single company, numeric, and comparison) except a sector plan,
        which keeps 1 sub-query per company, so its first rerank round
        still scores every company of a large group. A trend plan has its
        own period cells.
        """
        return (
            self.analysis.time_scope.kind == "none"
            and self.analysis.primary_type != "sector"
        )

    def superseded(self, ticker: str) -> tuple[str, ...]:
        """The filings whose standing sections a question with no scope skips.

        The latest 10-K restates Item 1 and Item 1A in full, so without a
        time scope the earlier `risk_factors` and `business` chunks only
        take candidate rows from the latest ones (they weigh x0.54).
        """
        if not self.latest_first:
            return ()
        return tuple(
            sorted(superseded_filings(self.catalog.for_ticker(ticker)))
        )

    def cell_sections(self, cell: understanding.FilingRef) -> tuple[str, ...]:
        """The sections of 1 trend cell.

        A 10-Q states only the changes to its risk factors (chapter 11.2),
        so for a risk question a 10-Q cell reads its risk section alone,
        without `unknown`, and the quota and the rerank pairs it cannot
        use move to the 10-K cells instead of filling with MD&A or
        unclassified chunks.
        """
        if self.risk_delta_cell(cell):
            return (RISK_SECTION,)
        return self.sections

    def risk_delta_cell(self, cell: understanding.FilingRef) -> bool:
        """True for a 10-Q cell of a risk question (risk changes only)."""
        return cell.form == "10-Q" and is_risk_question(self.analysis)

    def latest_query(self, ticker: str, group: str) -> SubQuery | None:
        """The sub-query over the latest 10-K of a question with no scope.

        Without a time scope the company sub-query reads the top 100 rows
        of every filing of the company, and the earlier filings, which the
        weights rank down later, take most of them. This sub-query gives
        the latest 10-K its own top 100 rows, under the same sections and
        the same dense text, so the reranker sees its best chunks.
        """
        if not self.latest_first:
            return None
        annual = latest_10k(self.catalog.for_ticker(ticker), None)
        if annual is None or annual.filing_id is None:
            return None
        return SubQuery(
            group=group,
            label=f"{ticker} {LATEST_LABEL}",
            dense_text=self.dense_text(ticker),
            terms=self.terms,
            filter=Filter(
                tickers=(ticker,),
                filing_ids=(annual.filing_id,),
                sections=self.sections,
            ),
        )

    def response_query(self, ticker: str, group: str) -> SubQuery:
        """The sub-query over the sections that state responses."""
        window = _window(self.analysis, ticker)
        return SubQuery(
            group=group,
            label=f"{ticker} {RESPONSE_LABEL}",
            dense_text=self.dense_text(
                ticker, "how the company responds and what it does"
            ),
            terms=self.terms,
            filter=Filter(
                tickers=(ticker,),
                sections=RESPONSE_SECTIONS,
                windows=((ticker, *window),) if window else (),
            ),
        )


def _company_groups(
    data: _PlanInput, ticker: str, quota: int, token_quota: int | None
) -> tuple[list[SubQuery], list[context.QuotaGroup]]:
    """The sub-queries and quota groups of 1 company (chapter 11.3).

    A question that asks how the companies respond to their risks splits
    the company quota: a third goes to a response group over
    `RESPONSE_SECTIONS`, the rest stays with the risk group. A trend plan
    keeps its period cells and has no response group.
    """
    queries = [data.company_query(ticker, ticker)]
    extra = data.supplement(ticker, ticker)
    if extra is not None:
        queries.append(extra[0])
    latest = data.latest_query(ticker, ticker)
    if latest is not None:
        queries.append(latest)
    reserve = quota // RESPONSE_SHARE
    if not asks_for_response(data.analysis) or reserve < 1:
        group = context.QuotaGroup(ticker, ticker, ticker, quota, token_quota)
        return queries, [group]
    key = f"{ticker} {RESPONSE_LABEL}"
    reserved: int | None = None
    rest: int | None = None
    if token_quota is not None:
        reserved = token_quota * reserve // quota
        rest = token_quota - reserved
    queries.append(data.response_query(ticker, key))
    return queries, [
        context.QuotaGroup(ticker, ticker, ticker, quota - reserve, rest),
        context.QuotaGroup(key, ticker, key, reserve, reserved),
    ]


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
                context.QuotaGroup(
                    key,
                    ticker,
                    label,
                    _cell_quota(cell, base),
                    minimum=_cell_minimum(cell),
                )
            )
            queries.append(
                SubQuery(
                    group=key,
                    label=label,
                    dense_text=data.dense_text(ticker, label),
                    terms=data.terms,
                    filter=Filter(
                        filing_ids=(str(cell.filing_id),),
                        sections=data.cell_sections(cell),
                        unknown=not data.risk_delta_cell(cell),
                    ),
                )
            )
        if extra is not None:
            query, filing = extra
            key = f"{ticker}|{filing.filing_id}"
            groups.append(
                context.QuotaGroup(
                    key,
                    ticker,
                    query.label,
                    _cell_quota(filing, base),
                    minimum=_cell_minimum(filing),
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
        more, owned = _company_groups(data, ticker, quota, token_quota)
        queries += more
        groups += owned
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
        superseded_filings: The filings before the latest 10-K of a company
            with no time scope; their standing sections get x0.6 on top
            of the 0.9 of an earlier filing.
        quarter_filings: The 10-Qs inside a whole-year scope that the 10-K
            of that year covers; their chunks get x0.6.
    """

    section_weights: Mapping[str, float]
    table_weight: float = 1.0
    risk_question: bool = False
    latest_filings: frozenset[str] = frozenset()
    later_comparatives: frozenset[str] = frozenset()
    superseded_filings: frozenset[str] = frozenset()
    quarter_filings: frozenset[str] = frozenset()


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
    if (
        candidate.filing_id in rules.superseded_filings
        and candidate.section in STANDING_SECTIONS
    ):
        weight *= SUPERSEDED_WEIGHT
    if candidate.filing_id in rules.quarter_filings:
        weight *= QUARTER_IN_YEAR_WEIGHT
    return weight


def weight_rules(
    analysis: understanding.QuestionAnalysis,
    catalog: understanding.Catalog,
    candidates: Sequence[context.Candidate],
) -> WeightRules:
    """Collect the facts the weights of 1 question need (11.1, 11.5).

    Args:
        analysis: The question analysis.
        catalog: The corpus facts with filing IDs.
        candidates: The candidates of the question.

    Returns:
        The weight rules.
    """
    latest: set[str] = set()
    superseded: set[str] = set()
    quarters: set[str] = set()
    trend = "trend" in analysis.types
    unscoped = analysis.time_scope.kind == "none"
    year_scope = analysis.time_scope.kind in YEAR_SCOPES
    for ticker in {c.ticker for c in candidates}:
        window = _window(analysis, ticker)
        filings = catalog.for_ticker(ticker)
        scoped = _filings_in(filings, window)
        if scoped and scoped[-1].filing_id:
            latest.add(scoped[-1].filing_id)
        annual = latest_10k(filings, window)
        if annual is not None and annual.filing_id:
            latest.add(annual.filing_id)
        if trend:
            continue
        if unscoped:
            superseded |= superseded_filings(filings)
        elif year_scope and window is not None:
            quarters |= quarter_filings(filings, window)
    numeric = {"numeric", "trend"} & set(analysis.types)
    return WeightRules(
        section_weights=analysis.section_weights,
        table_weight=analysis.table_weight,
        risk_question=is_risk_question(analysis),
        latest_filings=frozenset(latest),
        later_comparatives=(
            later_comparatives(candidates) if numeric else frozenset()
        ),
        superseded_filings=frozenset(superseded),
        quarter_filings=frozenset(quarters),
    )


def superseded_filings(
    filings: Sequence[understanding.FilingRef],
) -> frozenset[str]:
    """The filings of 1 company that end before its latest 10-K.

    Args:
        filings: The filings of 1 company.

    Returns:
        Their filing IDs; empty without a 10-K.
    """
    annual = latest_10k(filings, None)
    if annual is None:
        return frozenset()
    return frozenset(
        f.filing_id
        for f in filings
        if f.filing_id and f.period_end_date < annual.period_end_date
    )


def quarter_filings(
    filings: Sequence[understanding.FilingRef], window: tuple[str, str]
) -> frozenset[str]:
    """The 10-Qs of a whole-year window that the 10-K in it covers.

    Only a 10-Q that ends on or before the period end of the 10-K in the
    window is part of that fiscal year: a calendar year scope over a
    company with a January year end holds the 10-K of the previous fiscal
    year and the 10-Qs of the next one, which keep their weight.

    Args:
        filings: The filings of 1 company.
        window: The (start, end) window of the year.

    Returns:
        Their filing IDs; empty when the window holds no 10-K.
    """
    scoped = _filings_in(filings, window)
    annual = latest_10k(scoped, None)
    if annual is None:
        return frozenset()
    return frozenset(
        f.filing_id
        for f in scoped
        if f.form == "10-Q"
        and f.filing_id
        and f.period_end_date <= annual.period_end_date
    )


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


def company_counts(
    before: Sequence[context.Candidate], after: Sequence[context.Candidate]
) -> tuple[tuple[str, int, int], ...]:
    """Count the candidates per company before and after the collapse.

    Args:
        before: The candidates before the near-duplicate collapse.
        after: The candidates the collapse kept.

    Returns:
        (ticker, before, after) per company, in first-seen order.
    """
    counts: dict[str, list[int]] = {}
    for c in before:
        counts.setdefault(c.ticker, [0, 0])[0] += 1
    for c in after:
        counts.setdefault(c.ticker, [0, 0])[1] += 1
    return tuple((t, n[0], n[1]) for t, n in counts.items())


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
    group starts from reranked candidates. With more sub-queries than N,
    each gets 1 and the caller stops at N.

    Args:
        top_n: The pairs left to score.
        sub_queries: The sub-queries with candidates.

    Returns:
        The candidates to rerank per sub-query.
    """
    return max(1, top_n // max(1, sub_queries))


def pick_for_rerank(
    groups: Sequence[Sequence[context.Candidate]],
    limit: int,
    *,
    fill: bool = True,
) -> list[context.Candidate]:
    """Choose the candidates the reranker scores (D-10).

    Each group (the unscored candidates of 1 sub-query) gives its top
    `rerank_share` candidates by weighted fused score. With `fill`, the
    pairs a small group leaves unused go to the groups with candidates
    left, in the same equal split, until `limit`; when fewer pairs remain
    than groups, the earlier groups get them.

    Args:
        groups: The candidates per sub-query, in sub-query order.
        limit: The most pairs to score.
        fill: Move the unused pairs; False keeps equal shares, as the
            first round of the sector cap needs.

    Returns:
        The chosen candidates, at most `limit`.
    """
    ordered = [
        sorted(g, key=lambda c: (-c.fused * c.weight, c.chunk_id))
        for g in groups
    ]
    share = rerank_share(limit, len(ordered))
    chosen = [c for g in ordered for c in g[:share]][:limit]
    rest = [g[share:] for g in ordered if len(g) > share]
    while fill and len(chosen) < limit and rest:
        more = rerank_share(limit - len(chosen), len(rest))
        for group in rest:
            chosen += group[:more]
            del group[:more]
        chosen = chosen[:limit]
        rest = [g for g in rest if g]
    return chosen


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


# The result has a field named `context`, which hides the module there.
_Candidate = context.Candidate


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
        ranked: The candidates after the collapse, best first (the label
            helper and the eval read them).
        per_company: (ticker, before, after) candidate counts around the
            near-duplicate collapse, for the trace drawer (chapter 25.1).
    """

    plan: Plan
    context: context.Context
    candidates: int
    collapsed: int
    reranked: int
    gaps: tuple[str, ...]
    degraded: tuple[str, ...]
    timings: Timings
    ranked: tuple[_Candidate, ...] = ()
    per_company: tuple[tuple[str, int, int], ...] = ()


@dataclasses.dataclass
class _Clock:
    """A private accumulator of 1 retrieval, never returned."""

    lexical: float = 0.0
    dense: float = 0.0
    rerank: float = 0.0


def candidate_from_row(
    row: Sequence[Any], query: int, sub: SubQuery
) -> context.Candidate:
    """Build a candidate from 1 row of `ROW_COLUMNS`.

    Args:
        row: The row.
        query: The index of the sub-query that found the chunk.
        sub: That sub-query.

    Returns:
        The candidate, unscored.
    """
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
        mode: `hybrid`, or `lexical` or `dense` alone for the ablation of
            chapter 18.7.

    Raises:
        ConfigError: An unknown mode.
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
        mode: str = HYBRID,
    ) -> None:
        if mode not in MODES:
            raise errors.ConfigError(f"unknown retrieval mode {mode!r}")
        self.mode = mode
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
        if not expression or self.mode == DENSE:
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
        if (
            self.embedder is None
            or self.vectors is None
            or self.mode == LEXICAL
        ):
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
            f"SELECT {ROW_COLUMNS} FROM chunks AS c "  # noqa: S608
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
                    candidate_from_row(rows[row_id], index, sub), fused=score
                )
                known = found.get(candidate.chunk_id)
                if known is None or known.fused < score:
                    found[candidate.chunk_id] = candidate
        return list(found.values())

    def _rerank(
        self,
        queries: Sequence[SubQuery],
        candidates: list[context.Candidate],
        clock: _Clock,
        limit: int,
        *,
        fill: bool = True,
    ) -> tuple[list[context.Candidate], int]:
        """Rerank the top weighted candidates of each sub-query.

        A candidate that an earlier round scored keeps its score; at most
        `limit` new pairs are scored, split evenly over the sub-queries,
        and with `fill` the share a sub-query cannot use goes to the
        others (the first round of the sector cap keeps equal shares, so
        the summed scores compare). The call returns the count of new
        scores.
        """
        chosen: list[context.Candidate] = []
        if self.reranker is not None and limit > 0:
            by_query: dict[int, list[context.Candidate]] = {}
            for c in candidates:
                if c.rerank is None:
                    by_query.setdefault(c.query, []).append(c)
            chosen = pick_for_rerank(list(by_query.values()), limit, fill=fill)
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
            return plan, [c for c in candidates if c.ticker in keep], gaps
        # The sub-queries of the dropped companies go; each candidate then
        # points at the index of its sub-query in the shorter tuple.
        owner = {g.key: g.ticker for g in plan.groups}
        kept_queries = [
            i
            for i, s in enumerate(plan.sub_queries)
            if owner.get(s.group, s.group) in keep
        ]
        index = {old: new for new, old in enumerate(kept_queries)}
        plan = dataclasses.replace(
            plan,
            groups=tuple(g for g in plan.groups if g.ticker in keep),
            sub_queries=tuple(plan.sub_queries[i] for i in kept_queries),
        )
        return (
            plan,
            [
                dataclasses.replace(c, query=index[c.query])
                for c in candidates
                if c.query in index
            ],
            gaps,
        )

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
        rules = weight_rules(analysis, self.catalog, candidates)
        candidates = [
            dataclasses.replace(
                c, weight=(w := weigh(c, rules)), score=c.fused * w
            )
            for c in candidates
        ]
        top_n = self.settings.reranker.top_n
        reranked = 0
        if plan.sector or plan.generic:
            # Reranker scores compare across sub-queries, fused ranks do
            # not, so the 12-company cap sums the scores of a first round;
            # both rounds share the top N of the question.
            candidates, reranked = self._rerank(
                plan.sub_queries, candidates, clock, top_n, fill=False
            )
        plan, candidates, cap_gaps = self._cap(
            plan, analysis, candidates, budget
        )
        candidates, more = self._rerank(
            plan.sub_queries, candidates, clock, top_n - reranked
        )
        reranked += more
        gathered = len(candidates)
        kept, collapsed = collapse(candidates, retrieval.simhash_max_distance)
        built = context.build_context(
            kept,
            plan.groups,
            budget,
            company_order=analysis.tickers
            or tuple(g.ticker for g in plan.groups),
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
            ranked=tuple(sorted(kept, key=lambda c: c.rank_key)),
            per_company=company_counts(candidates, kept),
        )
