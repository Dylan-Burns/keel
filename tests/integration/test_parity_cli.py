"""The CLI twins of the web pages: history, share, coverage, and jobs."""

import json
import pathlib

import pytest

import conftest
from keel import cache
from keel import cli
from keel import config
from keel import indexer
from keel import parity_cli
from keel.stores import admin_store

pytestmark = pytest.mark.integration

QUESTION = "What are NVIDIA's risk factors?"


@pytest.fixture
def env(
    settings: config.Settings,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, pathlib.Path]:
    paths = {
        "logs": tmp_path / "logs",
        "answers": tmp_path / "answers",
        "index": tmp_path / "index",
    }
    paths["logs"].mkdir()
    monkeypatch.setenv("KEEL_LOGS__DIR", str(paths["logs"]))
    monkeypatch.setenv("KEEL_CACHE__ANSWERS_DIR", str(paths["answers"]))
    monkeypatch.setenv("KEEL_INDEX__DIR", str(paths["index"]))
    del settings
    return paths


def keel(*args: str) -> int:
    return cli.main(["--config", str(conftest.CONFIG_FILE), *args])


def audit_line(request_id: str, user: str, stamp: str, **extra) -> str:
    record = {
        "request_id": request_id,
        "timestamp": stamp,
        "question": QUESTION,
        "user_name": user,
        "outcome": "answered",
        "model": "claude-sonnet-5-5",
        "index_version": "1.0.0",
        "prompt_version": "1.0.0",
        "cost_usd": 0.1,
        **extra,
    }
    return json.dumps(record) + "\n"


def test_history_command(env, capsys) -> None:
    (env["logs"] / "audit.jsonl").write_text(
        audit_line("r-1", "alice", "2026-10-22T01:00:00+00:00")
        + audit_line("r-2", "bob", "2026-10-22T02:00:00+00:00")
        + audit_line(
            "r-3",
            "alice",
            "2026-10-22T03:00:00+00:00",
            question="Apple\x1b[31m risks",
        )
    )
    assert keel("history") == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split("\t")[1] for line in out[:3]] == ["r-3", "r-2", "r-1"]
    assert out[-1].startswith("3 questions from")
    assert out[0].endswith("Apple [31m risks")
    assert keel("history", "--user", "alice", "--limit", "1", "--json") == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["request_id"] for r in rows] == ["r-3"]
    assert rows[0]["user"] == "alice"
    with pytest.raises(SystemExit):
        keel("history", "--limit", "0")


def test_share_command(env, capsys) -> None:
    line = audit_line("r-9", "alice", "2026-10-22T01:00:00+00:00")
    (env["logs"] / "audit.jsonl").write_text(line)
    assert keel("share", "r-9") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "/a/r-9"
    assert "does not hold it" in out[1]
    # Once the answer cache holds the answer, the link opens for anyone.
    record = json.loads(line)
    key = cache.cache_key(
        QUESTION,
        record["index_version"],
        record["prompt_version"],
        record["model"],
    )
    cache.AnswerCache(env["answers"]).put(key, {"request_id": "r-9"})
    base = "https://keel.example.com/"
    assert keel("share", "r-9", "--base-url", base) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "https://keel.example.com/a/r-9"
    assert "holds the answer" in out[1]
    assert keel("share", "r-unknown") == 1
    assert "no question with this ID" in capsys.readouterr().out
    assert keel("share", "bad id/../x") == 1
    assert keel("share", "r-9", "--base-url", "javascript:alert(1)") == 1


def test_share_link_rules() -> None:
    assert parity_cli.share_link("abc") == "/a/abc"
    assert (
        parity_cli.share_link("abc", "http://localhost:8000")
        == "http://localhost:8000/a/abc"
    )
    for bad in ("", "a b", "a/b", "x" * 129):
        with pytest.raises(ValueError, match="request ID"):
            parity_cli.share_link(bad)


def test_coverage_command(settings, env, capsys) -> None:
    assert keel("coverage") == 2  # no index yet: IndexMissingError
    indexer.build_index(
        settings,
        conftest.MINI_CORPUS,
        env["index"],
        conftest.FakeEmbedder,
    )
    capsys.readouterr()
    assert keel("coverage") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "3 companies, 3 filings, 0 quarantined"
    assert any(line.startswith("NVDA") for line in out)
    assert keel("coverage", "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert {c["ticker"] for c in report["companies"]} == {"AAPL", "JPM", "NVDA"}
    assert report["filing_count"] == 3


def test_jobs_command(env, capsys) -> None:
    assert keel("jobs") == 0
    assert capsys.readouterr().out.startswith("0 jobs in")
    path = env["logs"] / "state.sqlite"
    admin_store.insert_job(
        path,
        admin_store.JobRecord(
            id="0123456789abcdef",
            kind="refresh",
            params={"dry_run": True},
            requested_by="carol",
            heavy=True,
            status="failed",
            done=1,
            total=2,
            phase="failed",
            created_at="2026-10-22T00:00:00+00:00",
            started_at="2026-10-22T00:00:01+00:00",
            finished_at="2026-10-22T00:00:02+00:00",
            log=("ZTS: up to date",),
            result={"new_count": 0},
            error="EdgarFetchError: offline",
        ),
    )
    assert keel("jobs") == 0
    out = capsys.readouterr().out
    assert "0123456789abcdef  refresh" in out
    assert "1/2" in out
    assert keel("jobs", "0123456789abcdef") == 0
    out = capsys.readouterr().out
    assert "error: EdgarFetchError: offline" in out
    assert "  ZTS: up to date" in out
    assert keel("jobs", "0123456789abcdef", "--json") == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["log"] == ["ZTS: up to date"]
    assert keel("jobs", "--json") == 0
    listed = json.loads(capsys.readouterr().out.splitlines()[0])
    assert listed["log"] == []
    assert keel("jobs", "ffffffffffffffff") == 1
