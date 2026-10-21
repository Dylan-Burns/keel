"""The context budget: quotas, order, and the token estimate (chapter 11.6).

The retriever hands over scored candidates, each in 1 quota group. This
module fills the groups in turn up to their quotas within the token and
chunk budget, moves the unused quota to the groups that still have
candidates, cuts an oversized table chunk at a row boundary, orders the
context, and renders the context index and the chunk elements of chapter
12.2. The token estimate is local: the chunk tokens times the calibration
factor plus the wrapper line; no provider call happens per question.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import datetime
import html
import logging
import math
import threading

logger = logging.getLogger(__name__)

WRAPPER_TOKENS = 60
MAX_CHUNK_TOKENS = 480
DRIFT_LIMIT = 0.10
NO_CONTEXT_MESSAGE = (
    "No filing text matched the question and its filters, so no answer "
    "was generated."
)


@dataclasses.dataclass(frozen=True)
class Candidate:  # pylint: disable=too-many-instance-attributes
    """1 retrieved chunk with its scores and its quota group.

    Attributes:
        chunk_id: The chunk ID.
        filing_id: The filing ID.
        ticker: The ticker.
        company: The company name from the header.
        form: `10-K` or `10-Q`.
        fiscal_year: The fiscal year, or None.
        fiscal_period: `FY`, `Q1` to `Q3`, or `unknown`.
        period_end_date: The ISO period end date.
        filing_date: The ISO filing date.
        section: The canonical section.
        item_label: The raw item label, or None.
        text: The chunk text with its prefix line.
        token_count: The tokens of `text`.
        is_table: True for a table part.
        delta_only: True for a 10-Q risk-factor chunk.
        boilerplate_flag: `forward_looking`, or None.
        simhash: The signed 64-bit SimHash.
        vector_row: The row in `vectors.npy`.
        group: The key of the quota group.
        query: The index of the sub-query that found the chunk.
        fused: The reciprocal rank fusion score.
        weight: The product of the chapter 11.1 weights.
        rerank: The reranker probability, or None when not reranked.
        score: The final score: the reranker or the fused score times the
            weight.
        in_window: False for a chunk outside the time window (the 10-K
            risk supplement).
    """

    chunk_id: str
    filing_id: str
    ticker: str
    company: str
    form: str
    fiscal_year: int | None
    fiscal_period: str | None
    period_end_date: str
    filing_date: str
    section: str
    item_label: str | None
    text: str
    token_count: int
    is_table: bool
    delta_only: bool
    boilerplate_flag: str | None
    simhash: int
    vector_row: int
    group: str = ""
    query: int = 0
    fused: float = 0.0
    weight: float = 1.0
    rerank: float | None = None
    score: float = 0.0
    in_window: bool = True

    @property
    def fiscal_label(self) -> str:
        """The fiscal label: `FY2025` or `Q3 FY2026` (the prefix line)."""
        if self.fiscal_year is None:
            return "unknown"
        if self.fiscal_period in {None, "FY", "unknown"}:
            return f"FY{self.fiscal_year}"
        return f"{self.fiscal_period} FY{self.fiscal_year}"

    @property
    def rank_key(self) -> tuple[bool, float, str]:
        """Sort key, best first: reranked before the rest, then score."""
        return (self.rerank is None, -self.score, self.chunk_id)


@dataclasses.dataclass(frozen=True)
class QuotaGroup:
    """1 quota group of chapter 11.3: a company, a period cell, or both.

    Attributes:
        key: The group key.
        ticker: The company of the group.
        label: A readable name, such as `NVDA FY2025 10-K`.
        quota: The chunk quota.
        token_quota: The token quota, or None for the budget alone.
    """

    key: str
    ticker: str
    label: str
    quota: int
    token_quota: int | None = None


@dataclasses.dataclass(frozen=True)
class Budget:
    """The context limits (chapter 11.6 step 1).

    Attributes:
        max_tokens: The estimated token limit of the context.
        max_chunks: The chunk limit.
        calibration_factor: The model tokens per embedding token.
    """

    max_tokens: int = 32000
    max_chunks: int = 48
    calibration_factor: float = 1.15

    def lowered(
        self, max_tokens: int | None = None, max_chunks: int | None = None
    ) -> Budget:
        """Lower the limits for 1 request, never above the config.

        Args:
            max_tokens: The requested token limit, or None.
            max_chunks: The requested chunk limit, or None.

        Returns:
            The budget with each limit at most the configured one.
        """
        return dataclasses.replace(
            self,
            max_tokens=min(self.max_tokens, max_tokens or self.max_tokens),
            max_chunks=min(self.max_chunks, max_chunks or self.max_chunks),
        )


def estimate_tokens(token_count: int, factor: float) -> int:
    """Estimate the model tokens of 1 chunk with its wrapper line.

    Args:
        token_count: The embedding-tokenizer count of the chunk text.
        factor: The calibration factor.

    Returns:
        `ceil(token_count * factor) + 60`.
    """
    return math.ceil(token_count * factor) + WRAPPER_TOKENS


def truncate_table(
    candidate: Candidate, limit: int = MAX_CHUNK_TOKENS
) -> tuple[Candidate, bool]:
    """Cut a table chunk over `limit` tokens at the last row that fits.

    The token count of the cut text is estimated from the share of
    characters kept, since the retriever does not load the tokenizer.

    Args:
        candidate: The candidate.
        limit: The token limit (chapter 11.6 step 6).

    Returns:
        The candidate, cut when needed, and True when it was cut.
    """
    if not candidate.is_table or candidate.token_count <= limit:
        return candidate, False
    lines = candidate.text.split("\n")
    allowed = len(candidate.text) * limit / candidate.token_count
    kept = lines[:2]  # the prefix line and the caption or first row
    used = len("\n".join(kept))
    for line in lines[2:]:
        if used + 1 + len(line) > allowed:
            break
        kept.append(line)
        used += 1 + len(line)
    if len(kept) == len(lines):
        return candidate, False
    text = "\n".join(kept)
    tokens = min(
        limit,
        math.ceil(candidate.token_count * len(text) / len(candidate.text)),
    )
    return dataclasses.replace(candidate, text=text, token_count=tokens), True


@dataclasses.dataclass(frozen=True)
class ContextChunk:
    """1 chunk of the context.

    Attributes:
        candidate: The candidate, with the cut text when truncated.
        truncated: True when the chunk was cut at a row boundary.
        estimated_tokens: The token estimate with the wrapper line.
    """

    candidate: Candidate
    truncated: bool
    estimated_tokens: int


@dataclasses.dataclass(frozen=True)
class GroupFill:
    """How 1 quota group filled.

    Attributes:
        key: The group key.
        label: The group label.
        quota: The chunk quota.
        taken: The chunks in the context.
        tokens: The estimated tokens of those chunks.
        candidates: The candidates the group had.
    """

    key: str
    label: str
    quota: int
    taken: int
    tokens: int
    candidates: int


@dataclasses.dataclass(frozen=True)
class Context:
    """The context of 1 question (chapter 11.6 steps 8 to 11).

    Attributes:
        chunks: The chunks in context order.
        token_estimate: The estimated tokens of the chunks and wrappers.
        collapsed: The near-duplicates the retriever collapsed.
        dropped: The candidates left out of the context.
        fills: The fill of each quota group, in group order.
        budget: The budget used.
    """

    chunks: tuple[ContextChunk, ...]
    token_estimate: int
    collapsed: int
    dropped: int
    fills: tuple[GroupFill, ...]
    budget: Budget

    @property
    def empty(self) -> bool:
        """True when no chunk passed: the no-context response, no call."""
        return not self.chunks

    def sections(self) -> dict[str, int]:
        """Count the chunks per section, most frequent first.

        Returns:
            The chunk count per section.
        """
        counts: dict[str, int] = {}
        for chunk in self.chunks:
            section = chunk.candidate.section
            counts[section] = counts.get(section, 0) + 1
        return dict(
            sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        )


@dataclasses.dataclass
class _Fill:
    group: QuotaGroup
    queue: list[Candidate]
    taken: list[ContextChunk] = dataclasses.field(default_factory=list)
    tokens: int = 0
    candidates: int = 0


def _fill_groups(
    fills: Sequence[_Fill], budget: Budget, *, quotas: bool
) -> None:
    """Take candidates round-robin until the quotas or the budget stop it.

    Args:
        fills: The groups with their remaining candidates, in turn order.
        budget: The budget.
        quotas: True for the quota pass (step 4); False for the pass that
            moves the unused quota to the groups with candidates (step 7).
    """
    used_tokens = sum(f.tokens for f in fills)
    used_chunks = sum(len(f.taken) for f in fills)
    active = True
    while active and used_chunks < budget.max_chunks:
        active = False
        for fill in fills:
            if used_chunks >= budget.max_chunks:
                break
            if quotas and len(fill.taken) >= fill.group.quota:
                continue
            token_room = budget.max_tokens - used_tokens
            if quotas and fill.group.token_quota is not None:
                token_room = min(
                    token_room, fill.group.token_quota - fill.tokens
                )
            # Step 5: skip what does not fit, take the next that does. A
            # skipped candidate stays queued: the next pass may have room.
            for position, queued in enumerate(fill.queue):
                candidate, truncated = truncate_table(queued)
                cost = estimate_tokens(
                    candidate.token_count, budget.calibration_factor
                )
                if cost <= token_room:
                    del fill.queue[position]
                    fill.taken.append(ContextChunk(candidate, truncated, cost))
                    fill.tokens += cost
                    used_tokens += cost
                    used_chunks += 1
                    active = True
                    break


def _order_key(
    chunk: ContextChunk,
    company_order: Mapping[str, int],
    section_weights: Mapping[str, float],
) -> tuple[int, int, float, bool, float, str]:
    """Step 8: company, period from the latest, section weight, score."""
    candidate = chunk.candidate
    try:
        period = datetime.date.fromisoformat(candidate.period_end_date)
    except ValueError:
        period = datetime.date.min
    return (
        company_order.get(candidate.ticker, len(company_order)),
        -period.toordinal(),
        -section_weights.get(candidate.section, 1.0),
        candidate.rerank is None,
        -candidate.score,
        candidate.chunk_id,
    )


def build_context(
    candidates: Sequence[Candidate],
    groups: Sequence[QuotaGroup],
    budget: Budget,
    *,
    company_order: Sequence[str],
    section_weights: Mapping[str, float],
    collapsed: int = 0,
) -> Context:
    """Fill the quota groups within the budget (chapter 11.6).

    Args:
        candidates: The candidates after the collapse, each with a group.
        groups: The quota groups, in turn order.
        budget: The budget.
        company_order: The tickers in question order.
        section_weights: The section weights of the question.
        collapsed: The near-duplicates the retriever collapsed.

    Returns:
        The context; empty when no candidate fits.
    """
    fills = {group.key: _Fill(group=group, queue=[]) for group in groups}
    for candidate in sorted(candidates, key=lambda c: c.rank_key):
        fill = fills.get(candidate.group)
        if fill is not None:
            fill.queue.append(candidate)
            fill.candidates += 1
    ordered = list(fills.values())
    _fill_groups(ordered, budget, quotas=True)
    _fill_groups(ordered, budget, quotas=False)
    order = {ticker: i for i, ticker in enumerate(company_order)}
    chunks = sorted(
        (chunk for fill in ordered for chunk in fill.taken),
        key=lambda c: _order_key(c, order, section_weights),
    )
    return Context(
        chunks=tuple(chunks),
        token_estimate=sum(c.estimated_tokens for c in chunks),
        collapsed=collapsed,
        dropped=len(candidates) - len(chunks),
        fills=tuple(
            GroupFill(
                key=f.group.key,
                label=f.group.label,
                quota=f.group.quota,
                taken=len(f.taken),
                tokens=f.tokens,
                candidates=f.candidates,
            )
            for f in ordered
        ),
        budget=budget,
    )


def render_index(context: Context) -> str:
    """Render the context index: 1 line per chunk (step 9, chapter 12.2).

    Args:
        context: The context.

    Returns:
        The lines `{chunk_id} | {ticker} | {form} | {fiscal} | {section} |
        filed {date}`.
    """
    return "\n".join(
        f"{c.candidate.chunk_id} | {c.candidate.ticker} | {c.candidate.form} "
        f"| {c.candidate.fiscal_label} | {c.candidate.section} | filed "
        f"{c.candidate.filing_date}"
        for c in context.chunks
    )


def _attribute(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_chunk(chunk: ContextChunk) -> str:
    """Render 1 `<chunk>` element with its 11 attributes (chapter 12.2).

    The chunk text is untrusted: a closing tag inside it is neutralized so
    the text cannot end its element.

    Args:
        chunk: The context chunk.

    Returns:
        The element.
    """
    c = chunk.candidate
    attributes = {
        "id": c.chunk_id,
        "ticker": c.ticker,
        "company": c.company,
        "form": c.form,
        "fiscal": c.fiscal_label,
        "period_end": c.period_end_date,
        "filed": c.filing_date,
        "section": c.section,
        "item": c.item_label or "",
        "is_table": str(c.is_table).lower(),
        "delta_only": str(c.delta_only).lower(),
        "truncated": str(chunk.truncated).lower(),
    }
    head = " ".join(f'{k}="{_attribute(v)}"' for k, v in attributes.items())
    body = c.text.replace("</chunk", "&lt;/chunk")
    return f"<chunk {head}>\n{body}\n</chunk>"


def render_chunks(context: Context) -> str:
    """Render every chunk element in context order.

    Args:
        context: The context.

    Returns:
        The elements joined by newlines.
    """
    return "\n".join(render_chunk(c) for c in context.chunks)


class Calibration:
    """The session calibration factor (chapter 11.6 step 2, E-C-13).

    The factor starts at the configured value. When the real input tokens
    of a request differ from the estimate by more than 10%, the factor
    scales by their ratio for the rest of the session and the drift is
    logged. The class is thread-safe; 2 requests may report at once.

    Args:
        factor: The starting factor.
    """

    def __init__(self, factor: float) -> None:
        self._factor = factor
        self._lock = threading.Lock()

    @property
    def factor(self) -> float:
        """The current factor."""
        with self._lock:
            return self._factor

    def observe(self, estimated: int, actual: int) -> float:
        """Compare an estimate with the provider count and adjust.

        Args:
            estimated: The estimated input tokens of the request.
            actual: The input tokens the provider reported.

        Returns:
            The factor after the observation.
        """
        if estimated <= 0 or actual <= 0:
            return self.factor
        drift = (actual - estimated) / estimated
        with self._lock:
            if abs(drift) > DRIFT_LIMIT:
                before = self._factor
                self._factor = round(before * actual / estimated, 4)
                logger.warning(
                    "token estimate drift %.1f%%: calibration factor %.4f "
                    "-> %.4f",
                    drift * 100,
                    before,
                    self._factor,
                )
            return self._factor
