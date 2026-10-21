"""Inventory tests on the header snippets copied from real filings."""

import pytest

import conftest
from keel import inventory

pytestmark = pytest.mark.unit


def test_header_keys_both_shapes() -> None:
    nine = inventory.header_keys(
        conftest.SNIPPETS / "aapl_10q_2022q4_header.txt"
    )
    assert nine == (
        "Company",
        "Ticker",
        "Filing Type",
        "Filing Date",
        "Report Period",
        "Quarter",
        "CIK",
        "Source",
        "URL",
    )
    seven = inventory.header_keys(
        conftest.SNIPPETS / "nvda_10k_fy2025_header.txt"
    )
    assert seven == (
        "Company",
        "Ticker",
        "Filing Type",
        "Filing Date",
        "CIK",
        "Source",
        "URL",
    )
