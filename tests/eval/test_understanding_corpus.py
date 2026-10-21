"""The 3 example questions on the full corpus (needs corpus/edgar).

PR runs exclude the `eval` marker. Run with
`uv run pytest -m eval tests/eval/test_understanding_corpus.py` after
`uv run keel inventory` has extracted the zip.
"""

import datetime

import pytest

import conftest
from keel import config
from keel import understanding
from keel.parsers import base
from keel.parsers import corpus

pytestmark = pytest.mark.eval

CORPUS = conftest.REPO_ROOT / "corpus" / "edgar"


@pytest.fixture(scope="module")
def step() -> understanding.Understander:
    if not (CORPUS / "manifest.json").is_file():
        pytest.skip("the full corpus is not extracted; run keel inventory")
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    context = base.ParseContext.from_settings(settings)
    catalog = understanding.Catalog.from_parse(
        corpus.parse_corpus(CORPUS, context)
    )
    return understanding.Understander.from_settings(settings, catalog)


def test_example_questions(step: understanding.Understander) -> None:
    """Chapters 10 and 11.7 to 11.9: the 3 examples resolve as planned."""
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    questions = settings.demo.example_questions
    first, second, third = (step.analyze(q) for q in questions)
    assert first.tickers == ("AAPL", "TSLA", "JPM")
    assert first.primary_type == "comparison"
    assert second.tickers == ("NVDA",)
    assert second.types == ("trend", "numeric", "single_company")
    window = second.windows["NVDA"]
    assert window is not None
    # A-15 is false: the anchor is the fiscal 2026 Q3 10-Q (case B).
    assert window.anchor == datetime.date(2025, 10, 26)
    assert window.filings[0] == "Q3 fiscal 2024 10-Q (ended 2023-10-29)"
    assert len(window.filings) == 9
    assert third.primary_type == "sector"
    assert third.tickers == ("PFE", "JNJ", "MRK", "LLY", "ABBV")
    assert all(a.elapsed_ms < 10 for a in (first, second, third))


def test_ge_quarantine_on_corpus(step: understanding.Understander) -> None:
    """E-Q-03 and E-D-01: GE is in the manifest but not indexed."""
    analysis = step.analyze("What are General Electric's risk factors?")
    (ge,) = analysis.not_indexed
    assert ge.reason == "registrant_mismatch"
    assert ge.file_name == "GE_10K_2015-02-27_full.txt"
