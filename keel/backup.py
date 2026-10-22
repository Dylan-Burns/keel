"""The nightly backup and the restore (chapters 27.2, 29.6, 29.9).

The Python twin of `infra/backup.sh`, for the in-app scheduler on Railway.
A backup writes `keel-<stamp>.tar.gz` and `keel-<stamp>.tar.gz.sha256` (the
`sha256sum -c` format) into `scheduler.backup_dir`. The archive is flat:

    manifest.json    the index manifest of chapter 9.5
    chunks.sqlite    the chunk store with FTS5
    vectors.npy      the dense vectors
    audit.jsonl      the audit log, when it exists
    <name>.sqlite    any SQLite file in the logs directory (the feedback
                     table of chapter 27), as an online-backup snapshot

A published build never changes, so its 2 index files are copied and each
copy must match the sha256 in the manifest: that proves a consistent copy,
and the restored build passes the checksum check of chapter 16. The SQLite
online backup API would rewrite 2 header counters (bytes 27 and 95) and
break that checksum, so it serves only the SQLite files that change while
the app runs.

The restore follows `infra/README.md`: check the sha256 file, extract into
`<index dir>/restore`, check the manifest checksums, then publish the
restored build as `current` and point `previous` at the old build. It also
rebuilds the per-filing vector shards from `vectors.npy`, so the next
incremental build reuses them instead of embedding the whole corpus.

The upload to an S3-compatible bucket sits behind the `Uploader` protocol.
`S3Uploader` refuses with `BackupUploadError`: the bucket endpoint is not on
the S-11 allow list yet, and no dependency signs the requests (decision log
D-38 and the stage 21 build report).
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import os
import pathlib
import re
import shutil
import sqlite3
import tarfile
import tempfile
from typing import Protocol

from keel import config
from keel import errors
from keel import indexer
from keel.stores import chunk_store
from keel.stores import numpy_dense

logger = logging.getLogger(__name__)

STAMP_FORMAT = "%Y-%m-%dT%H%M%SZ"
ARCHIVE_PREFIX = "keel-"
ARCHIVE_SUFFIX = ".tar.gz"
CHECKSUM_SUFFIX = ".sha256"
AUDIT_LOG = "audit.jsonl"
RESTORE_DIR = "restore"
PREVIOUS = "previous"
INDEX_FILES = (chunk_store.FILE_NAME, numpy_dense.FILE_NAME)
REQUIRED_MEMBERS = (indexer.MANIFEST, *INDEX_FILES)
_MEMBER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_ARCHIVE_NAME = re.compile(r"^keel-\d{4}-\d{2}-\d{2}T\d{6}Z\.tar\.gz$")
# The largest member accepted on restore; the full index is about 270 MB.
MAX_MEMBER_BYTES = 4 * 1024**3


@dataclasses.dataclass(frozen=True)
class Backup:
    """A written backup.

    Attributes:
        archive: The `keel-<stamp>.tar.gz` file.
        checksum_file: The `.sha256` file beside it.
        sha256: The hex sha256 of the archive.
        stamp: The UTC stamp in the file names.
        members: The archive member names, in archive order.
    """

    archive: pathlib.Path
    checksum_file: pathlib.Path
    sha256: str
    stamp: str
    members: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Restore:
    """A restored build.

    Attributes:
        build_dir: The restored build that `current` now points at.
        previous: The build that `previous` now points at, or None.
        manifest: The manifest of the restored build.
        extra_dir: Where the restored logs went (audit log, feedback), or
            None when the archive held none.
    """

    build_dir: pathlib.Path
    previous: pathlib.Path | None
    manifest: indexer.Manifest
    extra_dir: pathlib.Path | None


class Uploader(Protocol):
    """Puts a file into the backup bucket."""

    def upload(self, path: pathlib.Path, key: str) -> None:
        """Upload 1 file.

        Args:
            path: The local file.
            key: The object key, `keel/<stamp>/<file name>`.
        """


@dataclasses.dataclass(frozen=True)
class S3Uploader:
    """The S3-compatible upload of `scheduler.backup_bucket`, not built.

    Attributes:
        bucket: The bucket name.
    """

    bucket: str

    def upload(self, path: pathlib.Path, key: str) -> None:
        """Refuse the upload; the archive stays in the local directory.

        Args:
            path: The local file.
            key: The object key.

        Raises:
            BackupUploadError: Always. The bucket endpoint host needs a
                decision on the S-11 allow list, and the request signing
                needs either a new dependency or a SigV4 signer on httpx.
        """
        raise errors.BackupUploadError(
            f"the S3 upload of {path.name} to {self.bucket}/{key} is not "
            "available in this release; the archive stays local"
        )


def snapshot_sqlite(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Write a consistent copy of a live SQLite file (online backup API).

    Args:
        source: The database file.
        destination: The copy to write.

    Raises:
        BackupError: SQLite cannot read the source or write the copy.
    """
    try:
        src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except sqlite3.Error as error:
        raise errors.BackupError(
            f"cannot snapshot {source.name}: {error}"
        ) from error


def _copy_verified(
    source: pathlib.Path, destination: pathlib.Path, sha: str
) -> None:
    """Copy an immutable index file and check the copy against its hash."""
    shutil.copyfile(source, destination)
    if indexer.file_sha256(destination) != sha:
        raise errors.IndexCorruptError(
            f"{source} does not match its manifest checksum; not backed up"
        )


def _stage(
    build_dir: pathlib.Path, logs_dir: pathlib.Path, work: pathlib.Path
) -> list[str]:
    """Copy the files of 1 backup into the work directory."""
    manifest = indexer.load_manifest(build_dir)
    for name in INDEX_FILES:
        if name not in manifest.files:
            raise errors.IndexCorruptError(f"the manifest lists no {name}")
        _copy_verified(build_dir / name, work / name, manifest.files[name])
    shutil.copyfile(build_dir / indexer.MANIFEST, work / indexer.MANIFEST)
    members = list(REQUIRED_MEMBERS)
    audit = logs_dir / AUDIT_LOG
    if audit.is_file():
        # The audit log only grows, so a copy is a consistent prefix.
        shutil.copyfile(audit, work / AUDIT_LOG)
        members.append(AUDIT_LOG)
    if logs_dir.is_dir():
        for database in sorted(logs_dir.glob("*.sqlite")):
            if _MEMBER_NAME.match(database.name):
                snapshot_sqlite(database, work / database.name)
                members.append(database.name)
    return members


def create_backup(
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
    out_dir: pathlib.Path,
    *,
    now: datetime.datetime | None = None,
) -> Backup:
    """Write the checksummed archive of the current build and the logs.

    Args:
        index_dir: The index directory with the `current` pointer.
        logs_dir: The logs directory with `audit.jsonl`.
        out_dir: The directory that receives the archive.
        now: The time of the stamp; None takes the UTC clock.

    Returns:
        The written backup.

    Raises:
        IndexMissingError: No build sits behind `current`, or it has no
            manifest.
        IndexCorruptError: An index file does not match the manifest.
        BackupError: A file cannot be read or written.
    """
    build_dir = indexer.current_build(index_dir)
    if build_dir is None:
        raise errors.IndexMissingError(f"no current build in {index_dir}")
    moment = now or datetime.datetime.now(datetime.UTC)
    stamp = moment.strftime(STAMP_FORMAT)
    archive = out_dir / f"{ARCHIVE_PREFIX}{stamp}{ARCHIVE_SUFFIX}"
    checksum_file = archive.with_name(archive.name + CHECKSUM_SUFFIX)
    part = archive.with_name(archive.name + ".part")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        work = pathlib.Path(tempfile.mkdtemp(prefix=".backup-", dir=out_dir))
        try:
            members = _stage(build_dir, logs_dir, work)
            with tarfile.open(part, "w:gz") as tar:
                for name in members:
                    tar.add(work / name, arcname=name, recursive=False)
            os.replace(part, archive)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            part.unlink(missing_ok=True)
        digest = indexer.file_sha256(archive)
        checksum_file.write_text(
            f"{digest}  {archive.name}\n", encoding="utf-8"
        )
    except OSError as error:
        raise errors.BackupError(f"cannot write {archive}: {error}") from error
    logger.info(
        "backup %s: %s (%d members), sha256 %s",
        stamp,
        archive,
        len(members),
        digest,
    )
    return Backup(
        archive=archive,
        checksum_file=checksum_file,
        sha256=digest,
        stamp=stamp,
        members=tuple(members),
    )


def verify_archive(archive: pathlib.Path) -> str:
    """Check an archive against its `.sha256` file, like `sha256sum -c`.

    Args:
        archive: The `keel-<stamp>.tar.gz` file.

    Returns:
        The hex sha256 of the archive.

    Raises:
        BackupChecksumError: The sha256 file is absent, malformed, names
            another file, or holds another hash.
    """
    checksum_file = archive.with_name(archive.name + CHECKSUM_SUFFIX)
    try:
        line = checksum_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise errors.BackupChecksumError(
            f"cannot read {checksum_file.name}: {error}"
        ) from error
    expected, _, name = line.partition("  ")
    if name != archive.name or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise errors.BackupChecksumError(
            f"{checksum_file.name} is not a sha256 line for {archive.name}"
        )
    try:
        actual = indexer.file_sha256(archive)
    except OSError as error:
        raise errors.BackupChecksumError(
            f"cannot read {archive.name}: {error}"
        ) from error
    if actual != expected:
        raise errors.BackupChecksumError(
            f"{archive.name} does not match its sha256 file"
        )
    return actual


def _extract(archive: pathlib.Path, target: pathlib.Path) -> list[str]:
    """Extract the flat regular-file members of an archive after checks."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                if not member.isfile() or not _MEMBER_NAME.match(member.name):
                    raise errors.BackupError(
                        f"unexpected archive member {member.name!r}"
                    )
                if member.size > MAX_MEMBER_BYTES:
                    raise errors.BackupError(
                        f"archive member {member.name} is too large"
                    )
            names = [member.name for member in members]
            if len(set(names)) != len(names):
                raise errors.BackupError("duplicate archive members")
            target.mkdir(parents=True)
            tar.extractall(target, members=members, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise errors.BackupError(
            f"cannot extract {archive.name}: {error}"
        ) from error
    missing = [name for name in REQUIRED_MEMBERS if name not in names]
    if missing:
        listed = ", ".join(missing)
        raise errors.BackupError(f"{archive.name} lacks {listed}")
    return names


def rebuild_shards(build_dir: pathlib.Path) -> int:
    """Split `vectors.npy` into the per-filing shards of an index build.

    The chunks of a filing hold consecutive vector rows in filing-ID order
    (chapter 9.4), so the shards are slices of `vectors.npy`.

    Args:
        build_dir: The build directory with `chunks.sqlite`, `vectors.npy`.

    Returns:
        The number of shards written.

    Raises:
        IndexCorruptError: The rows of a filing are not consecutive, or the
            row counts do not add up to `vectors.npy`.
    """
    conn = chunk_store.open_read_only(build_dir / chunk_store.FILE_NAME)
    try:
        rows = conn.execute(
            "SELECT filing_id, COUNT(*), MIN(vector_row), MAX(vector_row) "
            "FROM chunks GROUP BY filing_id ORDER BY filing_id"
        ).fetchall()
    finally:
        conn.close()
    vectors = numpy_dense.load(build_dir / numpy_dense.FILE_NAME)
    offset = 0
    for filing_id, count, first, last in rows:
        if first != offset or last != offset + count - 1:
            raise errors.IndexCorruptError(
                f"the vector rows of {filing_id} are not consecutive"
            )
        numpy_dense.write_shard(
            numpy_dense.shard_path(build_dir, filing_id),
            vectors[offset : offset + count],
        )
        offset += count
    if offset != vectors.shape[0]:
        raise errors.IndexCorruptError(
            f"{offset} chunk rows for {vectors.shape[0]} vectors"
        )
    return len(rows)


def _swap_link(index_dir: pathlib.Path, name: str, target: str) -> None:
    """Point a symlink in the index directory at a build, atomically."""
    pointer = index_dir / name
    if pointer.exists() and not pointer.is_symlink():
        raise errors.IndexWriteError(f"{pointer} is not a symlink")
    temporary = index_dir / f".{name}-{target}"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, pointer)


def restore_backup(
    archive: pathlib.Path,
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
) -> Restore:
    """Restore an archive as the current build (infra/README.md).

    Stop the app first, or restart it after: a running server keeps the
    build it loaded.

    Args:
        archive: The `keel-<stamp>.tar.gz` file with its `.sha256` beside it.
        index_dir: The index directory with the `current` pointer.
        logs_dir: The logs directory; the restored audit log and SQLite
            files go to `restored-<stamp>` under it, never over the live log.

    Returns:
        The restored build.

    Raises:
        BackupChecksumError: The archive fails its sha256 check.
        BackupError: The archive holds an unexpected or missing member.
        IndexCorruptError: An index file fails its manifest checksum.
        IndexWriteError: The pointers cannot be swapped.
    """
    verify_archive(archive)
    if not _ARCHIVE_NAME.match(archive.name):
        raise errors.BackupError(f"{archive.name} is not a Keel archive name")
    stamp = archive.name.removeprefix(ARCHIVE_PREFIX).removesuffix(
        ARCHIVE_SUFFIX
    )
    index_dir.mkdir(parents=True, exist_ok=True)
    staging = index_dir / RESTORE_DIR
    shutil.rmtree(staging, ignore_errors=True)
    try:
        names = _extract(archive, staging)
        manifest = indexer.verify(staging)
        shards = rebuild_shards(staging)
        extras = [n for n in names if n not in REQUIRED_MEMBERS]
        extra_dir = logs_dir / f"restored-{stamp}" if extras else None
        if extra_dir is not None:
            extra_dir.mkdir(parents=True, exist_ok=True)
            for name in extras:
                os.replace(staging / name, extra_dir / name)
        old = indexer.current_build(index_dir)
        final = index_dir / indexer.new_build_id()
        staging.rename(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    try:
        if old is not None:
            _swap_link(index_dir, PREVIOUS, old.name)
        _swap_link(index_dir, indexer.CURRENT, final.name)
    except OSError as error:
        raise errors.IndexWriteError(
            f"cannot point current at {final}: {error}"
        ) from error
    logger.info(
        "restored %s as %s (index %s, %d shards); previous: %s",
        archive.name,
        final,
        manifest.index_version,
        shards,
        old,
    )
    return Restore(
        build_dir=final, previous=old, manifest=manifest, extra_dir=extra_dir
    )


def prune_backups(out_dir: pathlib.Path, keep: int) -> list[pathlib.Path]:
    """Remove the oldest local archives beyond the newest `keep`.

    Args:
        out_dir: The backup directory.
        keep: The archives to keep.

    Returns:
        The archives removed.
    """
    archives = sorted(
        (
            p
            for p in out_dir.glob("keel-*.tar.gz")
            if _ARCHIVE_NAME.match(p.name)
        ),
        reverse=True,
    )
    removed = archives[keep:]
    for path in removed:
        path.unlink(missing_ok=True)
        path.with_name(path.name + CHECKSUM_SUFFIX).unlink(missing_ok=True)
        logger.info("removed old backup %s", path.name)
    return removed


def run_nightly_backup(
    settings: config.Settings, uploader: Uploader | None = None
) -> Backup:
    """Run the scheduled backup: archive, prune, and upload when configured.

    Args:
        settings: The loaded settings.
        uploader: The bucket upload; None uses `S3Uploader` when
            `scheduler.backup_bucket` is set.

    Returns:
        The written backup.

    Raises:
        IndexMissingError: No current build.
        IndexCorruptError: An index file does not match the manifest.
        BackupError: The archive cannot be written.
        BackupUploadError: The upload fails; the local archive stays.
    """
    out_dir = settings.scheduler.backup_dir
    backup = create_backup(settings.index.dir, settings.logs.dir, out_dir)
    prune_backups(out_dir, settings.scheduler.backup_keep)
    bucket = settings.scheduler.backup_bucket
    if bucket:
        target = uploader or S3Uploader(bucket)
        for path in (backup.archive, backup.checksum_file):
            target.upload(path, f"keel/{backup.stamp}/{path.name}")
    return backup
