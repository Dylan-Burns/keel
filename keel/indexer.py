"""The index build: chunk store, FTS5, vectors, manifest (chapters 9, 7.12).

A build parses and chunks the corpus, embeds each filing into its own shard,
writes `chunks.sqlite` with the FTS5 index, concatenates the shards into
`vectors.npy`, and writes `manifest.json` with the checksums of both files.
Everything goes into a temporary directory under the index directory. Only a
complete build is renamed to `{index_dir}/{build_id}`, and then the
`current` symlink moves to it in 1 atomic rename. A failed build removes its
temporary directory and never touches `current`.

An incremental build (chapter 9.7) still parses and chunks every file,
because the fiscal year-end month and check CK-11 are corpus-wide, but it
copies the shard of a filing whose file hash, parser version, chunker
version, chunk hashes, and embedding model are unchanged, so only new or
changed filings reach the embedding model.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
import dataclasses
import datetime
import hashlib
import logging
import os
import pathlib
import re
import shutil
import sqlite3
import time

import pydantic

from keel import chunker
from keel import config
from keel import errors
from keel import inventory
from keel.parsers import base
from keel.parsers import corpus as parser_corpus
from keel.stores import chunk_store
from keel.stores import numpy_dense
from keel.stores import sqlite_fts

logger = logging.getLogger(__name__)

CURRENT = "current"
MANIFEST = "manifest.json"
FIRST_VERSION = "1.0.0"
COMPATIBLE_PROMPT_VERSIONS = ">=1.0.0,<2.0.0"
# Builds kept besides the new one: the previous build, for a rollback.
KEEP_PREVIOUS = 1
_BUILD_ID = re.compile(r"^\d{8}T\d{12}Z$")
_HASH_BLOCK = 1 << 20

EmbedderFactory = Callable[[], numpy_dense.Embedder]


class ModelRef(pydantic.BaseModel):
    """A pinned model in the manifest.

    Attributes:
        name: The Hugging Face repository id.
        revision: The pinned commit hash.
        dimensions: The vector width, for the embedding model.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    name: str
    revision: str
    dimensions: int | None = None


class Counts(pydantic.BaseModel):
    """The counts of a build (chapter 9.5).

    Attributes:
        files: The filings in the corpus directory.
        indexed: The filings with rows in the index.
        quarantined: The quarantined filings.
        chunks: The chunk rows, equal to the rows of `vectors.npy`.
        table_chunks: The table chunks.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    files: int
    indexed: int
    quarantined: int
    chunks: int
    table_chunks: int


class BuildInfo(pydantic.BaseModel):
    """How a build ran; not part of the reproducible content.

    Attributes:
        build_id: The directory name of the build.
        incremental: True when shards of the previous build were reused.
        previous_build: The build that `current` pointed at, or None.
        embedded_filings: The filings sent to the embedding model.
        reused_filings: The filings whose shard was copied.
        embedded_chunks: The chunks sent to the embedding model.
        seconds: The seconds per step and in total.
        chunks_per_second: The embedding throughput, or None.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    build_id: str
    incremental: bool
    previous_build: str | None
    embedded_filings: int
    reused_filings: int
    embedded_chunks: int
    seconds: dict[str, float]
    chunks_per_second: float | None


class Manifest(pydantic.BaseModel):
    """The index manifest of chapter 9.5.

    `files` holds the sha256 of `chunks.sqlite` and `vectors.npy`; the
    service refuses an index whose files do not match (chapter 16).
    `chunks_sha256` hashes the chunk IDs and chunk hashes, so it is equal on
    every machine even where the vector bits differ.

    Attributes:
        index_version: The semantic version of the index.
        built_at: The UTC build time.
        corpus_sha256: The sha256 of the sorted file hash list.
        chunks_sha256: The sha256 of the sorted chunk ID and hash lines.
        parser_version: The parser version.
        chunker_version: The chunker version.
        embedding_model: The pinned embedding model.
        reranker_model: The pinned reranker.
        counts: The counts.
        files: The sha256 of each index file, by file name.
        compatible_prompt_versions: The prompt versions this index serves.
        build: How the build ran.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    index_version: str
    built_at: str
    corpus_sha256: str
    chunks_sha256: str
    parser_version: str
    chunker_version: str
    embedding_model: ModelRef
    reranker_model: ModelRef
    counts: Counts
    files: dict[str, str]
    compatible_prompt_versions: str = COMPATIBLE_PROMPT_VERSIONS
    build: BuildInfo


@dataclasses.dataclass(frozen=True)
class BuildResult:
    """A published build.

    Attributes:
        build_dir: The build directory that `current` now points at.
        manifest: Its manifest.
    """

    build_dir: pathlib.Path
    manifest: Manifest


@dataclasses.dataclass(frozen=True)
class _Previous:
    build_dir: pathlib.Path
    manifest: Manifest
    states: dict[str, chunk_store.FilingState]


def file_sha256(path: pathlib.Path) -> str:
    """Hash 1 file.

    Args:
        path: The file.

    Returns:
        The hex sha256 of its bytes.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def corpus_sha256(file_hashes: Sequence[str]) -> str:
    """Hash the sorted list of file hashes (chapter 9.5).

    Args:
        file_hashes: The sha256 of each filing.

    Returns:
        The hex sha256 of the sorted hashes, 1 per line.
    """
    joined = "".join(f"{h}\n" for h in sorted(file_hashes))
    return hashlib.sha256(joined.encode("ascii")).hexdigest()


def chunks_sha256(chunks: Sequence[chunker.Chunk]) -> str:
    """Hash the chunk IDs and chunk hashes in chunk-ID order.

    Args:
        chunks: The chunks.

    Returns:
        The hex sha256 of the `{chunk_id} {chunk_hash}` lines.
    """
    lines = sorted(f"{c.chunk_id} {c.chunk_hash}\n" for c in chunks)
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def current_build(index_dir: pathlib.Path) -> pathlib.Path | None:
    """Return the build directory behind the `current` pointer.

    Args:
        index_dir: The index directory (`index.dir` or `--out`).

    Returns:
        The resolved build directory, or None when there is none.
    """
    pointer = index_dir / CURRENT
    if not pointer.exists():
        return None
    return pointer.resolve()


def load_manifest(build_dir: pathlib.Path) -> Manifest:
    """Read the manifest of 1 build.

    Args:
        build_dir: The build directory.

    Returns:
        The manifest.

    Raises:
        IndexMissingError: The build has no manifest.
        IndexCorruptError: The manifest is not valid.
    """
    path = build_dir / MANIFEST
    if not path.is_file():
        raise errors.IndexMissingError(f"no manifest at {path}")
    try:
        return Manifest.model_validate_json(path.read_bytes())
    except pydantic.ValidationError as error:
        raise errors.IndexCorruptError(
            f"{path} is not a valid manifest: {error.error_count()} errors"
        ) from error


def verify(build_dir: pathlib.Path) -> Manifest:
    """Check the sha256 of each index file against the manifest.

    Args:
        build_dir: The build directory.

    Returns:
        The manifest when every checksum matches.

    Raises:
        IndexMissingError: The manifest or an index file is absent.
        IndexCorruptError: A checksum does not match.
    """
    manifest = load_manifest(build_dir)
    for name, expected in sorted(manifest.files.items()):
        path = build_dir / name
        if not path.is_file():
            raise errors.IndexMissingError(f"no {name} in {build_dir}")
        if file_sha256(path) != expected:
            raise errors.IndexCorruptError(
                f"{name} in {build_dir} does not match its manifest checksum"
            )
    return manifest


def next_version(
    previous: Manifest | None,
    parser_version: str,
    chunker_version: str,
    filings_changed: bool,
) -> str:
    """Return the index version of a new build (chapter 9.5).

    Args:
        previous: The manifest of the current build, or None.
        parser_version: The parser version of the new build.
        chunker_version: The chunker version of the new build.
        filings_changed: True when the build adds or removes filings.

    Returns:
        `1.0.0` for a first build; else the major version up for a new
        parser or chunker version, the minor version up for added or removed
        filings, and the patch version up otherwise.
    """
    if previous is None:
        return FIRST_VERSION
    major, minor, patch = (int(p) for p in previous.index_version.split("."))
    if (
        previous.parser_version != parser_version
        or previous.chunker_version != chunker_version
    ):
        return f"{major + 1}.0.0"
    if filings_changed:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _new_build_id() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _load_previous(index_dir: pathlib.Path) -> _Previous | None:
    build_dir = current_build(index_dir)
    if build_dir is None:
        return None
    try:
        manifest = load_manifest(build_dir)
        conn = chunk_store.open_read_only(build_dir / chunk_store.FILE_NAME)
    except errors.KeelError as error:
        logger.warning("ignoring the current build: %s", error)
        return None
    try:
        states = chunk_store.filing_states(conn)
    finally:
        conn.close()
    return _Previous(build_dir=build_dir, manifest=manifest, states=states)


def _parse(
    settings: config.Settings, corpus_dir: pathlib.Path
) -> tuple[list[pathlib.Path], parser_corpus.CorpusParse]:
    files = sorted(corpus_dir.glob("*.txt"))
    if not files:
        raise errors.CorpusMissingError(f"no filings in {corpus_dir}")
    manifest_files = None
    try:
        manifest_files = inventory.load_manifest(
            corpus_dir / "manifest.json"
        ).files
    except errors.ManifestMissingError as error:
        logger.warning("%s", error)
    context = base.ParseContext.from_settings(settings, manifest_files)
    parsed = parser_corpus.finish_corpus(
        parser_corpus.parse_files(files, context), context
    )
    return files, parsed


def _can_reuse(
    previous: _Previous | None,
    settings: config.Settings,
    filing: base.ParsedFiling,
    chunks: Sequence[chunker.Chunk],
) -> pathlib.Path | None:
    """Return the previous shard of an unchanged filing, else None."""
    if previous is None or filing.filing_id is None:
        return None
    model = previous.manifest.embedding_model
    if (
        model.name != settings.embedding.model
        or model.revision != settings.embedding.revision
    ):
        return None
    state = previous.states.get(filing.filing_id)
    unchanged = state is not None and (
        state.file_sha256 == filing.metadata.file_sha256
        and state.parser_version == settings.parser.version
        and state.chunker_version == settings.chunker.version
        and state.chunk_hashes == tuple(c.chunk_hash for c in chunks)
    )
    shard = numpy_dense.shard_path(previous.build_dir, filing.filing_id)
    return shard if unchanged and shard.is_file() else None


@dataclasses.dataclass
class _EmbedProgress:
    """Mutable counters of the embedding step, local to 1 build."""

    total_filings: int
    total_chunks: int
    done_filings: int = 0
    done_chunks: int = 0
    embedded_filings: int = 0
    embedded_chunks: int = 0
    embed_seconds: float = 0.0


def _write_shards(
    build_dir: pathlib.Path,
    work: Sequence[tuple[base.ParsedFiling, list[chunker.Chunk]]],
    previous: _Previous | None,
    settings: config.Settings,
    embedder_factory: EmbedderFactory,
) -> _EmbedProgress:
    progress = _EmbedProgress(
        total_filings=len(work), total_chunks=sum(len(c) for _, c in work)
    )
    embedder: numpy_dense.Embedder | None = None
    for filing, chunks in work:
        filing_id = filing.filing_id or ""
        target = numpy_dense.shard_path(build_dir, filing_id)
        reused = _can_reuse(previous, settings, filing, chunks)
        if reused is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reused, target)
        else:
            if embedder is None:
                embedder = embedder_factory()
            started = time.perf_counter()
            vectors = embedder.encode([c.text for c in chunks])
            progress.embed_seconds += time.perf_counter() - started
            numpy_dense.write_shard(target, vectors)
            progress.embedded_filings += 1
            progress.embedded_chunks += len(chunks)
        progress.done_filings += 1
        progress.done_chunks += len(chunks)
        rate = (
            progress.embedded_chunks / progress.embed_seconds
            if progress.embed_seconds
            else 0.0
        )
        logger.info(
            "shard %d/%d %s: %d chunks, %s; %d/%d chunks done, %.1f chunks/s",
            progress.done_filings,
            progress.total_filings,
            filing_id,
            len(chunks),
            "reused" if reused is not None else "embedded",
            progress.done_chunks,
            progress.total_chunks,
            rate,
        )
    return progress


def _write_store(
    path: pathlib.Path,
    parsed: parser_corpus.CorpusParse,
    chunks: Sequence[chunker.Chunk],
    chunker_version: str,
) -> None:
    conn = chunk_store.create(path)
    try:
        chunk_store.write_filings(conn, parsed.filings, chunker_version)
        chunk_store.write_quarantine(
            conn, [f.quarantine for f in parsed.filings if f.quarantine]
        )
        chunk_store.write_chunks(conn, chunks)
        sqlite_fts.create(conn)
        sqlite_fts.rebuild(conn)
        conn.commit()
    except sqlite3.Error as error:
        raise errors.IndexWriteError(f"cannot write {path}: {error}") from error
    finally:
        conn.close()


def _publish(index_dir: pathlib.Path, staging: pathlib.Path) -> pathlib.Path:
    """Rename the staging build and swap the `current` symlink atomically."""
    build_id = staging.name.removeprefix(".tmp-")
    pointer = index_dir / CURRENT
    if pointer.exists() and not pointer.is_symlink():
        raise errors.IndexWriteError(
            f"{pointer} is not a symlink; move it away to publish a build"
        )
    final = index_dir / build_id
    link = index_dir / f".current-{build_id}"
    try:
        staging.rename(final)
        link.symlink_to(build_id, target_is_directory=True)
        os.replace(link, pointer)
    except OSError as error:
        raise errors.IndexWriteError(
            f"cannot publish {final}: {error}"
        ) from error
    return final


def _prune(index_dir: pathlib.Path, keep: Sequence[pathlib.Path]) -> None:
    """Delete old build directories, keeping the given ones."""
    kept = {p.resolve() for p in keep}
    builds = sorted(
        (p for p in index_dir.iterdir() if _BUILD_ID.match(p.name)),
        reverse=True,
    )
    for path in builds:
        if path.resolve() in kept or not path.is_dir() or path.is_symlink():
            continue
        logger.info("removing old build %s", path)
        shutil.rmtree(path, ignore_errors=True)


def _chunk_all(
    settings: config.Settings,
    parsed: parser_corpus.CorpusParse,
) -> list[tuple[base.ParsedFiling, list[chunker.Chunk]]]:
    counter = chunker.HFTokenCounter.from_settings(settings)
    sizes = chunker.ChunkSizes.from_settings(settings)
    by_id = {
        f.filing_id: f
        for f in parsed.filings
        if not f.quarantined and f.filing_id is not None
    }
    results = chunker.chunk_filings(by_id.values(), counter, sizes)
    return sorted(
        (
            (by_id[r.filing_id], sorted(r.chunks, key=lambda c: c.chunk_id))
            for r in results
        ),
        key=lambda pair: pair[0].filing_id or "",
    )


def build_index(  # pylint: disable=too-many-locals
    settings: config.Settings,
    corpus_dir: pathlib.Path,
    index_dir: pathlib.Path,
    embedder_factory: EmbedderFactory,
    *,
    incremental: bool = False,
) -> BuildResult:
    """Build an index from a corpus directory and publish it as `current`.

    Args:
        settings: The loaded settings.
        corpus_dir: The directory with the `*.txt` filings.
        index_dir: The index directory that holds the builds and `current`.
        embedder_factory: Loads the embedder; called only when a filing
            needs embedding.
        incremental: Reuse the shards of unchanged filings from `current`.

    Returns:
        The published build.

    Raises:
        CorpusMissingError: The corpus directory holds no filings.
        ModelMissingError: The tokenizer is not in the local cache.
        EmbeddingModelUnavailableError: The embedding model cannot load.
        IndexWriteError: A file cannot be written or published.
    """
    seconds: dict[str, float] = {}
    started = time.perf_counter()
    index_dir.mkdir(parents=True, exist_ok=True)
    previous = _load_previous(index_dir)
    if incremental and previous is None:
        logger.info("no current build in %s: building in full", index_dir)
    build_id = _new_build_id()
    staging = index_dir / f".tmp-{build_id}"
    staging.mkdir()
    logger.info("building %s from %s", staging, corpus_dir)
    try:
        step = time.perf_counter()
        files, parsed = _parse(settings, corpus_dir)
        seconds["parse"] = time.perf_counter() - step
        logger.info("parsed %d files in %.1f s", len(files), seconds["parse"])
        step = time.perf_counter()
        work = _chunk_all(settings, parsed)
        chunks = [c for _, filing_chunks in work for c in filing_chunks]
        seconds["chunk"] = time.perf_counter() - step
        logger.info(
            "chunked %d filings into %d chunks in %.1f s",
            len(work),
            len(chunks),
            seconds["chunk"],
        )
        step = time.perf_counter()
        progress = _write_shards(
            staging,
            work,
            previous if incremental else None,
            settings,
            embedder_factory,
        )
        seconds["embed"] = time.perf_counter() - step
        step = time.perf_counter()
        _write_store(
            staging / chunk_store.FILE_NAME,
            parsed,
            chunks,
            settings.chunker.version,
        )
        seconds["sqlite"] = time.perf_counter() - step
        step = time.perf_counter()
        rows = numpy_dense.concatenate(
            [
                numpy_dense.shard_path(staging, f.filing_id or "")
                for f, _ in work
            ],
            staging / numpy_dense.FILE_NAME,
        )
        if rows != len(chunks):
            raise errors.IndexWriteError(
                f"vectors.npy has {rows} rows for {len(chunks)} chunks"
            )
        seconds["vectors"] = time.perf_counter() - step
        filing_ids = {f.filing_id for f, _ in work}
        seconds["total"] = time.perf_counter() - started
        manifest = Manifest(
            index_version=next_version(
                previous.manifest if previous else None,
                settings.parser.version,
                settings.chunker.version,
                previous is not None and filing_ids != set(previous.states),
            ),
            built_at=datetime.datetime.now(datetime.UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            corpus_sha256=corpus_sha256(
                [f.metadata.file_sha256 for f in parsed.filings]
            ),
            chunks_sha256=chunks_sha256(chunks),
            parser_version=settings.parser.version,
            chunker_version=settings.chunker.version,
            embedding_model=ModelRef(
                name=settings.embedding.model,
                revision=settings.embedding.revision,
                dimensions=numpy_dense.DIMENSIONS,
            ),
            reranker_model=ModelRef(
                name=settings.reranker.model,
                revision=settings.reranker.revision,
            ),
            counts=Counts(
                files=len(files),
                indexed=len(work),
                quarantined=sum(1 for f in parsed.filings if f.quarantined),
                chunks=len(chunks),
                table_chunks=sum(1 for c in chunks if c.is_table),
            ),
            files={
                name: file_sha256(staging / name)
                for name in (chunk_store.FILE_NAME, numpy_dense.FILE_NAME)
            },
            build=BuildInfo(
                build_id=build_id,
                incremental=incremental and previous is not None,
                previous_build=previous.build_dir.name if previous else None,
                embedded_filings=progress.embedded_filings,
                reused_filings=len(work) - progress.embedded_filings,
                embedded_chunks=progress.embedded_chunks,
                seconds={k: round(v, 1) for k, v in seconds.items()},
                chunks_per_second=(
                    round(progress.embedded_chunks / progress.embed_seconds, 1)
                    if progress.embed_seconds
                    else None
                ),
            ),
        )
        (staging / MANIFEST).write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        final = _publish(index_dir, staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    keep = [final] + ([previous.build_dir] if previous else [])
    _prune(index_dir, keep[: KEEP_PREVIOUS + 1])
    logger.info(
        "published %s as %s: %d chunks in %.1f s",
        final,
        index_dir / CURRENT,
        len(chunks),
        seconds["total"],
    )
    return BuildResult(build_dir=final, manifest=manifest)
