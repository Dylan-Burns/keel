"""The step list of the admin jobs: the book, the reporters, the store."""

import json
import pathlib
import sqlite3

import conftest
from keel import steps
from keel.api import job_kinds
from keel.api import job_steps
from keel.api import jobs
from keel.stores import admin_store

PLAN = (
    steps.StepDef("fetch", "Fetch"),
    steps.StepDef("parse", "Parse"),
    steps.StepDef("embed", "Embed"),
    steps.StepDef("reload", "Reload the server"),
)


class Clock:
    """A clock text that moves 1 second per call."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return f"2026-10-23T00:00:{self.calls:02d}+00:00"


def book(plan: tuple[steps.StepDef, ...] = PLAN) -> job_steps.StepBook:
    return job_steps.StepBook(job_steps.plan_records(plan), Clock())


def statuses(value: job_steps.StepBook) -> list[str]:
    return [step["status"] for step in value.snapshot()]


def test_plan_records_are_pending_and_unique() -> None:
    records = job_steps.plan_records((*PLAN, PLAN[0]))
    assert [r["key"] for r in records] == ["fetch", "parse", "embed", "reload"]
    assert {r["status"] for r in records} == {"pending"}
    assert records[0] == {
        "key": "fetch",
        "name": "Fetch",
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "progress": None,
        "log": [],
    }
    many = tuple(steps.StepDef(f"s{i}", f"S{i}") for i in range(40))
    assert len(job_steps.plan_records(many)) == job_steps.MAX_STEPS


def test_steps_move_forward_and_skip_what_they_jump() -> None:
    value = book()
    assert not value.log("before any step")
    assert value.enter("fetch") == "Fetch"
    assert value.current == 0
    assert value.log("fetched 2 files")
    assert value.progress(1, 2, "files")
    # Jumping to embed finishes fetch and skips parse.
    assert value.enter("embed") == "Embed"
    assert statuses(value) == ["succeeded", "skipped", "running", "pending"]
    # An earlier or the same step changes nothing.
    assert value.enter("parse") is None
    assert value.enter("embed") is None
    snapshot = value.snapshot()
    assert snapshot[0]["log"] == ["fetched 2 files"]
    assert snapshot[0]["progress"] == {"done": 1, "total": 2, "unit": "files"}
    assert snapshot[0]["started_at"] < snapshot[0]["finished_at"]
    assert snapshot[2]["finished_at"] is None
    assert value.counts() == (2, 4)
    value.finish(True)
    # The reload was never reached: skipped.
    assert statuses(value) == ["succeeded", "skipped", "succeeded", "skipped"]
    assert value.current is None
    assert value.counts() == (4, 4)


def test_a_failed_step_holds_the_error() -> None:
    value = book()
    value.enter("fetch")
    value.enter("parse")
    value.finish(False, "ParseError: no cover page")
    assert statuses(value) == ["succeeded", "failed", "skipped", "skipped"]
    assert value.snapshot()[1]["log"] == ["error: ParseError: no cover page"]


def test_skip_marks_a_pending_step_with_its_reason() -> None:
    value = book()
    value.skip("parse", "nothing to parse")
    value.skip("unknown", "ignored")
    value.enter("fetch")
    value.skip("fetch", "too late: it runs")
    assert statuses(value) == ["running", "skipped", "pending", "pending"]
    assert value.snapshot()[1]["log"] == ["skipped: nothing to parse"]
    # A skipped step can still be entered later.
    value.enter("parse")
    assert statuses(value)[:2] == ["succeeded", "running"]


def test_an_unknown_step_is_inserted_after_the_running_one() -> None:
    value = book()
    value.enter("fetch")
    assert value.enter("extra_work") == "Extra work"
    assert [s["key"] for s in value.snapshot()][:3] == [
        "fetch",
        "extra_work",
        "parse",
    ]
    full = book(tuple(steps.StepDef(f"s{i}", "S") for i in range(24)))
    assert full.enter("one_more") is None
    assert job_steps.StepBook([]).enter("first") == "First"


def test_the_step_log_keeps_the_last_lines() -> None:
    value = book()
    value.enter("fetch")
    for number in range(job_steps.STEP_LOG_LINES + 50):
        value.log(f"line {number}")
    log = value.snapshot()[0]["log"]
    assert len(log) == job_steps.STEP_LOG_LINES
    assert log[0] == "line 50"


def test_a_book_resumes_from_a_running_record() -> None:
    records = job_steps.plan_records(PLAN)
    records[1]["status"] = "running"
    value = job_steps.StepBook(records)
    assert value.current == 1
    assert bool(value)
    assert not job_steps.StepBook([])


def test_null_and_prefixed_reporters() -> None:
    steps.NULL.step("x")
    steps.NULL.skip("x", "y")
    steps.NULL.log("x")
    steps.NULL.progress(1, 2, "z")
    outer = conftest.RecordingReporter()
    inner = steps.Prefixed(outer, "ZTS", steps.names_of(PLAN))
    inner.step("embed")
    inner.step("unknown")
    inner.skip("parse", "nothing new")
    inner.log("wrote 1 file")
    inner.progress(3, 4, "chunks")
    assert outer.lines() == [
        "ZTS: Embed",
        "ZTS: unknown",
        "ZTS: Parse skipped: nothing new",
        "ZTS: wrote 1 file",
    ]
    assert outer.of("progress") == []
    assert steps.Prefixed(outer, "A").names == {}


def test_every_job_kind_declares_its_plan() -> None:
    plans = {
        "add": job_kinds.plan_add(job_kinds.TickerParams(ticker="ZTS")),
        "refresh": job_kinds.plan_refresh(job_kinds.RefreshParams()),
        "warm_cache": job_kinds.plan_warm_cache(job_kinds.WarmCacheParams()),
        "facts_only": job_kinds.plan_warm_cache(
            job_kinds.WarmCacheParams(facts_only=True)
        ),
        "eval": job_kinds.plan_eval(job_kinds.EvalParams()),
        "eval_answers": job_kinds.plan_eval(job_kinds.EvalParams(answers=True)),
        "facts": job_kinds.plan_facts(job_kinds.TickerParams(ticker="NVDA")),
        "backup": job_kinds.plan_backup(job_kinds.BackupParams()),
        "restore": job_kinds.plan_restore(
            job_kinds.RestoreParams(archive="keel-2026-10-22T023000Z.tar.gz")
        ),
        "index": job_kinds.plan_index(job_kinds.IndexParams()),
    }
    keys = {kind: [s.key for s in plan] for kind, plan in plans.items()}
    assert keys["add"] == [
        "corpus",
        "resolve",
        "filings",
        "download_10k",
        "download_10q",
        "convert",
        "parse",
        "chunk",
        "embed",
        "store",
        "publish",
        "reload",
    ]
    assert keys["refresh"] == ["watch", "check", "add", "reload"]
    assert keys["warm_cache"] == ["index", "facts", "questions", "answer"]
    assert keys["facts_only"] == ["index", "facts"]
    assert "score" not in keys["eval"]
    assert keys["eval_answers"] == [
        "report_dir",
        "golden",
        "harness",
        "questions",
        "score",
        "report",
    ]
    assert keys["facts"] == ["resolve", "fetch", "map"]
    assert keys["backup"][0] == "build"
    assert keys["restore"][0] == "find"
    assert keys["restore"][-1] == "reload"
    assert keys["index"] == [
        "corpus",
        "parse",
        "chunk",
        "embed",
        "store",
        "publish",
        "reload",
    ]
    for plan in plans.values():
        assert all(step.name[0].isupper() for step in plan)
        assert len(plan) <= job_steps.MAX_STEPS
    # Every kind has a plan; a spec without one plans nothing.
    assert {spec.plan for spec in job_kinds.SPECS.values()}.isdisjoint(
        {jobs.no_plan}
    )
    assert jobs.no_plan(object()) == ()


def test_close_steps_ends_an_interrupted_plan() -> None:
    closed = admin_store.close_steps(
        [
            {"key": "a", "status": "succeeded", "log": []},
            {"key": "b", "status": "running", "log": ["half"]},
            {"key": "c", "status": "pending"},
            "not a step",
        ],
        "2026-10-23T00:00:00+00:00",
        "stopped",
    )
    assert [s["status"] for s in closed] == ["succeeded", "failed", "skipped"]
    assert closed[1]["log"] == ["half", "error: stopped"]
    assert closed[1]["finished_at"] == "2026-10-23T00:00:00+00:00"


def test_an_old_jobs_table_gets_the_steps_column(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "state.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE jobs (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, params TEXT NOT NULL,
          requested_by TEXT NOT NULL, heavy INTEGER NOT NULL,
          status TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
          total INTEGER, phase TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
          log TEXT NOT NULL DEFAULT '[]', result TEXT, error TEXT
        );
        INSERT INTO jobs VALUES ('old', 'backup', '{}', 'carol', 1,
          'succeeded', 1, 1, 'done', '2026-10-01T00:00:00+00:00', NULL,
          NULL, '["a line"]', NULL, NULL);
        """
    )
    conn.commit()
    conn.close()
    old = admin_store.get_job(path, "old")
    assert old is not None
    assert old.steps == ()
    assert old.log == ("a line",)
    updated = admin_store.update_job(
        path, "old", steps=[{"key": "a", "status": "succeeded"}]
    )
    assert updated is not None
    assert updated.steps == ({"key": "a", "status": "succeeded"},)
    raw = sqlite3.connect(path)
    try:
        (text,) = raw.execute("SELECT steps FROM jobs").fetchone()
    finally:
        raw.close()
    assert json.loads(text) == [{"key": "a", "status": "succeeded"}]


def test_a_job_that_fails_before_its_first_step_fails_that_step() -> None:
    value = book()
    value.finish(False, "IndexMissingError: no current build")
    assert statuses(value) == ["failed", "skipped", "skipped", "skipped"]
    first = value.snapshot()[0]
    assert first["log"] == ["error: IndexMissingError: no current build"]
    assert first["started_at"] is not None
    assert first["finished_at"] is not None


def test_a_finished_book_ignores_late_reports() -> None:
    value = book()
    value.enter("fetch")
    value.finish(True)
    before = value.snapshot()
    assert value.enter("parse") is None
    assert value.enter("late_unknown") is None
    assert not value.skip("parse", "late")
    assert not value.log("late line")
    assert not value.progress(1, 2, "late")
    value.finish(False, "late error")
    assert value.snapshot() == before


def test_prefixed_logs_a_repeated_step_once() -> None:
    outer = conftest.RecordingReporter()
    inner = steps.Prefixed(outer, "ZTS", steps.names_of(PLAN))
    inner.step("parse")
    inner.step("parse")
    inner.step("embed")
    assert outer.lines() == ["ZTS: Parse", "ZTS: Embed"]


def test_close_steps_keeps_the_last_lines() -> None:
    long_log = [f"line {i}" for i in range(admin_store.STEP_LOG_LINES)]
    (closed,) = admin_store.close_steps(
        [{"key": "a", "status": "running", "log": long_log}], "t", "stopped"
    )
    assert len(closed["log"]) == admin_store.STEP_LOG_LINES
    assert closed["log"][-1] == "error: stopped"
