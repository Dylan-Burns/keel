"""Sections and chunks on the mini corpus, and the stage 3 commands."""

import json

import pytest

import conftest
from keel import cli
from keel import config
from keel import sections
from keel.parsers import base
from keel.parsers import corpus

pytestmark = pytest.mark.integration

AAPL_10Q = "AAPL_10Q_2022Q4_2023-02-03_full.txt"
NVDA_10K = "NVDA_10K_2025-02-26_full.txt"


@pytest.fixture(scope="module")
def parsed() -> dict[str, base.ParsedFiling]:
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    context = base.ParseContext.from_settings(settings)
    result = corpus.parse_corpus(conftest.MINI_CORPUS, context)
    return {f.metadata.file_name: f for f in result.filings}


def detect(filing: base.ParsedFiling) -> sections.SectionResult:
    assert filing.metadata.form is not None
    return sections.detect(filing.text, filing.metadata.form)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = cli.main(["--config", str(conftest.CONFIG_FILE), *args])
    return code, capsys.readouterr().out


def test_10q_mdna(parsed: dict[str, base.ParsedFiling]) -> None:
    filing = parsed[AAPL_10Q]
    (mdna,) = detect(filing).of("mdna")
    assert mdna.item_label == "Part I Item 2"
    assert filing.text[mdna.start :].startswith("Item 2.")
    assert not mdna.delta_only


def test_10q_part_ii_risk(parsed: dict[str, base.ParsedFiling]) -> None:
    filing = parsed[AAPL_10Q]
    (risk,) = detect(filing).of("risk_factors")
    assert risk.item_label == "Part II Item 1A"
    assert risk.delta_only
    assert filing.text[risk.start :].startswith("Item 1A.")


def test_10k_properties_other(parsed: dict[str, base.ParsedFiling]) -> None:
    result = detect(parsed[NVDA_10K])
    properties = [s for s in result.sections if s.item_label == "Item 2"]
    assert [s.section for s in properties] == ["other"]
    assert properties[0].title == "Properties"
    assert not result.of("business")[0].delta_only


def test_10k_exhibits_span(parsed: dict[str, base.ParsedFiling]) -> None:
    filing = parsed[NVDA_10K]
    result = detect(filing)
    excluded = result.of("excluded")
    assert excluded[0].item_label == "Item 15"
    assert filing.text[excluded[0].start :].startswith("Item 15.")
    assert result.sections[-1].end == len(filing.text)


def test_parse_sections_report(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    del clean_env
    args = ("parse", "--all", "--corpus", str(conftest.MINI_CORPUS))
    code, out = run(capsys, *args, "--sections-report")
    assert code == 0
    assert "10-K: 2 filings" in out
    assert "10-Q: 1 filings" in out
    assert "filings with the section:" in out
    assert "section warnings:" in out
    code, out = run(capsys, *args, "--sections-report", "--json")
    payload = json.loads(out)
    assert payload["sections"]["filings"] == {"10-K": 2, "10-Q": 1}


def test_chunk_summary(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    del clean_env
    args = ("chunk", "--all", "--corpus", str(conftest.MINI_CORPUS))
    code, out = run(capsys, *args, "--summary")
    assert code == 0
    assert "filings chunked: 3" in out
    assert "tokens per chunk:" in out
    assert "over the limit: 0" in out
    code, out = run(capsys, *args, "--json")
    payload = json.loads(out)
    assert payload["filings"] == 3
    assert payload["chunks"] > 30
    assert payload["over_limit"] == 0
    assert set(payload["by_form"]) == {"10-K", "10-Q"}


def test_chunk_needs_files(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    del clean_env
    code, _ = run(capsys, "chunk")
    assert code == 2
    path = conftest.MINI_CORPUS / NVDA_10K
    code, out = run(capsys, "chunk", str(path))
    assert code == 0
    assert "filings chunked: 1" in out
