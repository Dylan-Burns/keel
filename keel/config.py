"""The config loader: `config/keel.yaml` first, then the environment.

The YAML file gives the defaults. An environment variable overrides any key:
a top-level key as `KEEL_<KEY>`, a nested key as `KEEL_<SECTION>__<KEY>`
(chapter 17.3). The `.env` file in the working directory feeds the same
variables. Secrets come only from the environment and never from the YAML.
"""

from __future__ import annotations

import datetime
import os
import pathlib
from typing import Any

import pydantic
import pydantic_settings
import yaml

from keel import errors

DEFAULT_CONFIG_PATH = pathlib.Path("config/keel.yaml")
CONFIG_PATH_VARIABLE = "KEEL_CONFIG_FILE"
DEFAULT_ENV_FILE = pathlib.Path(".env")


class _Section(pydantic.BaseModel):
    """The base of every config section: unknown keys are errors."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)


class ServerConfig(_Section):
    """The HTTP server bind address."""

    host: str = "127.0.0.1"
    port: int = pydantic.Field(default=8000, ge=1, le=65535)


class CacheConfig(_Section):
    """Where the answer cache lives."""

    answers_dir: pathlib.Path = pathlib.Path("demo/answer_cache")


class DateFilter(_Section):
    """An inclusive window on the filing date (E-D-02, decision D-19).

    Attributes:
        min: The first filing date to keep, or None for no lower bound.
        max: The last filing date to keep, or None for no upper bound.
    """

    min: datetime.date | None = None
    max: datetime.date | None = None

    @pydantic.model_validator(mode="after")
    def _check_order(self) -> DateFilter:
        if self.min and self.max and self.min > self.max:
            raise ValueError("date_filter.min is after date_filter.max")
        return self

    def includes(self, filing_date: datetime.date) -> bool:
        """Tell whether a filing date falls inside the window.

        Args:
            filing_date: The filing date of a file.

        Returns:
            True when the date is inside the window.
        """
        if self.min and filing_date < self.min:
            return False
        return not (self.max and filing_date > self.max)


class CorpusConfig(_Section):
    """The corpus zip, the extracted directory, and the manifest."""

    zip: pathlib.Path = pathlib.Path("corpus/edgar_corpus.zip")
    url: str | None = None
    dir: pathlib.Path = pathlib.Path("corpus/edgar")
    manifest: pathlib.Path = pathlib.Path("corpus/edgar/manifest.json")
    date_filter: DateFilter | None = None


class IndexConfig(_Section):
    """Where the index builds land."""

    dir: pathlib.Path = pathlib.Path("index")


class LogsConfig(_Section):
    """Where the audit log and the refresh log land."""

    dir: pathlib.Path = pathlib.Path("logs")


class ParserConfig(_Section):
    """The parser version and its dictionaries."""

    version: str = "1.0.0"
    protected_names: pathlib.Path = pathlib.Path("config/protected_names.txt")
    abbreviations: pathlib.Path = pathlib.Path("config/abbreviations.txt")
    overrides: pathlib.Path = pathlib.Path("config/overrides.yaml")
    fiscal_year_ends: pathlib.Path = pathlib.Path(
        "config/fiscal_year_ends.yaml"
    )


class DictionariesConfig(_Section):
    """The dictionaries of question understanding and retrieval."""

    companies: pathlib.Path = pathlib.Path("config/companies.yaml")
    groups: pathlib.Path = pathlib.Path("config/groups.yaml")
    synonyms: pathlib.Path = pathlib.Path("config/synonyms.yaml")
    known_external: pathlib.Path = pathlib.Path("config/known_external.yaml")


class ChunkerConfig(_Section):
    """The chunk sizes in tokens (decision D-16)."""

    version: str = "1.0.0"
    target_tokens: int = 400
    max_tokens: int = 480
    overlap_tokens: int = 50


class EmbeddingConfig(_Section):
    """The pinned embedding model (decision D-07)."""

    model: str = "BAAI/bge-small-en-v1.5"
    revision: str
    batch_size: int = 32


class RerankerConfig(_Section):
    """The pinned cross-encoder reranker (decision D-10)."""

    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    revision: str
    top_n: int = 80


class RetrievalConfig(_Section):
    """The retrieval and context budget settings (chapter 11)."""

    lexical_k: int = 100
    dense_k: int = 100
    rrf_k: int = 60
    max_context_tokens: int = 32000
    max_chunks: int = 48
    simhash_max_distance: int = 3
    calibration_factor: float = 1.15


class LlmConfig(_Section):
    """The provider, the pinned models, and the request settings."""

    provider: str = "anthropic"
    model: str
    fallback_model: str
    judge_model: str
    prices: pathlib.Path = pathlib.Path("config/prices.yaml")
    temperature: float | None = None
    thinking: dict[str, str] = pydantic.Field(default_factory=dict)
    max_output_tokens: int = 4000
    prompt_version: str = "1.0.0"
    prompts_dir: pathlib.Path = pathlib.Path("prompts")
    cache_system_block: bool = True
    timeout_seconds: float = 120.0
    connect_timeout_seconds: float = 10.0
    idle_timeout_seconds: float = 30.0
    max_retries: int = pydantic.Field(default=2, ge=0)


class LimitsConfig(_Section):
    """The question limits, the rate limits, and the budget."""

    question_min_chars: int = 3
    question_max_chars: int = 1000
    rate_per_minute: int = 10
    rate_per_hour: int = 100
    daily_budget_usd: float = 20.0


class EdgarConfig(_Section):
    """The SEC EDGAR client settings (chapter 26)."""

    user_agent: str
    cache_dir: pathlib.Path = pathlib.Path("cache/edgar")
    min_request_interval_seconds: float = 0.2


class DemoConfig(_Section):
    """The demo questions and the tickers for `keel add`."""

    example_questions: list[str] = pydantic.Field(default_factory=list)
    add_companies: list[str] = pydantic.Field(default_factory=list)


class SchedulerConfig(_Section):
    """The in-app scheduler for the nightly refresh and backup."""

    enabled: bool = False
    refresh_at: str = "02:00"
    backup_at: str = "02:30"
    backup_bucket: str | None = None


class DeployConfig(_Section):
    """The deploy target."""

    host: str = "railway"


class Settings(pydantic_settings.BaseSettings):
    """The full Keel config after the YAML file and the environment.

    Attributes:
        anthropic_api_key: The provider key, from `ANTHROPIC_API_KEY` only.
        api_token: The bearer token of the API, from `KEEL_API_TOKEN`.
    """

    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="KEEL_",
        env_nested_delimiter="__",
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    offline: bool = False
    server: ServerConfig = ServerConfig()
    cache: CacheConfig = CacheConfig()
    corpus: CorpusConfig = CorpusConfig()
    index: IndexConfig = IndexConfig()
    logs: LogsConfig = LogsConfig()
    parser: ParserConfig = ParserConfig()
    dictionaries: DictionariesConfig = DictionariesConfig()
    chunker: ChunkerConfig = ChunkerConfig()
    embedding: EmbeddingConfig
    reranker: RerankerConfig
    retrieval: RetrievalConfig = RetrievalConfig()
    llm: LlmConfig
    limits: LimitsConfig = LimitsConfig()
    edgar: EdgarConfig
    demo: DemoConfig = DemoConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    deploy: DeployConfig = DeployConfig()

    anthropic_api_key: pydantic.SecretStr | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("ANTHROPIC_API_KEY"),
    )
    api_token: pydantic.SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[pydantic_settings.BaseSettings],
        init_settings: pydantic_settings.PydanticBaseSettingsSource,
        env_settings: pydantic_settings.PydanticBaseSettingsSource,
        dotenv_settings: pydantic_settings.PydanticBaseSettingsSource,
        file_secret_settings: pydantic_settings.PydanticBaseSettingsSource,
    ) -> tuple[pydantic_settings.PydanticBaseSettingsSource, ...]:
        """Order the sources: the environment, then `.env`, then the YAML.

        `load_settings` passes the YAML values as the init values, so they
        have the lowest priority and an environment variable wins.

        Args:
            settings_cls: The settings class.
            init_settings: The values passed to the constructor (the YAML).
            env_settings: The process environment.
            dotenv_settings: The `.env` file.
            file_secret_settings: The secrets directory (unused).

        Returns:
            The sources from the highest priority to the lowest.
        """
        del settings_cls, file_secret_settings
        return env_settings, dotenv_settings, init_settings


def read_yaml(path: pathlib.Path) -> dict[str, Any]:
    """Read a YAML file that holds a mapping.

    Args:
        path: The file to read.

    Returns:
        The mapping, or an empty mapping for an empty file.

    Raises:
        ConfigError: The file is absent, invalid YAML, or not a mapping.
    """
    try:
        with path.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
    except OSError as error:
        raise errors.ConfigError(f"cannot read {path}: {error}") from error
    except yaml.YAMLError as error:
        raise errors.ConfigError(f"invalid YAML in {path}: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.ConfigError(f"{path} must hold a mapping")
    return data


def read_word_list(path: pathlib.Path) -> tuple[str, ...]:
    """Read a word list: 1 entry per line, `#` starts a comment line.

    Args:
        path: The text file to read.

    Returns:
        The entries in file order, stripped, without blank lines.

    Raises:
        ConfigError: The file is absent or unreadable.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise errors.ConfigError(f"cannot read {path}: {error}") from error
    stripped = (line.strip() for line in lines)
    return tuple(line for line in stripped if line and not line.startswith("#"))


def config_path() -> pathlib.Path:
    """Return the config file path from `KEEL_CONFIG_FILE` or the default.

    Returns:
        The path of the YAML config file.
    """
    return pathlib.Path(
        os.environ.get(CONFIG_PATH_VARIABLE, str(DEFAULT_CONFIG_PATH))
    )


def load_settings(
    path: pathlib.Path | None = None,
    env_file: pathlib.Path | None = DEFAULT_ENV_FILE,
) -> Settings:
    """Load the settings from the YAML file, then the environment.

    Args:
        path: The YAML file. None reads `KEEL_CONFIG_FILE` or the default.
        env_file: The dotenv file to read, or None to read no file.

    Returns:
        The validated settings.

    Raises:
        ConfigError: The file is unreadable or a value fails validation.
    """
    data = read_yaml(path or config_path())
    try:
        # `_env_file` is a pydantic-settings init option, not a field.
        options: dict[str, Any] = {**data, "_env_file": env_file}
        return Settings(**options)
    except pydantic.ValidationError as error:
        raise errors.ConfigError(
            f"invalid config: {_describe(error)}"
        ) from None


def _describe(error: pydantic.ValidationError) -> str:
    """Describe validation errors by location and message, never by input.

    The input of a validation error can hold a secret from the environment,
    so the message carries only the key path and the reason.

    Args:
        error: The validation error.

    Returns:
        1 line per error, joined by semicolons.
    """
    return "; ".join(
        ".".join(str(part) for part in item["loc"]) + ": " + item["msg"]
        for item in error.errors(include_input=False, include_url=False)
    )


class LongPromptPrices(_Section):
    """The prices for a prompt over the long-prompt threshold."""

    input: float
    output: float
    cache_read: float
    cache_write: float


class ModelPrices(_Section):
    """The prices of 1 model in USD per 1 million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float
    long_prompt_threshold: int | None = None
    long_prompt: LongPromptPrices | None = None


class Prices(_Section):
    """The price table of `config/prices.yaml`, keyed by model id.

    Attributes:
        checked_on: The date the prices were checked on the price page.
        models: The prices per model id.
    """

    checked_on: datetime.date
    models: dict[str, ModelPrices]


def load_prices(path: pathlib.Path) -> Prices:
    """Load the price table.

    Args:
        path: The prices YAML file.

    Returns:
        The validated price table.

    Raises:
        ConfigError: The file is unreadable or fails validation.
    """
    try:
        return Prices.model_validate(read_yaml(path))
    except pydantic.ValidationError as error:
        raise errors.ConfigError(
            f"invalid prices in {path}: {_describe(error)}"
        ) from None


def models_without_prices(settings: Settings, prices: Prices) -> list[str]:
    """List the configured model ids that have no price entry.

    Args:
        settings: The loaded settings.
        prices: The loaded price table.

    Returns:
        The model ids of llm.model, llm.fallback_model, and llm.judge_model
        that are absent from the price table, in that order.
    """
    wanted = [
        settings.llm.model,
        settings.llm.fallback_model,
        settings.llm.judge_model,
    ]
    return [model for model in wanted if model not in prices.models]
