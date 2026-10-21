"""Token chunks with overlap and SimHash (chapter 9.1).

The chunker splits each canonical section of a parsed filing into chunks
of about 400 tokens of the embedding model's tokenizer. A chunk never
crosses a section boundary, a table block becomes its own chunks with its
caption on each part, and each chunk starts with a prefix line that names
the company, the form, the fiscal label, and the section title.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from collections.abc import Sequence
import dataclasses
import hashlib
import os
import pathlib
import re
from typing import Protocol

import numpy
import pydantic
import tokenizers

from keel import config
from keel import doctor
from keel import errors
from keel import sections as sections_mod
from keel import tables
from keel.parsers import base

SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*[ \t]+(?=[\"'(\[]?[A-Z0-9$])")
SPLIT_POINT = re.compile(r"[;,][ \t]+")
WORD = re.compile(r"[a-z0-9]+(?:['.][a-z0-9]+)*")
SIMHASH_BITS = 64
SHINGLE = 3
# The embedding model reads 512 tokens, 2 of them the special tokens.
MODEL_TOKENS = 510
# A table row piece holds at least this many tokens.
MIN_ROW_ROOM = 16
_SIGN_BIT = 1 << (SIMHASH_BITS - 1)
_MASK = (1 << SIMHASH_BITS) - 1


class TokenCounter(Protocol):
    """Counts tokens and gives the token offsets of a text."""

    def offsets(self, texts: Sequence[str]) -> list[list[tuple[int, int]]]:
        """Return the character span of each token of each text.

        Args:
            texts: The texts.

        Returns:
            1 list of (start, end) spans per text, without special tokens.
        """


@dataclasses.dataclass(frozen=True)
class HFTokenCounter:
    """The tokenizer of the pinned embedding model (chapter 9.1).

    Attributes:
        tokenizer: The fast tokenizer read from `tokenizer.json`.
    """

    tokenizer: tokenizers.Tokenizer

    @classmethod
    def from_settings(cls, settings: config.Settings) -> HFTokenCounter:
        """Load the tokenizer from the local Hugging Face cache.

        Args:
            settings: The loaded settings with the pinned revision.

        Returns:
            The counter.

        Raises:
            ModelMissingError: The pinned snapshot has no tokenizer file.
        """
        snapshot = doctor.model_snapshot(
            doctor.hf_cache_dir(os.environ),
            settings.embedding.model,
            settings.embedding.revision,
        )
        path = pathlib.Path(snapshot) / "tokenizer.json"
        if not path.is_file():
            raise errors.ModelMissingError(
                f"no tokenizer at {path}; run keel doctor --download-models"
            )
        tokenizer = tokenizers.Tokenizer.from_file(str(path))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return cls(tokenizer=tokenizer)

    def offsets(self, texts: Sequence[str]) -> list[list[tuple[int, int]]]:
        """Return the character span of each token of each text.

        Args:
            texts: The texts.

        Returns:
            1 list of (start, end) spans per text, without special tokens.
        """
        encoded = self.tokenizer.encode_batch(
            list(texts), add_special_tokens=False
        )
        return [list(e.offsets) for e in encoded]

    def count(self, text: str) -> int:
        """Count the tokens of 1 text.

        Args:
            text: The text.

        Returns:
            The token count without special tokens.
        """
        return len(self.offsets([text])[0])


class Chunk(pydantic.BaseModel):
    """1 chunk with the metadata of chapter 9.2.

    The index assigns `vector_row` at stage 4.

    Attributes:
        chunk_id: `{filing_id}__{section}__{sequence:04d}` (chapter 7.11).
        filing_id: The filing ID.
        ticker: The ticker.
        company: The company name from the header.
        cik: The CIK.
        form: `10-K` or `10-Q`.
        fiscal_year: The fiscal year.
        fiscal_period: `FY`, `Q1`, `Q2`, `Q3`, or `unknown`.
        period_end_date: The ISO period end date.
        filing_date: The ISO filing date.
        section: The canonical section.
        item_label: The raw item label, for diagnostics.
        section_confidence: The title match ratio of the heading.
        sequence: The sequence inside the section, from 0.
        text: The prefix line, a newline, and the body.
        token_count: The tokens of `text`.
        char_start: The body start in the clean text.
        char_end: The body end in the clean text.
        is_table: True for a table part.
        split_sentence: True when a sentence over the hard maximum was cut.
        delta_only: True for a 10-Q risk-factor chunk.
        boilerplate_flag: `forward_looking`, or None.
        source_url: The filing URL when trusted, else None.
        chunk_hash: The first 16 hex characters of the text's sha256.
        simhash: The 64-bit SimHash of the body, as a signed integer.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    chunk_id: str
    filing_id: str
    ticker: str
    company: str
    cik: str | None
    form: str
    fiscal_year: int | None
    fiscal_period: str | None
    period_end_date: str
    filing_date: str
    section: str
    item_label: str | None
    section_confidence: float
    sequence: int
    text: str
    token_count: int
    char_start: int
    char_end: int
    is_table: bool = False
    split_sentence: bool = False
    delta_only: bool = False
    boilerplate_flag: str | None = None
    source_url: str | None = None
    chunk_hash: str
    simhash: int


@dataclasses.dataclass(frozen=True)
class ChunkSizes:
    """The chunk sizes in tokens (chapter 9.1, decision D-16).

    Attributes:
        target: The target body size.
        maximum: The hard maximum body size.
        overlap: The overlap carried into the next chunk.
    """

    target: int = 400
    maximum: int = 480
    overlap: int = 50

    @classmethod
    def from_settings(cls, settings: config.Settings) -> ChunkSizes:
        """Read the sizes from the config.

        Args:
            settings: The loaded settings.

        Returns:
            The sizes.
        """
        chunker = settings.chunker
        return cls(
            target=chunker.target_tokens,
            maximum=chunker.max_tokens,
            overlap=chunker.overlap_tokens,
        )


@dataclasses.dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    tokens: int
    split: bool = False


@dataclasses.dataclass(frozen=True)
class _Body:
    start: int
    end: int
    tokens: int
    split: bool
    is_table: bool
    text: str


def simhash(text: str) -> int:
    """Compute the 64-bit SimHash over lowercase word 3-grams.

    Args:
        text: The text.

    Returns:
        The SimHash as a signed 64-bit integer, so SQLite stores it.
    """
    words = WORD.findall(text.lower())
    if len(words) < SHINGLE:
        grams = [" ".join(words)] if words else []
    else:
        grams = [
            " ".join(words[i : i + SHINGLE])
            for i in range(len(words) - SHINGLE + 1)
        ]
    if not grams:
        return 0
    digests = b"".join(
        hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest()
        for g in grams
    )
    # 1 row of 64 bits per 3-gram, most significant bit first.
    bits = numpy.unpackbits(numpy.frombuffer(digests, dtype=numpy.uint8))
    votes = bits.reshape(len(grams), SIMHASH_BITS).sum(axis=0) * 2
    # Pack the 64 majority bits, most significant first, into an integer.
    majority = numpy.packbits(votes > len(grams)).tobytes()
    unsigned = int.from_bytes(majority, "big")
    return unsigned - (1 << SIMHASH_BITS) if unsigned & _SIGN_BIT else unsigned


def hamming(first: int, second: int) -> int:
    """Count the differing bits of 2 SimHash values.

    Args:
        first: A SimHash.
        second: A SimHash.

    Returns:
        The Hamming distance, 0 to 64.
    """
    return bin((first ^ second) & _MASK).count("1")


def fiscal_label(meta: base.FilingMetadata) -> str:
    """Render the fiscal label of the prefix line.

    Args:
        meta: The filing metadata.

    Returns:
        `FY2025` for a 10-K, `Q3 FY2025` for a 10-Q, or `unknown`.
    """
    if meta.fiscal_year is None:
        return "unknown"
    if meta.fiscal_period in {None, "FY", "unknown"}:
        return f"FY{meta.fiscal_year}"
    return f"{meta.fiscal_period} FY{meta.fiscal_year}"


def prefix_line(meta: base.FilingMetadata, title: str) -> str:
    """Render the prefix line of a chunk (chapter 9.1).

    Args:
        meta: The filing metadata.
        title: The section title.

    Returns:
        `company | form | fiscal label | section title`.
    """
    return " | ".join(
        (
            meta.company or meta.ticker or "",
            meta.form or "",
            fiscal_label(meta),
            title,
        )
    )


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split a prose range into sentence spans at lines and sentence ends."""
    spans: list[tuple[int, int]] = []
    line_start = start
    while line_start < end:
        line_end = text.find("\n", line_start, end)
        line_end = end if line_end < 0 else line_end
        cursor = line_start
        for match in SENTENCE_END.finditer(text, line_start, line_end):
            spans.append((cursor, match.start()))
            cursor = match.end()
        spans.append((cursor, line_end))
        line_start = line_end + 1
    return [(a, b) for a, b in spans if text[a:b].strip()]


class _Tokens:
    """Token starts of 1 range of text, for counts by character range."""

    def __init__(
        self, text: str, base_offset: int, spans: list[tuple[int, int]]
    ) -> None:
        self.text = text
        self.starts = [base_offset + s for s, _ in spans]
        self.ends = [base_offset + e for _, e in spans]

    def _word_start(self, index: int, low: int) -> int:
        """Move a cut back to a token after a space, so no word splits."""
        for candidate in range(index, low, -1):
            if self.ends[candidate - 1] < self.starts[candidate]:
                return candidate
        return index

    def count(self, start: int, end: int) -> int:
        return bisect.bisect_left(self.starts, end) - bisect.bisect_left(
            self.starts, start
        )

    def cut(self, start: int, end: int, size: int) -> list[tuple[int, int]]:
        """Cut a range into pieces of at most `size` tokens."""
        first = bisect.bisect_left(self.starts, start)
        last = bisect.bisect_left(self.starts, end)
        pieces: list[tuple[int, int]] = []
        piece_start, index = start, first
        while last - index > size:
            cut = self._word_start(index + size, index)
            boundary = self.starts[cut]
            pieces.append((piece_start, boundary))
            piece_start, index = boundary, cut
        pieces.append((piece_start, end))
        return pieces


def _units(
    text: str, start: int, end: int, tokens: _Tokens, maximum: int
) -> list[_Unit]:
    """Sentences of a prose range, with the long ones split (step 3)."""
    units: list[_Unit] = []
    for first, last in _sentence_spans(text, start, end):
        count = tokens.count(first, last)
        if count <= maximum:
            units.append(_Unit(first, last, count))
            continue
        pieces: list[tuple[int, int]] = []
        cursor = first
        for match in SPLIT_POINT.finditer(text, first, last):
            pieces.append((cursor, match.end()))
            cursor = match.end()
        pieces.append((cursor, last))
        merged = _merge(pieces, tokens, maximum)
        for a, b in merged:
            size = tokens.count(a, b)
            if size <= maximum:
                units.append(_Unit(a, b, size, split=True))
                continue
            for c, d in tokens.cut(a, b, maximum):
                units.append(_Unit(c, d, tokens.count(c, d), split=True))
    return units


def _merge(
    pieces: list[tuple[int, int]], tokens: _Tokens, maximum: int
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for a, b in pieces:
        if merged and tokens.count(merged[-1][0], b) <= maximum:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def pack(units: Sequence[_Unit], sizes: ChunkSizes) -> list[list[_Unit]]:
    """Pack sentence units into chunks with overlap (steps 2 and 4).

    Args:
        units: The sentence units of 1 prose range, in order.
        sizes: The chunk sizes.

    Returns:
        The units of each chunk. Consecutive chunks share up to
        `sizes.overlap` tokens of whole sentences.
    """
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    total = 0
    carried = 0
    for unit in units:
        if current and total + unit.tokens > sizes.target:
            if len(current) == carried:
                current, total = [], 0
            else:
                groups.append(current)
                current, total = _overlap(current, sizes.overlap)
                carried = len(current)
                if total + unit.tokens > sizes.target:
                    current, total, carried = [], 0, 0
        current.append(unit)
        total += unit.tokens
    if current and len(current) > carried:
        groups.append(current)
    return groups


def _overlap(units: Sequence[_Unit], budget: int) -> tuple[list[_Unit], int]:
    carried: list[_Unit] = []
    total = 0
    for unit in reversed(units[1:]):
        if total + unit.tokens > budget:
            break
        carried.insert(0, unit)
        total += unit.tokens
    return carried, total


def _table_bodies(
    table: tables.Table, counter: TokenCounter, sizes: ChunkSizes
) -> list[_Body]:
    """Render a table as parts of at most `target` tokens (step 5)."""
    caption = table.caption()
    rows = [" | ".join(row) for row in table.rows]
    counts = [len(o) for o in counter.offsets([caption, *rows])]
    caption_tokens, row_tokens = counts[0], counts[1:]
    bodies: list[_Body] = []
    lines: list[str] = []
    total = caption_tokens
    split = False
    room = max(sizes.target - caption_tokens, MIN_ROW_ROOM)
    pieces: list[tuple[str, int, bool]] = []
    for row, size in zip(rows, row_tokens, strict=True):
        if size <= room:
            pieces.append((row, size, False))
            continue
        # A row longer than the room splits like a long sentence.
        row_tokens_ = _Tokens(row, 0, counter.offsets([row])[0])
        for first, last in row_tokens_.cut(0, len(row), room):
            piece = row[first:last].strip()
            pieces.append((piece, row_tokens_.count(first, last), True))
    for line, size, cut in pieces:
        if lines and total + size > sizes.target:
            bodies.append(_table_body(table, caption, lines, total, split))
            lines, total, split = [], caption_tokens, False
        lines.append(line)
        total += size
        split = split or cut
    if lines or not bodies:
        bodies.append(_table_body(table, caption, lines, total, split))
    return bodies


def _table_body(
    table: tables.Table, caption: str, lines: list[str], total: int, split: bool
) -> _Body:
    return _Body(
        start=table.start,
        end=table.end,
        tokens=total,
        split=split,
        is_table=True,
        text="\n".join([caption, *lines]),
    )


@dataclasses.dataclass(frozen=True)
class FilingChunks:
    """The chunks and sections of 1 filing.

    Attributes:
        filing_id: The filing ID.
        form: `10-K` or `10-Q`.
        sections: The section detection.
        chunks: The chunks in text order per section.
    """

    filing_id: str
    form: str
    sections: sections_mod.SectionResult
    chunks: tuple[Chunk, ...]


def _prose_ranges(
    span: sections_mod.Section,
    table_list: Sequence[tables.Table],
    consumed: int,
) -> list[tuple[str, int, int, tables.Table | None]]:
    """Split a section span into prose ranges and the tables in it.

    A table belongs to the span where it starts, whole. When it runs past
    the span end, the next span starts after it (`consumed`), so no row is
    cut twice.
    """
    pieces: list[tuple[str, int, int, tables.Table | None]] = []
    cursor = max(span.start, consumed)
    for table in table_list:
        if not cursor <= table.start < span.end:
            continue
        if table.start > cursor:
            pieces.append(("prose", cursor, table.start, None))
        pieces.append(("table", table.start, table.end, table))
        cursor = table.end
    if cursor < span.end:
        pieces.append(("prose", cursor, span.end, None))
    return pieces


def chunk_filing(
    filing: base.ParsedFiling,
    counter: TokenCounter,
    sizes: ChunkSizes,
    detected: sections_mod.SectionResult | None = None,
) -> FilingChunks:
    """Chunk 1 parsed filing (chapter 9.1, steps 1 to 7).

    Args:
        filing: The parsed filing, not quarantined.
        counter: The token counter of the embedding model.
        sizes: The chunk sizes.
        detected: The section detection, or None to run it.

    Returns:
        The sections and the chunks.

    Raises:
        FilingNotIndexableError: The filing is quarantined or has no ID.
    """
    meta = filing.metadata
    filing_key = filing.filing_id
    if filing.quarantined or filing_key is None or meta.form is None:
        raise errors.FilingNotIndexableError(
            f"{meta.file_name}: quarantined or without a filing ID"
        )
    text = filing.text
    result = (
        detected
        if detected is not None
        else sections_mod.detect(text, meta.form)
    )
    spans = [s for s in result.sections if not s.excluded]
    prose_texts: list[str] = []
    layout: list[
        tuple[
            sections_mod.Section,
            list[tuple[str, int, int, tables.Table | None]],
        ]
    ] = []
    consumed = 0
    for span in spans:
        pieces = _prose_ranges(span, filing.tables, consumed)
        if pieces:
            consumed = max(consumed, pieces[-1][2])
        layout.append((span, pieces))
        prose_texts.extend(
            text[a:b] for kind, a, b, _ in pieces if kind == "prose"
        )
    offsets = iter(counter.offsets(prose_texts))
    prefixes = sorted({span.title for span in spans})
    prefix_tokens = {
        title: len(spans_)
        for title, spans_ in zip(
            prefixes,
            counter.offsets([prefix_line(meta, t) for t in prefixes]),
            strict=True,
        )
    }
    sequences: dict[str, int] = {}
    chunks: list[Chunk] = []
    for span, pieces in layout:
        bodies: list[_Body] = []
        # The prefix line and the body fit the 510 tokens of the model.
        room = MODEL_TOKENS - prefix_tokens[span.title]
        span_sizes = dataclasses.replace(
            sizes,
            maximum=min(sizes.maximum, room),
            target=min(sizes.target, room),
        )
        for kind, a, b, table in pieces:
            if kind == "table" and table is not None:
                bodies.extend(_table_bodies(table, counter, span_sizes))
                continue
            tokens = _Tokens(text, a, next(offsets))
            units = _units(text, a, b, tokens, span_sizes.maximum)
            for group in pack(units, span_sizes):
                first, last = group[0].start, group[-1].end
                bodies.append(
                    _Body(
                        start=first,
                        end=last,
                        tokens=tokens.count(first, last),
                        split=any(u.split for u in group),
                        is_table=False,
                        text=text[first:last].strip(),
                    )
                )
        for body in bodies:
            sequence = sequences.get(span.section, 0)
            sequences[span.section] = sequence + 1
            chunks.append(
                _make_chunk(
                    filing,
                    span,
                    body,
                    sequence=sequence,
                    prefix_tokens=prefix_tokens[span.title],
                )
            )
    return FilingChunks(
        filing_id=filing_key,
        form=meta.form,
        sections=result,
        chunks=tuple(chunks),
    )


def _make_chunk(
    filing: base.ParsedFiling,
    span: sections_mod.Section,
    body: _Body,
    *,
    sequence: int,
    prefix_tokens: int,
) -> Chunk:
    meta = filing.metadata
    filing_key = filing.filing_id or ""
    prefix = prefix_line(meta, span.title)
    full = f"{prefix}\n{body.text}"
    return Chunk(
        chunk_id=base.chunk_id(filing_key, span.section, sequence),
        filing_id=filing_key,
        ticker=meta.ticker or "",
        company=meta.company or "",
        cik=meta.cik,
        form=meta.form or "",
        fiscal_year=meta.fiscal_year,
        fiscal_period=meta.fiscal_period,
        period_end_date=str(meta.period_end_date),
        filing_date=str(meta.filing_date),
        section=span.section,
        item_label=span.item_label,
        section_confidence=round(span.confidence, 4),
        sequence=sequence,
        text=full,
        token_count=prefix_tokens + body.tokens,
        char_start=body.start,
        char_end=body.end,
        is_table=body.is_table,
        split_sentence=body.split,
        delta_only=span.delta_only,
        boilerplate_flag=span.boilerplate_flag,
        source_url=meta.url if meta.url_trusted else None,
        chunk_hash=base.chunk_hash(full),
        simhash=simhash(body.text),
    )


def chunk_filings(
    filings: Iterable[base.ParsedFiling],
    counter: TokenCounter,
    sizes: ChunkSizes,
) -> list[FilingChunks]:
    """Chunk every indexable filing.

    Args:
        filings: The parsed filings; quarantined ones are skipped.
        counter: The token counter.
        sizes: The chunk sizes.

    Returns:
        1 result per indexable filing, in the given order.

    Raises:
        FilingNotIndexableError: A filing without a form reached the chunker.
    """
    return [
        chunk_filing(f, counter, sizes)
        for f in filings
        if not f.quarantined and f.filing_id is not None
    ]


class ChunkSummary(pydantic.BaseModel):
    """The numbers the build report records for the chunker.

    Attributes:
        filings: The chunked filings.
        chunks: The chunk count.
        by_form: The chunk count per form.
        by_section: The chunk count per canonical section.
        tables: The table chunks.
        split_sentences: The chunks with a cut sentence.
        forward_looking: The chunks with the forward-looking flag.
        delta_only: The 10-Q risk-factor chunks.
        tokens_mean: The mean token count.
        tokens_median: The median token count.
        tokens_p95: The 95th percentile token count.
        tokens_min: The smallest token count.
        tokens_max: The largest token count.
        over_limit: The chunks over the 510 tokens the model reads besides
            its 2 special tokens.
        seconds: The wall time of the chunking.
    """

    filings: int
    chunks: int
    by_form: dict[str, int]
    by_section: dict[str, int]
    tables: int
    split_sentences: int
    forward_looking: int
    delta_only: int
    tokens_mean: float
    tokens_median: int
    tokens_p95: int
    tokens_min: int
    tokens_max: int
    over_limit: int
    seconds: float


def summarize(results: Sequence[FilingChunks], seconds: float) -> ChunkSummary:
    """Summarize the chunks of a corpus.

    Args:
        results: The chunked filings.
        seconds: The wall time of the chunking.

    Returns:
        The summary.
    """
    chunks = [c for r in results for c in r.chunks]
    counts = sorted(c.token_count for c in chunks) or [0]
    by_form: dict[str, int] = {}
    by_section: dict[str, int] = {}
    for chunk in chunks:
        by_form[chunk.form] = by_form.get(chunk.form, 0) + 1
        by_section[chunk.section] = by_section.get(chunk.section, 0) + 1
    limit = MODEL_TOKENS
    return ChunkSummary(
        filings=len(results),
        chunks=len(chunks),
        by_form=dict(sorted(by_form.items())),
        by_section=dict(sorted(by_section.items(), key=lambda kv: -kv[1])),
        tables=sum(c.is_table for c in chunks),
        split_sentences=sum(c.split_sentence for c in chunks),
        forward_looking=sum(c.boilerplate_flag is not None for c in chunks),
        delta_only=sum(c.delta_only for c in chunks),
        tokens_mean=round(sum(counts) / len(counts), 1),
        tokens_median=counts[len(counts) // 2],
        tokens_p95=counts[min(len(counts) - 1, len(counts) * 95 // 100)],
        tokens_min=counts[0],
        tokens_max=counts[-1],
        over_limit=sum(c.token_count > limit for c in chunks),
        seconds=round(seconds, 1),
    )
