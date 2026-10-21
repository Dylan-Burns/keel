"""Inventory tests on the 3-file mini corpus."""

import datetime
import json
import pathlib
import shutil

import pytest

import conftest
from keel import cli
from keel import config
from keel import inventory

pytestmark = pytest.mark.integration


def test_inventory_counts() -> None:
    """The counts of the mini corpus, and E-D-25 on a quarterly claim."""
    report = inventory.build_inventory(
        conftest.MINI_CORPUS, conftest.MINI_CORPUS / "manifest.json"
    )
    assert report.file_count == 3
    assert report.ticker_count == 3
    assert report.form_counts == {"10-K": 2, "10-Q": 1}
    assert report.year_counts == {2023: 1, 2025: 1, 2026: 1}
    assert report.first_filing == (
        datetime.date(2023, 2, 3),
        "AAPL_10Q_2022Q4_2023-02-03_full.txt",
    )
    assert report.last_filing == (
        datetime.date(2026, 2, 13),
        "JPM_10K_2026-02-13_full.txt",
    )
    assert report.pattern_counts == {"no_period": 2, "with_period": 1}
    assert report.header_shapes == {
        "Company, Ticker, Filing Type, Filing Date, CIK, Source, URL": 2,
        "Company, Ticker, Filing Type, Filing Date, Report Period, Quarter, "
        "CIK, Source, URL": 1,
    }
    assert report.tickers["NVDA"].ten_k == 1
    assert report.tickers["AAPL"].ten_q == 1
    assert report.quarterly_tickers == ["AAPL"]
    assert report.full_quarterly_tickers == []
    assert report.manifest.license is not None
    assert report.manifest.claimed_quarterly_companies == 0
    assert report.discrepancies == []
    latest = report.latest("NVDA", "10-K")
    assert latest is not None
    assert latest.filing_date == datetime.date(2025, 2, 26)
    assert report.latest("NVDA", "10-Q") is None


def test_quarterly_claim_discrepancy(tmp_path: pathlib.Path) -> None:
    """E-D-25: the manifest claims more quarterly companies than exist."""
    corpus = tmp_path / "edgar"
    shutil.copytree(conftest.MINI_CORPUS, corpus)
    manifest = json.loads((corpus / "manifest.json").read_text())
    manifest["description"] = (
        "54 companies. 15 companies have full quarterly coverage for 2023-2025."
    )
    (corpus / "manifest.json").write_text(json.dumps(manifest))
    report = inventory.build_inventory(corpus, corpus / "manifest.json")
    assert report.manifest.claimed_quarterly_companies == 15
    assert report.discrepancies == [
        "manifest claims 15 companies with full quarterly coverage, the "
        "files show 0 (E-D-25)"
    ]


def test_inventory_command(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        [
            "--config",
            str(conftest.CONFIG_FILE),
            "inventory",
            "--corpus",
            str(conftest.MINI_CORPUS),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "files: 3" in out
    assert "forms: 10-K 2, 10-Q 1" in out
    assert "A-15: NVDA 10-K filed February 2026 is absent" in out
    assert "discrepancies: 0" in out


def test_inventory_command_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        [
            "--config",
            str(conftest.CONFIG_FILE),
            "inventory",
            "--corpus",
            str(conftest.MINI_CORPUS),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["file_count"] == 3
    assert payload["a15"].startswith("A-15: NVDA 10-K")


def test_inventory_command_without_corpus(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    code = cli.main(
        [
            "--config",
            str(conftest.CONFIG_FILE),
            "inventory",
            "--corpus",
            str(tmp_path / "absent"),
        ]
    )
    assert code == 2
    assert "CorpusMissingError" in caplog.text


def _copy_mini(tmp_path: pathlib.Path) -> pathlib.Path:
    corpus = tmp_path / "edgar"
    shutil.copytree(conftest.MINI_CORPUS, corpus)
    return corpus


def _rewrite_manifest(corpus: pathlib.Path, **changes: object) -> None:
    path = corpus / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_manifest_mismatch(tmp_path: pathlib.Path) -> None:
    """E-D-24: absent and unmanifested files are both listed."""
    corpus = _copy_mini(tmp_path)
    (corpus / "AAPL_10Q_2022Q4_2023-02-03_full.txt").rename(
        corpus / "AAPL_10Q_2023-02-03_full.txt"
    )
    (corpus / "notes_full.txt").write_text("stray\n", encoding="utf-8")
    _rewrite_manifest(corpus, file_count=4, filing_types={"10-K": 2, "10-Q": 2})
    report = inventory.build_inventory(corpus, corpus / "manifest.json")
    assert report.manifest.present
    assert report.manifest.absent_files == [
        "AAPL_10Q_2022Q4_2023-02-03_full.txt"
    ]
    assert report.manifest.unmanifested_files == [
        "AAPL_10Q_2023-02-03_full.txt",
        "notes_full.txt",
    ]
    assert report.unmatched_files == ["notes_full.txt"]
    text = "\n".join(report.discrepancies)
    assert "1 manifest files absent on disk" in text
    assert "2 files on disk not in the manifest" in text
    assert "manifest 10-Q count 2, directory 1" in text
    assert "file name matches no pattern: notes_full.txt" in text
    # The file count agrees (4 on disk), so no count line.
    assert "file_count" not in text


def test_manifest_missing_is_a_warning(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    corpus = _copy_mini(tmp_path)
    (corpus / "manifest.json").unlink()
    report = inventory.build_inventory(corpus, corpus / "manifest.json")
    assert not report.manifest.present
    assert report.file_count == 3
    assert report.discrepancies == [
        "manifest absent or unusable: no manifest comparison"
    ]
    assert "manifest unusable" in caplog.text


def test_file_count_claim(tmp_path: pathlib.Path) -> None:
    corpus = _copy_mini(tmp_path)
    _rewrite_manifest(corpus, file_count=246)
    report = inventory.build_inventory(corpus, corpus / "manifest.json")
    assert report.discrepancies == ["manifest file_count 246, directory 3"]


def test_date_filter_config(clean_env: pytest.MonkeyPatch) -> None:
    """E-D-02: all files stay by default; a config window can exclude."""
    default = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    assert default.corpus.date_filter is None
    kept = inventory.build_inventory(
        conftest.MINI_CORPUS,
        conftest.MINI_CORPUS / "manifest.json",
        default.corpus.date_filter,
    )
    assert kept.date_filter_excluded == []

    clean_env.setenv(
        "KEEL_CORPUS__DATE_FILTER", '{"min": "2023-01-01", "max": "2025-12-31"}'
    )
    loaded = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    window = loaded.corpus.date_filter
    assert window == config.DateFilter(
        min=datetime.date(2023, 1, 1), max=datetime.date(2025, 12, 31)
    )
    assert window.includes(datetime.date(2023, 2, 3))
    assert not window.includes(datetime.date(2022, 12, 31))
    assert not window.includes(datetime.date(2026, 2, 13))
    report = inventory.build_inventory(
        conftest.MINI_CORPUS, conftest.MINI_CORPUS / "manifest.json", window
    )
    # The JPM 10-K filed 2026-02-13 falls outside; the files still count.
    assert report.date_filter_excluded == ["JPM_10K_2026-02-13_full.txt"]
    assert report.file_count == 3
