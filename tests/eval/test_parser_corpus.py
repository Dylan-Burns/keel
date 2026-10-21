"""Parser facts on the full extracted corpus (needs corpus/edgar).

PR runs exclude the `eval` marker. Run with
`uv run pytest -m eval tests/eval/test_parser_corpus.py` after
`uv run keel inventory` has extracted the zip.
"""

import re

import pytest

import conftest
from keel import config
from keel import inventory
from keel.parsers import base
from keel.parsers import corpus

pytestmark = pytest.mark.eval

CORPUS = conftest.REPO_ROOT / "corpus" / "edgar"


@pytest.fixture(scope="module")
def result() -> corpus.CorpusParse:
    if not (CORPUS / "manifest.json").is_file():
        pytest.skip("the full corpus is not extracted; run keel inventory")
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    manifest = inventory.load_manifest(CORPUS / "manifest.json")
    context = base.ParseContext.from_settings(settings, manifest.files)
    return corpus.parse_corpus(CORPUS, context)


def test_all_files_parse_and_ge_quarantined(
    result: corpus.CorpusParse,
) -> None:
    summary = corpus.summarize(result)
    assert summary.files == 246
    assert summary.parsed == 245
    (record,) = summary.quarantined
    assert record.file_name == "GE_10K_2015-02-27_full.txt"
    assert record.reason == "registrant_mismatch"
    assert summary.period_source_filename == []
    assert summary.slow_files == []


def test_xbrl_block_lengths(result: corpus.CorpusParse) -> None:
    lengths = {
        f.metadata.file_name: f.metadata.xbrl_block_chars
        for f in result.filings
    }
    assert lengths["NVDA_10K_2025-02-26_full.txt"] == 18_772
    assert lengths["BAC_10K_2025-02-25_full.txt"] == 284_260
    assert lengths["GE_10K_2015-02-27_full.txt"] == 0
    assert max(lengths.values()) == 284_260


def test_cover_period_agrees_with_header_and_url(
    result: corpus.CorpusParse,
) -> None:
    """The cover period equals the header Report Period and the URL date."""
    for filing in result.filings:
        meta = filing.metadata
        if meta.header_report_period:
            assert meta.header_report_period == str(meta.period_end_date)
        stamp = re.search(r"-(\d{4})(\d{2})(\d{2})\.htm", meta.url or "")
        if stamp:
            assert "-".join(stamp.groups()) == str(meta.period_end_date)
        assert meta.fiscal_period in {"FY", "Q1", "Q2", "Q3"}
