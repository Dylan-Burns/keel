"""Safe zip extraction for the corpus (control S-10, chapter 15).

The extractor checks every entry before it writes a byte: no absolute path,
no `..` component, no symbolic link, and a target path inside the target
directory. It rejects a zip with more than 10,000 entries or more than 2 GB
uncompressed. It writes into a temporary directory next to the target and
renames that directory into place, so a failed extraction leaves no partial
corpus behind.
"""

import dataclasses
import logging
import pathlib
import shutil
import stat
import tempfile
import zipfile

from keel import errors

logger = logging.getLogger(__name__)

MAX_ENTRIES = 10_000
MAX_TOTAL_BYTES = 2 * 1024**3
_COPY_CHUNK_BYTES = 1024 * 1024


@dataclasses.dataclass(frozen=True)
class ExtractResult:
    """The outcome of 1 extraction.

    Attributes:
        target: The directory that holds the extracted files.
        file_count: The number of files written.
        total_bytes: The number of bytes written.
    """

    target: pathlib.Path
    file_count: int
    total_bytes: int


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def check_entry(info: zipfile.ZipInfo, target: pathlib.Path) -> pathlib.Path:
    """Check 1 zip entry and return its resolved destination.

    Args:
        info: The zip entry.
        target: The absolute, resolved target directory.

    Returns:
        The absolute destination path of the entry inside the target.

    Raises:
        UnsafePathError: The entry is absolute, has a `..` component, is a
            symbolic link, or resolves outside the target directory.
    """
    name = info.filename
    parts = name.replace("\\", "/").split("/")
    if name.startswith(("/", "\\")) or (len(name) > 1 and name[1] == ":"):
        raise errors.UnsafePathError(f"absolute path in zip entry: {name}")
    if ".." in parts:
        raise errors.UnsafePathError(f"'..' in zip entry: {name}")
    if _is_symlink(info):
        raise errors.UnsafePathError(f"symbolic link in zip entry: {name}")
    destination = (target / name).resolve()
    if not destination.is_relative_to(target):
        raise errors.UnsafePathError(f"zip entry leaves the target: {name}")
    return destination


def check_archive(
    archive: zipfile.ZipFile,
    target: pathlib.Path,
    max_entries: int = MAX_ENTRIES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> list[tuple[zipfile.ZipInfo, pathlib.Path]]:
    """Check every entry of an archive before any write.

    Args:
        archive: The open zip archive.
        target: The absolute, resolved directory the entries land in.
        max_entries: The largest number of entries accepted.
        max_total_bytes: The largest declared uncompressed size accepted.

    Returns:
        The entries with their destination paths, in archive order.

    Raises:
        BadZipError: The archive exceeds the entry or size limit.
        UnsafePathError: An entry fails the path checks.
    """
    entries = archive.infolist()
    if len(entries) > max_entries:
        raise errors.BadZipError(
            f"zip has {len(entries)} entries, the limit is {max_entries}"
        )
    declared = sum(info.file_size for info in entries)
    if declared > max_total_bytes:
        raise errors.BadZipError(
            f"zip expands to {declared} bytes, the limit is {max_total_bytes}"
        )
    return [(info, check_entry(info, target)) for info in entries]


def _copy_entry(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: pathlib.Path,
    budget: int,
) -> int:
    """Copy 1 entry and stop when it writes more than the byte budget."""
    written = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, destination.open("wb") as sink:
        while chunk := source.read(_COPY_CHUNK_BYTES):
            written += len(chunk)
            if written > budget:
                raise errors.BadZipError(
                    f"zip entry {info.filename} expands past the size limit"
                )
            sink.write(chunk)
    return written


def extract_zip(
    zip_path: pathlib.Path,
    target: pathlib.Path,
    max_entries: int = MAX_ENTRIES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> ExtractResult:
    """Extract a zip archive into a directory that does not hold files yet.

    Args:
        zip_path: The zip archive.
        target: The directory to create. An empty directory is replaced.
        max_entries: The largest number of entries accepted.
        max_total_bytes: The largest uncompressed size accepted.

    Returns:
        The target, the file count, and the bytes written.

    Raises:
        BadZipError: The archive is corrupt or exceeds a limit.
        UnsafePathError: An entry fails the path checks. Nothing is written.
        ExtractTargetError: The target already holds files.
    """
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise errors.ExtractTargetError(f"{target} already holds files")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(
        tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent)
    )
    try:
        result = _extract_into(zip_path, staging, max_entries, max_total_bytes)
        if target.exists():
            target.rmdir()
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    logger.info(
        "extracted %d files (%d bytes) into %s",
        result.file_count,
        result.total_bytes,
        target,
    )
    return dataclasses.replace(result, target=target)


def _extract_into(
    zip_path: pathlib.Path,
    staging: pathlib.Path,
    max_entries: int,
    max_total_bytes: int,
) -> ExtractResult:
    """Check and extract every entry into the staging directory."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as error:
        raise errors.BadZipError(f"cannot open {zip_path}: {error}") from error
    with archive:
        planned = check_archive(
            archive, staging.resolve(), max_entries, max_total_bytes
        )
        file_count = 0
        total = 0
        for info, destination in planned:
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            try:
                total += _copy_entry(
                    archive, info, destination, max_total_bytes - total
                )
            except zipfile.BadZipFile as error:
                raise errors.BadZipError(
                    f"corrupt zip entry {info.filename}: {error}"
                ) from error
            file_count += 1
    return ExtractResult(staging, file_count, total)
