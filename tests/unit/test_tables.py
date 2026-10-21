"""Table reconstruction rules of chapter 7.8 on real row shapes."""

import pytest

from keel import tables

pytestmark = pytest.mark.unit


def test_numeric_and_label_cells() -> None:
    for cell in ("130,497", "$ 4.93", "(1,234)", "12 %", "-", "(31)", "0.5"):
        assert tables.is_numeric(cell), cell
    for cell in ("Net income", "Jan 26, 2025", "2026 and thereafter"):
        assert not tables.is_numeric(cell), cell
    assert tables.is_label_row(["", "Jan 26, 2025", "", "Jan 28, 2024"])
    assert not tables.is_label_row(["Net income", "$", "72,880", "$", "29,760"])
    assert not tables.is_label_row(["", ""])
    assert tables.is_label_row(["Segment", "2025", "2024"])
    assert not tables.is_label_row(["2026", "$", "354"])
    assert tables.is_label_row(["Revenue", "100"])
    assert not tables.is_label_row(["Revenue", "100"], strict=True)


def test_split_and_merge_cells() -> None:
    assert tables.split_cells("| a |  | b |") == ["a", "", "b"]
    assert tables.split_cells("a | b") == ["a", "b"]
    assert tables.merge_currency(["Total", "$", "807", ""]) == (
        "Total",
        "$ 807",
    )
    assert tables.merge_currency(["x", "$"]) == ("x", "$")
    assert not tables.is_table_row("a | b")
    assert not tables.is_table_row("a | b | " + "x" * 3000)


def test_groups_allow_1_blank_line() -> None:
    text = "\n".join(
        [
            "Revenue by Reportable Segments",
            "(In millions)",
            "Segment | 2025 | 2024",
            "Compute | 116,193 | 47,405",
            "",
            "Graphics | 14,304 | 13,517",
            "",
            "",
            "Other | 1 | 2",
            "Total | 3 | 4",
        ]
    )
    first, second = tables.find_tables(text)
    assert first.title == "Revenue by Reportable Segments"
    assert first.units == "in millions"
    assert first.columns == ("Segment", "2025", "2024")
    assert first.rows == (
        ("Compute", "116,193", "47,405"),
        ("Graphics", "14,304", "13,517"),
    )
    assert text[first.start : first.end].startswith("Segment")
    assert text[first.start : first.end].endswith("13,517")
    assert second.title == ""
    assert second.caption() == "TABLE:"
    assert second.rows == (("Other", "1", "2"), ("Total", "3", "4"))


def test_long_table_splits_in_parts_of_40() -> None:
    rows = [f"Row {n} | {n},000 |" for n in range(95)]
    (table,) = tables.find_tables("\n".join(["Name | Value |", *rows]))
    parts = table.render()
    assert [len(part.split("\n")) for part in parts] == [41, 41, 16]
    assert all(
        part.startswith("TABLE: | columns: Name | Value") for part in parts
    )


def test_title_rules() -> None:
    lines = [
        "This sentence ends with a period.",
        "| Year Ended",
        "a | b | c",
        "1 | 2 | 3",
    ]
    (table,) = tables.find_tables("\n".join(lines))
    assert table.title == ""
    labels_only = tables.Table(
        start=0, end=0, title="T", units="", columns=("a",), rows=()
    )
    assert labels_only.render() == ["TABLE: T | columns: a"]
