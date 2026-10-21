"""Dense store tests with a fake embedder (chapter 9.4)."""

import pathlib

import numpy
import pytest

import conftest
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


@pytest.mark.parametrize(
    "filing_id",
    ["../x", "../../etc/passwd", "AAPL_10K_2024-12-31/../../x", "", "a_10K_x"],
)
def test_shard_path_rejects_traversal(
    tmp_path: pathlib.Path, filing_id: str
) -> None:
    with pytest.raises(errors.InvalidFilingIdError):
        numpy_dense.shard_path(tmp_path, filing_id)


def test_shard_path_accepts_filing_ids(tmp_path: pathlib.Path) -> None:
    for filing_id in ["AAPL_10Q_2022-12-31", "BRK.B_10K_2024-12-31"]:
        path = numpy_dense.shard_path(tmp_path, filing_id)
        assert path == tmp_path / "vectors" / f"{filing_id}.npy"
