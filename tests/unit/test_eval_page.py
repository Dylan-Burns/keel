"""The eval page data of chapter 25.2: the documents and the gates."""

import pathlib

import pytest

from keel.api import eval_page


def test_read_document_truncates(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(eval_page, "MAX_BYTES", 8)
    path = tmp_path / "report.md"
    path.write_bytes(b"0123456789\xff")
    document = eval_page.read_document(path, "eval/report.md")
    assert document.markdown == "01234567"
    assert document.truncated is True


def test_read_document_unreadable(tmp_path: pathlib.Path) -> None:
    folder = tmp_path / "report.md"
    folder.mkdir()
    assert eval_page.read_document(folder, "x").markdown is None
    blocked = tmp_path / "blocked.md"
    blocked.write_text("text")
    blocked.chmod(0)
    try:
        assert eval_page.read_document(blocked, "x").markdown is None
    finally:
        blocked.chmod(0o600)


def test_parse_gates_edge_rows() -> None:
    assert eval_page.parse_gates(None) == []
    assert eval_page.parse_gates("no table\n| a | b |\n| - | - |\n") == []
    text = (
        "| Gate | Threshold | Value |\n"
        "| --- | --- | --- |\n"
        "| Schema validity | >= 1.00 | 1.00 |\n"
        "| No threshold | n/a | 1 |\n"
        "| | >= 1 | 1 |\n"
        "| Cost | < 1,000 USD | 1,200 USD |\n"
        "\n"
        "| Gate | Threshold | Value |\n"
    )
    gates = eval_page.parse_gates(text)
    assert [g.name for g in gates] == ["Schema validity", "Cost"]
    assert gates[0].passed is True
    assert gates[0].status is None
    assert gates[1].comparator == "<="
    assert gates[1].threshold == 1000.0
    assert gates[1].passed is False
