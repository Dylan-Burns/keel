"""Question understanding on the mini corpus and `keel understand`."""

import datetime
import json

import pytest

import conftest
from keel import cli
from keel import config
from keel import understanding
from keel.parsers import base
from keel.parsers import corpus

pytestmark = pytest.mark.integration


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = cli.main(["--config", str(conftest.CONFIG_FILE), *args])
    return code, capsys.readouterr().out


def test_catalog_from_mini_corpus(settings: config.Settings) -> None:
    context = base.ParseContext.from_settings(settings)
    result = corpus.parse_corpus(conftest.MINI_CORPUS, context)
    catalog = understanding.Catalog.from_parse(result)
    assert catalog.indexed_tickers == ["AAPL", "JPM", "NVDA"]
    assert catalog.year_end_month("NVDA") == 1
    assert catalog.last_filing_date == datetime.date(2026, 2, 13)
    step = understanding.Understander.from_settings(settings, catalog)
    analysis = step.analyze(
        "How has NVIDIA's revenue and growth outlook changed over the last "
        "two years?"
    )
    window = analysis.windows["NVDA"]
    assert window is not None
    assert window.anchor == datetime.date(2025, 1, 26)
    assert window.filings == ("fiscal 2025 10-K (ended 2025-01-26)",)


def test_catalog_quarantine() -> None:
    meta = base.FilingMetadata(
        file_name="GE_10K_2015-02-27_full.txt",
        file_sha256="0" * 64,
        parser_version="1.0.0",
    )
    record = base.QuarantineRecord(
        file_name="GE_10K_2015-02-27_full.txt",
        reason="registrant_mismatch",
        detail="cover and header names differ",
    )
    result = corpus.CorpusParse(
        filings=[
            base.ParsedFiling(metadata=meta, quarantine=record),
            base.ParsedFiling(metadata=meta.model_copy(update={"ticker": "X"})),
        ],
        year_end_months={},
        year_end_sources={},
    )
    catalog = understanding.Catalog.from_parse(result)
    assert catalog.filings == ()
    assert catalog.quarantined[0].ticker == "GE"
    assert catalog.quarantined[0].reason == "registrant_mismatch"


def test_understand_command(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    del clean_env
    code, out = run(
        capsys,
        "understand",
        "What are the primary risk factors facing Apple and JPMorgan?",
        "--corpus",
        str(conftest.MINI_CORPUS),
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["tickers"] == ["AAPL", "JPM"]
    assert payload["section_weights"]["risk_factors"] == 1.5
    code, out = run(
        capsys,
        "understand",
        "x" * 1001,
        "--corpus",
        str(conftest.MINI_CORPUS),
    )
    assert code == 1
    assert out.startswith("HTTP 413")
