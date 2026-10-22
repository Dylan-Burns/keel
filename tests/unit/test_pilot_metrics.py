"""Tests of the pilot metrics script (chapter 27.6) on a synthetic audit log."""

import importlib.util
import json
import pathlib
import sqlite3
import sys
import types

import pytest

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
        "outcome": outcome,
        "cost_usd": cost,
        "model_requests": 1,
    }
    if user is not None:
        record["user"] = user
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
            "not json",
            {"request_id": "r0", "timestamp": "never", "cost_usd": 1.0},
            {"request_id": "r9", "timestamp": 1e300, "cost_usd": 1.0},
        ],
    )
    _write(
        logs / "audit.jsonl",
        [
            _question("r4", "2026-10-27T09:00:00+00:00", 0.08, user="cy"),
            {
                "event": "export",
                "request_id": "r4",
                "timestamp": "2026-10-27T09:05:00+00:00",
                "format": "docx",
                "user": "cy",
            },
        ],
    )
    return logs


def _feedback_db(path: pathlib.Path) -> pathlib.Path:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE feedback (request_id TEXT, vote INTEGER, "
            "note TEXT, created_at TEXT)"
        )
        conn.executemany(
            "INSERT INTO feedback VALUES (?, ?, ?, ?)",
            [
                ("r1", 1, "", "2026-10-19T10:01:00+00:00"),
                ("r2", -1, "wrong year", "2026-10-20T11:01:00+00:00"),
                ("r4", 1, "", "2026-10-27T09:01:00+00:00"),
            ],
        )
    return path


def _manifest(path: pathlib.Path) -> pathlib.Path:
    path.write_text(
        json.dumps(
            {
                "files": [
                    "AAPL_10K_2025-10-31_full.txt",
                    {
                        "file": "ZTS_10K_2026-02-12_full.txt",
                        "source": "edgar",
                        "added_at": "2026-10-28T02:00:00Z",
                    },
                    {
                        "file": "ZTS_10Q_2025Q3_2025-11-04_full.txt",
                        "source": "edgar",
                    },
                    {"ticker": "wday", "source": "edgar"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_pilot_metrics(logs: pathlib.Path, tmp_path: pathlib.Path) -> None:
    files = pilot_metrics.audit_files([logs / "audit.jsonl"])
    assert [f.name for f in files] == ["audit-2026-10-20.jsonl", "audit.jsonl"]
    records, skipped = pilot_metrics.read_records(files)
    assert skipped == 1
    metrics = pilot_metrics.compute(
        records,
        votes=pilot_metrics.read_votes(_feedback_db(tmp_path / "fb.sqlite")),
        additions=pilot_metrics.read_additions(
            _manifest(tmp_path / "manifest.json")
        ),
        skipped_lines=skipped,
    )
    first, second = metrics.weeks
    assert (first.week, second.week) == ("2026-W43", "2026-W44")
    assert (first.active_users, first.questions) == (2, 3)
    assert first.cost_usd == pytest.approx(0.20)
    assert first.cost_per_question == pytest.approx(0.20 / 3, rel=1e-4)
    assert first.thumbs_up_rate == pytest.approx(0.5)
    assert (first.memos_exported, first.companies_added) == (0, 0)
    assert (second.active_users, second.questions) == (1, 1)
    assert (second.memos_exported, second.companies_added) == (1, 1)
    assert metrics.users == 3
    assert metrics.questions == 4
    assert metrics.undated_records == 2
    assert metrics.outcomes == {"answered": 3, "out_of_scope": 1}
    assert metrics.thumbs_up_rate == pytest.approx(2 / 3)
    assert metrics.companies_added == 2
    assert metrics.memos_exported == 1
    assert all(metrics.sources.values())
    held = {r["metric"]: r["holds"] for r in pilot_metrics.targets(metrics)}
    assert held == {
        "active users in the best week": False,
        "questions in the best week": False,
        "thumbs-up rate": False,
        "memos exported": False,
    }


def test_pilot_metrics_legacy_log(tmp_path: pathlib.Path) -> None:
    """A stage 12 log: no user, no feedback, no exports, no manifest."""
    path = tmp_path / "audit.jsonl"
    _write(
        path,
        [
            _question("r1", "2026-10-19T10:00:00+00:00", 0.09),
            _question("r2", "2026-10-21T10:00:00+00:00", 0.07),
        ],
    )
    records, _ = pilot_metrics.read_records(pilot_metrics.audit_files([path]))
    metrics = pilot_metrics.compute(
        records,
        votes=pilot_metrics.read_votes(tmp_path / "absent.sqlite"),
        additions=pilot_metrics.read_additions(tmp_path / "absent.json"),
    )
    (week,) = metrics.weeks
    assert (week.active_users, week.questions) == (1, 2)
    assert week.thumbs_up_rate is None
    assert week.memos_exported is None
    assert week.companies_added is None
    assert metrics.sources == {
        "user_field": False,
        "feedback_table": False,
        "export_events": False,
        "manifest": False,
    }
    text = pilot_metrics.to_markdown(metrics)
    assert "| 2026-W43 | 1 | 2 | 0.16 | 0.0800 | n/a | n/a | n/a |" in text
    assert "the legacy token counts as 1 user" in text


def test_pilot_metrics_main(
    logs: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db = _feedback_db(tmp_path / "fb.sqlite")
    code = pilot_metrics.main(
        [
            str(logs),
            "--json",
            "--feedback-db",
            str(db),
            "--manifest",
            str(tmp_path / "none.json"),
        ]
    )
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["questions"] == 4
    assert body["sources"]["manifest"] is False
    assert len(body["targets"]) == 4
    assert "What are Apple" not in json.dumps(body)
    assert (
        pilot_metrics.main(
            [str(logs), "--manifest", str(tmp_path / "none.json")]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert out.startswith("## Pilot metrics")
    assert pilot_metrics.main([str(tmp_path / "missing" / "audit.jsonl")]) == 1


def test_iso_week() -> None:
    assert pilot_metrics.iso_week("2026-10-25T23:30:00-07:00") == "2026-W44"
    assert pilot_metrics.iso_week("2026-10-21") == "2026-W43"
    assert pilot_metrics.iso_week(0) == "1970-W01"
    assert pilot_metrics.iso_week("yesterday") is None
    assert pilot_metrics.iso_week(None) is None
