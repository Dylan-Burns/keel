"""Tests of the pilot metrics script (chapter 27.6) on synthetic logs.

The fixtures write each source in the format the merged code writes: the
audit record of `keel/answer.py` with `user_name`, the `feedback` table of
`keel/stores/pilot.py`, the `added` entries of `keel/add.py`, the
`refresh.log` lines of `keel/refresh.py`, and the `exports.jsonl` lines of
`keel/export.py`.
"""

import datetime
import importlib.util
import json
import os
import pathlib
import sqlite3
import sys
import types

import pytest

from keel import export
from keel import refresh
from keel.stores import pilot

pytestmark = pytest.mark.unit

SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "pilot_metrics.py"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("pilot_metrics", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve the module through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pilot_metrics = _load()


def _question(
    request_id: str,
    timestamp: str,
    cost: float,
    outcome: str = "answered",
    user: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "request_id": request_id,
        "timestamp": timestamp,
        "question": "What are Apple's risk factors?",
        "user_name": user,
        "outcome": outcome,
        "cost_usd": cost,
        "model_requests": 1,
    }
    return record


def _write(path: pathlib.Path, records: list[object]) -> None:
    path.write_text(
        "".join(
            (r if isinstance(r, str) else json.dumps(r)) + "\n" for r in records
        ),
        encoding="utf-8",
    )


@pytest.fixture(name="logs")
def _logs(tmp_path: pathlib.Path) -> pathlib.Path:
    """A rotated file of week 43 and the current file of week 44."""
    logs = tmp_path / "logs"
    logs.mkdir()
    _write(
        logs / "audit-2026-10-20.jsonl",
        [
            _question("r1", "2026-10-19T10:00:00+00:00", 0.09, user="ana"),
            _question("r2", "2026-10-20T11:00:00+00:00", 0.11, user="ben"),
            _question(
                "r3",
                "2026-10-20T12:00:00+00:00",
                0.0,
                outcome="out_of_scope",
                user="ana",
            ),
            _question("r5", "2026-10-21T08:00:00+00:00", 0.5, user="eng"),
            "not json",
            [1, 2],
            {"request_id": "r0", "timestamp": "never", "cost_usd": 1.0},
            {"request_id": "r9", "timestamp": 1e300, "cost_usd": 1.0},
        ],
    )
    _write(
        logs / "audit.jsonl",
        [_question("r4", "2026-10-27T09:00:00+00:00", 0.08, user="cy")],
    )
    return logs


def _feedback_db(path: pathlib.Path) -> pathlib.Path:
    store = pilot.PilotStore(path)
    store.record_vote(request_id="r1", user_name="ana", vote="up")
    store.record_vote(
        request_id="r2", user_name="ben", vote="down", note="wrong year"
    )
    store.record_vote(request_id="r4", user_name="cy", vote="up")
    store.record_vote(request_id="r5", user_name="eng", vote="down")
    with sqlite3.connect(path) as conn:
        for request_id, created in (
            ("r1", "2026-10-19T10:01:00+00:00"),
            ("r2", "2026-10-20T11:01:00+00:00"),
            ("r4", "2026-10-27T09:01:00+00:00"),
            ("r5", "2026-10-21T08:01:00+00:00"),
        ):
            conn.execute(
                "UPDATE feedback SET created_at = ? WHERE request_id = ?",
                (created, request_id),
            )
    return path


def _stamp(path: pathlib.Path, when: str) -> None:
    path.write_text("Ticker: X\n", encoding="utf-8")
    moment = datetime.datetime.fromisoformat(when).timestamp()
    os.utime(path, (moment, moment))


def _corpus(directory: pathlib.Path) -> pathlib.Path:
    """A manifest with 1 zip file, 2 added companies, 1 refreshed filing."""
    directory.mkdir()
    added = {
        "ZTS_10K_2026-02-12_full.txt": ("ZTS", "2026-10-28T02:00:00+00:00"),
        "ZTS_10Q_2026Q3_2026-08-06_full.txt": (
            "ZTS",
            "2026-10-29T02:00:00+00:00",
        ),
        "WDAY_10K_2026-03-06_full.txt": ("WDAY", None),
        "AAPL_10Q_2026Q3_2026-08-01_full.txt": (
            "AAPL",
            "2026-10-27T02:00:00+00:00",
        ),
    }
    for name, (_, when) in added.items():
        if when is not None:
            _stamp(directory / name, when)
    path = directory / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "files": sorted(["AAPL_10K_2025-10-31_full.txt", *added]),
                "added": {
                    name: {"source": "edgar", "ticker": ticker, "form": "10-K"}
                    for name, (ticker, _) in added.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _refresh_log(path: pathlib.Path) -> pathlib.Path:
    lines = [
        refresh.LogEntry(
            time=datetime.datetime(2026, 10, 27, 2, tzinfo=datetime.UTC),
            event="added",
            ticker="AAPL",
        ),
        refresh.LogEntry(
            time=datetime.datetime(2026, 10, 28, 2, tzinfo=datetime.UTC),
            event="added",
            dry_run=True,
            ticker="ZTS",
        ),
        refresh.LogEntry(
            time=datetime.datetime(2026, 10, 28, 2, tzinfo=datetime.UTC),
            event="done",
        ),
    ]
    path.write_text(
        "".join(line.model_dump_json() + "\n" for line in lines),
        encoding="utf-8",
    )
    return path


def _exports(directory: pathlib.Path) -> pathlib.Path:
    """4 memos in week 43 (1 by the engineer), 1 in week 44."""
    directory.mkdir(parents=True, exist_ok=True)
    for request_id, fmt, user in (
        ("r1", export.MARKDOWN, "ana"),
        ("r2", export.DOCX, "ben"),
        ("r3", export.MARKDOWN, "ana"),
        ("r5", export.MARKDOWN, "eng"),
        ("r4", export.DOCX, "cy"),
    ):
        written = export.log_export(directory, request_id, fmt, user)
        assert written
    path = directory / export.LOG_NAME
    times = iter(
        [
            "2026-10-19T10:05:00+00:00",
            "2026-10-20T11:05:00+00:00",
            "2026-10-20T12:05:00+00:00",
            "2026-10-21T08:05:00+00:00",
            "2026-10-27T09:05:00+00:00",
        ]
    )
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        value["time"] = next(times)
        lines.append(json.dumps(value))
    path.write_text("\n".join([*lines, "not json", "[1]"]) + "\n")
    return path


def test_pilot_metrics(logs: pathlib.Path, tmp_path: pathlib.Path) -> None:
    files = pilot_metrics.audit_files([logs / "audit.jsonl"])
    assert [f.name for f in files] == ["audit-2026-10-20.jsonl", "audit.jsonl"]
    records, skipped = pilot_metrics.read_records(files)
    assert skipped == 2
    additions = pilot_metrics.read_additions(_corpus(tmp_path / "corpus"))
    assert additions == [
        pilot_metrics.Addition("WDAY", None),
        pilot_metrics.Addition("ZTS", "2026-W44"),
    ]
    metrics = pilot_metrics.compute(
        records,
        votes=pilot_metrics.read_votes(_feedback_db(tmp_path / "p.sqlite")),
        additions=additions,
        refreshed=pilot_metrics.read_refreshed(
            _refresh_log(tmp_path / "refresh.log")
        ),
        exports=pilot_metrics.read_exports(_exports(tmp_path / "out")),
        exclude_users=["eng"],
        skipped_lines=skipped,
    )
    first, second = metrics.weeks
    assert (first.week, second.week) == ("2026-W43", "2026-W44")
    assert (first.active_users, first.questions) == (2, 3)
    assert first.cost_usd == pytest.approx(0.20)
    assert first.cost_per_question == pytest.approx(0.20 / 3, rel=1e-4)
    assert (first.thumbs_up_rate, first.votes) == (0.5, 2)
    assert (first.memos_exported, second.memos_exported) == (3, 1)
    assert (first.companies_added, first.filings_refreshed) == (0, 0)
    assert (second.active_users, second.questions) == (1, 1)
    assert (second.companies_added, second.filings_refreshed) == (1, 1)
    assert metrics.users == 3
    assert metrics.questions == 4
    assert metrics.undated_records == 2
    assert metrics.outcomes == {"answered": 3, "out_of_scope": 1}
    assert metrics.thumbs_up_rate == pytest.approx(2 / 3)
    # WDAY has no corpus file, so no week; it still counts in the total.
    assert metrics.companies_added == 2
    assert metrics.filings_refreshed == 1
    assert metrics.memos_exported == 4
    assert metrics.sources == {
        "user_name": True,
        "feedback_table": True,
        "export_log": True,
        "manifest": True,
        "refresh_log": True,
    }
    held = {r["metric"]: r["holds"] for r in pilot_metrics.targets(metrics)}
    assert held == {
        "active users each week": False,
        "questions each week": None,
        "thumbs-up rate": False,
        "memos exported": True,
    }
    assert pilot_metrics.decision(pilot_metrics.targets(metrics)).startswith(
        "1 of 4 metrics hold, 1 open: fix the top 3 feedback reasons"
    )


def test_pilot_metrics_since_and_gaps(
    logs: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """`--since` makes its week week 1, and an empty week is a 0 row."""
    _write(
        logs / "audit.jsonl",
        [_question("r6", "2026-11-10T09:00:00+00:00", 0.1, user="cy")],
    )
    records, _ = pilot_metrics.read_records(pilot_metrics.audit_files([logs]))
    metrics = pilot_metrics.compute(
        records,
        votes=pilot_metrics.read_votes(tmp_path / "absent.sqlite"),
        since="2026-W44",
        until="2026-W47",
    )
    assert [w.week for w in metrics.weeks] == [
        "2026-W44",
        "2026-W45",
        "2026-W46",
        "2026-W47",
    ]
    # The idle week 4 is a 0 row, so the questions target cannot hold.
    assert [w.questions for w in metrics.weeks] == [0, 0, 1, 0]
    assert metrics.questions == 1
    rows = {r["metric"]: r for r in pilot_metrics.targets(metrics)}
    assert rows["questions each week"]["value"] == 0
    assert rows["active users each week"]["holds"] is False


def test_pilot_metrics_legacy_log(tmp_path: pathlib.Path) -> None:
    """A stage 12 log: no user, no feedback, no manifest, no refresh."""
    path = tmp_path / "audit.jsonl"
    _write(
        path,
        [
            _question("r1", "2026-10-19T10:00:00+00:00", 0.09),
            _question("r2", "2026-10-21T10:00:00+00:00", 0.07),
        ],
    )
    records, _ = pilot_metrics.read_records(pilot_metrics.audit_files([path]))
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    metrics = pilot_metrics.compute(
        records,
        votes=pilot_metrics.read_votes(tmp_path / "absent.sqlite"),
        additions=pilot_metrics.read_additions(broken),
        refreshed=pilot_metrics.read_refreshed(tmp_path / "absent.log"),
        exports=pilot_metrics.read_exports(tmp_path / "absent.jsonl"),
    )
    (week,) = metrics.weeks
    assert (week.active_users, week.questions) == (1, 2)
    assert week.thumbs_up_rate is None
    assert week.companies_added is None
    assert week.filings_refreshed is None
    assert week.memos_exported is None
    assert not any(metrics.sources.values())
    text = pilot_metrics.to_markdown(metrics)
    assert (
        "| 2026-W43 | 1 | 2 | 0.16 | 0.0800 | n/a | 0 | n/a | n/a | n/a |"
        in text
    )
    assert "the legacy token counts as 1 user" in text
    assert "0 of 4 metrics hold, 4 open: too early to decide" in text
    assert (
        "Sources absent (n/a): feedback_table, export_log, manifest, "
        "refresh_log." in text
    )


def test_pilot_metrics_main(
    logs: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defaults come from the config: `KEEL_LOGS__DIR` moves them."""
    monkeypatch.setenv("KEEL_LOGS__DIR", str(logs))
    monkeypatch.delenv("KEEL_PILOT__DB", raising=False)
    _feedback_db(logs / pilot.FILE_NAME)
    _refresh_log(logs / refresh.LOG_NAME)
    _exports(logs)
    manifest = _corpus(tmp_path / "corpus")
    code = pilot_metrics.main(["--json", "--manifest", str(manifest)])
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["questions"] == 5
    assert body["votes"] == 4
    assert body["filings_refreshed"] == 1
    assert body["memos_exported"] == 5
    assert body["sources"]["export_log"] is True
    assert body["sources"]["feedback_table"] is True
    assert len(body["targets"]) == 4
    assert "decision" in body
    assert "What are Apple" not in json.dumps(body)
    code = pilot_metrics.main(
        [
            str(logs),
            "--since",
            "2026-10-26",
            "--exclude-user",
            "eng",
            "--manifest",
            str(manifest),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("## Pilot metrics")
    assert "| 2026-W44 | 1 | 1 |" in out
    assert "| memos exported | >= 3 | 1 | no |" in out
    assert "2026-W43" not in out
    assert pilot_metrics.main([str(tmp_path / "missing" / "audit.jsonl")]) == 1
    assert pilot_metrics.main(["--config", str(tmp_path / "none.yaml")]) == 1


def test_iso_week() -> None:
    assert pilot_metrics.iso_week("2026-10-25T23:30:00-07:00") == "2026-W44"
    assert pilot_metrics.iso_week("2026-10-21") == "2026-W43"
    assert pilot_metrics.iso_week("2026-10-21T10:00:00Z") == "2026-W43"
    assert pilot_metrics.iso_week(datetime.date(2026, 10, 21)) == "2026-W43"
    assert pilot_metrics.iso_week(0) == "1970-W01"
    assert pilot_metrics.iso_week(True) is None
    assert pilot_metrics.iso_week("yesterday") is None
    assert pilot_metrics.iso_week(None) is None
    assert pilot_metrics.week_range("2026-W52", "2027-W01") == [
        "2026-W52",
        "2026-W53",
        "2027-W01",
    ]


def test_pilot_metrics_week_4_rule_can_reach_4_of_4() -> None:
    """With the export log, all 4 log metrics can hold."""
    users = ("ana", "ben", "cy")
    days = ("10-19", "10-26", "11-02", "11-09")
    records = [
        _question(
            f"q{day}-{n}", f"2026-{day}T10:00:00+00:00", 0.1, user=users[n % 3]
        )
        for day in days
        for n in range(30)
    ]
    votes = [pilot_metrics.Vote(True, "2026-W46", "ana")] * 3
    exports = [pilot_metrics.Export("2026-W45", "ben")] * 3
    exports.append(pilot_metrics.Export("2026-W45", "eng"))
    metrics = pilot_metrics.compute(
        records, votes=votes, exports=exports, exclude_users=["eng"]
    )
    assert metrics.memos_exported == 3
    rows = pilot_metrics.targets(metrics)
    assert all(row["holds"] is True for row in rows)
    assert pilot_metrics.decision(rows).startswith(
        "4 of 4 metrics hold, 0 open: continue to phase 2"
    )
