"""Tests for the safe zip extraction (control S-10)."""

import pathlib
import stat
import zipfile

import pytest

from keel import errors
from keel import extractor

pytestmark = pytest.mark.unit


def _zip(path: pathlib.Path, entries: dict[str, bytes]) -> pathlib.Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_extracts_into_place(tmp_path: pathlib.Path) -> None:
    archive = _zip(
        tmp_path / "corpus.zip",
        {"A_10K_2024-01-01_full.txt": b"abc", "manifest.json": b"{}"},
    )
    target = tmp_path / "edgar"
    result = extractor.extract_zip(archive, target)
    assert result.file_count == 2
    assert result.total_bytes == 5
    assert result.target == target.resolve()
    assert (target / "A_10K_2024-01-01_full.txt").read_bytes() == b"abc"
    # The staging directory is gone after the rename.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["corpus.zip", "edgar"]


def test_nested_entries_and_empty_target(tmp_path: pathlib.Path) -> None:
    archive = tmp_path / "nested.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("sub/", b"")
        handle.writestr("sub/file.txt", b"x")
    target = tmp_path / "edgar"
    target.mkdir()
    result = extractor.extract_zip(archive, target)
    assert result.file_count == 1
    assert (target / "sub" / "file.txt").read_bytes() == b"x"


@pytest.mark.parametrize(
    "name",
    ["../escape.txt", "sub/../../escape.txt", "/etc/passwd", "C:/evil.txt"],
)
def test_path_traversal_rejected(tmp_path: pathlib.Path, name: str) -> None:
    archive = _zip(tmp_path / "evil.zip", {"ok.txt": b"x", name: b"evil"})
    target = tmp_path / "edgar"
    with pytest.raises(errors.UnsafePathError):
        extractor.extract_zip(archive, target)
    assert not target.exists()
    assert not (tmp_path / "escape.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["evil.zip"]


def test_symlink_rejected(tmp_path: pathlib.Path) -> None:
    archive = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link.txt")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(info, "/etc/passwd")
    with pytest.raises(errors.UnsafePathError, match="symbolic link"):
        extractor.extract_zip(archive, tmp_path / "edgar")


def test_entry_resolving_outside_rejected(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "edgar"
    target.mkdir()
    (target / "jump").symlink_to(tmp_path)
    info = zipfile.ZipInfo("jump/outside.txt")
    with pytest.raises(errors.UnsafePathError, match="leaves the target"):
        extractor.check_entry(info, target.resolve())


def test_entry_count_cap(tmp_path: pathlib.Path) -> None:
    archive = _zip(tmp_path / "many.zip", {f"f{i}.txt": b"x" for i in range(4)})
    with pytest.raises(errors.BadZipError, match="entries"):
        extractor.extract_zip(archive, tmp_path / "edgar", max_entries=3)


def test_size_cap(tmp_path: pathlib.Path) -> None:
    archive = _zip(tmp_path / "big.zip", {"big.txt": b"x" * 100})
    with pytest.raises(errors.BadZipError, match="expands"):
        extractor.extract_zip(archive, tmp_path / "edgar", max_total_bytes=50)
    assert not (tmp_path / "edgar").exists()


def test_size_cap_while_writing(tmp_path: pathlib.Path) -> None:
    archive = _zip(tmp_path / "liar.zip", {"a.txt": b"x" * 100})
    with zipfile.ZipFile(archive) as handle:
        info = handle.infolist()[0]
        destination = tmp_path / "out" / "a.txt"
        with pytest.raises(errors.BadZipError, match="past the size limit"):
            extractor._copy_entry(handle, info, destination, budget=10)


def test_corrupt_zip(tmp_path: pathlib.Path) -> None:
    archive = tmp_path / "corrupt.zip"
    archive.write_bytes(b"not a zip at all")
    with pytest.raises(errors.BadZipError, match="cannot open"):
        extractor.extract_zip(archive, tmp_path / "edgar")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["corrupt.zip"]


def test_target_with_files_refused(tmp_path: pathlib.Path) -> None:
    archive = _zip(tmp_path / "corpus.zip", {"a.txt": b"x"})
    target = tmp_path / "edgar"
    target.mkdir()
    (target / "keep.txt").write_text("existing", encoding="utf-8")
    with pytest.raises(errors.ExtractTargetError):
        extractor.extract_zip(archive, target)
    assert (target / "keep.txt").read_text(encoding="utf-8") == "existing"
