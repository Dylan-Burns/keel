"""The corpus facts on the full extracted corpus (needs corpus/edgar).

PR runs exclude the `eval` marker. Run with
`uv run pytest -m eval tests/eval/test_corpus_facts.py` after
`uv run keel inventory` has extracted the zip.
"""

import datetime

import pytest

import conftest
from keel import inventory

pytestmark = pytest.mark.eval

CORPUS = conftest.REPO_ROOT / "corpus" / "edgar"


@pytest.fixture(scope="module")
def report() -> inventory.InventoryReport:
    if not (CORPUS / "manifest.json").is_file():
        pytest.skip("the full corpus is not extracted; run keel inventory")
    return inventory.build_inventory(CORPUS, CORPUS / "manifest.json")


def test_corpus_facts(report: inventory.InventoryReport) -> None:
    assert report.file_count == 246
    assert report.ticker_count == 54
    assert report.form_counts == {"10-K": 89, "10-Q": 157}
    assert report.year_counts == {
        2015: 1,
        2022: 37,
        2023: 50,
        2024: 52,
        2025: 79,
        2026: 27,
    }
    assert report.first_filing == (
        datetime.date(2015, 2, 27),
        "GE_10K_2015-02-27_full.txt",
    )
    assert report.last_filing is not None
    assert report.last_filing[0] == datetime.date(2026, 2, 19)
    assert report.pattern_counts == {"no_period": 54, "with_period": 192}


def test_corpus_discrepancies(report: inventory.InventoryReport) -> None:
    # E-D-25 and A-14: the manifest claims 15, the files show 12.
    assert report.manifest.claimed_quarterly_companies == 15
    assert len(report.full_quarterly_tickers) == 12
    assert report.manifest.absent_files == []
    assert report.manifest.unmanifested_files == []
    assert len(report.discrepancies) == 1


def test_a15_nvda_10k(report: inventory.InventoryReport) -> None:
    # A-15: the NVDA 10-K filed in February 2026 is not in the corpus.
    latest = report.latest("NVDA", "10-K")
    assert latest is not None
    assert latest.name == "NVDA_10K_2025-02-26_full.txt"
