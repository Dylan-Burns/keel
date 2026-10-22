"""The build-time calibration of the token estimate (chapter 11.6 step 2).

The context budget estimates the model tokens of a chunk from its
embedding-tokenizer count: `ceil(token_count x factor) + 60`. This module
measures the factor once: it renders a fixed sample of 200 chunks exactly
as the context renders them, sends them to the provider's token count
endpoint in 1 call (no text is generated), and solves the estimate for the
factor. The engineer writes the result into `retrieval.calibration_factor`;
no question ever calls the count endpoint (docs/GOTCHAS.md).
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import sqlite3
from typing import Any
from typing import Protocol

from keel import context
from keel import retriever

SAMPLE_SIZE = 200


class TokenCounter(Protocol):
    """Counts the input tokens of 1 user message for 1 model."""

    def __call__(self, model: str, text: str) -> int:
        """Count the tokens.

        Args:
            model: The model identifier.
            text: The user message text.

        Returns:
            The input tokens the provider reports.

        Raises:
            NotImplementedError: Always; a counter implements the call.
        """
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class Measurement:
    """The result of 1 calibration call.

    Attributes:
        chunks: The chunks in the sample.
        embedding_tokens: The sum of their embedding-tokenizer counts.
        counted_tokens: The input tokens the provider counted.
        factor: The calibration factor, rounded to 2 decimals up.
        estimate_before: The estimate of the sample with the old factor.
    """

    chunks: int
    embedding_tokens: int
    counted_tokens: int
    factor: float
    estimate_before: int


def sample_chunks(
    conn: sqlite3.Connection, size: int = SAMPLE_SIZE
) -> list[context.Candidate]:
    """Pick a fixed, spread-out sample of chunks from the store.

    The sample takes every k-th chunk by row ID, so 2 runs over 1 index
    pick the same chunks, and every company and section has its share.

    Args:
        conn: The chunk store.
        size: The sample size.

    Returns:
        The sampled chunks, in row order.
    """
    total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    step = max(1, int(total) // max(1, size))
    rows = conn.execute(
        f"SELECT {retriever.ROW_COLUMNS} FROM chunks AS c "  # noqa: S608
        "WHERE c.id % ? = 0 ORDER BY c.id LIMIT ?",
        (step, size),
    ).fetchall()
    query = retriever.SubQuery(
        group="", label="", dense_text="", terms=(), filter=retriever.Filter()
    )
    return [retriever.candidate_from_row(row, 0, query) for row in rows]


def render_sample(chunks: Sequence[context.Candidate]) -> str:
    """Render the sample as the `<context>` of a prompt renders it.

    Args:
        chunks: The sampled chunks.

    Returns:
        The chunk elements joined by newlines.
    """
    return "\n".join(
        context.render_chunk(
            context.ContextChunk(chunk, False, chunk.token_count)
        )
        for chunk in chunks
    )


def solve_factor(counted: int, token_counts: Sequence[int]) -> float:
    """Solve `counted = sum(token_count x factor + 60)` for the factor.

    The wrapper allowance of 60 tokens per chunk stays as chapter 11.6
    sets it; the factor absorbs any error in it. The result rounds up to 2
    decimals, so the estimate errs on the side of a smaller context.

    Args:
        counted: The tokens the provider counted for the rendered sample.
        token_counts: The embedding-tokenizer count of each chunk.

    Returns:
        The factor.

    Raises:
        ValueError: The sample is empty.
    """
    total = sum(token_counts)
    if total <= 0:
        raise ValueError("the calibration sample holds no tokens")
    body = counted - context.WRAPPER_TOKENS * len(token_counts)
    return -(-max(body, 0) * 100 // total) / 100


def measure(
    conn: sqlite3.Connection,
    counter: TokenCounter,
    model: str,
    *,
    factor_before: float,
    size: int = SAMPLE_SIZE,
) -> Measurement:
    """Run the calibration: 1 count call over the sample.

    Args:
        conn: The chunk store.
        counter: The token counter of the provider.
        model: The model whose tokenizer counts.
        factor_before: The configured factor, for the comparison.
        size: The sample size.

    Returns:
        The measurement.

    Raises:
        ValueError: The store holds no chunks.
    """
    chunks = sample_chunks(conn, size)
    counts = [c.token_count for c in chunks]
    counted = counter(model, render_sample(chunks))
    return Measurement(
        chunks=len(chunks),
        embedding_tokens=sum(counts),
        counted_tokens=counted,
        factor=solve_factor(counted, counts),
        estimate_before=sum(
            context.estimate_tokens(n, factor_before) for n in counts
        ),
    )


def anthropic_counter(client: Any) -> TokenCounter:  # noqa: ANN401
    """Wrap `messages.count_tokens` of a synchronous Anthropic client.

    Args:
        client: An `anthropic.Anthropic` client.

    Returns:
        The counter.
    """

    def count(model: str, text: str) -> int:
        result = client.messages.count_tokens(
            model=model, messages=[{"role": "user", "content": text}]
        )
        return int(result.input_tokens)

    return count
