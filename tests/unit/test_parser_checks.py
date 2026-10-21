"""The metadata checks CK-01 to CK-11 and the corpus pass of the parser."""

import dataclasses
import datetime
import pathlib

import pytest

import conftest
from keel import config
from keel import errors
from keel import parsers
from keel.parsers import base
from keel.parsers import corpus
from keel.parsers import form_10k_10q

pytestmark = pytest.mark.unit

NVDA_10Q = "NVDA_10Q_2024Q4_2024-11-20_full.txt"


@pytest.fixture
def context(settings: config.Settings) -> base.ParseContext:
    return base.ParseContext.from_settings(settings)


@pytest.fixture
def cover() -> str:
    return (conftest.SNIPPETS / "nvda_10q_2024q4_cover.txt").read_text(
        encoding="utf-8"
    )


def parse_as(
    tmp_path: pathlib.Path,
    name: str,
    text: str,
    context: base.ParseContext,
) -> base.ParsedFiling:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return parsers.parser_for(None).parse(path, context)


def status(filing: base.ParsedFiling, check: str) -> str:
    result = filing.check(check)
    assert result is not None
    return result.status


def test_clean_file_passes_every_check(
    tmp_path: pathlib.Path, cover: str, context: base.ParseContext
) -> None:
    parsed = parse_as(tmp_path, NVDA_10Q, cover, context)
    assert parsed.quarantine is None
    for check in base.CHECK_IDS[:9]:
        assert status(parsed, check) == "pass", check
    assert status(parsed, "CK-10") == "skipped"
    meta = parsed.metadata
    assert meta.registrant == "NVIDIA CORPORATION"
    assert meta.header_report_period == "2024-10-27"
    assert meta.header_quarter == "2024Q4"
    assert meta.url_trusted


def test_ticker_and_form_mismatch_quarantine(
    tmp_path: pathlib.Path, cover: str, context: base.ParseContext
) -> None:
    ticker = parse_as(
        tmp_path, "AMD_10Q_2024Q4_2024-11-20_full.txt", cover, context
    )
    assert ticker.quarantine is not None
    assert ticker.quarantine.reason == "ticker_mismatch"
    form = parse_as(
        tmp_path, "NVDA_10K_2024Q4_2024-11-20_full.txt", cover, context
    )
    assert form.quarantine is not None
    assert form.quarantine.reason == "form_mismatch"


def test_warnings_do_not_quarantine(
    tmp_path: pathlib.Path, cover: str, context: base.ParseContext
) -> None:
    date = parse_as(
        tmp_path, "NVDA_10Q_2024Q4_2024-11-21_full.txt", cover, context
    )
    assert date.quarantine is None
    assert "filing_date_mismatch" in date.warnings
    code = parse_as(
        tmp_path, "NVDA_10Q_2024Q3_2024-11-20_full.txt", cover, context
    )
    assert "period_code_mismatch" in code.warnings
    late = cover.replace("Filing Date: 2024-11-20", "Filing Date: 2025-06-01")
    lag = parse_as(
        tmp_path, "NVDA_10Q_2024Q4_2025-06-01_full.txt", late, context
    )
    assert "filing_lag" in lag.warnings
    unmatched = parse_as(tmp_path, "nvda.txt", cover, context)
    assert "filename_unmatched" in unmatched.warnings
    assert status(unmatched, "CK-08") == "skipped"
    listed = dataclasses.replace(context, manifest_files=frozenset())
    unlisted = parse_as(tmp_path, NVDA_10Q, cover, listed)
    assert "unmanifested" in unlisted.warnings
    untrusted = cover.replace("https://www.sec.gov", "http://example.com")
    url = parse_as(tmp_path, NVDA_10Q, untrusted, context)
    assert url.quarantine is None
    assert not url.metadata.url_trusted


def test_period_fallback_to_file_name(
    tmp_path: pathlib.Path, cover: str, context: base.ParseContext
) -> None:
    """CK-07: no cover period gives the period code with a warning."""
    blind = cover.replace("quarterly period ended", "quarterly report as of")
    parsed = parse_as(tmp_path, NVDA_10Q, blind, context)
    assert parsed.quarantine is None
    assert parsed.metadata.period_source == "filename"
    assert parsed.metadata.period_end_date == datetime.date(2024, 12, 31)
    assert status(parsed, "CK-07") == "fallback"
    assert "period_source_filename" in parsed.warnings
    no_code = parse_as(tmp_path, "NVDA_10Q_2024-11-20_full.txt", blind, context)
    assert no_code.quarantine is not None
    assert no_code.quarantine.reason == "cover_page_not_found"


def test_split_cell_cover() -> None:
    """The JPM 10-K cover puts the phrase and the date in 2 cells."""
    text = (conftest.MINI_CORPUS / "JPM_10K_2026-02-13_full.txt").read_text(
        encoding="utf-8"
    )
    marker = form_10k_10q.COVER_MARKER.search(text)
    assert marker is not None
    page = form_10k_10q.read_cover(base.normalize_text(text[marker.start() :]))
    assert page.split_layout
    assert page.period_end == datetime.date(2025, 12, 31)
    assert page.registrant == "JPMorgan Chase & Co"
    assert form_10k_10q.parse_date("Sept. 30, 2024") == datetime.date(
        2024, 9, 30
    )
    assert form_10k_10q.parse_date("Smarch 3, 2024") is None
    assert form_10k_10q.parse_date("February 30, 2024") is None
    assert form_10k_10q.parse_date("no date") is None


def test_registrant_variants() -> None:
    after = form_10k_10q.read_cover(
        "Exact name of registrant as specified in its charter:Bank of America "
        "Corporation State or other jurisdiction"
    )
    assert after.registrant == "Bank of America Corporation"
    assert after.registrant_labeled
    file_no = form_10k_10q.read_cover(
        "Commission File Number 001-37845\nMICROSOFT CORPORATION\nwashington"
    )
    assert file_no.registrant == "MICROSOFT CORPORATION"
    assert not file_no.registrant_labeled
    assert base.names_match("The Coca-Cola Company", "COCA COLA CO")
    assert base.names_match(
        "The Procter & Gamble Company", "THEPROCTER & GAMBLE COMPANY"
    )
    assert not base.names_match(
        "General Electric Company", "General Electric Capital Corporation"
    )


def test_unlabeled_registrant_mismatch_warns(
    tmp_path: pathlib.Path, cover: str, context: base.ParseContext
) -> None:
    text = cover.replace(
        "NVIDIA CORPORATION(Exact name of registrant as specified in its "
        "charter)",
        "\nDelaware\n",
    )
    parsed = parse_as(tmp_path, NVDA_10Q, text, context)
    assert parsed.quarantine is None
    assert "registrant_not_found" in parsed.warnings
    assert parsed.metadata.registrant is None


def test_header_errors(
    tmp_path: pathlib.Path, cover: str, context: base.ParseContext
) -> None:
    no_cik = cover.replace("CIK: 0001045810\n", "")
    parsed = parse_as(tmp_path, NVDA_10Q, no_cik, context)
    assert parsed.quarantine is not None
    assert parsed.quarantine.reason == "header_error"
    assert "CIK" in parsed.quarantine.detail
    eight_k = cover.replace("10-Q (Quarterly Report)", "8-K (Current Report)")
    with pytest.raises(errors.HeaderError):
        form_10k_10q.parse_header(eight_k.split("\n")[:9])
    assert parse_as(tmp_path, NVDA_10Q, eight_k, context).quarantine


def test_override_lifts_quarantine(
    tmp_path: pathlib.Path, context: base.ParseContext
) -> None:
    ge = (conftest.SNIPPETS / "ge_10k_2015_cover.txt").read_text(
        encoding="utf-8"
    )
    lift = {
        "GE_10K_2015-02-27_full.txt": {
            "ticker": "GE",
            "company": "General Electric Capital Corporation",
            "form": "10-K",
            "period_end_date": "2014-12-31",
        }
    }
    lifted = dataclasses.replace(context, overrides=lift)
    parsed = parse_as(tmp_path, "GE_10K_2015-02-27_full.txt", ge, lifted)
    assert parsed.quarantine is None
    assert parsed.metadata.period_source == "override"
    assert parsed.filing_id == "GE_10K_2014-12-31"


def test_context_from_settings_errors(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    bad = tmp_path / "months.yaml"
    bad.write_text("AAPL: 13\n", encoding="utf-8")
    parser = settings.parser.model_copy(update={"fiscal_year_ends": bad})
    with pytest.raises(errors.ConfigError):
        base.ParseContext.from_settings(
            settings.model_copy(update={"parser": parser})
        )
    bad.write_text("AAPL: september\n", encoding="utf-8")
    with pytest.raises(errors.ConfigError):
        base.ParseContext.from_settings(
            settings.model_copy(update={"parser": parser})
        )
    with pytest.raises(errors.ConfigError):
        config.read_word_list(tmp_path / "absent.txt")
    words = tmp_path / "words.txt"
    words.write_text("# comment\n\nInc.\n Corp. \n", encoding="utf-8")
    assert config.read_word_list(words) == ("Inc.", "Corp.")


def test_year_end_months_notes() -> None:
    def ten_k(ticker: str, day: datetime.date, filed: str) -> base.ParsedFiling:
        meta = base.FilingMetadata(
            file_name=f"{ticker}_10K_{filed}_full.txt",
            file_sha256="",
            parser_version="1.0.0",
            ticker=ticker,
            form="10-K",
            filing_date=datetime.date.fromisoformat(filed),
            period_end_date=day,
            period_source="cover",
        )
        return base.ParsedFiling(
            metadata=form_10k_10q.with_fiscal_period(meta, 12)
        )

    filings = [
        ten_k("V", datetime.date(2025, 9, 30), "2025-11-06"),
        ten_k("X", datetime.date(2023, 6, 30), "2023-08-01"),
        ten_k("X", datetime.date(2024, 9, 30), "2024-11-01"),
    ]
    months, sources, notes = corpus.year_end_months(filings, {"X": 9})
    assert months == {"V": 9, "X": 9}
    assert sources == {"V": "10-K", "X": "10-K"}
    assert "V: 10-K year-end month 9, config 12" in notes
    assert "X: 10-K year-end months differ: [6, 9]" in notes
    quarterly = base.ParsedFiling(
        metadata=base.FilingMetadata(
            file_name="Y_10Q_2024-05-01_full.txt",
            file_sha256="",
            parser_version="1.0.0",
            ticker="Y",
            form="10-Q",
        )
    )
    months, sources, _ = corpus.year_end_months([quarterly], {"Y": 6})
    assert (months["Y"], sources["Y"]) == (6, "config")


def test_corpus_summary(context: base.ParseContext) -> None:
    result = corpus.parse_corpus(conftest.MINI_CORPUS, context)
    summary = corpus.summarize(result)
    assert summary.files == summary.parsed == 3
    assert summary.quarantined == []
    assert summary.xbrl_min is not None
    assert summary.xbrl_max is not None
    assert summary.split_cover_layout == ["JPM_10K_2026-02-13_full.txt"]
    assert summary.check_status["CK-11"] == {"pass": 3}
    assert summary.year_end_months["NVDA"] == 1
    assert summary.tables > 0
    assert base.quarter_end("2024Q1") == datetime.date(2024, 3, 31)
    assert base.calendar_quarter(datetime.date(2024, 10, 27)) == "2024Q4"
