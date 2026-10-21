"""Dense store tests with a fake embedder (chapter 9.4)."""

import pathlib

import numpy
import pytest

import conftest
from keel import config
from keel import errors
from keel.stores import numpy_dense

pytestmark = pytest.mark.unit


def test_embed_query_prefix() -> None:
    embedder = conftest.FakeEmbedder()
    vector = numpy_dense.embed_query(embedder, "revenue growth")
    assert embedder.seen == [numpy_dense.QUERY_PREFIX + "revenue growth"]
    assert numpy_dense.QUERY_PREFIX.endswith("passages: ")
    assert vector.shape == (numpy_dense.DIMENSIONS,)
    assert vector.dtype == numpy.float32


def test_shards_concatenate_in_order(tmp_path: pathlib.Path) -> None:
    embedder = conftest.FakeEmbedder()
    first = embedder.encode(["a", "b"])
    second = embedder.encode(["c"])
    paths = [
        numpy_dense.shard_path(tmp_path, "AAA_10K_2024-12-31"),
        numpy_dense.shard_path(tmp_path, "BBB_10K_2024-12-31"),
    ]
    numpy_dense.write_shard(paths[0], first)
    numpy_dense.write_shard(paths[1], second)
    out = tmp_path / numpy_dense.FILE_NAME
    assert numpy_dense.concatenate(paths, out) == 3
    vectors = numpy_dense.load(out)
    assert vectors.dtype == numpy.float32
    assert numpy.array_equal(vectors, numpy.vstack([first, second]))
    norms = numpy.linalg.norm(vectors, axis=1)
    assert numpy.allclose(norms, 1.0, atol=1e-5)


def test_concatenate_empty(tmp_path: pathlib.Path) -> None:
    out = tmp_path / numpy_dense.FILE_NAME
    assert numpy_dense.concatenate([], out) == 0
    assert numpy_dense.load(out).shape == (0, numpy_dense.DIMENSIONS)


def test_bad_shard(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "bad.npy"
    numpy.save(path, numpy.zeros((2, 8), dtype=numpy.float64))
    with pytest.raises(errors.IndexCorruptError):
        numpy_dense.read_shard(path)


def test_load_missing(tmp_path: pathlib.Path) -> None:
    with pytest.raises(errors.IndexMissingError):
        numpy_dense.load(tmp_path / "absent.npy")


def test_top_k() -> None:
    vectors = numpy.asarray(
        [[1, 0], [0, 1], [1, 0], [0.6, 0.8]], dtype=numpy.float32
    )
    query = numpy.asarray([1, 0], dtype=numpy.float32)
    assert numpy_dense.top_k(vectors, query, 3) == [
        (0, 1.0),
        (2, 1.0),
        (3, pytest.approx(0.6)),
    ]
    assert numpy_dense.top_k(vectors, query, 2, rows=[1, 3]) == [
        (3, pytest.approx(0.6)),
        (1, 0.0),
    ]
    assert numpy_dense.top_k(vectors, query, 0) == []
    assert numpy_dense.top_k(vectors, query, 5, rows=[]) == []


def test_missing_model(
    settings: config.Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    pinned = settings.model_copy(
        update={
            "embedding": settings.embedding.model_copy(
                update={"model": "keel-test/absent-model"}
            )
        }
    )
    with pytest.raises(errors.EmbeddingModelUnavailableError):
        numpy_dense.SentenceEmbedder.from_settings(pinned)


def test_sentence_embedder(settings: config.Settings) -> None:
    embedder = numpy_dense.SentenceEmbedder.from_settings(settings)
    assert embedder.dimensions == numpy_dense.DIMENSIONS
    assert embedder.encode([]).shape == (0, numpy_dense.DIMENSIONS)
    vectors = embedder.encode(["Net sales increased 12%.", "Risk factors."])
    assert vectors.dtype == numpy.float32
    assert vectors.shape == (2, numpy_dense.DIMENSIONS)
    assert numpy.allclose(numpy.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)
