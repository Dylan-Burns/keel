"""Tests of the answer cache, the audit log, and the cost (chapter 16)."""

import datetime
import json
import os
import pathlib
import stat

import pytest

from keel import audit
from keel import cache
from keel import config
from keel.providers import base

pytestmark = pytest.mark.unit

QUESTION = "What are the primary risk factors facing Apple?"


def test_cache_key_parts() -> None:
    key = cache.cache_key(QUESTION, "1.0.1", "1.0.0", "claude-sonnet-5-5")
    same = cache.cache_key(
        "  what are the primary RISK factors   facing Apple?",
        "1.0.1",
        "1.0.0",
        "claude-sonnet-5-5",
    )
    assert key == same
    others = {
        cache.cache_key(QUESTION, "1.1.0", "1.0.0", "claude-sonnet-5-5"),
        cache.cache_key(QUESTION, "1.0.1", "1.1.0", "claude-sonnet-5-5"),
        cache.cache_key(QUESTION, "1.0.1", "1.0.0", "claude-haiku-5-5"),
    }
    assert key not in others
    assert len(others) == 3


def test_cache_round_trip_and_checksum(tmp_path: pathlib.Path) -> None:
    store = cache.AnswerCache(tmp_path / "answers")
    assert store.get("k") is None
    record = {"answer": {"direct_answer": "x"}, "meta": {"cost_usd": 0.1}}
    store.put("k", record)
    assert store.get("k") == record
    entry = json.loads(store.path("k").read_text())
    entry["record"]["answer"]["direct_answer"] = "tampered"
    store.path("k").write_text(json.dumps(entry))
    assert store.get("k") is None
    store.path("k").write_text("not json")
    assert store.get("k") is None
    store.path("k").write_text(
        json.dumps({"sha256": cache._checksum([1]), "record": [1]})
    )
    assert store.get("k") is None
    assert list((tmp_path / "answers").glob(".tmp-*")) == []


def test_cache_write_failure_is_logged(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    cache.AnswerCache(blocker / "answers").put("k", {"a": 1})
    assert "answer cache write failed" in caplog.text


def test_audit_line(tmp_path: pathlib.Path) -> None:
    log = audit.AuditLog(tmp_path / "logs")
    assert log.write({"request_id": "r1", "model_requests": 1})
    assert log.write({"request_id": "r2", "model_requests": 1})
    lines = log.path.read_text().splitlines()
    assert [json.loads(line)["request_id"] for line in lines] == ["r1", "r2"]
    assert stat.S_IMODE(log.path.stat().st_mode) == audit.FILE_MODE


def test_audit_refuses_prompt_and_logs_failure(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    log = audit.AuditLog(tmp_path / "logs")
    assert not log.write({"request_id": "r", "prompt": "the full prompt"})
    assert "AuditWriteError" in caplog.text
    assert not log.path.exists()
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert not audit.AuditLog(blocker).write({"request_id": "r"})


def test_audit_rotates_daily(tmp_path: pathlib.Path) -> None:
    log = audit.AuditLog(tmp_path)
    log.write({"request_id": "old"})
    yesterday = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(
        days=1
    )
    os.utime(log.path, (yesterday.timestamp(), yesterday.timestamp()))
    log.write({"request_id": "new"})
    rotated = tmp_path / f"audit-{yesterday.date().isoformat()}.jsonl"
    assert json.loads(rotated.read_text())["request_id"] == "old"
    assert json.loads(log.path.read_text())["request_id"] == "new"


def test_cost_with_cache_miss() -> None:
    prices = config.load_prices(pathlib.Path("config/prices.yaml"))
    sonnet = prices.models["claude-sonnet-5-5"]
    hit = base.UsageReport(
        input_tokens=30000, cache_read_tokens=1800, output_tokens=1650
    )
    miss = base.UsageReport(
        input_tokens=30000, cache_write_tokens=1800, output_tokens=1650
    )
    cold = base.UsageReport(input_tokens=31800, output_tokens=1650)
    assert base.cost_usd(hit, sonnet) == pytest.approx(0.07668)
    assert base.cost_usd(miss, sonnet) == pytest.approx(0.081)
    assert base.cost_usd(cold, sonnet) == pytest.approx(0.0801)
    # E-C-10: a miss costs a few tenths of a cent more, no other action.
    assert base.cost_usd(miss, sonnet) - base.cost_usd(hit, sonnet) < 0.005
    assert miss.total_input == hit.total_input == 31800


def test_cost_long_prompt_prices() -> None:
    prices = config.load_prices(pathlib.Path("config/prices.yaml"))
    haiku = prices.models["claude-haiku-5-5"]
    short = base.UsageReport(input_tokens=100000, output_tokens=1000)
    long = base.UsageReport(input_tokens=100001, output_tokens=1000)
    assert base.cost_usd(short, haiku) == pytest.approx(0.0105)
    assert base.cost_usd(long, haiku) == pytest.approx(0.0525, abs=1e-6)
