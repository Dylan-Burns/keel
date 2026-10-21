"""Shared fixtures: the repository paths and a settings loader."""

from collections.abc import Sequence
import hashlib
import os
import pathlib

import numpy
import pytest

from keel import config
from keel.stores import numpy_dense

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


class FakeEmbedder:
    """Deterministic unit vectors from a hash of each text."""

    def __init__(self, dimensions: int = numpy_dense.DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.seen: list[str] = []

    def encode(self, texts: Sequence[str]) -> numpy_dense.Vectors:
        self.seen.extend(texts)
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8])
            row = numpy.random.default_rng(seed).standard_normal(
                self.dimensions
            )
            rows.append(row / numpy.linalg.norm(row))
        return numpy.asarray(rows, dtype=numpy.float32).reshape(
            len(texts), self.dimensions
        )
