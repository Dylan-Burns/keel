"""Chunker tests (chapter 9.1) with the tokenizer of the pinned model.

The tokenizer comes from the local Hugging Face cache (`keel doctor
--download-models`); pytest runs with HF_HUB_OFFLINE=1.
"""

import datetime
import itertools
import pathlib

import pytest

import conftest
from keel import chunker
from keel import config
from keel import errors
from keel import sections
from keel import tables
from keel.parsers import base

SENTENCE = (
    "NVIDIA pioneered accelerated computing to help solve the most "
    "challenging computational problems. "
)


@pytest.fixture(scope="module")
def counter() -> chunker.HFTokenCounter:
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    return chunker.HFTokenCounter.from_settings(settings)


@pytest.fixture
def sizes() -> chunker.ChunkSizes:
    return chunker.ChunkSizes()


def filing(
    text: str, found: tuple[tables.Table, ...] = ()
) -> base.ParsedFiling:
    meta = base.FilingMetadata(
        file_name="NVDA_10K_2025-02-26_full.txt",
        file_sha256="0" * 64,
        parser_version="1.0.0",
        ticker="NVDA",
        company="NVIDIA Corporation",
        cik="0001045810",
        form="10-K",
        filing_date=datetime.date(2025, 2, 26),
        url="https://www.sec.gov/Archives/edgar/data/1045810/x.htm",
        url_trusted=True,
        period_end_date=datetime.date(2025, 1, 26),
        fiscal_year=2025,
        fiscal_period="FY",
    )
    return base.ParsedFiling(metadata=meta, text=text, tables=found)


def ten_k(risk_sentences: int = 120) -> str:
    return (
        "Item 1. Business\n"
        + SENTENCE * 12
        + "\nItem 1A. Risk Factors\n"
        + SENTENCE * risk_sentences
        + "\nItem 7. Management's Discussion and Analysis of Financial "
        "Condition and Results of Operations\n"
        + SENTENCE * 30
        + "\nItem 8. Financial Statements and Supplementary Data\n"
        + SENTENCE * 12
    )


def test_chunk_size_limits(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    giant = "word " * 1_200  # 1 sentence with no punctuation
    text = ten_k() + "\n" + giant.strip() + "."
    result = chunker.chunk_filing(filing(text), counter, sizes)
    chunks = result.chunks
    assert len(chunks) > 5
    for chunk in chunks:
        body_tokens = counter.count(chunk.text.split("\n", 1)[1])
        assert body_tokens <= sizes.maximum
        assert chunk.token_count == counter.count(chunk.text)
        assert chunk.token_count <= 512
    split = [c for c in chunks if c.split_sentence]
    assert len(split) >= 3
    packed = [c for c in chunks if c.section == "risk_factors"]
    bodies = [counter.count(c.text.split("\n", 1)[1]) for c in packed]
    assert all(size <= sizes.target for size in bodies)
    assert all(size >= 300 for size in bodies[:-1])


def test_overlap(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    numbered = "".join(
        f"Risk number {n} could harm our business and results. "
        for n in range(200)
    )
    text = "Item 1A. Risk Factors\n" + numbered
    result = chunker.chunk_filing(filing(text), counter, sizes)
    risk = [c for c in result.chunks if c.section == "risk_factors"]
    assert len(risk) >= 3
    for first, second in itertools.pairwise(risk):
        assert second.char_start < first.char_end
        shared = text[second.char_start : first.char_end]
        assert 20 <= counter.count(shared) <= sizes.overlap
        assert first.text.endswith(shared.strip())


def test_no_section_crossing(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    text = ten_k()
    result = chunker.chunk_filing(filing(text), counter, sizes)
    spans = [s for s in result.sections.sections if not s.excluded]
    for chunk in result.chunks:
        holder = [
            s
            for s in spans
            if s.start <= chunk.char_start and chunk.char_end <= s.end
        ]
        assert len(holder) == 1
        assert holder[0].section == chunk.section
        assert holder[0].item_label == chunk.item_label
    risk = [c for c in result.chunks if c.section == "risk_factors"]
    assert [c.sequence for c in risk] == list(range(len(risk)))
    assert risk[0].chunk_id == "NVDA_10K_2025-01-26__risk_factors__0000"
    assert {c.section for c in result.chunks} >= {
        "business",
        "risk_factors",
        "mdna",
        "financial_statements",
    }


def test_table_caption(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    rows = "".join(
        f"| Segment number {n} revenue | $ {n},000 | $ {n},500 |\n"
        for n in range(1, 120)
    )
    body = "Revenue by segment follows.\n"
    text = (
        "Item 7. Management's Discussion and Analysis of Financial Condition "
        "and Results of Operations\n"
        + SENTENCE * 8
        + "\n"
        + body
        + "Revenue by Segment\n(in millions)\n"
        + "| | Jan 26, 2025 | Jan 28, 2024 |\n"
        + rows
        + "\n"
        + SENTENCE * 8
    )
    found = tuple(tables.find_tables(text))
    assert len(found) == 1
    result = chunker.chunk_filing(filing(text, found), counter, sizes)
    parts = [c for c in result.chunks if c.is_table]
    assert len(parts) >= 3
    caption = found[0].caption()
    assert caption.startswith("TABLE: Revenue by Segment")
    assert "units: in millions" in caption
    for part in parts:
        assert part.text.split("\n")[1] == caption
        assert counter.count(part.text.split("\n", 1)[1]) <= sizes.target
        assert part.char_start == found[0].start
    prose = [c for c in result.chunks if not c.is_table]
    assert all("| Segment number" not in c.text for c in prose)


def test_prefix_and_metadata(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    result = chunker.chunk_filing(filing(ten_k(10)), counter, sizes)
    chunk = result.chunks[0]
    assert chunk.text.split("\n")[0] == (
        "NVIDIA Corporation | 10-K | FY2025 | Business"
    )
    assert chunk.filing_id == "NVDA_10K_2025-01-26"
    assert chunk.source_url is not None
    assert chunk.chunk_hash == base.chunk_hash(chunk.text)
    assert chunk.period_end_date == "2025-01-26"
    assert chunk.section_confidence == pytest.approx(1.0)


def test_quarantined_filing_raises(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    quarantined = filing("text").model_copy(
        update={
            "quarantine": base.QuarantineRecord(
                file_name="x.txt", reason="registrant_mismatch", detail="d"
            )
        }
    )
    with pytest.raises(errors.KeelError):
        chunker.chunk_filing(quarantined, counter, sizes)
    assert chunker.chunk_filings([quarantined], counter, sizes) == []


def test_simhash_near_duplicates() -> None:
    text = SENTENCE * 6
    near = text.replace("most challenging", "hardest", 1)
    other = "Revenue grew because data center demand rose in every region."
    assert chunker.simhash(text) == chunker.simhash(text)
    assert chunker.hamming(chunker.simhash(text), chunker.simhash(near)) <= 12
    assert chunker.hamming(chunker.simhash(text), chunker.simhash(other)) > 12
    assert chunker.simhash("") == 0
    assert -(2**63) <= chunker.simhash(other) < 2**63


def test_fiscal_label() -> None:
    meta = filing("").metadata
    assert chunker.fiscal_label(meta) == "FY2025"
    quarter = meta.model_copy(update={"form": "10-Q", "fiscal_period": "Q3"})
    assert chunker.fiscal_label(quarter) == "Q3 FY2025"
    unknown = meta.model_copy(update={"fiscal_year": None})
    assert chunker.fiscal_label(unknown) == "unknown"


def test_summary(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    results = chunker.chunk_filings([filing(ten_k())], counter, sizes)
    summary = chunker.summarize(results, 1.25)
    assert summary.filings == 1
    assert summary.chunks == len(results[0].chunks)
    assert summary.by_form == {"10-K": summary.chunks}
    assert summary.over_limit == 0
    assert summary.tokens_min <= summary.tokens_median <= summary.tokens_max
    assert summary.seconds == pytest.approx(1.2, abs=0.1)


def test_missing_tokenizer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    with pytest.raises(errors.ModelMissingError):
        chunker.HFTokenCounter.from_settings(settings)


def test_detected_sections_reused(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    text = ten_k(10)
    detected = sections.detect(text, "10-K")
    result = chunker.chunk_filing(filing(text), counter, sizes, detected)
    assert result.sections is detected


def test_long_table_row_split(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    long_cell = "1,234,567 " * 190  # under 2,000 characters, 950 tokens
    text = (
        "Item 8. Financial Statements and Supplementary Data\n"
        + SENTENCE * 8
        + "\nSegment Data\n| | 2025 | 2024 |\n"
        + f"| {long_cell.strip()} | 1 | 2 |\n| Total | $ 3 | $ 4 |\n\n"
        + SENTENCE * 8
    )
    found = tuple(tables.find_tables(text))
    result = chunker.chunk_filing(filing(text, found), counter, sizes)
    parts = [c for c in result.chunks if c.is_table]
    assert len(parts) >= 2
    assert any(c.split_sentence for c in parts)
    assert all(c.token_count == counter.count(c.text) for c in parts)
    assert all(c.token_count <= 512 for c in parts)
    joined = " ".join(c.text for c in parts)
    assert joined.count("1,234,567") == 190


def test_table_across_span_end_chunked_once(
    counter: chunker.HFTokenCounter, sizes: chunker.ChunkSizes
) -> None:
    rows = "".join(f"| Line {n} | $ {n} |\n" for n in range(1, 30))
    text = "Item 7. MD&A\n" + SENTENCE * 4 + "\nTitle\n" + rows + SENTENCE * 4
    found = tuple(tables.find_tables(text))
    (table,) = found
    middle = (table.start + table.end) // 2

    def span(name: str, start: int, end: int) -> sections.Section:
        return sections.Section(
            section=name, item_label=None, start=start, end=end, confidence=1
        )

    detected = sections.SectionResult(
        sections=(
            span("mdna", 0, middle),
            span("unknown", middle, len(text)),
        ),
        candidates=(),
    )
    result = chunker.chunk_filing(filing(text, found), counter, sizes, detected)
    joined = "\n".join(c.text for c in result.chunks)
    assert joined.count("Line 17 | $ 17") == 1
    unknown = [c for c in result.chunks if c.section == "unknown"]
    assert all(c.char_start >= table.end for c in unknown)
