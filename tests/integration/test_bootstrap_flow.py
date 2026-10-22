"""The bootstrap end to end on the mini corpus with a fake embedder.

The zip comes from a local file, an https URL served by a mock transport,
or a fake `gh`; the index build is the real one with a fake embedder.
"""

from collections.abc import Sequence
import dataclasses
import io
import pathlib
import zipfile

import httpx
import pytest

import conftest
from keel import answer
from keel import backup
from keel import bootstrap
from keel import cli
from keel import config
from keel import indexer
from keel.providers import mock

pytestmark = pytest.mark.integration

URL = "https://bucket.example.com/edgar_corpus.zip?X-Signature=secret123"


def mini_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(conftest.MINI_CORPUS.iterdir()):
            archive.write(path, path.name)
    return buffer.getvalue()


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


def fake_deps(**changes: object) -> bootstrap.Dependencies:
    embedder = conftest.FakeEmbedder()
    deps = bootstrap.Dependencies(
        embedder_factory=lambda: embedder,
        resolver=lambda host: ["93.184.216.34"],
        environ={},
        which=lambda name: None,
    )
    return dataclasses.replace(deps, **changes)  # type: ignore[arg-type]


def test_bootstrap_extracts_and_builds_then_skips(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    zip_path = tmp_path / "edgar_corpus.zip"
    zip_path.write_bytes(mini_zip())
    configured = configure(settings, tmp_path, zip_path=zip_path)
    state = bootstrap.BootstrapState()

    status = bootstrap.run_bootstrap(configured, state, fake_deps())

    assert status.phase == bootstrap.Phase.READY
    assert (status.corpus, status.index) == ("extracted", "built")
    assert (status.done, status.total) == (3, 3)
    build = indexer.current_build(configured.index.dir)
    assert build is not None
    assert indexer.verify(build).counts.indexed == 3

    again = bootstrap.run_bootstrap(configured, state, fake_deps())
    assert (again.corpus, again.index) == ("present", "present")
    assert indexer.current_build(configured.index.dir) == build


def test_bootstrap_downloads_from_the_url(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    body = mini_zip()
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return conftest.with_peer(httpx.Response(200, content=body))

    configured = configure(settings, tmp_path, url=URL)
    deps = fake_deps(transport=httpx.MockTransport(handler))

    status = bootstrap.run_bootstrap(configured, deps=deps)

    assert status.phase == bootstrap.Phase.READY, status.error
    assert (status.corpus, status.index) == ("downloaded", "built")
    assert hosts == ["bucket.example.com"]
    assert bootstrap.download_path(configured).read_bytes() == body
    assert len(list(configured.corpus.dir.glob("*.txt"))) == 3


def test_bootstrap_reuses_an_earlier_download(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    configured = configure(settings, tmp_path, url=URL)
    target = bootstrap.download_path(configured)
    target.parent.mkdir(parents=True)
    target.write_bytes(mini_zip())

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("downloaded again")

    status = bootstrap.run_bootstrap(
        configured, deps=fake_deps(transport=httpx.MockTransport(refuse))
    )

    assert (status.corpus, status.index) == ("extracted", "built")


def test_bootstrap_rejects_a_private_address_without_secrets(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    configured = configure(settings, tmp_path, url=URL)

    status = bootstrap.run_bootstrap(
        configured, deps=fake_deps(resolver=lambda host: ["10.1.2.3"])
    )

    assert status.phase == bootstrap.Phase.FAILED
    assert status.error is not None
    assert status.error.startswith("HostNotAllowedError")
    assert "secret123" not in status.error
    assert "secret123" not in status.detail


def test_bootstrap_uses_gh_with_a_token(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    commands: list[list[str]] = []

    def fake_gh(command: Sequence[str]) -> None:
        commands.append(list(command))
        out = pathlib.Path(command[command.index("--dir") + 1])
        (out / "edgar_corpus.zip").write_bytes(mini_zip())

    configured = configure(settings, tmp_path, url=URL)
    deps = fake_deps(
        environ={"GH_TOKEN": "token"},
        which=lambda name: "/usr/bin/gh",
        run_command=fake_gh,
    )

    status = bootstrap.run_bootstrap(configured, deps=deps)

    assert status.phase == bootstrap.Phase.READY, status.error
    assert status.corpus == "downloaded"
    assert commands[0][3] == configured.corpus.release_tag
    assert commands[0][5] == configured.corpus.release_repo
    assert all("token" not in part for part in commands[0])


def release_archive(
    settings: config.Settings, tmp_path: pathlib.Path
) -> pathlib.Path:
    """The `index-v1` release: an index-only archive of a mini build."""
    built = tmp_path / "offhost-index"
    embedder = conftest.FakeEmbedder()
    indexer.build_index(settings, conftest.MINI_CORPUS, built, lambda: embedder)
    return backup.create_backup(built, None, tmp_path / "release").archive


def release_deps(
    archive: pathlib.Path, commands: list[list[str]]
) -> bootstrap.Dependencies:
    """A fake `gh` that downloads the archive and its sha256 file."""

    def fake_gh(command: Sequence[str]) -> None:
        commands.append(list(command))
        out = pathlib.Path(command[command.index("--dir") + 1])
        if command[3] == "index-v1":
            for path in (archive, archive.with_name(archive.name + ".sha256")):
                (out / path.name).write_bytes(path.read_bytes())
        else:
            (out / "edgar_corpus.zip").write_bytes(mini_zip())

    def refuse() -> conftest.FakeEmbedder:
        raise AssertionError("the index was built, not restored")

    return fake_deps(
        environ={"GH_TOKEN": "token"},
        which=lambda name: "/usr/bin/gh",
        run_command=fake_gh,
        embedder_factory=refuse,
    )


def test_bootstrap_restores_the_index_release(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    """Option A: an empty data volume gets the index from the release."""
    archive = release_archive(settings, tmp_path)
    data = tmp_path / "data"
    configured = configure(settings, data)
    configured = configured.model_copy(
        update={
            "index": configured.index.model_copy(
                update={"release_tag": "index-v1"}
            ),
            "logs": config.LogsConfig(dir=data / "logs"),
        }
    )
    commands: list[list[str]] = []

    status = bootstrap.run_bootstrap(
        configured, deps=release_deps(archive, commands)
    )

    assert status.phase == bootstrap.Phase.READY, status.error
    assert (status.corpus, status.index) == ("downloaded", "restored")
    assert commands[1][3:6] == ["index-v1", "--repo", "Dylan-Burns/keel"]
    assert not list(data.glob(".gh-index-*"))
    # The restored build loads: the pipeline opens it without the models.
    opened = answer.Answerer.open(
        configured,
        provider=mock.MockProvider(configured.llm.model),
        load_models=False,
    )
    assert (
        opened.index_version
        == indexer.verify(configured.index.dir / indexer.CURRENT).index_version
    )
    assert not (data / "logs").exists()


def test_bootstrap_builds_when_the_release_fails(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    archive = release_archive(settings, tmp_path)
    archive.with_name(archive.name + ".sha256").write_text("0" * 64 + "  x\n")
    data = tmp_path / "data"
    configured = configure(settings, data)
    configured = configured.model_copy(
        update={
            "index": configured.index.model_copy(
                update={"release_tag": "index-v1"}
            )
        }
    )
    deps = dataclasses.replace(
        release_deps(archive, []),
        embedder_factory=conftest.FakeEmbedder,
    )

    status = bootstrap.run_bootstrap(configured, deps=deps)

    assert status.phase == bootstrap.Phase.READY, status.error
    assert status.index == "built"


def test_start_background(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    zip_path = tmp_path / "edgar_corpus.zip"
    zip_path.write_bytes(mini_zip())
    configured = configure(settings, tmp_path, zip_path=zip_path)
    state = bootstrap.BootstrapState()

    thread = bootstrap.start_background(configured, state, fake_deps())
    thread.join(timeout=120)

    assert not thread.is_alive()
    assert state.snapshot().phase == bootstrap.Phase.READY


def test_bootstrap_command(
    clean_env: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus_dir = tmp_path / "corpus" / "edgar"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "AAPL_10K_2024-11-01_full.txt").write_text("filing")
    build = tmp_path / "index" / "20260101T000000000000Z"
    build.mkdir(parents=True)
    (tmp_path / "index" / indexer.CURRENT).symlink_to(build.name)
    clean_env.setenv("KEEL_CORPUS__DIR", str(corpus_dir))
    clean_env.setenv("KEEL_INDEX__DIR", str(tmp_path / "index"))

    assert cli.main(["bootstrap"]) == 0
    out = capsys.readouterr().out
    assert "phase: ready" in out
    assert "corpus: present" in out

    clean_env.setenv("KEEL_INDEX__DIR", str(tmp_path / "other-index"))
    clean_env.setenv("KEEL_CORPUS__DIR", str(tmp_path / "empty"))
    clean_env.setenv("KEEL_CORPUS__ZIP", str(tmp_path / "absent.zip"))
    clean_env.delenv("GH_TOKEN", raising=False)
    assert cli.main(["bootstrap"]) == 2
    assert "CorpusMissingError" in capsys.readouterr().out
