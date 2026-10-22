"""`keel refresh` on the mini corpus with recorded responses (26.3).

The tiny index holds the 3 mini corpus filings and the ZTS 10-K, which an
earlier `keel add` brought in. The submissions that the refresh fetches
are the recorded ZTS submissions, which list a 10-Q (accession
0001555280-26-000040) that the corpus lacks. A mock transport serves them;
the network is blocked.
"""

from collections.abc import Sequence
import datetime
import json
import pathlib
import shutil
import socket

import httpx
import pytest

import conftest
from keel import add
from keel import cli
from keel import config
from keel import edgar
from keel import indexer
from keel import refresh
from keel.stores import numpy_dense
from keel.stores import state_store

pytestmark = pytest.mark.integration

EDGAR_FIXTURES = conftest.FIXTURES / "edgar"
ZTS_CIK = "0001555280"
ZTS_10K = "ZTS_10K_2026-02-12_full.txt"
ZTS_10Q = "ZTS_10Q_2026Q2_2026-08-06_full.txt"
ZTS_10Q_ACCESSION = "0001555280-26-000040"
SUBMISSIONS_URL = edgar.SUBMISSIONS_URL.format(cik=ZTS_CIK)
T0 = datetime.datetime(2026, 10, 22, 2, 0, tzinfo=datetime.UTC)

Workspace = tuple[config.Settings, pathlib.Path, pathlib.Path]


class NetworkBlockedError(OSError):
    """A test tried to open a socket or resolve a name."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block every socket connect and name lookup (test_no_network)."""

    def blocked(*args: object, **kwargs: object) -> None:
        raise NetworkBlockedError(f"network access in a test: {args}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def workspace(settings: config.Settings, tmp_path: pathlib.Path) -> Workspace:
    """Settings on temporary dirs, a corpus copy, and a tiny index."""
    companies = tmp_path / "companies.yaml"
    shutil.copyfile(settings.dictionaries.companies, companies)
    shutil.copytree(EDGAR_FIXTURES, tmp_path / "cache")
    local = settings.model_copy(
        update={
            "dictionaries": settings.dictionaries.model_copy(
                update={"companies": companies}
            ),
            "edgar": settings.edgar.model_copy(
                update={"cache_dir": tmp_path / "cache"}
            ),
            "logs": settings.logs.model_copy(update={"dir": tmp_path / "logs"}),
        }
    )
    corpus = tmp_path / "corpus"
    shutil.copytree(conftest.MINI_CORPUS, corpus)
    index = tmp_path / "index"
    indexer.build_index(local, corpus, index, conftest.FakeEmbedder)
    return local, corpus, index


def _offline(settings: config.Settings) -> edgar.EdgarClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"request in a test: {request.url}")

    return edgar.EdgarClient(
        "Keel Test test@example.com",
        settings.edgar.cache_dir,
        offline=True,
        transport=httpx.MockTransport(handler),
    )


class RecordedSec:
    """A mock transport that serves the recorded ZTS submissions."""

    def __init__(self) -> None:
        recorded = json.loads(
            (EDGAR_FIXTURES / "submissions" / f"CIK{ZTS_CIK}.json").read_text()
        )
        self.body = json.dumps(recorded["data"]).encode()
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if str(request.url) == SUBMISSIONS_URL:
            return httpx.Response(200, content=self.body)
        return httpx.Response(404)

    def client(self, settings: config.Settings) -> edgar.EdgarClient:
        """Build an online client on this transport, with no wait."""
        return edgar.EdgarClient(
            "Keel Test test@example.com",
            settings.edgar.cache_dir,
            transport=httpx.MockTransport(self),
            resolver=lambda host: ["162.159.152.4"],
            sleep=lambda seconds: None,
        )


class CountingAdder:
    """Wraps `add.add_ticker` and records each call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def __call__(  # pylint: disable=too-many-arguments
        self,
        settings: config.Settings,
        ticker: str,
        *,
        client: edgar.EdgarClient,
        corpus_dir: pathlib.Path,
        index_dir: pathlib.Path,
        embedder_factory: indexer.EmbedderFactory,
        forms: Sequence[str] = edgar.ADD_FORMS,
    ) -> add.AddReport:
        self.calls.append((ticker, tuple(forms)))
        return add.add_ticker(
            settings,
            ticker,
            client=client,
            corpus_dir=corpus_dir,
            index_dir=index_dir,
            embedder_factory=embedder_factory,
            forms=forms,
        )


def _add_10k(workspace: Workspace) -> None:
    """The earlier `keel add`: the ZTS 10-K only, from the cache."""
    settings, corpus, index = workspace
    with _offline(settings) as client:
        add.add_ticker(
            settings,
            "ZTS",
            client=client,
            corpus_dir=corpus,
            index_dir=index,
            embedder_factory=conftest.FakeEmbedder,
            forms=("10-K",),
        )


def test_refresh_new_filing(workspace: Workspace) -> None:
    """A newer accession in the submissions triggers exactly 1 add."""
    settings, corpus, index = workspace
    _add_10k(workspace)
    assert not (corpus / ZTS_10Q).exists()
    sec = RecordedSec()
    adder = CountingAdder()
    fake = conftest.FakeEmbedder()
    with sec.client(settings) as client:
        report = refresh.run_refresh(
            settings,
            client=client,
            corpus_dir=corpus,
            index_dir=index,
            embedder_factory=lambda: fake,
            adder=adder,
            clock=lambda: T0,
        )
    # 1 request: the submissions; the ticker map and the 10-Q are cached.
    assert sec.urls == [SUBMISSIONS_URL]
    assert report.requests == 1
    assert adder.calls == [("ZTS", ("10-Q",))]
    (result,) = report.tickers
    assert [ref.accession for ref in result.new] == [ZTS_10Q_ACCESSION]
    (filing,) = result.added
    assert (filing.file_name, filing.filing_id) == (
        ZTS_10Q,
        "ZTS_10Q_2026-06-30",
    )
    assert filing.quarantine is None
    assert filing.chunks > 0
    assert (report.new_count, report.added_count, report.error_count) == (
        1,
        1,
        0,
    )
    # Only the new filing reached the embedding model.
    manifest = indexer.verify(indexer.current_build(index) or index)
    assert manifest.build.embedded_filings == 1
    assert len(fake.seen) == filing.chunks
    assert manifest.counts.indexed == 3 + 2

    # The banner lists the filing added after the last visit.
    log = refresh.log_path(settings)
    (added,) = refresh.added_since(log, T0 - datetime.timedelta(days=1))
    assert (added.ticker, added.form, added.accession) == (
        "ZTS",
        "10-Q",
        ZTS_10Q_ACCESSION,
    )
    assert added.filing_id == "ZTS_10Q_2026-06-30"
    assert not added.dry_run
    assert refresh.added_since(log, T0) == []

    # The next refresh finds nothing new and adds nothing.
    with sec.client(settings) as client:
        again = refresh.run_refresh(
            settings,
            client=client,
            corpus_dir=corpus,
            index_dir=index,
            embedder_factory=lambda: fake,
            adder=adder,
        )
    assert again.new_count == 0
    assert len(adder.calls) == 1


def test_refresh_dry_run(workspace: Workspace) -> None:
    """A dry run lists the new filings and writes no file and no index."""
    settings, corpus, index = workspace
    state_store.add_watch(state_store.state_path(settings), "ZTS")
    before = indexer.current_build(index)
    manifest_text = (corpus / "manifest.json").read_text()
    adder = CountingAdder()
    with _offline(settings) as client:
        report = refresh.run_refresh(
            settings,
            dry_run=True,
            client=client,
            corpus_dir=corpus,
            index_dir=index,
            embedder_factory=conftest.FakeEmbedder,
            adder=adder,
            clock=lambda: T0,
        )
    assert report.dry_run
    (result,) = report.tickers
    assert [(ref.form, ref.accession) for ref in result.new] == [
        ("10-K", "0001555280-26-000011"),
        ("10-Q", ZTS_10Q_ACCESSION),
    ]
    assert result.added == []
    assert adder.calls == []
    assert indexer.current_build(index) == before
    assert (corpus / "manifest.json").read_text() == manifest_text
    assert not (corpus / ZTS_10K).exists()
    entries = refresh.read_log(refresh.log_path(settings))
    assert [entry.event for entry in entries] == ["start", "new", "new", "done"]
    assert all(entry.dry_run for entry in entries)
    assert entries[-1].detail == (
        "1 tickers, 2 new, 0 added, 0 errors, 0 requests"
    )
    assert refresh.added_since(refresh.log_path(settings), T0.min) == []


def test_refresh_log_and_errors(workspace: Workspace) -> None:
    """An unknown watched ticker is logged and the run goes on."""
    settings, corpus, index = workspace
    path = state_store.state_path(settings)
    state_store.add_watch(path, "ZZZZ", "ana")
    _add_10k(workspace)
    with _offline(settings) as client:
        report = refresh.run_refresh(
            settings,
            dry_run=True,
            client=client,
            corpus_dir=corpus,
            index_dir=index,
            embedder_factory=conftest.FakeEmbedder,
        )
    assert [r.ticker for r in report.tickers] == ["ZTS", "ZZZZ"]
    assert report.tickers[1].error is not None
    assert "UnknownTickerError" in report.tickers[1].error
    assert report.error_count == 1
    lines = refresh.log_path(settings).read_text().splitlines()
    events = [json.loads(line) for line in lines]
    assert [e["event"] for e in events] == ["start", "new", "error", "done"]
    assert events[0]["detail"] == "2 tickers: ZTS ZZZZ"
    assert events[1]["accession"] == ZTS_10Q_ACCESSION
    assert events[2]["ticker"] == "ZZZZ"
    # A log line from another version, or a broken one, is skipped.
    with refresh.log_path(settings).open("a") as handle:
        handle.write("not json\n\n")
    assert len(refresh.read_log(refresh.log_path(settings))) == 4


@pytest.fixture
def cli_env(
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> Workspace:
    """Point the CLI config at the workspace through the environment."""
    settings = workspace[0]
    monkeypatch.setenv("KEEL_EDGAR__CACHE_DIR", str(settings.edgar.cache_dir))
    monkeypatch.setenv("KEEL_LOGS__DIR", str(settings.logs.dir))
    monkeypatch.setenv(
        "KEEL_DICTIONARIES__COMPANIES", str(settings.dictionaries.companies)
    )
    monkeypatch.setattr(
        numpy_dense.SentenceEmbedder,
        "from_settings",
        lambda settings: conftest.FakeEmbedder(),
    )
    return workspace


def _keel(*args: str) -> int:
    return cli.main(["--config", str(conftest.CONFIG_FILE), *args])


def test_refresh_command(
    cli_env: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    """`keel watch` and `keel refresh --dry-run`, then a real refresh."""
    _, corpus, index = cli_env
    assert _keel("watch", "add", "zts") == 0
    assert _keel("watch", "list") == 0
    out = capsys.readouterr().out
    assert "cli watching ZTS" in out
    assert "1 watched tickers" in out
    where = ["--corpus", str(corpus), "--out", str(index)]
    assert _keel("refresh", "--dry-run", "--offline", *where) == 0
    out = capsys.readouterr().out
    assert (
        "ZTS: new 10-Q filed 2026-08-06 accession " + ZTS_10Q_ACCESSION in out
    )
    assert "dry run: 1 tickers, 2 new, 0 added, 0 errors" in out
    assert _keel("refresh", "--offline", *where) == 0
    out = capsys.readouterr().out
    assert f"{ZTS_10Q}: added as ZTS_10Q_2026-06-30" in out
    assert "1 tickers, 2 new, 2 added, 0 errors, 0 EDGAR requests" in out
    assert _keel("refresh", "--offline", *where) == 0
    assert "ZTS: up to date" in capsys.readouterr().out
    assert _keel("watch", "remove", "ZTS") == 0
    assert _keel("watch", "add") == 1
    assert "cli stopped watching ZTS" in capsys.readouterr().out


def test_refresh_command_error(
    cli_env: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    _, corpus, index = cli_env
    assert _keel("watch", "add", "ZZZZ") == 0
    where = ["--corpus", str(corpus), "--out", str(index)]
    assert _keel("refresh", "--dry-run", "--offline", *where) == 1
    assert "ZZZZ: error: UnknownTickerError" in capsys.readouterr().out
