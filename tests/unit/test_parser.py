"""Parser tests from real snippets (chapter 7.13 and the E-D rows of 19).

Every snippet under tests/fixtures/snippets is 2 KB or smaller and copied
from the corpus. Tests that need a long input (the XBRL block lengths, the
giant line, the large file) repeat a real snippet to the measured length.
"""

import datetime
import pathlib
import re

import pytest

import conftest
from keel import config
from keel import errors
from keel import tables
from keel.parsers import base
from keel.parsers import corpus
from keel.parsers import form_10k_10q

pytestmark = pytest.mark.unit

NVDA_10K = "NVDA_10K_2025-02-26_full.txt"
NVDA_10Q = "NVDA_10Q_2024Q4_2024-11-20_full.txt"
GE_10K = "GE_10K_2015-02-27_full.txt"
AAPL_10Q = "AAPL_10Q_2022Q4_2023-02-03_full.txt"


def snippet(name: str) -> str:
    return (conftest.SNIPPETS / name).read_text(encoding="utf-8")


@pytest.fixture
def context(settings: config.Settings) -> base.ParseContext:
    return base.ParseContext.from_settings(settings)


def write(directory: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = directory / name
    path.write_bytes(text.encode("utf-8"))
    return path


def parse(path: pathlib.Path, context: base.ParseContext) -> base.ParsedFiling:
    return form_10k_10q.TenKTenQParser().parse(path, context)


def xbrl_body(cover_snippet: str, block_chars: int) -> tuple[str, str]:
    """Rebuild a body with a real XBRL tail repeated to block_chars."""
    marker = form_10k_10q.COVER_MARKER.search(cover_snippet)
    assert marker is not None
    tail, cover = (
        cover_snippet[: marker.start()],
        cover_snippet[marker.start() :],
    )
    repeats = block_chars // len(tail) + 1
    block = "\n" + (tail * repeats)[-(block_chars - 1) :]
    assert len(block) == block_chars
    return base.normalize_text(block + cover), cover


# Chapter 7.13 -------------------------------------------------------------


def test_header_parse() -> None:
    lines = snippet("nvda_10k_fy2025_header.txt").split("\n")
    separator = form_10k_10q.find_separator(lines)
    header = form_10k_10q.parse_header(lines[:separator])
    assert set(form_10k_10q.REQUIRED_KEYS) <= set(header.values)
    assert len(header.values) == 7
    assert header.form == "10-K"
    assert header.url_trusted
    assert header.values["Ticker"] == "NVDA"
    nine = snippet("aapl_10q_2022q4_header.txt").split("\n")
    header = form_10k_10q.parse_header(
        nine[: form_10k_10q.find_separator(nine)]
    )
    assert len(header.values) == 9
    assert header.values["Report Period"] == "2022-12-31"
    assert header.form == "10-Q"


def test_separator_missing(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    text = snippet("nvda_10k_fy2025_header.txt").replace("=" * 60 + "\n", "")
    with pytest.raises(errors.SeparatorMissingError):
        form_10k_10q.find_separator(text.split("\n"))
    parsed = parse(write(tmp_path, NVDA_10K, text), context)
    assert parsed.quarantine is not None
    assert parsed.quarantine.reason == "separator_missing"
    check = parsed.check("CK-02")
    assert check is not None
    assert check.status == "quarantine"


def test_xbrl_cut_at_cover() -> None:
    body, cover = xbrl_body(snippet("nvda_10k_fy2025_xbrl_cover.txt"), 18_772)
    cut = form_10k_10q.cut_xbrl(body)
    assert cut.cut == cut.cover_marker == 18_772
    assert cut.block_chars == 18_772
    assert cut.xbrl_present
    assert cut.warnings == ()
    assert body[cut.cut :] == base.normalize_text(cover)


def test_xbrl_long_block() -> None:
    body, _ = xbrl_body(snippet("bac_10k_2025_xbrl_cover.txt"), 284_260)
    cut = form_10k_10q.cut_xbrl(body)
    assert cut.block_chars == 284_260
    assert form_10k_10q.COVER_MARKER.match(body, cut.cut)
    assert "xbrl_block_over_max" not in cut.warnings
    longer, _ = xbrl_body(snippet("bac_10k_2025_xbrl_cover.txt"), 400_100)
    assert "xbrl_block_over_max" in form_10k_10q.cut_xbrl(longer).warnings


def test_no_xbrl_block(caplog: pytest.LogCaptureFixture) -> None:
    text = snippet("ge_10k_2015_cover.txt")
    body = base.normalize_text(text[text.index("=" * 60) + 60 :])
    cut = form_10k_10q.cut_xbrl(body)
    assert cut.block_chars == 0
    assert not cut.xbrl_present
    assert cut.warnings == ("no_xbrl_block",)
    assert body[cut.cut :].startswith("UNITED STATES")
    # A long prefix without an XBRL sign stays whole (rule 4 of 7.4).
    prose = snippet("nvda_10k_fy2025_overview.txt")
    long_body = base.normalize_text(prose + body[cut.cut :])
    kept = form_10k_10q.cut_xbrl(long_body)
    assert kept.cut == 0
    assert kept.warnings == ("no_xbrl_block",)
    # No cover marker and no prose window: no cut point at all.
    assert form_10k_10q.cut_xbrl("dei:x" * 10).warnings == ("no_xbrl_block",)
    del caplog


def test_cover_fused_or() -> None:
    cover = form_10k_10q.read_cover(
        "For the fiscal year ended January 26, 2025OR"
    )
    assert cover.period_end == datetime.date(2025, 1, 26)
    assert cover.form_phrase == "fiscal year"
    assert not cover.split_layout


def test_cover_fused_transition() -> None:
    cover = form_10k_10q.read_cover(
        "For the quarterly period ended December 31, 2022or TRANSITION REPORT"
    )
    assert cover.period_end == datetime.date(2022, 12, 31)
    assert cover.form_phrase == "quarterly period"


def test_fiscal_q1_apple(context: base.ParseContext) -> None:
    parsed = parse(conftest.MINI_CORPUS / AAPL_10Q, context)
    meta = parsed.metadata
    assert parsed.quarantine is None
    assert meta.period_end_date == datetime.date(2022, 12, 31)
    assert meta.period_source == "cover"
    assert (meta.fiscal_year, meta.fiscal_period) == (2023, "Q1")
    assert meta.fiscal_year_end_month == 9
    # E-D-05: the period code 2022Q4 is the calendar quarter; no warning.
    check = parsed.check("CK-08")
    assert check is not None
    assert check.status == "pass"
    assert parsed.filing_id == "AAPL_10Q_2022-12-31"


def test_fiscal_q3_nvda(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    ten_q = write(tmp_path, NVDA_10Q, snippet("nvda_10q_2024q4_cover.txt"))
    filings = corpus.parse_files(
        [conftest.MINI_CORPUS / NVDA_10K, ten_q], context
    )
    result = corpus.finish_corpus(filings, context)
    assert result.year_end_months["NVDA"] == 1
    assert result.year_end_sources["NVDA"] == "10-K"
    meta = result.filings[1].metadata
    assert meta.period_end_date == datetime.date(2024, 10, 27)
    assert (meta.fiscal_year, meta.fiscal_period) == (2025, "Q3")
    ten_k = result.filings[0].metadata
    assert (ten_k.fiscal_year, ten_k.fiscal_period) == (2025, "FY")


def test_nominal_month() -> None:
    assert base.nominal_month(datetime.date(2022, 10, 2)) == (2022, 9)
    assert base.nominal_month(datetime.date(2022, 10, 5)) == (2022, 10)
    assert base.nominal_month(datetime.date(2022, 1, 2)) == (2021, 12)
    # A 52-53 week 10-K that ends on January 2 is the previous fiscal year.
    assert base.fiscal_period("10-K", datetime.date(2022, 1, 2), 12) == (
        2021,
        "FY",
    )
    assert base.fiscal_period("10-Q", datetime.date(2023, 4, 2), 12) == (
        2023,
        "Q1",
    )
    assert base.fiscal_period("10-Q", datetime.date(2023, 6, 30), 12) == (
        2023,
        "Q2",
    )
    assert base.fiscal_period("10-Q", datetime.date(2023, 3, 31), 3) == (
        2023,
        "unknown",
    )


def test_registrant_mismatch(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    path = write(tmp_path, GE_10K, snippet("ge_10k_2015_cover.txt"))
    parsed = parse(path, context)
    record = parsed.quarantine
    assert record is not None
    assert record.reason == "registrant_mismatch"
    assert "gecc10k2014.htm" in record.evidence["url"]
    assert record.evidence["filing_date"] == "2015-02-27"
    assert record.evidence["cover_registrant"] == (
        "General Electric Capital Corporation"
    )
    assert base.name_tokens("General Electric Company") == {
        "GENERAL",
        "ELECTRIC",
    }
    assert "no_xbrl_block" in parsed.warnings


def test_fused_items() -> None:
    text = form_10k_10q.repair_boundaries(
        "Item 3. Defaults Upon Senior SecuritiesNone.Item 4. Mine Safety "
        "DisclosuresNot applicable.",
        frozenset(),
        (),
    )
    assert text.split("\n") == [
        "Item 3. Defaults Upon Senior Securities",
        "None.",
        "Item 4. Mine Safety Disclosures",
        "Not applicable.",
    ]


def test_nbsp_item_label() -> None:
    nbsp = chr(0xA0) * 3
    text = base.normalize_text(f"Risk.Item 1A.{nbsp}Risk Factors")
    repaired = form_10k_10q.repair_boundaries(text, frozenset(), ())
    assert re.search(r"(?m)^Item 1A\. Risk Factors$", repaired)


def test_heading_split(context: base.ParseContext) -> None:
    text = form_10k_10q.repair_boundaries(
        "OverviewOur Company and Our BusinessesNVIDIA pioneered",
        context.abbreviations,
        context.protected_names,
    )
    assert text.split("\n") == [
        "Overview",
        "Our Company and Our Businesses",
        "NVIDIA pioneered",
    ]


def test_page_artifact() -> None:
    text, removals = form_10k_10q.remove_artifacts(
        "36Table of ContentsIn July 2023"
    )
    assert removals == 1
    assert text.split("\n")[-1] == "In July 2023"
    real, count = form_10k_10q.remove_artifacts(
        snippet("nvda_10k_fy2025_page_artifact.txt")
    )
    assert count == 1
    assert "\nIn July 2023, the USG" in real
    # Rule A1 keeps the real heading in upper case (chapter 8 uses it).
    assert form_10k_10q.remove_artifacts("TABLE OF CONTENTS") == (
        "TABLE OF CONTENTS",
        0,
    )


def test_protected_name(context: base.ParseContext) -> None:
    for name in ("JPMorgan Chase", "McDonald's", "BlackRock", "ExxonMobil"):
        repaired = form_10k_10q.repair_boundaries(
            name, context.abbreviations, context.protected_names
        )
        assert repaired == name
    # R1 keeps a protected abbreviation fused to the next word.
    assert (
        form_10k_10q.repair_boundaries(
            "Apple Inc.The Company", context.abbreviations, ()
        )
        == "Apple Inc.The Company"
    )


def test_table_units(context: base.ParseContext) -> None:
    text, _ = form_10k_10q.remove_artifacts(
        base.normalize_text(snippet("nvda_10k_fy2025_income_table.txt"))
    )
    clean = form_10k_10q.repair_boundaries(
        text, context.abbreviations, context.protected_names
    )
    (table,) = tables.find_tables(clean)
    caption = table.caption()
    assert "units: in millions" in caption
    assert "columns: Jan 26, 2025 | Jan 28, 2024 | Jan 29, 2023" in caption
    assert table.title == "Consolidated Statements of Comprehensive Income"
    assert table.rows[0] == ("Net income", "$ 72,880", "$ 29,760", "$ 4,368")
    rendered = table.render()
    assert len(rendered) == 1
    assert rendered[0].split("\n")[0] == caption


def test_idempotent_ids(context: base.ParseContext) -> None:
    path = conftest.MINI_CORPUS / NVDA_10K
    first, second = parse(path, context), parse(path, context)
    assert first.filing_id == second.filing_id == "NVDA_10K_2025-01-26"
    assert first.text == second.text
    assert first.metadata == second.metadata

    def ids(filing: base.ParsedFiling) -> list[tuple[str, str]]:
        assert filing.filing_id is not None
        return [
            (
                base.chunk_id(filing.filing_id, "table", index),
                base.chunk_hash(part),
            )
            for index, part in enumerate(
                part for table in filing.tables for part in table.render()
            )
        ]

    assert ids(first) == ids(second)
    assert ids(first)
    assert ids(first)[0][0] == "NVDA_10K_2025-01-26__table__0000"
    assert len(ids(first)[0][1]) == 16


# Chapter 19 rows on the stage card -----------------------------------------


def test_giant_line_parse(context: base.ParseContext) -> None:
    """E-D-09: a single line of 287,855 characters gets its boundaries."""
    prose = snippet("nvda_10k_fy2025_overview.txt")
    line = (prose * (287_855 // len(prose) + 1))[:287_855]
    assert "\n" not in line
    repaired = form_10k_10q.repair_boundaries(
        line, context.abbreviations, context.protected_names
    )
    longest = max(len(part) for part in repaired.split("\n"))
    assert longest < len(prose)
    assert "Overview\nOur Company and Our Businesses\nNVIDIA" in repaired


def test_large_file_parse_time(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    """E-D-21: a 1.5 MB filing parses well under the 60-second limit."""
    nvda = (conftest.MINI_CORPUS / NVDA_10K).read_text(encoding="utf-8")
    prose = snippet("nvda_10k_fy2025_overview.txt") + "\n"
    table = snippet("nvda_10k_fy2025_income_table.txt")
    filler = (prose + table) * (1_500_000 // len(prose + table) + 1)
    path = write(tmp_path, NVDA_10K, nvda + filler)
    assert path.stat().st_size > 1_500_000
    parsed = parse(path, context)
    assert parsed.quarantine is None
    assert parsed.parse_seconds < corpus.SLOW_PARSE_SECONDS
    result = corpus.finish_corpus([parsed], context)
    assert "parse_slow" not in result.filings[0].warnings
    slow = parsed.model_copy(update={"parse_seconds": 61.0})
    flagged = corpus.finish_corpus([slow], context)
    assert "parse_slow" in flagged.filings[0].warnings
    assert corpus.summarize(flagged).slow_files == [NVDA_10K]


def test_bom_and_crlf(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    """E-D-27: a byte order mark and CRLF line ends parse as usual."""
    text = snippet("nvda_10q_2024q4_cover.txt")
    data = b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")
    decoded = base.decode(data)
    assert "\r" not in decoded
    assert decoded.startswith("Company:")
    path = tmp_path / NVDA_10Q
    path.write_bytes(data)
    parsed = parse(path, context)
    assert parsed.quarantine is None
    assert parsed.metadata.company == "NVIDIA Corporation"


def test_invalid_utf8(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    """E-D-27: an invalid byte sequence sends the file to quarantine."""
    data = snippet("nvda_10q_2024q4_cover.txt").encode("utf-8")
    path = tmp_path / NVDA_10Q
    path.write_bytes(data[:500] + b"\xff\xfe" + data[500:])
    with pytest.raises(errors.FilingDecodeError):
        base.decode(path.read_bytes())
    parsed = parse(path, context)
    assert parsed.quarantine is not None
    assert parsed.quarantine.reason == "decode_error"
    assert parsed.metadata.file_sha256


def test_truncated_file_quarantine(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    """E-D-22: a file cut inside the XBRL block has no cover page."""
    data = (conftest.MINI_CORPUS / NVDA_10K).read_bytes()[:1500]
    path = tmp_path / NVDA_10K
    path.write_bytes(data)
    parsed = parse(path, context)
    assert parsed.quarantine is not None
    assert parsed.quarantine.reason == "cover_page_not_found"
    header_only = tmp_path / "AAPL_10Q_2022Q4_2023-02-03_full.txt"
    header_only.write_text("Company: Apple Inc\n", encoding="utf-8")
    parsed = parse(header_only, context)
    assert parsed.quarantine is not None
    assert parsed.quarantine.reason == "separator_missing"
    missing = parse(tmp_path / "absent.txt", context)
    assert missing.quarantine is not None
    assert missing.quarantine.reason == "read_error"


def test_duplicate_filing_id(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    """E-D-26, E-D-29: 2 files with 1 filing ID keep the later filing."""
    original = (conftest.MINI_CORPUS / AAPL_10Q).read_text(encoding="utf-8")
    amended = original.replace(
        "Filing Date: 2023-02-03", "Filing Date: 2023-03-01"
    )
    first = write(tmp_path, AAPL_10Q, original)
    second = write(tmp_path, "AAPL_10Q_2022Q4_2023-03-01_full.txt", amended)
    result = corpus.finish_corpus(
        corpus.parse_files([first, second], context), context
    )
    dropped, kept = result.filings
    assert kept.quarantine is None
    assert "duplicate_filing_id" in kept.warnings
    kept_check = kept.check("CK-11")
    assert kept_check is not None
    assert kept_check.status == "warning"
    assert dropped.quarantine is not None
    assert dropped.quarantine.reason == "duplicate_filing_id"
    assert dropped.quarantine.evidence["kept"] == second.name


def test_header_url_trust() -> None:
    """E-D-28 at parse time: only a plain https URL on www.sec.gov."""
    assert form_10k_10q.url_trusted("https://www.sec.gov/Archives/x.htm")
    for url in (
        "http://www.sec.gov/Archives/x.htm",
        "https://sec.gov.evil.example/x",
        "https://www.sec.gov.evil.example/x",
        "https://www.sec.gov@evil.com/x",
        "https://user:pw@www.sec.gov/x",
        "https://www.sec.gov:8443/x",
        "https://www.sec.gov:bad/x",
        "https://www.sec.gov\\@evil.com/x",
        "https:\\\\www.sec.gov/x",
        "https://www.sec.gov/x y",
        "https://www.sec.gov/x" + chr(0x0A),
        "https://www.sec.gov/x" + chr(0x09),
        "HTTPS://www.sec.gov/x",
        "https://WWW.SEC.GOV/x",
        "https://www.sec.gov",
    ):
        assert not form_10k_10q.url_trusted(url), url
