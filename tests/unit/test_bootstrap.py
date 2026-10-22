"""Tests for the bootstrap: S-11 checks, downloads, state, and skips.

No test touches the network: downloads go through `httpx.MockTransport`,
host names resolve through a fake resolver, and `gh` is a fake runner.
"""

from collections.abc import Sequence
import pathlib

import httpx
import pytest

from keel import bootstrap
from keel import config
from keel import errors
from keel import indexer
from keel.stores import numpy_dense

pytestmark = pytest.mark.unit

PUBLIC_IP = "93.184.216.34"
URL = "https://bucket.example.com/edgar_corpus.zip?X-Signature=secret123"


def public(host: str) -> list[str]:
    del host
    return [PUBLIC_IP]


def configure(
    settings: config.Settings,
    root: pathlib.Path,
    *,
    url: str | None = None,
    zip_path: pathlib.Path | None = None,
) -> config.Settings:
    corpus = settings.corpus.model_copy(
        update={
            "dir": root / "corpus" / "edgar",
            "zip": zip_path or root / "absent" / "edgar_corpus.zip",
            "url": url,
        }
    )
    index = settings.index.model_copy(update={"dir": root / "index"})
    return settings.model_copy(update={"corpus": corpus, "index": index})


def no_outside_world() -> bootstrap.Dependencies:
    def refuse_embedder() -> numpy_dense.Embedder:
        raise AssertionError("the embedder was loaded")

    def refuse_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a request went to {request.url.host}")

    def refuse_command(command: Sequence[str]) -> None:
        raise AssertionError(f"a command ran: {command[0]}")

    return bootstrap.Dependencies(
        embedder_factory=refuse_embedder,
        transport=httpx.MockTransport(refuse_request),
        resolver=public,
        run_command=refuse_command,
        environ={"GH_TOKEN": "token"},
        which=lambda name: f"/usr/bin/{name}",
    )


def test_bootstrap_skips_when_present(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    configured = configure(settings, tmp_path, url=URL)
    corpus_dir = configured.corpus.dir
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "AAPL_10K_2024-11-01_full.txt").write_text("filing")
    build = configured.index.dir / "20260101T000000000000Z"
    build.mkdir(parents=True)
    (configured.index.dir / indexer.CURRENT).symlink_to(build.name)
    state = bootstrap.BootstrapState()

    status = bootstrap.run_bootstrap(configured, state, no_outside_world())

    assert status.phase == bootstrap.Phase.READY
    assert status.corpus == "present"
    assert status.index == "present"
    assert status.error is None
    assert status.started_at is not None
    assert status.finished_at is not None
    assert not status.running
    # A second run is as cheap: still nothing fetched or built.
    again = bootstrap.run_bootstrap(configured, state, no_outside_world())
    assert (again.corpus, again.index) == ("present", "present")


def test_bootstrap_without_a_source_fails(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    configured = configure(settings, tmp_path)
    deps = bootstrap.Dependencies(environ={}, which=lambda name: None)

    status = bootstrap.run_bootstrap(configured, deps=deps)

    assert status.phase == bootstrap.Phase.FAILED
    assert status.error is not None
    assert status.error.startswith("CorpusMissingError")


def test_unexpected_error_marks_failed_and_raises(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    configured = configure(settings, tmp_path)
    state = bootstrap.BootstrapState()

    def broken(name: str) -> str | None:
        raise RuntimeError(name)

    with pytest.raises(RuntimeError):
        bootstrap.run_bootstrap(
            configured,
            state,
            bootstrap.Dependencies(environ={}, which=broken),
        )
    assert state.snapshot().phase == bootstrap.Phase.FAILED
    assert state.snapshot().error == "RuntimeError"


def test_state_refuses_a_second_run() -> None:
    state = bootstrap.BootstrapState()
    assert state.begin()
    state.enter(bootstrap.Phase.INDEXING, "building", total=10)
    state.advance(4, 10)
    assert not state.begin()
    snapshot = state.snapshot()
    assert snapshot.running
    assert (snapshot.done, snapshot.total) == (4, 10)


def test_active_run_returns_its_status(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    state = bootstrap.BootstrapState()
    state.begin()
    state.enter(bootstrap.Phase.DOWNLOADING, "downloading")

    status = bootstrap.run_bootstrap(
        configure(settings, tmp_path), state, no_outside_world()
    )

    assert status.phase == bootstrap.Phase.DOWNLOADING


def test_allowed_hosts() -> None:
    hosts = bootstrap.allowed_hosts(URL)
    assert "bucket.example.com" in hosts
    assert "github.com" in hosts
    assert "objects.githubusercontent.com" in hosts
    assert bootstrap.allowed_hosts(None) == bootstrap.GITHUB_RELEASE_HOSTS


@pytest.mark.parametrize(
    ("url", "addresses", "reason"),
    [
        ("http://bucket.example.com/c.zip", [PUBLIC_IP], "https"),
        ("https://evil.example.org/c.zip", [PUBLIC_IP], "not allowed"),
        ("https://u:p@bucket.example.com/c.zip", [PUBLIC_IP], "credentials"),
        ("https://bucket.example.com:8443/c.zip", [PUBLIC_IP], "port"),
        ("https://bucket.example.com/c.zip", ["10.0.0.5"], "non-public"),
        ("https://bucket.example.com/c.zip", ["127.0.0.1"], "non-public"),
        ("https://bucket.example.com/c.zip", ["169.254.169.254"], "non-public"),
        ("https://bucket.example.com/c.zip", ["::1"], "non-public"),
        ("https://bucket.example.com/c.zip", [], "no address"),
    ],
)
def test_check_url_rejects(url: str, addresses: list[str], reason: str) -> None:
    allowed = bootstrap.allowed_hosts(URL)
    with pytest.raises(errors.HostNotAllowedError, match=reason):
        bootstrap.check_url(url, allowed, lambda host: addresses)


def test_check_url_accepts_public_https() -> None:
    allowed = bootstrap.allowed_hosts(URL)
    assert bootstrap.check_url(URL, allowed, public) == "bucket.example.com"


def test_resolve_host_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("no name")

    monkeypatch.setattr(bootstrap.socket, "getaddrinfo", fail)
    with pytest.raises(errors.HostNotAllowedError, match="cannot resolve"):
        bootstrap.resolve_host("bucket.example.com")


def test_resolve_host(monkeypatch: pytest.MonkeyPatch) -> None:
    infos = [
        (2, 1, 6, "", (PUBLIC_IP, 443)),
        (2, 1, 6, "", (PUBLIC_IP, 443)),
    ]
    monkeypatch.setattr(bootstrap.socket, "getaddrinfo", lambda *a, **k: infos)
    assert bootstrap.resolve_host("bucket.example.com") == [PUBLIC_IP]


def serve(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.url.host}{request.url.path}"
        return routes.get(key, httpx.Response(404))

    return httpx.MockTransport(handler)


def test_download_follows_allowed_redirects(tmp_path: pathlib.Path) -> None:
    body = b"PK" + b"x" * 5000
    transport = serve(
        {
            "github.com/o/r/releases/download/corpus-v1/c.zip": httpx.Response(
                302,
                headers={
                    "location": "https://objects.githubusercontent.com/a?s=1"
                },
            ),
            "objects.githubusercontent.com/a": httpx.Response(
                200, content=body
            ),
        }
    )
    seen: list[tuple[int, int | None]] = []
    target = tmp_path / "c.zip"

    written = bootstrap.download(
        "https://github.com/o/r/releases/download/corpus-v1/c.zip",
        target,
        allowed=bootstrap.allowed_hosts(None),
        resolver=public,
        transport=transport,
        progress=lambda done, total: seen.append((done, total)),
    )

    assert written == len(body)
    assert target.read_bytes() == body
    assert seen[-1] == (len(body), len(body))
    assert not target.with_name("c.zip.part").exists()


@pytest.mark.parametrize(
    "location",
    ["https://evil.example.org/c.zip", "http://bucket.example.com/c.zip"],
)
def test_download_rejects_a_redirect_off_the_list(
    tmp_path: pathlib.Path, location: str
) -> None:
    transport = serve(
        {
            "bucket.example.com/edgar_corpus.zip": httpx.Response(
                302, headers={"location": location}
            )
        }
    )
    with pytest.raises(errors.HostNotAllowedError):
        bootstrap.download(
            URL,
            tmp_path / "c.zip",
            allowed=bootstrap.allowed_hosts(URL),
            resolver=public,
            transport=transport,
        )
    assert not list(tmp_path.iterdir())


def test_download_stops_after_too_many_redirects(
    tmp_path: pathlib.Path,
) -> None:
    transport = serve(
        {
            "bucket.example.com/edgar_corpus.zip": httpx.Response(
                302, headers={"location": "/edgar_corpus.zip"}
            )
        }
    )
    with pytest.raises(errors.CorpusDownloadError, match="redirects"):
        bootstrap.download(
            URL,
            tmp_path / "c.zip",
            allowed=bootstrap.allowed_hosts(URL),
            resolver=public,
            transport=transport,
        )


def test_download_http_error_names_only_the_host(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(errors.CorpusDownloadError) as caught:
        bootstrap.download(
            URL,
            tmp_path / "c.zip",
            allowed=bootstrap.allowed_hosts(URL),
            resolver=public,
            transport=serve({}),
        )
    assert "404" in str(caught.value)
    assert "secret123" not in str(caught.value)


@pytest.mark.parametrize("declare", [True, False])
def test_download_size_limit(tmp_path: pathlib.Path, declare: bool) -> None:
    body = b"x" * 3000
    headers = {} if declare else {"transfer-encoding": "chunked"}
    response = (
        httpx.Response(200, content=body)
        if declare
        else httpx.Response(200, content=iter([body]), headers=headers)
    )
    transport = serve({"bucket.example.com/edgar_corpus.zip": response})
    with pytest.raises(errors.CorpusDownloadError, match="bytes"):
        bootstrap.download(
            URL,
            tmp_path / "c.zip",
            allowed=bootstrap.allowed_hosts(URL),
            resolver=public,
            transport=transport,
            max_bytes=1000,
        )
    assert not list(tmp_path.iterdir())


def test_download_network_error(tmp_path: pathlib.Path) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(errors.CorpusDownloadError, match="ConnectError"):
        bootstrap.download(
            URL,
            tmp_path / "c.zip",
            allowed=bootstrap.allowed_hosts(URL),
            resolver=public,
            transport=httpx.MockTransport(fail),
        )


def test_download_write_error(tmp_path: pathlib.Path) -> None:
    transport = serve(
        {"bucket.example.com/edgar_corpus.zip": httpx.Response(200)}
    )
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(errors.CorpusDownloadError, match="cannot write"):
        bootstrap.download(
            URL,
            blocker / "c.zip",
            allowed=bootstrap.allowed_hosts(URL),
            resolver=public,
            transport=transport,
        )


def test_gh_download(tmp_path: pathlib.Path) -> None:
    commands: list[list[str]] = []

    def fake_gh(command: Sequence[str]) -> None:
        commands.append(list(command))
        out = pathlib.Path(command[command.index("--dir") + 1])
        (out / "edgar_corpus.zip").write_bytes(b"PK")

    target = tmp_path / "corpus" / "edgar_corpus.zip"
    bootstrap.gh_download("/bin/gh", "o/r", "corpus-v1", target, fake_gh)

    assert target.read_bytes() == b"PK"
    assert commands[0][:7] == [
        "/bin/gh",
        "release",
        "download",
        "corpus-v1",
        "--repo",
        "o/r",
        "--pattern",
    ]
    assert [p.name for p in target.parent.iterdir()] == ["edgar_corpus.zip"]


def test_gh_download_without_a_file(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "edgar_corpus.zip"
    with pytest.raises(errors.CorpusDownloadError, match="no edgar"):
        bootstrap.gh_download(
            "/bin/gh", "o/r", "corpus-v1", target, lambda command: None
        )
    assert not list(tmp_path.iterdir())


def test_run_command_errors() -> None:
    with pytest.raises(errors.CorpusDownloadError, match="exited with 3"):
        bootstrap._run_command(["/bin/sh", "-c", "exit 3"])
    with pytest.raises(errors.CorpusDownloadError, match="failed"):
        bootstrap._run_command(["/no/such/gh"])
