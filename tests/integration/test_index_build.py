"""Index build tests with the pinned embedding model (chapter 9.8).

The model comes from the local Hugging Face cache; pytest runs with
HF_HUB_OFFLINE=1. The vectors are compared on 1 machine only: torch 2.2 on
the Intel laptop and torch 2.x on Linux CI may differ in the last float bits.
"""

from collections.abc import Iterator
import os
import pathlib
import re
import shutil
import signal
import sqlite3

import numpy
import pytest

import conftest
from keel import cli
from keel import config
from keel import errors
from keel import indexer
from keel.stores import chunk_store
from keel.stores import numpy_dense
from keel.stores import sqlite_fts

pytestmark = pytest.mark.integration

# Words skipped at the body start, past the overlap with the previous chunk.
PHRASE_SKIP = 60
PHRASE_WORDS = 8


@pytest.fixture(scope="module")
def module_settings() -> Iterator[config.Settings]:
    """The repository config without KEEL_ variables or the dotenv file."""
    with pytest.MonkeyPatch.context() as patch:
        for name in list(os.environ):
            if name.startswith("KEEL_"):
                patch.delenv(name)
        yield config.load_settings(conftest.CONFIG_FILE, env_file=None)


@pytest.fixture(scope="module")
def embedder(module_settings: config.Settings) -> numpy_dense.SentenceEmbedder:
    return numpy_dense.SentenceEmbedder.from_settings(module_settings)


def build(
    embedder: numpy_dense.SentenceEmbedder,
    out: pathlib.Path,
    corpus: pathlib.Path = conftest.MINI_CORPUS,
    *,
    incremental: bool = False,
) -> indexer.BuildResult:
    settings = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    return indexer.build_index(
        settings, corpus, out, lambda: embedder, incremental=incremental
    )


@pytest.fixture(scope="module")
def built(
    embedder: numpy_dense.SentenceEmbedder,
    tmp_path_factory: pytest.TempPathFactory,
) -> indexer.BuildResult:
    return build(embedder, tmp_path_factory.mktemp("index"))


def store(result: indexer.BuildResult) -> sqlite3.Connection:
    return chunk_store.open_read_only(result.build_dir / chunk_store.FILE_NAME)


def chunk_rows(result: indexer.BuildResult) -> list[tuple[str, str, int]]:
    conn = store(result)
    try:
        return conn.execute(
            "SELECT chunk_id, chunk_hash, vector_row FROM chunks ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()


def prose_chunks(result: indexer.BuildResult) -> list[tuple[str, str, int]]:
    conn = store(result)
    try:
        return conn.execute(
            "SELECT chunk_id, text, vector_row FROM chunks "
            "WHERE is_table = 0 ORDER BY chunk_id"
        ).fetchall()
    finally:
        conn.close()


def words_of(text: str) -> str:
    return " " + " ".join(re.findall(r"\w+", text.lower())) + " "


def test_vector_rows(built: indexer.BuildResult) -> None:
    vectors = numpy_dense.load(built.build_dir / numpy_dense.FILE_NAME)
    rows = chunk_rows(built)
    assert vectors.shape == (len(rows), numpy_dense.DIMENSIONS)
    assert vectors.dtype == numpy.float32
    assert built.manifest.counts.chunks == len(rows) > 0
    # Rows are in chunk-ID order and vector_row is the position.
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)
    assert [r[2] for r in rows] == list(range(len(rows)))
    norms = numpy.linalg.norm(vectors, axis=1)
    assert numpy.allclose(norms, 1.0, atol=1e-4)


def test_manifest_checksums(built: indexer.BuildResult) -> None:
    files = built.manifest.files
    assert set(files) == {chunk_store.FILE_NAME, numpy_dense.FILE_NAME}
    for name, digest in files.items():
        assert indexer.file_sha256(built.build_dir / name) == digest
    assert indexer.verify(built.build_dir) == built.manifest
    hashes = [
        indexer.file_sha256(p) for p in conftest.MINI_CORPUS.glob("*.txt")
    ]
    assert built.manifest.corpus_sha256 == indexer.corpus_sha256(hashes)


def test_deterministic_build(
    embedder: numpy_dense.SentenceEmbedder,
    built: indexer.BuildResult,
    tmp_path: pathlib.Path,
) -> None:
    again = build(embedder, tmp_path)
    assert chunk_rows(again) == chunk_rows(built)
    assert again.manifest.chunks_sha256 == built.manifest.chunks_sha256
    assert again.manifest.corpus_sha256 == built.manifest.corpus_sha256
    assert again.manifest.files == built.manifest.files
    assert again.manifest.counts == built.manifest.counts


def test_lexical_known_phrase(built: indexer.BuildResult) -> None:
    chunks = prose_chunks(built)
    texts = [words_of(text) for _, text, _ in chunks]
    conn = store(built)
    try:
        checked = 0
        for chunk_id, text, _ in chunks:
            words = text.split("\n", 1)[1].split()
            if len(words) < PHRASE_SKIP + PHRASE_WORDS:
                continue
            phrase = " ".join(words[PHRASE_SKIP : PHRASE_SKIP + PHRASE_WORDS])
            # FTS5 matches tokens, not case or punctuation, so a phrase
            # whose tokens 2 chunks share (a running header) names no chunk.
            if sum(words_of(phrase) in t for t in texts) > 1:
                continue
            hits = sqlite_fts.search(conn, [phrase], 3)
            assert chunk_id in [h.chunk_id for h in hits], phrase
            checked += 1
        assert checked >= 10
    finally:
        conn.close()


def test_dense_self_retrieval(
    embedder: numpy_dense.SentenceEmbedder, built: indexer.BuildResult
) -> None:
    vectors = numpy_dense.load(built.build_dir / numpy_dense.FILE_NAME)
    chunks = prose_chunks(built)
    for _, text, row in chunks:
        query = embedder.encode([text])[0]
        assert numpy_dense.top_k(vectors, query, 1)[0][0] == row
    # With the query instruction, as the retriever embeds a question.
    for _, text, row in chunks[::5]:
        query = numpy_dense.embed_query(embedder, text)
        assert numpy_dense.top_k(vectors, query, 1)[0][0] == row


def test_incremental_add(
    embedder: numpy_dense.SentenceEmbedder,
    built: indexer.BuildResult,
    tmp_path: pathlib.Path,
) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(conftest.MINI_CORPUS, corpus)
    added = next(corpus.glob("NVDA_*.txt"))
    held = tmp_path / added.name
    added.rename(held)
    out = tmp_path / "index"
    first = build(embedder, out, corpus)
    assert first.manifest.counts.indexed == 2
    held.rename(added)
    result = build(embedder, out, corpus, incremental=True)
    info = result.manifest.build
    assert info.incremental
    assert info.embedded_filings == 1
    assert info.reused_filings == 2
    assert result.manifest.index_version == "1.1.0"
    assert indexer.current_build(out) == result.build_dir.resolve()
    # Same rows, IDs, hashes, and vectors as the full build.
    assert chunk_rows(result) == chunk_rows(built)
    assert result.manifest.chunks_sha256 == built.manifest.chunks_sha256
    assert result.manifest.files == built.manifest.files


def test_index_command(
    clean_env: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    del clean_env
    before = signal.getsignal(signal.SIGTERM)
    out = tmp_path / "ci"
    code = cli.main(
        ["index", "--corpus", str(conftest.MINI_CORPUS), "--out", str(out)]
    )
    assert code == 0
    assert signal.getsignal(signal.SIGTERM) == before
    pointer = out / indexer.CURRENT
    assert pointer.is_symlink()
    assert indexer.verify(pointer).counts.indexed == 3


def test_sentence_embedder(embedder: numpy_dense.SentenceEmbedder) -> None:
    assert embedder.dimensions == numpy_dense.DIMENSIONS
    assert embedder.encode([]).shape == (0, numpy_dense.DIMENSIONS)
    vectors = embedder.encode(["Net sales increased 12%.", "Risk factors."])
    assert vectors.dtype == numpy.float32
    assert vectors.shape == (2, numpy_dense.DIMENSIONS)
    assert numpy.allclose(numpy.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


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
