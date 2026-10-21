"""Section facts on the full extracted corpus (needs corpus/edgar).

PR runs exclude the `eval` marker. Run with
`uv run pytest -m eval tests/eval/test_sections_corpus.py` after
`uv run keel inventory` has extracted the zip.
"""

import pytest

import conftest
from keel import config
from keel import sections
from keel.parsers import base
from keel.parsers import corpus

pytestmark = pytest.mark.eval

CORPUS = conftest.REPO_ROOT / "corpus" / "edgar"
NVDA_10K = "NVDA_10K_2025-02-26_full.txt"


@pytest.fixture(scope="module")
def result() -> corpus.CorpusParse:
    if not (CORPUS / "manifest.json").is_file():
        pytest.skip("the full corpus is not extracted; run keel inventory")
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    context = base.ParseContext.from_settings(settings)
    return corpus.parse_corpus(CORPUS, context)


def test_nvda_item_1a_once(result: corpus.CorpusParse) -> None:
    """Chapter 8.7: 1 real risk section over 20,000 characters, 7 rejects."""
    filing = next(f for f in result.filings if f.metadata.file_name == NVDA_10K)
    detected = sections.detect(filing.text, "10-K")
    (risk,) = detected.of("risk_factors")
    assert risk.end - risk.start > 20_000
    labels = [c for c in detected.candidates if c.item == "1A"]
    assert len(labels) == 8
    assert sum(c.kind != "heading" for c in labels) == 7


def test_core_section_coverage(result: corpus.CorpusParse) -> None:
    """Chapter 8.6: 95% or more of the 10-Ks have the 3 core sections."""
    rows = [
        (
            f.metadata.file_name,
            f.metadata.form or "",
            sections.detect(f.text, f.metadata.form or ""),
        )
        for f in result.filings
        if not f.quarantined
    ]
    report = sections.coverage_report(rows)
    assert report.core_share["10-K"] >= 0.95
    assert report.core_share["10-Q"] >= 0.95
