"""The backup archive and the restore on a mini corpus build."""

import datetime
import hashlib
import io
import os
import pathlib
import sqlite3
import tarfile

import pytest

import conftest
from keel import backup
from keel import cli
from keel import config
from keel import errors
from keel import indexer
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

STAMP_TIME = datetime.datetime(2026, 10, 22, 2, 30, tzinfo=datetime.UTC)


@pytest.fixture
def index_dir(
    settings: config.Settings, tmp_path: pathlib.Path
) -> pathlib.Path:
    out = tmp_path / "index"
    embedder = conftest.FakeEmbedder()
    indexer.build_index(settings, conftest.MINI_CORPUS, out, lambda: embedder)
    return out


@pytest.fixture
def logs_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "audit.jsonl").write_text('{"request_id": "r1"}\n')
    conn = sqlite3.connect(logs / "feedback.sqlite")
    conn.execute("CREATE TABLE feedback (request_id TEXT, vote INTEGER)")
    conn.execute("INSERT INTO feedback VALUES ('r1', 1)")
    conn.commit()
    conn.close()
    return logs


def test_backup_archive_checksum(
    index_dir: pathlib.Path, logs_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    out = tmp_path / "backups"

    result = backup.create_backup(index_dir, logs_dir, out, now=STAMP_TIME)

    assert result.stamp == "2026-10-22T023000Z"
    assert result.archive.name == "keel-2026-10-22T023000Z.tar.gz"
    digest = hashlib.sha256(result.archive.read_bytes()).hexdigest()
    assert result.sha256 == digest
    # The sha256sum -c format: the hash, 2 spaces, the archive base name.
    assert result.checksum_file.read_text() == (
        f"{digest}  keel-2026-10-22T023000Z.tar.gz\n"
    )
    assert backup.verify_archive(result.archive) == digest
    assert result.members == (
        "manifest.json",
        "chunks.sqlite",
        "vectors.npy",
        "audit.jsonl",
        "feedback.sqlite",
    )
    manifest = indexer.load_manifest(index_dir / indexer.CURRENT)
    with tarfile.open(result.archive) as tar:
        assert tar.getnames() == list(result.members)
        for name in ("chunks.sqlite", "vectors.npy"):
            member = tar.extractfile(name)
            assert member is not None
            copied = hashlib.sha256(member.read()).hexdigest()
            assert copied == manifest.files[name]
    assert sorted(p.name for p in out.iterdir()) == [
        result.archive.name,
        result.checksum_file.name,
    ]


def test_tampered_archive_fails_the_check(
    index_dir: pathlib.Path, logs_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    result = backup.create_backup(index_dir, logs_dir, tmp_path / "b")
    with result.archive.open("ab") as handle:
        handle.write(b"x")
    with pytest.raises(errors.BackupChecksumError, match="does not match"):
        backup.verify_archive(result.archive)
    result.checksum_file.write_text("nonsense\n")
    with pytest.raises(errors.BackupChecksumError, match="not a sha256"):
        backup.verify_archive(result.archive)
    result.checksum_file.unlink()
    with pytest.raises(errors.BackupChecksumError, match="cannot read"):
        backup.verify_archive(result.archive)


def test_backup_refuses_a_corrupt_index(
    index_dir: pathlib.Path, logs_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    build = indexer.current_build(index_dir)
    assert build is not None
    (build / "vectors.npy").write_bytes(b"corrupt")
    with pytest.raises(errors.IndexCorruptError):
        backup.create_backup(index_dir, logs_dir, tmp_path / "b")
    assert not list((tmp_path / "b").iterdir())


def test_backup_without_an_index(tmp_path: pathlib.Path) -> None:
    with pytest.raises(errors.IndexMissingError):
        backup.create_backup(tmp_path / "none", tmp_path, tmp_path / "b")


def test_restore_swaps_current_and_previous(
    settings: config.Settings,
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    old = indexer.current_build(index_dir)
    assert old is not None
    archive = backup.create_backup(index_dir, logs_dir, tmp_path / "b").archive
    # A stale restore directory from an interrupted run is replaced.
    (index_dir / backup.RESTORE_DIR).mkdir()

    result = backup.restore_backup(archive, index_dir, logs_dir)

    assert indexer.current_build(index_dir) == result.build_dir.resolve()
    assert (index_dir / backup.PREVIOUS).resolve() == old
    assert result.previous == old
    assert not (index_dir / backup.RESTORE_DIR).exists()
    manifest = indexer.verify(index_dir / indexer.CURRENT)
    assert manifest.chunks_sha256 == indexer.load_manifest(old).chunks_sha256
    # The shards are back, so an incremental build embeds nothing.
    old_shards = sorted(p.name for p in (old / numpy_dense.SHARD_DIR).iterdir())
    new_shards = sorted(
        p.name for p in (result.build_dir / numpy_dense.SHARD_DIR).iterdir()
    )
    assert new_shards == old_shards
    assert result.extra_dir is not None
    assert result.extra_dir.parent == logs_dir
    assert result.extra_dir.name.startswith("restored-")
    assert (result.extra_dir / "audit.jsonl").read_text() == (
        '{"request_id": "r1"}\n'
    )
    assert (result.extra_dir / "feedback.sqlite").is_file()
    assert (logs_dir / "audit.jsonl").is_file()
    embedder = conftest.FakeEmbedder()
    rebuilt = indexer.build_index(
        settings,
        conftest.MINI_CORPUS,
        index_dir,
        lambda: embedder,
        incremental=True,
    )
    assert rebuilt.manifest.build.embedded_filings == 0


def test_restore_without_a_current_build(
    index_dir: pathlib.Path, logs_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    (logs_dir / "audit.jsonl").unlink()
    (logs_dir / "feedback.sqlite").unlink()
    archive = backup.create_backup(index_dir, logs_dir, tmp_path / "b").archive
    fresh = tmp_path / "fresh-index"

    result = backup.restore_backup(archive, fresh, logs_dir)

    assert result.previous is None
    assert result.extra_dir is None
    assert not (fresh / backup.PREVIOUS).exists()
    assert indexer.verify(fresh / indexer.CURRENT).counts.indexed == 3


def write_archive(
    path: pathlib.Path, members: dict[str, bytes], link: str | None = None
) -> pathlib.Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if link:
            info = tarfile.TarInfo(link)
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n")
    return path


@pytest.mark.parametrize(
    ("members", "link", "reason"),
    [
        ({"../evil.txt": b"x"}, None, "unexpected"),
        ({"dir/evil.txt": b"x"}, None, "unexpected"),
        ({"manifest.json": b"{}"}, "chunks.sqlite", "unexpected"),
        ({"manifest.json": b"{}"}, None, "lacks"),
    ],
)
def test_restore_rejects_bad_archives(
    tmp_path: pathlib.Path,
    members: dict[str, bytes],
    link: str | None,
    reason: str,
) -> None:
    archive = write_archive(
        tmp_path / "keel-2026-10-22T023000Z.tar.gz", members, link
    )
    index_dir = tmp_path / "index"
    with pytest.raises(errors.BackupError, match=reason):
        backup.restore_backup(archive, index_dir, tmp_path / "logs")
    assert not (index_dir / backup.RESTORE_DIR).exists()
    assert not (index_dir / indexer.CURRENT).exists()


def test_restore_rejects_a_foreign_name(tmp_path: pathlib.Path) -> None:
    archive = write_archive(tmp_path / "other.tar.gz", {"a": b"x"})
    with pytest.raises(errors.BackupError, match="not a Keel archive"):
        backup.restore_backup(archive, tmp_path / "i", tmp_path / "l")


def test_prune_backups(
    index_dir: pathlib.Path, logs_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    out = tmp_path / "b"
    made = [
        backup.create_backup(
            index_dir,
            logs_dir,
            out,
            now=STAMP_TIME + datetime.timedelta(days=day),
        )
        for day in range(3)
    ]

    removed = backup.prune_backups(out, keep=2)

    assert removed == [made[0].archive]
    assert not made[0].checksum_file.exists()
    assert made[2].archive.is_file()


class RecordingUploader:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def upload(self, path: pathlib.Path, key: str) -> None:
        assert path.is_file()
        self.keys.append(key)


def nightly_settings(
    settings: config.Settings,
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
    out: pathlib.Path,
    bucket: str | None,
) -> config.Settings:
    return settings.model_copy(
        update={
            "index": settings.index.model_copy(update={"dir": index_dir}),
            "logs": settings.logs.model_copy(update={"dir": logs_dir}),
            "scheduler": settings.scheduler.model_copy(
                update={"backup_dir": out, "backup_bucket": bucket}
            ),
        }
    )


def test_nightly_backup_uploads_when_a_bucket_is_set(
    settings: config.Settings,
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    configured = nightly_settings(
        settings, index_dir, logs_dir, tmp_path / "b", "keel-backups"
    )
    uploader = RecordingUploader()

    result = backup.run_nightly_backup(configured, uploader)

    assert uploader.keys == [
        f"keel/{result.stamp}/{result.archive.name}",
        f"keel/{result.stamp}/{result.checksum_file.name}",
    ]


def test_nightly_backup_keeps_the_archive_when_s3_is_unavailable(
    settings: config.Settings,
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    out = tmp_path / "b"
    configured = nightly_settings(
        settings, index_dir, logs_dir, out, "keel-backups"
    )
    with pytest.raises(errors.BackupUploadError, match="not available"):
        backup.run_nightly_backup(configured)
    assert len(list(out.glob("keel-*.tar.gz"))) == 1
    local = nightly_settings(settings, index_dir, logs_dir, out, None)
    assert backup.run_nightly_backup(local).archive.is_file()


def test_backup_and_restore_commands(
    clean_env: pytest.MonkeyPatch,
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clean_env.setenv("KEEL_INDEX__DIR", str(index_dir))
    clean_env.setenv("KEEL_LOGS__DIR", str(logs_dir))
    out = tmp_path / "b"

    assert cli.main(["backup", "--out", str(out)]) == 0
    archive = next(out.glob("keel-*.tar.gz"))
    assert f"archive: {archive}" in capsys.readouterr().out

    assert cli.main(["restore", str(archive)]) == 0
    printed = capsys.readouterr().out
    assert "index version: 1.0.0" in printed
    assert "restored logs:" in printed

    index_only = tmp_path / "release"
    assert cli.main(["backup", "--index-only", "--out", str(index_only)]) == 0
    assert "members: manifest.json, chunks.sqlite, vectors.npy\n" in (
        capsys.readouterr().out
    )


def test_backup_skips_log_files_with_index_names(
    index_dir: pathlib.Path, logs_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    sqlite3.connect(logs_dir / "chunks.sqlite").close()
    result = backup.create_backup(index_dir, logs_dir, tmp_path / "b")
    assert result.members.count("chunks.sqlite") == 1
    assert not list((tmp_path / "b").glob("*.part"))
    restored = backup.restore_backup(result.archive, index_dir, logs_dir)
    assert indexer.verify(restored.build_dir).counts.indexed == 3


def test_restore_rejects_too_many_members(tmp_path: pathlib.Path) -> None:
    members = {f"f{n}.sqlite": b"x" for n in range(backup.MAX_MEMBERS + 1)}
    archive = write_archive(
        tmp_path / "keel-2026-10-22T023000Z.tar.gz", members
    )
    with pytest.raises(errors.BackupError, match="limit"):
        backup.restore_backup(archive, tmp_path / "i", tmp_path / "l")


def test_previous_survives_the_next_build(
    settings: config.Settings,
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
    tmp_path: pathlib.Path,
) -> None:
    archive = backup.create_backup(index_dir, logs_dir, tmp_path / "b").archive
    backup.restore_backup(archive, index_dir, logs_dir)
    previous = (index_dir / backup.PREVIOUS).resolve()
    embedder = conftest.FakeEmbedder()
    for _ in range(2):
        indexer.build_index(
            settings, conftest.MINI_CORPUS, index_dir, lambda: embedder
        )
    assert (index_dir / backup.PREVIOUS).resolve() == previous
    assert previous.is_dir()


def test_failed_pointer_swap_removes_the_restored_build(
    index_dir: pathlib.Path,
    logs_dir: pathlib.Path,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = backup.create_backup(index_dir, logs_dir, tmp_path / "b").archive
    before = sorted(p.name for p in index_dir.iterdir())

    def fail(index: pathlib.Path, name: str, target: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(backup, "_swap_link", fail)
    with pytest.raises(errors.IndexWriteError, match="disk full"):
        backup.restore_backup(archive, index_dir, logs_dir)
    assert sorted(p.name for p in index_dir.iterdir()) == before


def test_restore_refuses_a_directory_named_current(
    index_dir: pathlib.Path, logs_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    archive = backup.create_backup(index_dir, logs_dir, tmp_path / "b").archive
    plain = tmp_path / "plain-index"
    (plain / indexer.CURRENT).mkdir(parents=True)
    with pytest.raises(errors.IndexWriteError, match="not a symlink"):
        backup.restore_backup(archive, plain, logs_dir)
    assert sorted(p.name for p in plain.iterdir()) == [indexer.CURRENT]


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_backup_keeps_the_rotated_audit_days_private(
    index_dir: pathlib.Path, logs_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The archive joins the rotated days and today, and is 0600."""
    (logs_dir / "audit-2026-10-20.jsonl").write_text('{"request_id": "r0"}\n')
    (logs_dir / "audit-2026-10-21.jsonl").write_text('{"request_id": "rx"}\n')
    result = backup.create_backup(index_dir, logs_dir, tmp_path / "b")

    with tarfile.open(result.archive, "r:gz") as tar:
        member = tar.extractfile("audit.jsonl")
        assert member is not None
        lines = member.read().decode().splitlines()
    assert [line.split('"')[3] for line in lines] == ["r0", "rx", "r1"]
    assert result.archive.stat().st_mode & 0o777 == 0o600
    assert result.checksum_file.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "b").stat().st_mode & 0o777 == 0o700
    assert not list((tmp_path / "b").glob(".backup-*"))

    restored = backup.restore_backup(
        result.archive, tmp_path / "fresh", tmp_path / "fresh-logs"
    )
    assert restored.extra_dir is not None
    assert restored.extra_dir.stat().st_mode & 0o777 == 0o700
    audit = restored.extra_dir / "audit.jsonl"
    assert audit.stat().st_mode & 0o777 == 0o600
