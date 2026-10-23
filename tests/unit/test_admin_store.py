"""The admin job and audit tables, the backup listing, and the cost math."""

import json
import pathlib

import pytest

from keel import backup
from keel import config
from keel import errors
from keel.api import costs
from keel.api import jobs
from keel.stores import admin_store


def record(job_id: str, status: str = "queued", heavy: bool = True):
    return admin_store.JobRecord(
        id=job_id,
        kind="backup",
        params={"index_only": False},
        requested_by="carol",
        heavy=heavy,
        status=status,
        done=0,
        total=None,
        phase="queued",
        created_at=f"2026-10-22T00:00:0{len(job_id) % 10}+00:00",
        started_at=None,
        finished_at=None,
        log=(),
        result=None,
        error=None,
    )


def test_job_rows_round_trip(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "state.sqlite"
    assert admin_store.get_job(path, "a") is None
    assert admin_store.list_jobs(path) == []
    assert admin_store.fail_interrupted(path) == 0
    admin_store.insert_job(path, record("a"))
    admin_store.insert_job(path, record("bb", status="running"))
    admin_store.insert_job(path, record("ccc", status="succeeded"))
    updated = admin_store.update_job(
        path,
        "a",
        log=["one", "two"],
        result={"archive": "x"},
        done=1,
        total=2,
    )
    assert updated is not None
    assert updated.log == ("one", "two")
    assert updated.result == {"archive": "x"}
    assert updated.active
    assert admin_store.update_job(path, "missing", phase="x") is None
    with pytest.raises(ValueError, match="not a changeable job field"):
        admin_store.update_job(path, "a", kind="index")
    newest = admin_store.list_jobs(path)
    assert [j.id for j in newest] == ["ccc", "bb", "a"]
    active = admin_store.list_jobs(path, statuses=admin_store.ACTIVE)
    assert {j.id for j in active} == {"a", "bb"}
    assert len(admin_store.list_jobs(path, limit=1)) == 1
    assert admin_store.fail_interrupted(path, "2026-10-22T01:00:00+00:00") == 2
    failed = admin_store.get_job(path, "bb")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == admin_store.INTERRUPTED
    assert failed.finished_at == "2026-10-22T01:00:00+00:00"
    done = admin_store.get_job(path, "ccc")
    assert done is not None
    assert done.status == "succeeded"


def test_audit_drops_secret_keys(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "state.sqlite"
    assert admin_store.list_audit(path) == []
    admin_store.record_audit(
        path,
        "carol",
        "users.add",
        target="dave",
        params={
            "name": "dave",
            "Token": "t0p",
            "api_key": "k",
            "new_api_token": "t1",
            "role": "x",
        },
    )
    admin_store.record_audit(path, "carol", "job.index", outcome="busy")
    entries = admin_store.list_audit(path)
    assert [e.action for e in entries] == ["job.index", "users.add"]
    assert entries[1].params == {"name": "dave", "role": "x"}
    assert entries[0].outcome == "busy"
    assert "t0p" not in path.read_bytes().decode("utf-8", "ignore")


def test_store_errors_are_keel_errors(tmp_path: pathlib.Path) -> None:
    blocker = tmp_path / "state.sqlite"
    blocker.mkdir()
    with pytest.raises(errors.StateStoreError):
        admin_store.insert_job(blocker, record("a"))


def test_backup_listing(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "backups"
    assert backup.list_backups(out) == []
    out.mkdir()
    newer = out / "keel-2026-10-22T023000Z.tar.gz"
    older = out / "keel-2026-10-21T023000Z.tar.gz"
    newer.write_bytes(b"abc")
    older.write_bytes(b"abcdef")
    (out / (newer.name + ".sha256")).write_text("0" * 64 + "  " + newer.name)
    (out / "notes.txt").write_text("x")
    (out / "keel-2026-13-45T999999Z.tar.gz").write_text("bad date")
    (out / "keel-2026-10-20T023000Z.tar.gz").symlink_to(newer)
    (out / "keel-2026-10-19T023000Z.tar.gz").mkdir()
    items = backup.list_backups(out)
    assert [i.name for i in items] == [newer.name, older.name]
    assert items[0].size_bytes == 3
    assert items[0].has_checksum
    assert not items[1].has_checksum
    assert items[0].created_at == "2026-10-22T02:30:00+00:00"
    assert backup.is_archive_name(newer.name)
    for name in ("../" + newer.name, newer.name + "\n", "keel-x.tar.gz"):
        assert not backup.is_archive_name(name)


def test_costs_from_prices_and_audit(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    local = settings.model_copy(
        update={"logs": config.LogsConfig(dir=tmp_path / "logs")}
    )
    answer_usd, judge_usd, basis = costs.unit_costs(local)
    assert basis == "prices"
    prices = config.load_prices(local.llm.prices)
    model = prices.models[local.llm.model]
    assert answer_usd == pytest.approx(
        (
            costs.ANSWER_INPUT_TOKENS * model.input
            + costs.ANSWER_OUTPUT_TOKENS * model.output
        )
        / 1e6
    )
    assert judge_usd > 0
    golden = tmp_path / "golden.yaml"
    golden.write_text(
        "version: 1.0.0\n"
        "created: '2026-10-22'\n"
        "index_version: 1.0.0\n"
        "questions:\n"
        "  - {id: G-01, type: single_company, question: 'Apple risks'}\n"
    )
    local.logs.dir.mkdir()
    lines = [
        {
            "request_id": "r1",
            "outcome": "answered",
            "model": local.llm.model,
            "cost_usd": 0.1,
        },
        {
            "request_id": "r2",
            "outcome": "answered",
            "model": local.llm.model,
            "cost_usd": 0.3,
        },
        {
            "request_id": "r3",
            "outcome": "cached",
            "model": local.llm.model,
            "cost_usd": 9.0,
        },
        {
            "request_id": "r4",
            "outcome": "answered",
            "model": "other",
            "cost_usd": 9.0,
        },
    ]
    (local.logs.dir / "audit.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines)
    )
    assert costs.measured_answer_usd(
        local.logs.dir, local.llm.model
    ) == pytest.approx(0.2)
    estimate = costs.eval_estimate(local, golden, answers=True)
    assert estimate.basis == "audit"
    assert estimate.model_requests == estimate.questions == 1
    assert estimate.usd == pytest.approx(0.2 + judge_usd, abs=0.01)
    no_judge = costs.eval_estimate(local, golden, answers=True, judge=False)
    assert no_judge.judge_requests == 0


def test_warm_cache_estimate_without_golden(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    local = settings.model_copy(
        update={"logs": config.LogsConfig(dir=tmp_path / "logs")}
    )
    estimate = costs.warm_cache_estimate(
        local,
        None,
        None,
        refresh=False,
        facts_only=False,
        golden_path=tmp_path / "absent.yaml",
    )
    assert estimate.questions == len(local.demo.example_questions)
    assert estimate.model_requests == estimate.questions
    assert estimate.confirm == "cost"


def test_runner_cleans_log_lines() -> None:
    runner = jobs.JobRunner.__new__(jobs.JobRunner)
    runner._secrets = ["supersecretvalue"]
    line = runner.clean("token supersecretvalue\x00\x1b[31m" + "x" * 900)
    assert "supersecretvalue" not in line
    assert "\x00" not in line
    assert "\x1b" not in line
    assert len(line) == jobs.LOG_LINE_CHARS
    # A line break cannot forge a second log line.
    forged = runner.clean("done\nerror: forged line\r\u2028more")
    assert forged == "done error: forged line  more"


class FakeRunner:
    """The 2 runner methods a job context calls."""

    def __init__(self) -> None:
        self.writes: list[dict] = []
        self._secrets = ["supersecretvalue"]

    def clean(self, text: str) -> str:
        return jobs.JobRunner.clean(self, text)  # type: ignore[arg-type]

    def update(self, job_id: str, **fields: object) -> None:
        del job_id
        self.writes.append(fields)


def test_job_context_reports_steps() -> None:
    fake = FakeRunner()
    plan = [
        {"key": "fetch", "name": "Fetch", "status": "pending", "log": []},
        {"key": "embed", "name": "Embed", "status": "pending", "log": []},
    ]
    context = jobs.JobContext(fake, "job", plan=plan)  # type: ignore[arg-type]
    context.progress(5, 10)
    context.step("fetch")
    assert fake.writes[-1]["phase"] == "Fetch"
    assert (fake.writes[-1]["done"], fake.writes[-1]["total"]) == (0, 2)
    context.log("got supersecretvalue\nforged")
    context.progress(3, 4, "files")
    context.skip("embed", "nothing to embed")
    context.finish(True)
    context.flush()
    merged: dict = {}
    for write in fake.writes:
        merged.update(write)
    fetch, embed = merged["steps"]
    assert fetch["status"] == "succeeded"
    (line,) = fetch["log"]
    assert line.startswith("got ")
    assert line.endswith(" forged")
    assert "supersecretvalue" not in json.dumps(merged)
    assert fetch["progress"] == {"done": 3, "total": 4, "unit": "files"}
    assert embed == {**embed, "status": "skipped"}
    assert embed["log"] == ["skipped: nothing to embed"]
    assert (merged["done"], merged["total"]) == (2, 2)
    # The job log keeps every line too, for a client without steps.
    assert len(merged["log"]) == 1
    assert context.has_step("embed")
    assert not context.has_step("other")


def test_job_context_without_a_plan_keeps_the_job_progress() -> None:
    fake = FakeRunner()
    context = jobs.JobContext(fake, "job")  # type: ignore[arg-type]
    context.progress(2, 5)
    context.finish(False, "boom")
    context.flush()
    merged: dict = {}
    for write in fake.writes:
        merged.update(write)
    assert (merged["done"], merged["total"]) == (2, 5)
    assert "steps" not in merged
    # A step reported by a job without a plan starts a plan of its own.
    context.step("anything")
    context.flush()
    assert fake.writes[-1]["steps"][0]["key"] == "anything"
