"""The timebox security controls of chapter 15 that stage 11 adds.

S-01 (secrets from the environment only, redacted log lines), S-04 (the
context and chunk caps), S-14 (no key pattern in a log line), and S-16
(the answer cache directory for the service user only).
"""

import logging
import pathlib
import stat
import sys

import pydantic
import pytest
import yaml

import conftest
from keel import cache
from keel import config
from keel import errors
from keel import security

pytestmark = pytest.mark.unit

KEY = "sk-ant-api03-abcdefghijklmnop"


def test_redact_patterns_and_values() -> None:
    text = (
        f"key {KEY} header Authorization: Bearer abc.def-123456 "
        "env ANTHROPIC_API_KEY=plainvalue123 KEEL_API_TOKEN: 'tok-9876543' "
        "secret s3cr3t-value-x and short=ok"
    )
    masked = security.redact(text, ["s3cr3t-value-x"])
    for secret in (
        KEY,
        "abc.def-123456",
        "plainvalue123",
        "tok-9876543",
        "s3cr3t-value-x",
    ):
        assert secret not in masked
    assert "Bearer [REDACTED]" in masked
    assert "ANTHROPIC_API_KEY=[REDACTED]" in masked
    assert "short=ok" in masked


def test_secret_values(settings: config.Settings) -> None:
    loaded = settings.model_copy(
        update={
            "anthropic_api_key": pydantic.SecretStr("from-settings-key-1"),
            "api_token": pydantic.SecretStr("from-settings-tok-2"),
        }
    )
    found = security.secret_values(
        {"GITHUB_TOKEN": "ghp_longenough", "HOME": "/home/x", "A_KEY": "s"},
        loaded,
    )
    assert "ghp_longenough" in found
    assert "from-settings-key-1" in found
    assert "from-settings-tok-2" in found
    assert "/home/x" not in found
    assert "s" not in found  # too short to mask safely
    assert security.secret_values({}) == []


def test_log_lines_are_redacted(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S-01 step 3: a secret in a log line, or its traceback, is masked."""
    root = logging.getLogger()
    handler = logging.StreamHandler()
    monkeypatch.setattr(root, "handlers", [handler])
    formatter = security.install(None, {"MY_TOKEN": "env-token-value-1"})
    assert handler.formatter is formatter
    record = logging.LogRecord(
        "keel", logging.WARNING, __file__, 1, "sent %s with %s", None, None
    )
    record.args = (KEY, "env-token-value-1")
    line = formatter.format(record)
    assert KEY not in line
    assert "env-token-value-1" not in line
    assert line.count(security.MASK) == 2
    try:
        raise ValueError(f"boom {KEY}")
    except ValueError:
        failed = logging.LogRecord(
            "keel", logging.ERROR, __file__, 1, "failed", None, None
        )
        failed.exc_info = sys.exc_info()
    assert KEY not in formatter.format(failed)


def test_install_adds_a_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    security.install(None, {})
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, security.RedactingFormatter)


def test_secrets_refused_in_config_file(
    clean_env: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """S-01 step 1: a secret in the YAML file stops the load."""
    del clean_env
    data = config.read_yaml(conftest.CONFIG_FILE)
    for name in ("api_token", "ANTHROPIC_API_KEY"):
        bad = dict(data, **{name: "in-the-repo-secret"})
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(errors.ConfigError) as caught:
            config.load_settings(path, env_file=None)
        assert "environment" in str(caught.value)
        assert "in-the-repo-secret" not in str(caught.value)


def test_context_caps(clean_env: pytest.MonkeyPatch) -> None:
    """S-04 step 4: the budget is clamped to 64,000 tokens and 96 chunks."""
    clean_env.setenv("KEEL_RETRIEVAL__MAX_CONTEXT_TOKENS", "500000")
    clean_env.setenv("KEEL_RETRIEVAL__MAX_CHUNKS", "1000")
    loaded = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    assert loaded.retrieval.max_context_tokens == config.MAX_CONTEXT_TOKENS_CAP
    assert loaded.retrieval.max_chunks == config.MAX_CHUNKS_CAP
    clean_env.setenv("KEEL_RETRIEVAL__MAX_CHUNKS", "0")
    with pytest.raises(errors.ConfigError):
        config.load_settings(conftest.CONFIG_FILE, env_file=None)


def test_cache_directory_is_private(tmp_path: pathlib.Path) -> None:
    """S-16 step 3: only the service user may write the cache."""
    directory = tmp_path / "answers"
    directory.mkdir(mode=0o777)
    directory.chmod(0o777)
    store = cache.AnswerCache(directory)
    store.put("k", {"answer": {}})
    mode = stat.S_IMODE(directory.stat().st_mode)
    assert mode == cache.DIRECTORY_MODE
    entry = stat.S_IMODE(store.path("k").stat().st_mode)
    assert entry & 0o077 == 0


def test_redact_keeps_plain_words_and_masks_json() -> None:
    value = "z" * 12
    plain = "cache key: " + "0" * 16
    text = plain + ' {"api_' + 'key": "' + value + '"}'
    masked = security.redact(text)
    assert plain in masked
    assert value not in masked


def test_short_service_token_masked(settings: config.Settings) -> None:
    loaded = settings.model_copy(
        update={"api_token": pydantic.SecretStr("abc12")}
    )
    found = security.secret_values({"X_TOKEN": "short"}, loaded)
    assert found == ["abc12"]
