"""Tests for the config loader, the price table, and the dictionaries."""

import datetime
import pathlib

import pytest
import yaml

import conftest
from keel import config
from keel import errors

pytestmark = pytest.mark.unit


def test_yaml_values_load(settings: config.Settings) -> None:
    assert settings.llm.model == "claude-sonnet-5-5"
    assert settings.llm.fallback_model == "claude-haiku-5-5"
    assert settings.llm.judge_model == "claude-opus-5-5"
    assert len(settings.embedding.revision) == 40
    assert len(settings.reranker.revision) == 40
    assert settings.corpus.date_filter is None
    assert settings.offline is False


def test_env_overrides_yaml(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("KEEL_OFFLINE", "1")
    clean_env.setenv("KEEL_LLM__MODEL", "claude-test")
    clean_env.setenv("KEEL_INDEX__DIR", "/data/index")
    loaded = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    assert loaded.offline is True
    assert loaded.llm.model == "claude-test"
    # A nested override keeps the sibling keys from the YAML file.
    assert loaded.llm.fallback_model == "claude-haiku-5-5"
    assert loaded.index.dir == pathlib.Path("/data/index")


def test_dotenv_file_feeds_secrets(
    clean_env: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    del clean_env
    dotenv = tmp_path / "test.env"
    dotenv.write_text(
        "ANTHROPIC_API_KEY=sk-test-value\nKEEL_API_TOKEN=token-value\n"
        "GITHUB_TOKEN=ignored\n",
        encoding="utf-8",
    )
    loaded = config.load_settings(conftest.CONFIG_FILE, env_file=dotenv)
    assert loaded.anthropic_api_key is not None
    assert loaded.anthropic_api_key.get_secret_value() == "sk-test-value"
    assert loaded.api_token is not None
    assert "sk-test-value" not in repr(loaded)
    assert "token-value" not in str(loaded)


def test_config_file_variable(
    clean_env: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    data = config.read_yaml(conftest.CONFIG_FILE)
    data["server"]["port"] = 8123
    custom = tmp_path / "custom.yaml"
    custom.write_text(yaml.safe_dump(data), encoding="utf-8")
    clean_env.setenv(config.CONFIG_PATH_VARIABLE, str(custom))
    assert config.config_path() == custom
    assert config.load_settings(env_file=None).server.port == 8123


def test_invalid_config_raises(
    clean_env: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    del clean_env
    data = config.read_yaml(conftest.CONFIG_FILE)
    data["server"]["unknown_key"] = 1
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(errors.ConfigError, match="invalid config"):
        config.load_settings(broken, env_file=None)


@pytest.mark.parametrize(
    ("content", "message"),
    [("a: [1", "invalid YAML"), ("- 1\n- 2\n", "must hold a mapping")],
)
def test_read_yaml_errors(
    tmp_path: pathlib.Path, content: str, message: str
) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(errors.ConfigError, match=message):
        config.read_yaml(path)


def test_read_yaml_absent_and_empty(tmp_path: pathlib.Path) -> None:
    with pytest.raises(errors.ConfigError, match="cannot read"):
        config.read_yaml(tmp_path / "absent.yaml")
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert config.read_yaml(empty) == {}


def test_date_filter_open_ends_and_order() -> None:
    lower = config.DateFilter(min=datetime.date(2023, 1, 1))
    assert lower.includes(datetime.date(2030, 1, 1))
    assert not lower.includes(datetime.date(2015, 2, 27))
    upper = config.DateFilter(max=datetime.date(2025, 12, 31))
    assert upper.includes(datetime.date(2015, 2, 27))
    with pytest.raises(ValueError, match="after"):
        config.DateFilter(
            min=datetime.date(2025, 1, 1), max=datetime.date(2024, 1, 1)
        )


def test_prices_cover_configured_models(settings: config.Settings) -> None:
    prices = config.load_prices(settings.llm.prices)
    assert config.models_without_prices(settings, prices) == []
    haiku = prices.models["claude-haiku-5-5"]
    assert haiku.long_prompt is not None
    assert haiku.long_prompt_threshold == 100000


def test_prices_invalid(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "prices.yaml"
    path.write_text("checked_on: 2026-10-21\nmodels: {m: {input: 1}}\n")
    with pytest.raises(errors.ConfigError, match="invalid prices"):
        config.load_prices(path)


def test_dictionaries_are_consistent(settings: config.Settings) -> None:
    companies = config.read_yaml(settings.dictionaries.companies)
    groups = config.read_yaml(settings.dictionaries.groups)
    assert len(companies) == 54
    for ticker, entry in companies.items():
        assert entry["company"], ticker
        assert entry["aliases"], ticker
        assert all(alias == alias.lower() for alias in entry["aliases"])
    for name, group in groups.items():
        assert group["triggers"], name
        assert set(group["tickers"]) <= set(companies), name
    months = config.read_yaml(settings.parser.fiscal_year_ends)
    assert set(months) <= set(companies)
    assert all(1 <= month <= 11 for month in months.values())
    assert config.read_yaml(settings.parser.overrides) == {}
    for path in (
        settings.parser.protected_names,
        settings.parser.abbreviations,
    ):
        words = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        assert len(words) == len(set(words)), path
    assert config.read_yaml(settings.dictionaries.synonyms)["revenue"]
    assert config.read_yaml(settings.dictionaries.known_external)["Uber"]
