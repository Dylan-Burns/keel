"""The eval page data of chapter 25.2: the documents and the gates."""

import os
import pathlib

import pytest

import conftest
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
    if os.geteuid() == 0:  # root reads a file with mode 0
        return
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
    assert gates[1].comparator == "<"
    assert gates[1].threshold == 1000.0
    assert gates[1].passed is False


def test_parse_gates_chapter_wording() -> None:
    text = (
        "| Gate | Threshold | Value |\n"
        "| --- | --- | --- |\n"
        "| Recall at 25 | 0.85 or more | 0.85 |\n"
        "| Latency p95 | 40 seconds or less | 41 s |\n"
        "| Mean cost per question | $0.25 or less | $0.20 |\n"
        "| Strict | > 0.5 | 0.5 |\n"
        "| Strict below | < 2 | 1 |\n"
    )
    gates = {g.name: g for g in eval_page.parse_gates(text)}
    assert gates["Recall at 25"].comparator == ">="
    assert gates["Recall at 25"].passed is True
    assert gates["Latency p95"].comparator == "<="
    assert gates["Latency p95"].passed is False
    assert gates["Mean cost per question"].comparator == "<="
    assert gates["Mean cost per question"].passed is True
    assert gates["Strict"].comparator == ">"
    assert gates["Strict"].passed is False
    assert gates["Strict below"].passed is True


def test_load_prefers_the_newest_job_report(tmp_path: pathlib.Path) -> None:
    committed = tmp_path / "report.md"
    committed.write_text("committed")
    runs = tmp_path / "runs"
    log = tmp_path / "PROMPT_LOG.md"
    # No run directory yet: the committed report.
    page = eval_page.load(committed, log, runs)
    assert page.report.source == eval_page.REPORT_LABEL
    assert page.report.markdown == "committed"
    assert eval_page.load(committed, log).report.markdown == "committed"
    runs.mkdir()
    (runs / "eval-20261021T090000Z.md").write_text("older")
    (runs / "eval-20261022T090000Z.md").write_text("newer")
    (runs / "eval-20261023T090000Z.json").write_text("{}")
    (runs / "eval-20261024T090000Z.md").symlink_to(committed)
    page = eval_page.load(committed, log, runs)
    assert page.report.source == "eval run eval-20261022T090000Z"
    assert page.report.markdown == "newer"


def test_latest_run_report_unreadable_dir(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> list[pathlib.Path]:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pathlib.Path, "glob", broken)
    assert eval_page.latest_run_report(tmp_path) is None
    assert eval_page.latest_run_report(None) is None


def test_read_prompts_in_version_order(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for version in ("1.10.0", "1.2.0", "1.9.1"):
        (tmp_path / f"answer_system_v{version}.md").write_text(
            f"system {version}", encoding="utf-8"
        )
    (tmp_path / "answer_user_v1.2.0.md").write_text("user", encoding="utf-8")
    (tmp_path / "judge_v1.0.0.md").write_text("judge", encoding="utf-8")
    (tmp_path / "answer_system_v2.0.0.md").write_text("x" * 20, "utf-8")
    monkeypatch.setattr(eval_page, "MAX_PROMPT_BYTES", 16)
    prompts = eval_page.read_prompts(tmp_path, "1.9.1")
    # Numeric order, not text order; the judge and the oversize file stay out.
    assert [p.version for p in prompts] == ["1.2.0", "1.9.1", "1.10.0"]
    assert prompts[0].user == "user"
    assert prompts[1].user is None
    assert [p.current for p in prompts] == [False, True, False]


def test_read_prompts_without_a_directory(tmp_path: pathlib.Path) -> None:
    assert not eval_page.read_prompts(None, "1.0.0")
    assert not eval_page.read_prompts(tmp_path / "missing", "1.0.0")


def test_load_includes_the_committed_prompts(tmp_path: pathlib.Path) -> None:
    page = eval_page.load(
        tmp_path / "report.md",
        tmp_path / "log.md",
        prompts_dir=conftest.REPO_ROOT / "prompts",
        current_prompt="1.5.1",
    )
    versions = [p.version for p in page.prompts]
    assert versions[0] == "1.0.0"
    assert "1.5.1" in versions
    assert [p.version for p in page.prompts if p.current] == ["1.5.1"]
