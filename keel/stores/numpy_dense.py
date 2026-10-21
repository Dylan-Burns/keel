"""The dense index: float32 unit vectors in 1 NumPy file (chapter 9.4).

The build embeds each filing on its own and writes 1 shard per filing,
`vectors/{filing_id}.npy`, with the rows in chunk-ID order. It then
concatenates the shards in filing-ID order into `vectors.npy`, so row `i`
holds the vector of the chunk whose `vector_row` is `i` (the chunk-ID rank).
Embedding 1 filing per call makes the vectors of a filing independent of the
other filings in the build, so a full and an incremental build give the
same bytes on 1 machine.

Passages get no prefix; a question gets the bge query instruction. The
vectors are normalized, so the dot product is the cosine (docs/GOTCHAS.md).
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import logging
import pathlib
from typing import Any
from typing import Protocol

import numpy
import numpy.typing

from keel import config
from keel import errors

logger = logging.getLogger(__name__)

FILE_NAME = "vectors.npy"
SHARD_DIR = "vectors"
DIMENSIONS = 384
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

Vectors = numpy.typing.NDArray[numpy.float32]


class Embedder(Protocol):
    """Turns texts into float32 unit vectors."""

    @property
    def dimensions(self) -> int:
        """The vector width."""

    def encode(self, texts: Sequence[str]) -> Vectors:
        """Embed texts as they are, 1 row per text.

        Args:
            texts: The texts.

        Returns:
            A float32 array of shape (len(texts), dimensions) of unit rows.
        """


@dataclasses.dataclass(frozen=True)
class SentenceEmbedder:
    """The pinned sentence-transformers model on the CPU.

    Attributes:
        model: The loaded `SentenceTransformer`.
        batch_size: The encode batch size from `embedding.batch_size`.
        dimensions: The vector width of the model.
    """

    model: Any
    batch_size: int
    dimensions: int

    @classmethod
    def from_settings(cls, settings: config.Settings) -> SentenceEmbedder:
        """Load the pinned model (`embedding.model` at `embedding.revision`).

        Uses only `SentenceTransformer(name, revision=..., device=...)`,
        which sentence-transformers 3.4 and 6 share (decision D-37).

        Args:
            settings: The loaded settings.

        Returns:
            The embedder.

        Raises:
            EmbeddingModelUnavailableError: The model cannot load, for
                example because it is not in the local cache offline.
        """
        # Heavy (torch), so imported only when an index is built or read.
        import sentence_transformers  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

        embedding = settings.embedding
        try:
            model = sentence_transformers.SentenceTransformer(
                embedding.model, revision=embedding.revision, device="cpu"
            )
        # The hub client and torch raise unrelated error types.
        except Exception as error:  # pylint: disable=broad-exception-caught
            raise errors.EmbeddingModelUnavailableError(
                f"cannot load {embedding.model} at {embedding.revision}: "
                f"{error}; run keel doctor --download-models"
            ) from error
        dimensions = model.get_sentence_embedding_dimension()
        if dimensions is None:
            raise errors.EmbeddingModelUnavailableError(
                f"{embedding.model} reports no embedding dimension"
            )
        return cls(
            model=model,
            batch_size=embedding.batch_size,
            dimensions=int(dimensions),
        )

    def encode(self, texts: Sequence[str]) -> Vectors:
        """Embed texts as they are, normalized, as float32.

        Args:
            texts: The texts.

        Returns:
            A float32 array of shape (len(texts), dimensions).
        """
        if not texts:
            return numpy.zeros((0, self.dimensions), dtype=numpy.float32)
        encoded = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return numpy.asarray(encoded, dtype=numpy.float32)


def embed_query(embedder: Embedder, question: str) -> Vectors:
    """Embed 1 question with the bge query instruction (chapter 9.4).

    Args:
        embedder: The embedder.
        question: The dense query text.

    Returns:
        A float32 vector of shape (dimensions,).
    """
    vectors = embedder.encode([QUERY_PREFIX + question])
    return numpy.asarray(vectors[0], dtype=numpy.float32)


def shard_path(build_dir: pathlib.Path, filing_id: str) -> pathlib.Path:
    """Return the shard file of 1 filing.

    Args:
        build_dir: The index build directory.
        filing_id: The filing ID.

    Returns:
        `{build_dir}/vectors/{filing_id}.npy`.
    """
    return build_dir / SHARD_DIR / f"{filing_id}.npy"


def write_shard(path: pathlib.Path, vectors: Vectors) -> None:
    """Write 1 shard as float32.

    Args:
        path: The shard file.
        vectors: The rows of the filing in chunk-ID order.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    numpy.save(path, numpy.asarray(vectors, dtype=numpy.float32))


def read_shard(path: pathlib.Path, dimensions: int = DIMENSIONS) -> Vectors:
    """Read 1 shard and check its shape.

    Args:
        path: The shard file.
        dimensions: The expected vector width.

    Returns:
        The float32 rows.

    Raises:
        IndexCorruptError: The shard is not a float32 matrix of that width.
    """
    vectors = numpy.load(path)
    if (
        vectors.dtype != numpy.float32
        or vectors.ndim != 2
        or vectors.shape[1] != dimensions
    ):
        raise errors.IndexCorruptError(
            f"{path}: {vectors.dtype} {vectors.shape}, "
            f"expected float32 (n, {dimensions})"
        )
    return numpy.asarray(vectors, dtype=numpy.float32)


def concatenate(
    shards: Sequence[pathlib.Path],
    out_path: pathlib.Path,
    dimensions: int = DIMENSIONS,
) -> int:
    """Concatenate shards, in the given order, into `vectors.npy`.

    Args:
        shards: The shard files in filing-ID order.
        out_path: The `vectors.npy` file to write.
        dimensions: The vector width.

    Returns:
        The number of rows written.
    """
    parts = [read_shard(path, dimensions) for path in shards]
    matrix = (
        numpy.concatenate(parts, axis=0)
        if parts
        else numpy.zeros((0, dimensions), dtype=numpy.float32)
    )
    numpy.save(out_path, matrix)
    return int(matrix.shape[0])


def load(path: pathlib.Path) -> Vectors:
    """Map `vectors.npy` read-only.

    Args:
        path: The vectors file.

    Returns:
        The memory-mapped float32 matrix.

    Raises:
        IndexMissingError: The file does not exist.
    """
    if not path.is_file():
        raise errors.IndexMissingError(f"no vectors at {path}")
    vectors: Vectors = numpy.load(path, mmap_mode="r")
    return vectors


def top_k(
    vectors: Vectors,
    query: Vectors,
    k: int,
    rows: Sequence[int] | None = None,
) -> list[tuple[int, float]]:
    """Score rows by dot product with the query and keep the best `k`.

    Args:
        vectors: The dense matrix.
        query: The unit query vector.
        k: The number of results.
        rows: The candidate rows from the metadata filter, or None for all.

    Returns:
        (row, score) pairs, best first; ties break on the lower row.
    """
    candidates = (
        numpy.arange(vectors.shape[0])
        if rows is None
        else numpy.asarray(rows, dtype=numpy.int64)
    )
    if k <= 0 or candidates.size == 0:
        return []
    scores = vectors[candidates] @ query
    order = numpy.lexsort((candidates, -scores))[:k]
    return [(int(candidates[i]), float(scores[i])) for i in order]
