"""Tests for the file-name patterns, the header keys, and the manifest."""

import datetime
import pathlib

import pytest

from keel import errors
from keel import inventory

pytestmark = pytest.mark.unit


def test_filename_patterns() -> None:
    """E-D-03 and E-D-04: both file-name patterns parse."""
    with_period = inventory.parse_filename(
        "AAPL_10Q_2022Q4_2023-02-03_full.txt"
    )
    assert with_period == inventory.FileName(
        name="AAPL_10Q_2022Q4_2023-02-03_full.txt",
        ticker="AAPL",
        form="10-Q",
        period_code="2022Q4",
        filing_date=datetime.date(2023, 2, 3),
        pattern="with_period",
    )
    no_period = inventory.parse_filename("NVDA_10K_2025-02-26_full.txt")
    assert no_period is not None
    assert no_period.form == "10-K"
    assert no_period.period_code is None
    assert no_period.pattern == "no_period"
    assert no_period.filing_date == datetime.date(2025, 2, 26)
    one_letter = inventory.parse_filename("T_10K_2026-02-09_full.txt")
    assert one_letter is not None
    assert one_letter.ticker == "T"
    for bad in (
        "manifest.json",
        "AAPL_8K_2023-02-03_full.txt",
        "AAPL_10Q_2022Q5_2023-02-03_full.txt",
        "AAPL_10Q_2023-02-30_full.txt",
        "aapl_10Q_2023-02-03_full.txt",
        "AAPL_10Q_2023-02-03.txt",
    ):
        assert inventory.parse_filename(bad) is None, bad


def test_header_without_separator(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "A_10K_2024-01-01_full.txt"
    path.write_text("\ufeffCompany: A\nTicker: A\nbody\n", encoding="utf-8")
    assert inventory.header_keys(path) == ()


def test_manifest_invalid_json(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(errors.ManifestMissingError):
        inventory.load_manifest(path)
    path.write_text('{"file_count": 1}', encoding="utf-8")
    with pytest.raises(errors.ManifestMissingError):
        inventory.load_manifest(path)


def test_corpus_missing(tmp_path: pathlib.Path) -> None:
    with pytest.raises(errors.CorpusMissingError):
        inventory.build_inventory(tmp_path / "absent", tmp_path / "m.json")


def test_full_quarterly_coverage_rule() -> None:
    names = [
        f"AAA_10Q_{year}-{month:02d}-01_full.txt"
        for year in (2023, 2024, 2025)
        for month in (5, 8, 11)
    ]
    names += [
        f"BBB_10Q_{year}-{month:02d}-01_full.txt"
        for year in (2023, 2024, 2025)
        for month in (5, 8)
    ]
    names.append("CCC_10K_2024-02-01_full.txt")
    parsed = [inventory.parse_filename(name) for name in names]
    files = [item for item in parsed if item is not None]
    assert inventory.full_quarterly_coverage(files) == ["AAA"]
