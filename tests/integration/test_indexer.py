"""Index build mechanics on the mini corpus with a fake embedder.

The pointer swap, the failure path, the versions, the pruning, and the
checksum check (chapters 7.12, 9.5, 9.7). The tests with the pinned model
are in `test_index_build.py`.
"""

import json
import pathlib
import shutil

import numpy
import pytest

import conftest
from keel import config
from keel import errors
from keel import indexer
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration


class FailingEmbedder(conftest.FakeEmbedder):
    """Fails on the second filing."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def encode(self, texts: object) -> numpy_dense.Vectors:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("embedding failed")
        return super().encode(texts)  # type: ignore[arg-type]


def build(
    settings: config.Settings,
    out: pathlib.Path,
    corpus: pathlib.Path = conftest.MINI_CORPUS,
    *,
    incremental: bool = False,
    embedder: conftest.FakeEmbedder | None = None,
) -> indexer.BuildResult:
    fake = embedder or conftest.FakeEmbedder()
    return indexer.build_index(
        settings, corpus, out, lambda: fake, incremental=incremental
    )


def test_current_pointer(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    result = build(settings, tmp_path)
    pointer = tmp_path / indexer.CURRENT
    assert pointer.is_symlink()
    assert pointer.resolve() == result.build_dir.resolve()
    assert indexer.current_build(tmp_path) == result.build_dir.resolve()
    assert sorted(p.name for p in result.build_dir.iterdir()) == [
        "chunks.sqlite",
        "manifest.json",
        "vectors",
        "vectors.npy",
    ]
    manifest = indexer.verify(pointer)
    assert manifest.index_version == "1.0.0"
    assert manifest.counts.files == 3
    assert manifest.counts.indexed == 3
    assert manifest.counts.quarantined == 0
    assert manifest.embedding_model.revision == settings.embedding.revision
    assert manifest.reranker_model.name == settings.reranker.model
    assert manifest.build.embedded_filings == 3
    assert not list(tmp_path.glob(".tmp-*"))
    assert not list(tmp_path.glob(".current-*"))


def test_failed_build_keeps_current(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    first = build(settings, tmp_path)
    with pytest.raises(RuntimeError):
        build(settings, tmp_path, embedder=FailingEmbedder())
    assert indexer.current_build(tmp_path) == first.build_dir.resolve()
    assert indexer.verify(tmp_path / indexer.CURRENT) == first.manifest
    assert not list(tmp_path.glob(".tmp-*"))


def test_versions_and_prune(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    first = build(settings, tmp_path)
    second = build(settings, tmp_path)
    third = build(settings, tmp_path, incremental=True)
    assert second.manifest.index_version == "1.0.1"
    assert third.manifest.index_version == "1.0.2"
    # The new build and the previous one stay; the oldest goes.
    assert not first.build_dir.exists()
    assert second.build_dir.exists()
    assert third.build_dir.exists()
    assert third.manifest.build.previous_build == second.build_dir.name
    assert third.manifest.build.incremental
    assert third.manifest.build.reused_filings == 3
    assert third.manifest.build.embedded_filings == 0
    assert third.manifest.files == second.manifest.files


def test_model_change_reembeds(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    first = build(settings, tmp_path)
    path = first.build_dir / indexer.MANIFEST
    data = json.loads(path.read_text())
    data["embedding_model"]["revision"] = "0" * 40
    path.write_text(json.dumps(data))
    result = build(settings, tmp_path, incremental=True)
    assert result.manifest.build.embedded_filings == 3


def test_chunker_version_is_major(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    build(settings, tmp_path)
    changed = settings.model_copy(
        update={
            "chunker": settings.chunker.model_copy(update={"version": "1.1.0"})
        }
    )
    result = build(changed, tmp_path, incremental=True)
    assert result.manifest.index_version == "2.0.0"
    assert result.manifest.build.embedded_filings == 3


def test_incremental_remove(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(conftest.MINI_CORPUS, corpus)
    out = tmp_path / "index"
    full = build(settings, out, corpus)
    removed = next(corpus.glob("AAPL_*.txt"))
    removed.unlink()
    result = build(settings, out, corpus, incremental=True)
    assert result.manifest.index_version == "1.1.0"
    assert result.manifest.counts.indexed == 2
    assert result.manifest.build.embedded_filings == 0
    assert not (
        result.build_dir / "vectors" / "AAPL_10Q_2022-12-31.npy"
    ).exists()
    rows = numpy_dense.load(result.build_dir / numpy_dense.FILE_NAME).shape[0]
    assert rows == result.manifest.counts.chunks
    assert rows < full.manifest.counts.chunks


def test_incremental_without_current(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    result = build(settings, tmp_path, incremental=True)
    assert not result.manifest.build.incremental
    assert result.manifest.build.previous_build is None


def test_pointer_not_a_symlink(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    (tmp_path / indexer.CURRENT).mkdir()
    with pytest.raises(errors.IndexWriteError):
        build(settings, tmp_path)
    assert not list(tmp_path.glob(".tmp-*"))


def test_empty_corpus(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    with pytest.raises(errors.CorpusMissingError):
        build(settings, tmp_path / "index", tmp_path)


def test_verify_detects_changes(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    result = build(settings, tmp_path)
    vectors = result.build_dir / numpy_dense.FILE_NAME
    data = bytearray(vectors.read_bytes())
    data[-1] ^= 0xFF
    vectors.write_bytes(bytes(data))
    with pytest.raises(errors.IndexCorruptError):
        indexer.verify(result.build_dir)
    vectors.unlink()
    with pytest.raises(errors.IndexMissingError):
        indexer.verify(result.build_dir)
    manifest = result.build_dir / indexer.MANIFEST
    manifest.write_text(json.dumps({"index_version": "1.0.0"}))
    with pytest.raises(errors.IndexCorruptError):
        indexer.load_manifest(result.build_dir)
    manifest.unlink()
    with pytest.raises(errors.IndexMissingError):
        indexer.verify(result.build_dir)


def test_broken_current_is_ignored(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    first = build(settings, tmp_path)
    (first.build_dir / indexer.MANIFEST).unlink()
    result = build(settings, tmp_path, incremental=True)
    assert result.manifest.index_version == "1.0.0"
    assert result.manifest.build.embedded_filings == 3


def test_next_version() -> None:
    assert indexer.next_version(None, "1.0.0", "1.0.0", False) == "1.0.0"


def test_corpus_hash_is_order_free() -> None:
    hashes = ["b" * 64, "a" * 64]
    assert indexer.corpus_sha256(hashes) == indexer.corpus_sha256(
        list(reversed(hashes))
    )


def test_vectors_follow_chunk_order(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    embedder = conftest.FakeEmbedder()
    result = build(settings, tmp_path, embedder=embedder)
    vectors = numpy_dense.load(result.build_dir / numpy_dense.FILE_NAME)
    expected = conftest.FakeEmbedder().encode(embedder.seen)
    # Shards in filing-ID order, rows in chunk-ID order: the seen order.
    assert numpy.array_equal(vectors, expected)
