"""Shared fixtures: the repository paths and a settings loader."""

import os
import pathlib

import pytest

from keel import config

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
MINI_CORPUS = FIXTURES / "mini_corpus"
SNIPPETS = FIXTURES / "snippets"
CONFIG_FILE = REPO_ROOT / "config" / "keel.yaml"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every KEEL_ variable and the provider key from the env."""
    for name in list(os.environ):
        if name.startswith("KEEL_") or name == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(name)
    return monkeypatch


@pytest.fixture
def settings(clean_env: pytest.MonkeyPatch) -> config.Settings:
    """The repository config, with no environment and no dotenv file."""
    del clean_env
    return config.load_settings(CONFIG_FILE, env_file=None)
