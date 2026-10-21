"""Parser tests on the 3-file mini corpus and the `keel parse` command."""

import json
import pathlib

import pytest

import conftest
from keel import cli

pytestmark = pytest.mark.integration


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = cli.main(["--config", str(conftest.CONFIG_FILE), *args])
    return code, capsys.readouterr().out


def test_parse_all_summary(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    del clean_env
    code, out = run(
        capsys,
        "parse",
        "--all",
        "--summary",
        "--corpus",
        str(conftest.MINI_CORPUS),
    )
    assert code == 0
    assert "files: 3" in out
    assert "parsed: 3" in out
    assert "quarantined: 0" in out
    assert "CK-10: pass 3" in out
    assert (
        "cover period from split cells: 1 (JPM_10K_2026-02-13_full.txt)" in out
    )


def test_parse_files_json(
    clean_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    del clean_env
    files = sorted(str(p) for p in conftest.MINI_CORPUS.glob("*.txt"))
    code, out = run(capsys, "parse", "--json", "--summary", *files)
    assert code == 0
    payload = json.loads(out)
    rows = {row["file"]: row for row in payload["files"]}
    assert rows["AAPL_10Q_2022Q4_2023-02-03_full.txt"]["fiscal"] == "Q1 2023"
    assert rows["NVDA_10K_2025-02-26_full.txt"]["filing_id"] == (
        "NVDA_10K_2025-01-26"
    )
    assert rows["JPM_10K_2026-02-13_full.txt"]["quarantine"] is None
    assert payload["summary"]["files"] == 3


def test_parse_text_rows_and_errors(
    clean_env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: pathlib.Path,
) -> None:
    del clean_env
    path = conftest.MINI_CORPUS / "NVDA_10K_2025-02-26_full.txt"
    code, out = run(capsys, "parse", "--corpus", str(tmp_path), str(path))
    assert code == 0
    assert out.startswith(
        "NVDA_10K_2025-02-26_full.txt: ok, NVDA_10K_2025-01-26"
    )
    code, _ = run(capsys, "parse")
    assert code == 2
