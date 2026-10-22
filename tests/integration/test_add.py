"""`keel add TICKER` on the mini corpus with recorded responses (26.2).

The EDGAR client is offline and reads the responses that
`scripts/record_add_fixtures.py` recorded under `tests/fixtures/edgar/`;
the network is blocked. A tiny index of the 3 mini corpus filings, built
with the fake embedder, takes the 2 ZTS filings incrementally.
"""

from collections.abc import Iterator
from collections.abc import Sequence
import json
import pathlib
import shutil
import socket
import sqlite3

import httpx
import pytest

import conftest
from keel import add
from keel import cli
from keel import config
from keel import edgar
from keel import errors
from keel import indexer
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

EDGAR_FIXTURES = conftest.FIXTURES / "edgar"
ZTS_10K = "ZTS_10K_2026-02-12_full.txt"
ZTS_10Q = "ZTS_10Q_2026Q2_2026-08-06_full.txt"
MINI_FILINGS = 3


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
def workspace(
    settings: config.Settings, tmp_path: pathlib.Path
) -> tuple[config.Settings, pathlib.Path, pathlib.Path]:
    """Settings with a copied dictionary, a corpus copy, and a tiny index."""
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
        }
    )
    corpus = tmp_path / "corpus"
    shutil.copytree(conftest.MINI_CORPUS, corpus)
    index = tmp_path / "index"
    fake = conftest.FakeEmbedder()
    indexer.build_index(local, corpus, index, lambda: fake)
    return local, corpus, index


@pytest.fixture
def client(
    workspace: tuple[config.Settings, pathlib.Path, pathlib.Path],
) -> Iterator[edgar.EdgarClient]:
    """An offline client on the recorded responses; a request fails."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"request in a test: {request.url}")

    with edgar.EdgarClient(
        "Keel Test test@example.com",
        workspace[0].edgar.cache_dir,
        offline=True,
        transport=httpx.MockTransport(handler),
    ) as value:
        yield value


def _sources(build_dir: pathlib.Path) -> dict[str, str]:
    conn = sqlite3.connect(build_dir / chunk_store.FILE_NAME)
    try:
        rows = conn.execute("SELECT filing_id, source FROM filings").fetchall()
    finally:
        conn.close()
    return dict(rows)


def test_add_incremental(
    workspace: tuple[config.Settings, pathlib.Path, pathlib.Path],
    client: edgar.EdgarClient,
) -> None:
    """The 2 new filings parse, and only they reach the embedding model."""
    settings, corpus, index = workspace
    fake = conftest.FakeEmbedder()
    report = add.add_ticker(
        settings,
        "zts",
        client=client,
        corpus_dir=corpus,
        index_dir=index,
        embedder_factory=lambda: fake,
    )
    assert (report.ticker, report.cik) == ("ZTS", "0001555280")
    assert report.company == "Zoetis Inc."
    assert report.requests == 0
    assert not report.dictionary_added
    ten_k, ten_q = report.filings
    assert (ten_k.file_name, ten_q.file_name) == (ZTS_10K, ZTS_10Q)
    assert (ten_k.filing_id, ten_k.fiscal_year, ten_k.fiscal_period) == (
        "ZTS_10K_2025-12-31",
        2025,
        "FY",
    )
    assert (ten_q.filing_id, ten_q.fiscal_year, ten_q.fiscal_period) == (
        "ZTS_10Q_2026-06-30",
        2026,
        "Q2",
    )
    for filing in report.filings:
        assert filing.changed
        assert filing.quarantine is None
        assert filing.warnings == ("no_xbrl_block",)
        assert filing.chunks > 0

    # Only the new filings were embedded; the 3 shards were reused.
    manifest = indexer.verify(indexer.current_build(index) or index)
    assert report.index_built
    assert report.index_version == manifest.index_version == "1.1.0"
    assert manifest.build.incremental
    assert manifest.build.reused_filings == MINI_FILINGS
    assert manifest.build.embedded_filings == report.embedded_filings == 2
    assert report.embedded_chunks == ten_k.chunks + ten_q.chunks
    assert len(fake.seen) == report.embedded_chunks
    assert manifest.counts.indexed == MINI_FILINGS + 2
    sources = _sources(indexer.current_build(index) or index)
    added = {
        k: sources[k] for k in ("ZTS_10K_2025-12-31", "ZTS_10Q_2026-06-30")
    }
    assert added == {
        "ZTS_10K_2025-12-31": "edgar",
        "ZTS_10Q_2026-06-30": "edgar",
    }
    rest = {v for k, v in sources.items() if k not in added}
    assert rest == {"corpus"}

    # The corpus manifest lists the files with their source.
    listed = json.loads((corpus / "manifest.json").read_text())
    assert {ZTS_10K, ZTS_10Q} <= set(listed["files"])
    assert listed["file_count"] == MINI_FILINGS + 2
    assert listed["filing_types"] == {"10-K": 3, "10-Q": 2}
    assert listed["added"][ZTS_10K]["source"] == "edgar"
    assert listed["added"][ZTS_10Q]["accession"] == "0001555280-26-000040"
    assert listed["license"].startswith("Public domain")

    # A repeat run changes nothing and builds nothing.
    again = add.add_ticker(
        settings,
        "ZTS",
        client=client,
        corpus_dir=corpus,
        index_dir=index,
        embedder_factory=lambda: fake,
    )
    assert not again.index_built
    assert again.index_version == "1.1.0"
    assert [f.changed for f in again.filings] == [False, False]
    assert [f.chunks for f in again.filings] == [ten_k.chunks, ten_q.chunks]
    assert len(fake.seen) == report.embedded_chunks


def test_add_needs_an_index(
    workspace: tuple[config.Settings, pathlib.Path, pathlib.Path],
    client: edgar.EdgarClient,
    tmp_path: pathlib.Path,
) -> None:
    settings, corpus, _ = workspace
    with pytest.raises(errors.IndexMissingError, match="keel index"):
        add.add_ticker(
            settings,
            "ZTS",
            client=client,
            corpus_dir=corpus,
            index_dir=tmp_path / "empty",
            embedder_factory=conftest.FakeEmbedder,
        )
    assert not (corpus / ZTS_10K).exists()


def test_add_unknown_ticker(
    workspace: tuple[config.Settings, pathlib.Path, pathlib.Path],
    client: edgar.EdgarClient,
) -> None:
    settings, corpus, index = workspace
    with pytest.raises(errors.UnknownTickerError, match="companysearch"):
        add.add_ticker(
            settings,
            "ZZZZ",
            client=client,
            corpus_dir=corpus,
            index_dir=index,
            embedder_factory=conftest.FakeEmbedder,
        )


def test_add_command(
    workspace: tuple[config.Settings, pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`keel add ZTS --offline` as the evidence runs it."""
    settings, corpus, index = workspace
    monkeypatch.setenv("KEEL_EDGAR__CACHE_DIR", str(settings.edgar.cache_dir))
    monkeypatch.setenv(
        "KEEL_DICTIONARIES__COMPANIES", str(settings.dictionaries.companies)
    )
    monkeypatch.setattr(
        numpy_dense.SentenceEmbedder,
        "from_settings",
        lambda settings: conftest.FakeEmbedder(),
    )
    args = ["add", "ZTS", "--offline", "--corpus", str(corpus)]
    code = cli.main(
        ["--config", str(conftest.CONFIG_FILE), *args, "--out", str(index)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "ZTS CIK 0001555280 Zoetis Inc." in out
    assert f"{ZTS_10K} (new or changed)" in out
    assert "ZTS_10Q_2026-06-30, Q2 FY2026, period end 2026-06-30" in out
    assert "warnings: no_xbrl_block" in out
    assert "index version 1.1.0: embedded 2 filings" in out
    assert "; 0 EDGAR requests" in out


def test_corpus_names_and_aliases() -> None:
    assert add.corpus_ticker("brk-b") == "BRK.B"
    with pytest.raises(errors.EdgarError, match="corpus file"):
        add.corpus_ticker("1ABC")
    assert add.aliases("WDAY", "Workday, Inc.") == ["workday", "wday"]
    assert add.aliases("JPM", "JPMorgan Chase & Co.") == [
        "jpmorgan chase",
        "jpm",
    ]
    assert add.aliases("X", "X Corp") == ["x"]


def test_ensure_company(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "companies.yaml"
    path.write_text("# comment\nZTS:\n  company: Zoetis Inc.\n")
    assert not add.ensure_company(path, "ZTS", "Zoetis Inc.")
    assert add.ensure_company(path, "WDAY", 'Workday, "Inc."')
    assert add.ensure_company(path, "ON", "ON Semiconductor Corp")
    assert config.read_yaml(path)["ON"]["aliases"] == ["on semiconductor", "on"]
    entry = config.read_yaml(path)["WDAY"]
    assert entry == {
        "company": 'Workday, "Inc."',
        "aliases": ["workday", "wday"],
        "groups": [],
    }
    assert path.read_text().startswith("# comment\n")


def test_record_in_manifest_errors(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "manifest.json"
    with pytest.raises(errors.ManifestMissingError):
        add.record_in_manifest(path, {})
    path.write_text('{"files": "no list"}')
    with pytest.raises(errors.ManifestMissingError, match="files list"):
        add.record_in_manifest(path, {})
    path.write_text('{"files": ["A_10K_2026-01-01_full.txt"]}')
    entry = {"source": "edgar"}
    assert add.record_in_manifest(
        path, {"B_10Q_2026Q1_2026-05-01_full.txt": entry}
    )
    assert not add.record_in_manifest(
        path, {"B_10Q_2026Q1_2026-05-01_full.txt": entry}
    )
    written = json.loads(path.read_text())
    # No claims in the manifest: only the new file is counted.
    assert written["filing_types"] == {"10-Q": 1}
    assert "file_count" not in written


def test_add_rebuilds_after_a_failed_build(
    workspace: tuple[config.Settings, pathlib.Path, pathlib.Path],
    client: edgar.EdgarClient,
) -> None:
    """Files written by a run whose build failed are indexed by the next."""
    settings, corpus, index = workspace

    class BrokenEmbedder(conftest.FakeEmbedder):
        def encode(self, texts: Sequence[str]) -> numpy_dense.Vectors:
            raise RuntimeError("killed")

    with pytest.raises(errors.EmbeddingModelUnavailableError):
        add.add_ticker(
            settings,
            "ZTS",
            client=client,
            corpus_dir=corpus,
            index_dir=index,
            embedder_factory=BrokenEmbedder,
        )
    assert (corpus / ZTS_10K).is_file()
    report = add.add_ticker(
        settings,
        "ZTS",
        client=client,
        corpus_dir=corpus,
        index_dir=index,
        embedder_factory=conftest.FakeEmbedder,
    )
    assert [f.changed for f in report.filings] == [False, False]
    assert report.index_built
    assert report.embedded_filings == 2
    assert all(f.chunks for f in report.filings)


def test_add_rejects_other_forms(
    workspace: tuple[config.Settings, pathlib.Path, pathlib.Path],
    client: edgar.EdgarClient,
) -> None:
    settings, corpus, index = workspace
    with pytest.raises(errors.EdgarError, match="10-K/A"):
        add.add_ticker(
            settings,
            "ZTS",
            client=client,
            corpus_dir=corpus,
            index_dir=index,
            embedder_factory=conftest.FakeEmbedder,
            forms=("10-K/A",),
        )
