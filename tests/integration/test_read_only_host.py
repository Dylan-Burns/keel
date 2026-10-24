"""Every admin job kind on a read-only application root.

The pilot host runs the image with `read_only: true`: only the volumes of
`docker-compose.yml` (and the `/tmp` tmpfs) take writes. The tests run
outside that container, so a job that wrote a path under `/app` passed
here and failed there (`keel add` wrote `config/companies.yaml`, the eval
job wrote `eval/report.md` after a 28-minute run).

This test rebuilds that layout in a temporary folder: an application
root whose entries are links into the checkout, with real folders for the
compose volumes only, and the KEEL_ variables of the compose file mapped
onto it. A Python audit hook refuses every write outside the volumes and
the temporary folder with `EROFS`, as the host does, and records it. The
jobs run through the real job runner with the mock provider, the fake
embedder, and the recorded EDGAR responses; no test touches the network.
"""

import asyncio
from collections.abc import Iterator
import errno
import os
import pathlib
import shutil
import socket
import sys
import tempfile
import threading
import time
from typing import Any

import httpx
import pytest
import yaml

import conftest
from keel import answer
from keel import config
from keel import directory
from keel import edgar
from keel import indexer
from keel import retriever
from keel import users
from keel.api import eval_page
from keel.api import job_kinds
from keel.api import jobs
from keel.api import state
from keel.providers import mock
from keel.stores import admin_store
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

COMPOSE = conftest.REPO_ROOT / "docker-compose.yml"
APP = "/app/"
DONE = ("succeeded", "failed", "cancelled")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
# The path arguments of each event, and the index of its dir_fd argument
# (None when it has none). A call relative to a dir_fd (shutil.rmtree
# walks that way) is skipped: its "shutil.rmtree" event names the tree.
_PATH_EVENTS: dict[str, tuple[tuple[int, ...], int | None]] = {
    "os.mkdir": ((0,), 2),
    "os.remove": ((0,), 1),
    "os.rmdir": ((0,), 1),
    "os.rename": ((0, 1), 2),
    "os.symlink": ((1,), 2),
    "os.link": ((1,), 2),
    "os.truncate": ((0,), None),
    "os.chmod": ((0,), 2),
    "shutil.rmtree": ((0,), 1),
}


class ReadOnlyGuard:
    """Refuse and record the writes outside the writable folders.

    Python cannot remove an audit hook, so 1 hook is installed for the
    session and does nothing while no folders are set.
    """

    installed = False

    def __init__(self) -> None:
        self.allowed: tuple[str, ...] | None = None
        self.violations: list[tuple[str, str]] = []

    def install(self) -> None:
        if not ReadOnlyGuard.installed:
            sys.addaudithook(self.hook)
            ReadOnlyGuard.installed = True

    def inside(self, path: str) -> bool:
        assert self.allowed is not None
        return any(
            path == root or path.startswith(root + os.sep)
            for root in self.allowed
        )

    def written(self, event: str, args: tuple[Any, ...]) -> list[Any]:
        if event == "open":
            path, mode, flags = args
            if isinstance(mode, str):
                writes = any(c in mode for c in "wax+")
            else:
                writes = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
            return [path] if writes else []
        if event == "sqlite3.connect":
            database = args[0]
            if not isinstance(database, (str, os.PathLike)):
                return []
            text = os.fspath(database)
            if text == ":memory:" or "mode=ro" in text:
                return []
            return [text.removeprefix("file:").split("?")[0]]
        if event not in _PATH_EVENTS:
            return []
        indexes, dir_fd = _PATH_EVENTS[event]
        fd = None if dir_fd is None else args[dir_fd]
        if isinstance(fd, int) and fd >= 0:
            return []
        return [args[i] for i in indexes]

    def hook(self, event: str, args: tuple[Any, ...]) -> None:
        if self.allowed is None:
            return
        for raw in self.written(event, args):
            if isinstance(raw, int) or raw is None:
                continue
            text = os.fsdecode(raw)
            if "__pycache__" in text or text.startswith("/dev/"):
                continue
            path = os.path.realpath(text)
            if not self.inside(path):
                self.violations.append((event, path))
                raise PermissionError(
                    errno.EROFS, "Read-only file system", text
                )


GUARD = ReadOnlyGuard()


def compose_app() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return data["services"]["app"]


def compose_mounts() -> list[str]:
    """The `/app` volume targets, relative to the application root."""
    targets = []
    for volume in compose_app()["volumes"]:
        target = volume.split(":")[1]
        if target.startswith(APP):
            targets.append(target.removeprefix(APP))
    return targets


def build_app_root(root: pathlib.Path, mounts: list[str]) -> None:
    """Link the checkout into `root`; make the volume folders real."""

    def fill(source: pathlib.Path, target: pathlib.Path, rel: str) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir()):
            child_rel = f"{rel}{child.name}"
            if child_rel in mounts:
                continue
            if any(m.startswith(child_rel + "/") for m in mounts):
                fill(child, target / child.name, child_rel + "/")
            else:
                (target / child.name).symlink_to(child)

    fill(conftest.REPO_ROOT, root, "")
    for mount in mounts:
        (root / mount).mkdir(parents=True, exist_ok=True)


class NoSleep:
    async def __call__(self, _seconds: float) -> None:
        return None


class Host:
    """The emulated host: the settings, the services, the runner."""

    def __init__(
        self, settings: config.Settings, root: pathlib.Path, tmp: pathlib.Path
    ) -> None:
        self.settings = settings
        self.root = root
        volumes = [os.path.realpath(root / m) for m in compose_mounts()]
        self.writable = (*volumes, os.path.realpath(tmp))
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever)
        self.thread.start()
        self.services = state.Services(settings, self.answerer())
        self.runner = jobs.JobRunner(self.services, job_kinds.SPECS, self.loop)

    def answerer(self) -> answer.Answerer:
        build = self.settings.index.dir / "current"
        step = retriever.Retriever(
            chunk_store.open_read_only(build / chunk_store.FILE_NAME),
            numpy_dense.load(build / numpy_dense.FILE_NAME),
            conftest.FakeEmbedder(),
            conftest.FakeReranker(),
            self.settings,
        )
        return answer.Answerer(
            self.settings,
            step,
            mock.MockProvider(self.settings.llm.model),
            indexer.load_manifest(build).index_version,
            sleep=NoSleep(),
        )

    def run(self, kind: str, **params: Any) -> admin_store.JobRecord:
        spec = job_kinds.SPECS[kind]
        record = self.runner.submit(kind, spec.params(**params), "test")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            job = admin_store.get_job(self.runner.path, record.id)
            assert job is not None
            if job.status in DONE:
                return job
            time.sleep(0.02)
        raise AssertionError(f"the {kind} job never finished")

    def close(self) -> None:
        self.runner.stop(timeout=10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)
        self.loop.close()


@pytest.fixture
def host(
    clean_env: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> Iterator[Host]:
    """The compose layout with a read-only application root."""
    monkeypatch = clean_env
    root = tmp_path / "app"
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    build_app_root(root, compose_mounts())
    for name, value in compose_app()["environment"].items():
        if name.startswith("KEEL_"):
            text = str(value)
            if text.startswith(APP):
                text = str(root / text.removeprefix(APP))
            monkeypatch.setenv(name, text)
    monkeypatch.setenv("KEEL_LLM__PROVIDER", "mock")
    monkeypatch.chdir(root)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    # What infra/deploy_host.sh puts on the volumes before the start.
    shutil.copytree(
        conftest.MINI_CORPUS, settings.corpus.dir, dirs_exist_ok=True
    )
    shutil.copyfile(
        conftest.REPO_ROOT / "config" / "companies.yaml",
        settings.dictionaries.companies,
    )
    shutil.copytree(
        conftest.FIXTURES / "edgar",
        settings.edgar.cache_dir,
        dirs_exist_ok=True,
    )
    embedder = conftest.FakeEmbedder()
    indexer.build_index(
        settings, settings.corpus.dir, settings.index.dir, lambda: embedder
    )
    # No model loads, no socket opens, and EDGAR answers from the
    # recorded responses only.
    monkeypatch.setattr(
        numpy_dense.SentenceEmbedder,
        "from_settings",
        classmethod(lambda cls, s: conftest.FakeEmbedder()),
    )
    monkeypatch.setattr(
        retriever.CrossEncoderReranker,
        "from_settings",
        classmethod(lambda cls, s: conftest.FakeReranker()),
    )

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"request in a test: {request.url}")

    original = edgar.EdgarClient.from_settings.__func__  # type: ignore[attr-defined]
    monkeypatch.setattr(
        edgar.EdgarClient,
        "from_settings",
        classmethod(
            lambda cls, s, **k: original(
                cls,
                s,
                offline=True,
                transport=conftest.peer_transport(refuse),
            )
        ),
    )

    def blocked(*args: object, **kwargs: object) -> None:
        raise OSError(f"network access in a test: {args}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    emulated = Host(settings, root, tmp)
    GUARD.install()
    GUARD.violations = []
    emulated.runner.start()
    GUARD.allowed = emulated.writable
    try:
        yield emulated
    finally:
        GUARD.allowed = None
        emulated.close()


def test_every_job_kind_runs_on_a_read_only_root(host: Host) -> None:
    """Each job kind and the users file write only to the volumes."""
    results = {}
    stepped: dict[str, dict[str, str]] = {}
    for kind, params in (
        ("index", {"incremental": True}),
        ("add", {"ticker": "ZTS"}),
        ("refresh", {}),
        ("facts", {"ticker": "NVDA"}),
        ("warm_cache", {}),
        (
            "eval",
            {
                "answers": True,
                "judge": False,
                "subset": "G-01,G-22",
                "ablation": True,
            },
        ),
        ("backup", {}),
    ):
        job = host.run(kind, **params)
        assert job.status == "succeeded", (kind, job.error, job.log)
        results[kind] = job.result
        # Every step of the plan ended; none failed.
        ended = {step["status"] for step in job.steps}
        assert ended <= {"succeeded", "skipped"}, (kind, job.steps)
        assert job.steps[0]["status"] == "succeeded", (kind, job.steps)
        stepped[kind] = {step["key"]: step["status"] for step in job.steps}
    assert set(stepped["eval"].values()) == {"succeeded"}
    assert list(stepped["eval"]) == [
        "report_dir",
        "golden",
        "harness",
        "questions",
        "score",
        "report",
    ]
    assert set(stepped["warm_cache"].values()) == {"succeeded"}
    assert stepped["add"]["resolve"] == "succeeded"
    archive = results["backup"]["archive"]
    restored = host.run("restore", archive=archive)
    assert restored.status == "succeeded", restored.error
    users.add_user(host.settings.auth.users_file, "dana", "analyst")
    assert GUARD.violations == []
    # The eval report is on the logs volume, and the eval page shows it.
    report = pathlib.Path(results["eval"]["report"])
    assert report.parent == config.eval_report_dir(host.settings)
    assert os.path.realpath(report).startswith(host.writable)
    assert report.with_suffix(".json").is_file()
    page = eval_page.load(
        host.settings.server.eval_report,
        host.settings.server.prompt_log,
        config.eval_report_dir(host.settings),
    )
    assert page.report.source == f"eval run {report.stem}"
    assert page.gates


def test_eval_job_fails_before_the_run_on_a_read_only_dir(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A report folder on the read-only root fails before any question."""
    # A folder on the application root itself, not a link into the
    # checkout, so only the read-only root refuses it.
    bad = host.root / "eval-reports"
    host.services.settings = host.settings.model_copy(
        update={"eval": config.EvalConfig(report_dir=bad)}
    )
    asked: list[str] = []
    monkeypatch.setattr(
        job_kinds.runner,
        "evaluate",
        lambda *a, **k: asked.append("evaluate"),
    )
    job = host.run("eval", answers=True, judge=False, subset="G-01")
    assert job.status == "failed"
    assert job.error is not None
    assert "ConfigError: cannot write" in job.error
    assert "Read-only file system" in job.error
    assert "KEEL_EVAL__REPORT_DIR" in job.error
    assert asked == []
    statuses = [step["status"] for step in job.steps]
    assert statuses == ["failed"] + ["skipped"] * (len(statuses) - 1)
    assert job.steps[0]["log"][-1].startswith("error: ConfigError: ")
    assert GUARD.violations


def test_job_error_names_the_read_only_path(host: Host) -> None:
    """An OSError in a job reports its errno, reason, and path."""
    host.services.settings = host.settings.model_copy(
        update={
            "scheduler": host.settings.scheduler.model_copy(
                update={"backup_dir": pathlib.Path("backups")}
            )
        }
    )
    job = host.run("backup")
    assert job.status == "failed"
    assert job.error is not None
    assert "Read-only file system" in job.error
    assert "backups" in job.error


def test_company_browser_cache_is_on_a_volume(host: Host) -> None:
    """The company list of an industry lands on the EDGAR cache volume."""
    feed = conftest.FIXTURES / "edgar_sic"

    def pages(request: httpx.Request) -> httpx.Response:
        start = request.url.params.get("start")
        name = f"atom_3674_start{start}.xml"
        return httpx.Response(200, content=(feed / name).read_bytes())

    industries = directory.load_sic_codes(host.settings.edgar.sic_codes)
    assert any(i.code == "3674" for i in industries)
    cached = directory.cache_path(host.settings.edgar.cache_dir, "3674")
    cached.unlink()
    client = edgar.EdgarClient(
        host.settings.edgar.user_agent,
        host.settings.edgar.cache_dir,
        min_interval=0.0,
        transport=conftest.peer_transport(pages),
        resolver=lambda name: ["93.184.215.14"],
    )
    with client:
        listed = directory.industry_ciks(client, "3674", ttl_days=30)
    assert listed.requests == 2
    assert cached.is_file()
    assert os.path.realpath(cached).startswith(host.writable)
    assert GUARD.violations == []
