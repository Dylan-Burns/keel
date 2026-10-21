"""Tests for the `keel doctor` checks. No test touches the network."""

import datetime
import pathlib
import socket
import sys
import types
import zipfile

import pytest

import conftest
from keel import cli
from keel import config
from keel import doctor

pytestmark = pytest.mark.unit


def test_doctor_time_check() -> None:
    """E-F-12: a wrong clock is a warning against the corpus dates."""
    newest = datetime.date(2026, 2, 19)
    sane = doctor.check_clock(datetime.date(2026, 10, 21), newest, "PDT")
    assert sane.status == doctor.OK
    assert "newest filing 2026-02-19 (244 days)" in sane.detail
    before = doctor.check_clock(datetime.date(2024, 1, 1), newest, "UTC")
    assert before.status == doctor.WARN
    assert "before the newest filing" in before.detail
    late = doctor.check_clock(datetime.date(2031, 1, 1), newest, "UTC")
    assert late.status == doctor.WARN
    assert "days after the newest filing" in late.detail
    unknown = doctor.check_clock(datetime.date(2026, 10, 21), None, "UTC")
    assert unknown.status == doctor.WARN
    # Never a failure: time scopes use corpus dates, not the clock (D-33).
    assert doctor.FAIL not in {r.status for r in (sane, before, late, unknown)}


def test_corpus_last_filing_from_dir_and_zip(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    corpus = tmp_path / "edgar"
    corpus.mkdir()
    for name in ("JPM_10K_2026-02-13_full.txt", "notes.txt"):
        (corpus / name).write_text("x", encoding="utf-8")
    from_dir = settings.model_copy(
        update={
            "corpus": config.CorpusConfig(
                dir=corpus, zip=tmp_path / "absent.zip"
            )
        }
    )
    assert doctor.corpus_last_filing(from_dir) == datetime.date(2026, 2, 13)
    archive = tmp_path / "corpus.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("NVDA_10K_2025-02-26_full.txt", b"x")
        handle.writestr("manifest.json", b"{}")
    from_zip = settings.model_copy(
        update={
            "corpus": config.CorpusConfig(dir=tmp_path / "none", zip=archive)
        }
    )
    assert doctor.corpus_last_filing(from_zip) == datetime.date(2025, 2, 26)
    archive.write_bytes(b"not a zip")
    assert doctor.corpus_last_filing(from_zip) is None


def test_python_check() -> None:
    assert doctor.check_python((3, 12, 13)).status == doctor.OK
    assert doctor.check_python((3, 11, 9)).status == doctor.FAIL


def test_fts5_present() -> None:
    result = doctor.check_fts5()
    assert result.status == doctor.OK, result.detail


def test_secret_check_never_shows_value() -> None:
    present = doctor.check_secret("ANTHROPIC_API_KEY", True, "degraded")
    assert present == doctor.CheckResult("ANTHROPIC_API_KEY", doctor.OK, "set")
    absent = doctor.check_secret("KEEL_API_TOKEN", False, "no API")
    assert absent.status == doctor.WARN


def test_disk_check(tmp_path: pathlib.Path) -> None:
    assert doctor.check_disk(tmp_path / "not" / "yet").status == doctor.OK
    assert doctor.check_disk(tmp_path, min_free=1 << 62).status == doctor.WARN


def test_port_check_finds_next_free() -> None:
    busy = {8000, 8001}
    result = doctor.check_port(
        "127.0.0.1", 8000, is_free=lambda _host, port: port not in busy
    )
    assert result.status == doctor.WARN
    assert "8002 is free" in result.detail
    none_free = doctor.check_port(
        "127.0.0.1", 8000, is_free=lambda _h, _p: False
    )
    assert "all in use" in none_free.detail
    assert (
        doctor.check_port("127.0.0.1", 8000, is_free=lambda _h, _p: True).status
        == doctor.OK
    )


def test_port_free_probe() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        assert not doctor.port_free("127.0.0.1", port)


def test_prices_check(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    assert doctor.check_prices(settings).status == doctor.OK
    llm = settings.llm.model_copy(update={"judge_model": "claude-unpriced"})
    missing = doctor.check_prices(settings.model_copy(update={"llm": llm}))
    assert missing.status == doctor.FAIL
    assert "claude-unpriced" in missing.detail
    broken = settings.llm.model_copy(update={"prices": tmp_path / "x.yaml"})
    unreadable = doctor.check_prices(
        settings.model_copy(update={"llm": broken})
    )
    assert unreadable.status == doctor.FAIL


def test_hf_cache_dir() -> None:
    assert doctor.hf_cache_dir({"HF_HUB_CACHE": "/c/hub"}) == pathlib.Path(
        "/c/hub"
    )
    assert doctor.hf_cache_dir({"HF_HOME": "/h"}) == pathlib.Path("/h/hub")
    assert doctor.hf_cache_dir({"XDG_CACHE_HOME": "/x"}) == pathlib.Path(
        "/x/huggingface/hub"
    )
    assert doctor.hf_cache_dir({}).parts[-2:] == ("huggingface", "hub")


def test_model_cache_check(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    results = doctor.check_models(settings, tmp_path)
    assert [r.status for r in results] == [doctor.WARN, doctor.WARN]
    assert "--download-models" in results[0].detail
    snapshot = doctor.model_snapshot(
        tmp_path, settings.embedding.model, settings.embedding.revision
    )
    assert snapshot.parts[-3:] == (
        "models--BAAI--bge-small-en-v1.5",
        "snapshots",
        settings.embedding.revision,
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    results = doctor.check_models(settings, tmp_path)
    assert [r.status for r in results] == [doctor.OK, doctor.WARN]


def test_download_models_uses_shared_api(
    settings: config.Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, str]] = []

    def loader(kind: str) -> object:
        def load(name: str, revision: str) -> None:
            calls.append((kind, name, revision))
            if kind == "cross":
                raise OSError("offline")

        return load

    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = loader("dense")  # type: ignore[attr-defined]
    fake.CrossEncoder = loader("cross")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)
    results = doctor.download_models(settings)
    assert calls == [
        ("dense", settings.embedding.model, settings.embedding.revision),
        ("cross", settings.reranker.model, settings.reranker.revision),
    ]
    assert [r.status for r in results] == [doctor.OK, doctor.FAIL]


def test_index_check(tmp_path: pathlib.Path) -> None:
    assert doctor.check_index(tmp_path).status == doctor.WARN
    (tmp_path / "current").mkdir()
    assert doctor.check_index(tmp_path).status == doctor.OK


def test_run_doctor_hides_secrets(
    clean_env: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-secret-value-123")
    clean_env.setenv("KEEL_API_TOKEN", "   ")
    prices = conftest.REPO_ROOT / "config" / "prices.yaml"
    clean_env.setenv("KEEL_LLM__PRICES", str(prices))
    clean_env.setenv("HF_HUB_CACHE", str(tmp_path))
    clean_env.chdir(tmp_path)
    code = cli.main(["--config", str(conftest.CONFIG_FILE), "doctor"])
    out = capsys.readouterr().out
    assert code == 0
    assert "sk-secret-value-123" not in out
    assert "ok    ANTHROPIC_API_KEY: set" in out
    assert "warn  KEEL_API_TOKEN: absent" in out
    assert "warn  clock" in out
    code = cli.main(["--config", str(conftest.CONFIG_FILE), "doctor", "--json"])
    assert code == 0
    assert "sk-secret-value-123" not in capsys.readouterr().out


class _NoFts5Connection:
    def execute(self, sql: str) -> list[tuple[str]]:
        del sql
        return [("THREADSAFE=1",)]

    def close(self) -> None:
        pass


def test_fts5_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor.sqlite3, "connect", lambda _name: _NoFts5Connection()
    )
    result = doctor.check_fts5()
    assert result.status == doctor.FAIL
    assert "ENABLE_FTS5" in result.detail
