"""The admin API, the job runner, the watch list, and the debug routes.

The app runs on an index built from the mini corpus with the fake
embedder and the mock provider, with a users file of an analyst, a
partner, and an admin. No test touches the network: the jobs that would
reach EDGAR or answer the golden set run with fakes in their place.
"""

from collections.abc import Callable
from collections.abc import Iterator
import json
import logging
import pathlib
import threading
import time

import pydantic
import pytest
from starlette import testclient

import conftest
from keel import add
from keel import answer
from keel import config
from keel import errors
from keel import indexer
from keel import refresh
from keel import retriever
from keel import users
from keel import warm_cache
from keel.api import app as api_app
from keel.api import job_kinds
from keel.api import jobs
from keel.api import routes
from keel.providers import mock
from keel.stores import admin_store
from keel.stores import chunk_store
from keel.stores import numpy_dense
from keel.stores import state_store

pytestmark = pytest.mark.integration

LEGACY_TOKEN = "legacy-token-for-admin-tests"  # noqa: S105
DONE = ("succeeded", "failed", "cancelled")


class NoSleep:
    async def __call__(self, _seconds: float) -> None:
        return None


@pytest.fixture(autouse=True)
def no_pace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "MOCK_PACE_SECONDS", 0.0)


@pytest.fixture
def index_dir(
    settings: config.Settings, tmp_path: pathlib.Path
) -> pathlib.Path:
    out = tmp_path / "index"
    embedder = conftest.FakeEmbedder()
    indexer.build_index(settings, conftest.MINI_CORPUS, out, lambda: embedder)
    return out


@pytest.fixture
def users_file(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "users.yaml"


@pytest.fixture
def tokens(users_file: pathlib.Path) -> dict[str, str]:
    return {
        "alice": users.add_user(users_file, "alice", "analyst"),
        "bob": users.add_user(users_file, "bob", "partner"),
        "carol": users.add_user(users_file, "carol", "admin"),
    }


@pytest.fixture
def api_settings(
    settings: config.Settings,
    tmp_path: pathlib.Path,
    users_file: pathlib.Path,
    index_dir: pathlib.Path,
) -> config.Settings:
    return settings.model_copy(
        update={
            "api_token": pydantic.SecretStr(LEGACY_TOKEN),
            "llm": settings.llm.model_copy(update={"provider": "mock"}),
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "auth": config.AuthConfig(users_file=users_file),
            "server": config.ServerConfig(
                web_dist=tmp_path / "no-dist",
                eval_report=tmp_path / "eval" / "report.md",
            ),
            "index": settings.index.model_copy(update={"dir": index_dir}),
            "corpus": settings.corpus.model_copy(
                update={
                    "dir": conftest.MINI_CORPUS,
                    "manifest": conftest.MINI_CORPUS / "manifest.json",
                }
            ),
            "scheduler": settings.scheduler.model_copy(
                update={"backup_dir": tmp_path / "backups"}
            ),
            "edgar": settings.edgar.model_copy(
                update={"cache_dir": tmp_path / "edgar"}
            ),
        }
    )


def make_answerer(
    settings: config.Settings, index_dir: pathlib.Path
) -> answer.Answerer:
    build = index_dir / "current"
    step = retriever.Retriever(
        chunk_store.open_read_only(build / chunk_store.FILE_NAME),
        numpy_dense.load(build / numpy_dense.FILE_NAME),
        conftest.FakeEmbedder(),
        conftest.FakeReranker(),
        settings,
    )
    version = indexer.load_manifest(build).index_version
    return answer.Answerer(
        settings,
        step,
        mock.MockProvider(settings.llm.model),
        version,
        sleep=NoSleep(),
    )


@pytest.fixture
def services(api_settings, index_dir) -> api_app.Services:
    return api_app.Services(
        api_settings, make_answerer(api_settings, index_dir)
    )


@pytest.fixture
def client(services, tokens) -> Iterator[testclient.TestClient]:
    del tokens
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(tokens) -> dict[str, str]:
    return bearer(tokens["carol"])


def wait_for(
    client: testclient.TestClient,
    headers: dict[str, str],
    job_id: str,
    statuses: tuple[str, ...] = DONE,
) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        body = client.get(f"/api/admin/jobs/{job_id}", headers=headers).json()
        if body["status"] in statuses:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {statuses}")


def submit(
    client: testclient.TestClient,
    headers: dict[str, str],
    kind: str,
    params: dict | None = None,
    confirm: str | None = None,
):
    body: dict = {"kind": kind, "params": params or {}}
    if confirm is not None:
        body["confirm"] = confirm
    return client.post("/api/admin/jobs", json=body, headers=headers)


def fake_spec(
    kind: str,
    run: Callable[..., jobs.JobOutput],
    heavy: bool = True,
) -> jobs.JobSpec:
    spec = job_kinds.SPECS[kind]
    return jobs.JobSpec(kind, spec.params, heavy, run, spec.title)


ADMIN_ROUTES = (
    ("get", "/api/admin/jobs", None),
    ("post", "/api/admin/jobs", {"kind": "backup", "params": {}}),
    ("get", "/api/admin/jobs/0123456789abcdef", None),
    ("post", "/api/admin/jobs/0123456789abcdef/cancel", None),
    ("get", "/api/admin/costs/preview?kind=eval", None),
    ("get", "/api/admin/users", None),
    ("post", "/api/admin/users", {"name": "dave", "role": "analyst"}),
    ("delete", "/api/admin/users/bob", None),
    ("get", "/api/admin/system", None),
    ("get", "/api/admin/backups", None),
    ("get", "/api/admin/backups/keel-2026-10-22T023000Z.tar.gz", None),
    ("get", "/api/admin/audit", None),
    ("post", "/api/watch", {"tickers": ["ZTS"]}),
    ("delete", "/api/watch/ZTS", None),
)


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_admin_routes_need_the_admin_role(
    client, tokens, method, path, body
) -> None:
    kwargs = {"json": body} if body is not None else {}
    # No token: 401; an analyst or a partner: 403.
    assert getattr(client, method)(path, **kwargs).status_code == 401
    for name in ("alice", "bob"):
        response = getattr(client, method)(
            path, headers=bearer(tokens[name]), **kwargs
        )
        assert response.status_code == 403, (name, response.text)
        assert response.json()["detail"]["code"] == "forbidden"
    # The admin passes the role check (the route's own answer follows).
    for token in (tokens["carol"], LEGACY_TOKEN):
        response = getattr(client, method)(
            path, headers=bearer(token), **kwargs
        )
        assert response.status_code != 403, response.text
        assert response.status_code in {200, 201, 202, 204, 404, 409}


def test_job_lifecycle(client, services, admin) -> None:
    started = threading.Event()
    release = threading.Event()

    def slow(_services, context, params):
        context.phase("working")
        context.progress(1, 2)
        context.log(f"index only {params.index_only}")
        # The writes are throttled; a flush writes them now.
        context.flush()
        started.set()
        assert release.wait(10)
        context.progress(2, 2)
        return jobs.JobOutput({"archive": "fake"})

    services.jobs.specs["backup"] = fake_spec("backup", slow)
    response = submit(client, admin, "backup", {"index_only": True})
    assert response.status_code == 202, response.text
    queued = response.json()
    job_id = queued["job"]["id"]
    assert queued["job"]["status"] in {"queued", "running"}
    assert queued["job"]["requested_by"] == "carol"
    assert queued["warnings"] == []
    assert queued["estimate"] is None
    assert started.wait(10)
    running = client.get(f"/api/admin/jobs/{job_id}", headers=admin).json()
    assert running["status"] == "running"
    assert running["progress"] == {"done": 1, "total": 2}
    assert running["log"] == ["index only True"]
    # A second heavy job waits for the first: 409 with the holder's ID.
    busy = submit(client, admin, "refresh", {"dry_run": True})
    assert busy.status_code == 409
    assert busy.json()["detail"]["code"] == "job_running"
    assert busy.json()["detail"]["job_id"] == job_id
    listed = client.get("/api/admin/jobs", headers=admin).json()
    assert listed["active"]["id"] == job_id
    release.set()
    done = wait_for(client, admin, job_id)
    assert done["status"] == "succeeded"
    assert done["result"] == {"archive": "fake"}
    assert done["progress"] == {"done": 2, "total": 2}
    assert done["started_at"]
    assert done["finished_at"]
    # The slot is free again.
    assert client.get("/api/admin/jobs", headers=admin).json()["active"] is None
    audit = client.get("/api/admin/audit", headers=admin).json()["items"]
    actions = [(a["action"], a["outcome"]) for a in audit]
    assert ("job.backup", "ok") in actions
    assert ("job.refresh", "job_running") in actions


def test_job_failure_paths(client, services, admin) -> None:
    def keel_failure(_services, _context, _params):
        raise errors.BackupError(f"disk full for {LEGACY_TOKEN}")

    def crash(_services, _context, _params):
        raise RuntimeError("boom")

    services.jobs.specs["backup"] = fake_spec("backup", keel_failure)
    job_id = submit(client, admin, "backup").json()["job"]["id"]
    failed = wait_for(client, admin, job_id)
    assert failed["status"] == "failed"
    assert failed["error"].startswith("BackupError: disk full")
    # A secret in an error never reaches the record.
    assert LEGACY_TOKEN not in failed["error"]
    services.jobs.specs["backup"] = fake_spec("backup", crash)
    job_id = submit(client, admin, "backup").json()["job"]["id"]
    crashed = wait_for(client, admin, job_id)
    assert crashed["error"] == "internal error: RuntimeError"
    # The worker survives a crash and runs the next job.
    services.jobs.specs["backup"] = fake_spec(
        "backup", lambda *_: jobs.JobOutput({"ok": True})
    )
    job_id = submit(client, admin, "backup").json()["job"]["id"]
    assert wait_for(client, admin, job_id)["status"] == "succeeded"


def test_light_job_queues_and_cancel(client, services, admin) -> None:
    release = threading.Event()

    def hold(_services, _context, _params):
        assert release.wait(10)
        return jobs.JobOutput({})

    services.jobs.specs["backup"] = fake_spec("backup", hold)
    services.jobs.specs["facts"] = fake_spec(
        "facts", lambda *_: jobs.JobOutput({"lines": []}), heavy=False
    )
    heavy = submit(client, admin, "backup").json()["job"]["id"]
    wait_for(client, admin, heavy, ("running",))
    # A light job is accepted while a heavy job runs; it queues.
    light = submit(client, admin, "facts", {"ticker": "NVDA"})
    assert light.status_code == 202
    light_id = light.json()["job"]["id"]
    second = submit(client, admin, "facts", {"ticker": "AAPL"})
    second_id = second.json()["job"]["id"]
    cancelled = client.post(
        f"/api/admin/jobs/{second_id}/cancel", headers=admin
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    # A running job cannot be cancelled.
    refused = client.post(f"/api/admin/jobs/{heavy}/cancel", headers=admin)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_cancellable"
    missing = client.post(
        "/api/admin/jobs/0123456789abcdef/cancel", headers=admin
    )
    assert missing.status_code == 404
    release.set()
    assert wait_for(client, admin, light_id)["status"] == "succeeded"
    assert wait_for(client, admin, second_id)["status"] == "cancelled"


def test_restart_marks_running_jobs_failed(
    services, api_settings, tokens, admin
) -> None:
    path = state_store.state_path(api_settings)
    for status in ("running", "queued", "succeeded"):
        admin_store.insert_job(
            path,
            admin_store.JobRecord(
                id=f"{status[:4]:0<16}",
                kind="index",
                params={},
                requested_by="carol",
                heavy=True,
                status=status,
                done=3,
                total=10,
                phase="building",
                created_at="2026-10-22T00:00:00+00:00",
                started_at=None,
                finished_at=None,
                log=(),
                result=None,
                error=None,
            ),
        )
    del tokens
    with testclient.TestClient(api_app.create_app(services)) as client:
        items = client.get("/api/admin/jobs", headers=admin).json()["items"]
    by_id = {item["id"]: item for item in items}
    for job_id in ("runn000000000000", "queu000000000000"):
        assert by_id[job_id]["status"] == "failed"
        assert by_id[job_id]["error"] == admin_store.INTERRUPTED
    assert by_id["succ000000000000"]["status"] == "succeeded"


def test_params_and_confirm_rules(client, services, admin) -> None:
    services.jobs.specs["eval"] = fake_spec(
        "eval", lambda *_: jobs.JobOutput({"run_id": "fake"})
    )
    bad = submit(client, admin, "add", {"ticker": "../../etc"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "invalid_params"
    assert bad.json()["detail"]["fields"] == ["ticker"]
    extra = submit(client, admin, "refresh", {"dry_run": True, "x": 1})
    assert extra.status_code == 400
    unknown = client.post(
        "/api/admin/jobs", json={"kind": "shell", "params": {}}, headers=admin
    )
    assert unknown.status_code == 422
    # eval with answers costs money: a typed `cost` confirmation.
    needs = submit(client, admin, "eval", {"answers": True})
    assert needs.status_code == 400
    detail = needs.json()["detail"]
    assert detail["code"] == "confirm_required"
    assert detail["confirm"] == "cost"
    estimate = detail["estimate"]
    # The out-of-scope golden questions get the refusal with no request.
    assert 0 < estimate["model_requests"] < estimate["questions"]
    assert estimate["judge_requests"] == estimate["model_requests"]
    assert estimate["usd"] > 0
    wrong = submit(client, admin, "eval", {"answers": True}, confirm="yes")
    assert wrong.json()["detail"]["code"] == "confirm_mismatch"
    ok = submit(client, admin, "eval", {"answers": True}, confirm="cost")
    assert ok.status_code == 202
    assert ok.json()["estimate"]["confirm"] == "cost"
    assert ok.json()["warnings"]
    wait_for(client, admin, ok.json()["job"]["id"])
    # Without answers, eval needs no confirmation.
    free = submit(client, admin, "eval", {"answers": False})
    assert free.status_code == 202
    assert free.json()["estimate"]["model_requests"] == 0
    wait_for(client, admin, free.json()["job"]["id"])
    # A full rebuild needs `rebuild` and warns about memory and time.
    services.jobs.specs["index"] = fake_spec(
        "index", lambda *_: jobs.JobOutput({})
    )
    rebuild = submit(client, admin, "index")
    assert rebuild.json()["detail"]["confirm"] == "rebuild"
    accepted = submit(client, admin, "index", confirm="rebuild")
    assert accepted.status_code == 202
    assert "6.6 GB" in accepted.json()["warnings"][0]
    wait_for(client, admin, accepted.json()["job"]["id"])


def test_cost_preview(client, api_settings, admin) -> None:
    preview = client.get(
        "/api/admin/costs/preview?kind=eval&answers=true", headers=admin
    ).json()
    assert preview["basis"] == "prices"
    assert preview["confirm"] == "cost"
    assert preview["usd"] == pytest.approx(
        preview["model_requests"]
        * (preview["answer_usd"] + preview["judge_usd"]),
        abs=0.01,
    )
    no_answers = client.get(
        "/api/admin/costs/preview?kind=eval&answers=false", headers=admin
    ).json()
    assert no_answers["model_requests"] == 0
    assert no_answers["confirm"] is None
    subset = client.get(
        "/api/admin/costs/preview?kind=eval&subset=G-01,G-02", headers=admin
    ).json()
    assert subset["questions"] == 2
    empty = client.get(
        "/api/admin/costs/preview?kind=eval&subset=nothing", headers=admin
    )
    assert empty.status_code == 400
    # A measured answer cost in the audit log replaces the price basis.
    logs = api_settings.logs.dir
    logs.mkdir(parents=True, exist_ok=True)
    record = {
        "request_id": "r1",
        "outcome": "answered",
        "model": api_settings.llm.model,
        "cost_usd": 0.25,
    }
    (logs / "audit.jsonl").write_text(json.dumps(record) + "\n")
    warm = client.get(
        "/api/admin/costs/preview?kind=warm_cache", headers=admin
    ).json()
    assert warm["basis"] == "audit"
    assert warm["answer_usd"] == 0.25
    assert warm["model_requests"] == warm["questions"]
    facts = client.get(
        "/api/admin/costs/preview?kind=warm_cache&facts_only=true",
        headers=admin,
    ).json()
    assert facts["model_requests"] == 0


def test_backup_restore_and_download(client, services, api_settings, admin):
    before = services.answerer
    made = submit(client, admin, "backup", {"index_only": True})
    assert made.status_code == 202
    done = wait_for(client, admin, made.json()["job"]["id"])
    assert done["status"] == "succeeded", done
    name = done["result"]["archive"]
    listing = client.get("/api/admin/backups", headers=admin).json()
    assert [item["name"] for item in listing["items"]] == [name]
    assert len(listing["items"][0]["sha256"]) == 64
    download = client.get(f"/api/admin/backups/{name}", headers=admin)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/gzip"
    assert (
        download.content
        == (api_settings.scheduler.backup_dir / name).read_bytes()
    )
    # Restore: the archive name is the typed confirmation.
    needs = submit(client, admin, "restore", {"archive": name})
    assert needs.json()["detail"]["code"] == "confirm_required"
    assert needs.json()["detail"]["confirm"] == name
    wrong = submit(client, admin, "restore", {"archive": name}, confirm="yes")
    assert wrong.status_code == 400
    assert wrong.json()["detail"]["code"] == "confirm_mismatch"
    absent = "keel-2020-01-01T000000Z.tar.gz"
    missing = submit(client, admin, "restore", {"archive": absent}, absent)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "archive_not_found"
    traversal = submit(
        client, admin, "restore", {"archive": "../../etc/passwd"}, "x"
    )
    assert traversal.status_code == 400
    assert traversal.json()["detail"]["code"] == "invalid_params"
    restored = submit(client, admin, "restore", {"archive": name}, name)
    assert restored.status_code == 202
    result = wait_for(client, admin, restored.json()["job"]["id"])
    assert result["status"] == "succeeded", result
    assert result["result"]["reloaded"] is True
    # The server serves the restored build without a restart.
    assert services.answerer is not before
    current = indexer.current_build(api_settings.index.dir)
    assert current is not None
    assert current.name == result["result"]["build"]
    # The questions still answer on the new build.
    ask = client.post(
        "/api/ask",
        json={
            "question": "What are NVIDIA's risk factors?",
            "options": {"stream": False},
        },
        headers=admin,
    )
    assert ask.status_code == 200


def test_download_rejects_paths(client, api_settings, admin, tmp_path) -> None:
    backup_dir = api_settings.scheduler.backup_dir
    backup_dir.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("not for download")
    # A link with an archive name is never listed or served.
    (backup_dir / "keel-2026-10-22T023000Z.tar.gz").symlink_to(secret)
    for name in (
        "keel-2026-10-22T023000Z.tar.gz",
        "..%2Fsecret.txt",
        "..%2F..%2Fusers.yaml",
        "secret.txt",
    ):
        response = client.get(f"/api/admin/backups/{name}", headers=admin)
        assert response.status_code == 404, name
    assert client.get("/api/admin/backups", headers=admin).json()["items"] == []


def test_index_job_rebuilds_and_reloads(client, services, api_settings, admin):
    before = services.answerer
    old = indexer.current_build(api_settings.index.dir)
    response = submit(client, admin, "index", {"incremental": True}, "rebuild")
    assert response.status_code == 202
    done = wait_for(client, admin, response.json()["job"]["id"])
    assert done["status"] == "succeeded", done
    assert done["result"]["reloaded"] is True
    assert done["progress"]["done"] == done["progress"]["total"]
    assert services.answerer is not before
    assert indexer.current_build(api_settings.index.dir) != old


def test_add_refresh_and_facts_jobs(client, services, admin, monkeypatch):
    report = add.AddReport(
        ticker="ZTS",
        cik="0001555280",
        company="Zoetis Inc.",
        filings=[],
        dictionary_added=False,
        index_built=False,
        index_version="1.0.0",
    )
    seen: dict = {}

    def fake_add(settings, ticker, **kwargs):
        seen["ticker"] = ticker
        seen["embedder"] = kwargs["embedder_factory"]()
        return report

    monkeypatch.setattr(add, "add_ticker", fake_add)
    monkeypatch.setattr(
        refresh,
        "run_refresh",
        lambda *a, **k: refresh.RefreshReport(
            dry_run=True, tickers=[refresh.TickerResult(ticker="ZTS")]
        ),
    )

    class FakeClient:
        requests = 2

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cik(self, ticker):
            return "0001045810"

        def company_facts(self, cik):
            raise errors.EdgarFetchError("offline test")

    monkeypatch.setattr(
        job_kinds.edgar.EdgarClient,
        "from_settings",
        classmethod(lambda cls, *a, **k: FakeClient()),
    )
    added = submit(client, admin, "add", {"ticker": "zts"})
    done = wait_for(client, admin, added.json()["job"]["id"])
    assert done["status"] == "succeeded", done
    assert done["result"]["ticker"] == "ZTS"
    assert "reloaded" not in done["result"]
    assert seen["ticker"] == "zts"
    # The job reuses the server's embedder behind the retrieval lock.
    vectors = seen["embedder"].encode(["a", "b", "c"])
    assert vectors.shape == (3, numpy_dense.DIMENSIONS)
    assert seen["embedder"].dimensions == numpy_dense.DIMENSIONS
    refreshed = submit(client, admin, "refresh", {"dry_run": True})
    result = wait_for(client, admin, refreshed.json()["job"]["id"])
    assert result["result"]["new_count"] == 0
    assert result["log"] == ["ZTS: up to date"]
    facts = submit(client, admin, "facts", {"ticker": "NVDA"})
    failed = wait_for(client, admin, facts.json()["job"]["id"])
    assert failed["status"] == "failed"
    assert failed["error"] == "EdgarFetchError: offline test"


def test_warm_cache_job_answers_on_the_server_loop(
    client, services, admin, monkeypatch
) -> None:
    monkeypatch.setattr(
        warm_cache,
        "prefetch_facts",
        lambda *a, **k: warm_cache.FactsPrefetch(
            ("NVDA",), (), ("NVDA",), (), (), 0
        ),
    )

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        job_kinds.edgar.EdgarClient,
        "from_settings",
        classmethod(lambda cls, *a, **k: FakeClient()),
    )
    facts_only = submit(client, admin, "warm_cache", {"facts_only": True})
    assert facts_only.status_code == 202
    assert facts_only.json()["estimate"]["confirm"] is None
    done = wait_for(client, admin, facts_only.json()["job"]["id"])
    assert done["result"]["facts"]["cached"] == 1
    assert done["result"]["ok"] is True
    needs = submit(client, admin, "warm_cache")
    assert needs.json()["detail"]["confirm"] == "cost"
    started = submit(client, admin, "warm_cache", confirm="cost")
    assert started.status_code == 202
    done = wait_for(client, admin, started.json()["job"]["id"])
    assert done["status"] == "succeeded", done
    answers = done["result"]["answers"]
    assert answers["questions"] == started.json()["estimate"]["questions"]
    assert done["progress"]["done"] == answers["questions"]
    assert answers["model_requests"] == services.answerer.provider.requests


def test_users_token_shown_once(client, api_settings, admin, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    created = client.post(
        "/api/admin/users",
        json={"name": "dave", "role": "analyst"},
        headers=admin,
    )
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    token = created.json()["token"]
    assert created.json()["name"] == "dave"
    # The token works, and no later response, file, log, or audit holds it.
    me = client.get("/api/history", headers=bearer(token))
    assert me.json()["user"] == "dave"
    listed = client.get("/api/admin/users", headers=admin)
    assert token not in listed.text
    assert {"name": "dave", "role": "analyst"} in listed.json()["items"]
    assert listed.json()["legacy_enabled"] is True
    assert token not in api_settings.auth.users_file.read_text()
    assert token not in caplog.text
    audit = client.get("/api/admin/audit", headers=admin)
    assert token not in audit.text
    assert audit.json()["items"][0]["params"] == {
        "name": "dave",
        "role": "analyst",
    }
    again = client.post(
        "/api/admin/users",
        json={"name": "dave", "role": "admin"},
        headers=admin,
    )
    assert again.status_code == 409
    reserved = client.post(
        "/api/admin/users",
        json={"name": "legacy", "role": "admin"},
        headers=admin,
    )
    assert reserved.status_code == 400
    bad = client.post(
        "/api/admin/users",
        json={"name": "Dave!", "role": "analyst"},
        headers=admin,
    )
    assert bad.status_code == 422
    removed = client.delete("/api/admin/users/dave", headers=admin)
    assert removed.status_code == 204
    revoked = client.get("/api/history", headers=bearer(token))
    assert revoked.status_code == 401
    missing = client.delete("/api/admin/users/dave", headers=admin)
    assert missing.status_code == 404
    own = client.delete("/api/admin/users/carol", headers=admin)
    assert own.status_code == 409
    assert own.json()["detail"]["code"] == "self_delete"


def test_system_report(client, services, admin) -> None:
    body = client.get("/api/admin/system", headers=admin).json()
    names = {check["name"] for check in body["doctor"]}
    assert {"python", "sqlite fts5"} <= names
    assert body["inventory"]["file_count"] == 3
    index = body["index"]
    assert index["loaded"] is True
    assert index["build_id"]
    assert index["filings"] == 3
    assert body["backups"]["items"] == []
    assert body["scheduler"]["enabled"] is False
    assert body["budget"]["spent_usd"] == 0
    assert body["active_job"] is None
    assert body["bootstrap"] is None


def test_watch_routes(client, tokens, admin) -> None:
    alice = bearer(tokens["alice"])
    assert client.get("/api/watch", headers=alice).json()["items"] == []
    added = client.post(
        "/api/watch", json={"tickers": ["zts", "brk-b"]}, headers=admin
    )
    assert added.status_code == 200
    assert added.json() == {
        "user": "carol",
        "added": ["ZTS", "BRK.B"],
        "unchanged": [],
    }
    again = client.post(
        "/api/watch", json={"tickers": ["ZTS"], "user": "alice"}, headers=admin
    )
    assert again.json()["added"] == ["ZTS"]
    seen = client.get("/api/watch", headers=alice).json()
    assert seen["tickers"] == ["BRK.B", "ZTS"]
    # An analyst sees their own rows by name, others' rows without one.
    users_seen = {(i["ticker"], i["user"], i["mine"]) for i in seen["items"]}
    assert ("ZTS", "alice", True) in users_seen
    assert ("ZTS", None, False) in users_seen
    every = client.get("/api/watch", headers=admin).json()
    assert {i["user"] for i in every["items"]} == {"alice", "carol"}
    bad = client.post("/api/watch", json={"tickers": ["$$$"]}, headers=admin)
    assert bad.status_code == 422
    gone = client.delete("/api/watch/ZTS?user=alice", headers=admin)
    assert gone.status_code == 204
    again = client.delete("/api/watch/ZTS?user=alice", headers=admin)
    assert again.status_code == 404
    mine = client.delete("/api/watch/BRK.B", headers=admin)
    assert mine.status_code == 204


def test_debug_routes_make_no_model_request(client, services, tokens) -> None:
    alice = bearer(tokens["alice"])
    provider = services.answerer.provider
    question = "What are NVIDIA's risk factors?"
    understood = client.post(
        "/api/debug/understand", json={"question": question}, headers=alice
    )
    assert understood.status_code == 200
    assert "NVDA" in understood.json()["tickers"]
    retrieved = client.post(
        "/api/debug/retrieve", json={"question": question}, headers=alice
    )
    assert retrieved.status_code == 200
    body = retrieved.json()
    assert body["tickers"] == ["NVDA"]
    summary = body["retrieval"]
    assert summary["sub_queries"]
    assert summary["context"]["chunks"] == len(summary["context"]["items"]) > 0
    assert set(summary["timings_ms"]) == {"lexical", "dense", "rerank", "total"}
    outside = client.post(
        "/api/debug/retrieve",
        json={"question": "What are the risk factors of Zoetis?"},
        headers=alice,
    )
    assert outside.json()["out_of_scope"] is True
    assert outside.json()["retrieval"] is None
    short = client.post(
        "/api/debug/understand", json={"question": "a"}, headers=alice
    )
    assert short.status_code == 400
    assert (
        client.post(
            "/api/debug/understand", json={"question": question}
        ).status_code
        == 401
    )
    # D-02: no model request at retrieval time.
    assert provider.requests == 0


def test_debug_rate_limit(client, services, tokens) -> None:
    alice = bearer(tokens["alice"])
    services.limiter.limits = ((1.0, 1e-9), (1.0, 1e-9))
    first = client.post(
        "/api/debug/understand",
        json={"question": "Apple risks?"},
        headers=alice,
    )
    assert first.status_code == 200
    second = client.post(
        "/api/debug/understand",
        json={"question": "Apple risks?"},
        headers=alice,
    )
    assert second.status_code == 429


def test_nightly_jobs_and_admin_jobs_share_the_slot(
    client, services, admin
) -> None:
    from keel.api import background  # noqa: PLC0415

    release = threading.Event()

    def hold(_services, _context, _params):
        assert release.wait(10)
        return jobs.JobOutput({})

    services.jobs.specs["backup"] = fake_spec("backup", hold)
    job_id = submit(client, admin, "backup").json()["job"]["id"]
    # The nightly jobs skip while an admin job holds the slot.
    assert background.backup_job(services, lambda: "ran") is None
    assert background.refresh_job(services, lambda: None) is None
    release.set()
    wait_for(client, admin, job_id)
    assert background.backup_job(services, lambda: "ran") == "ran"
    # An admin job is refused while a nightly job holds the slot.
    with services.maintenance:
        busy = submit(client, admin, "backup")
    assert busy.status_code == 409
    assert busy.json()["detail"]["job_id"] is None


def test_run_async_needs_the_server_loop(services) -> None:
    runner = jobs.JobRunner(services, job_kinds.SPECS, loop=None)
    context = jobs.JobContext(runner, "0123456789abcdef")

    async def nothing() -> int:
        return 1

    with pytest.raises(errors.JobStateError, match="not running"):
        context.run_async(nothing())


def test_reload_failure_keeps_the_old_build(client, services, admin) -> None:
    def broken_reload() -> None:
        raise OSError("disk")

    services.reload = broken_reload
    services.jobs.specs["index"] = fake_spec(
        "index", lambda *_: jobs.JobOutput({}, reload=True)
    )
    job_id = submit(client, admin, "index", confirm="rebuild").json()["job"]
    done = wait_for(client, admin, job_id["id"])
    assert done["status"] == "succeeded"
    assert done["result"]["reloaded"] is False


def test_bad_state_store_starts_without_jobs(services, api_settings, tokens):
    del tokens
    api_settings.logs.dir.mkdir(parents=True)
    (api_settings.logs.dir / "state.sqlite").mkdir()
    with testclient.TestClient(api_app.create_app(services)) as client:
        cancel = client.post(
            "/api/admin/jobs/0123456789abcdef/cancel",
            headers=bearer(LEGACY_TOKEN),
        )
        assert cancel.status_code == 503
        assert client.get("/api/health").status_code == 200
