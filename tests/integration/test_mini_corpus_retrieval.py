"""Retrieval on the mini corpus index with the 2 pinned models.

The models come from the local Hugging Face cache; pytest runs with
HF_HUB_OFFLINE=1.
"""

from collections.abc import Iterator
import json
import os
import pathlib

import pytest

import conftest
from keel import cli
from keel import config
from keel import indexer
from keel import retriever
from keel import understanding
from keel.evaluation import labels
from keel.parsers import corpus as parser_corpus
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def module_settings() -> Iterator[config.Settings]:
    """The repository config without KEEL_ variables or the dotenv file."""
    with pytest.MonkeyPatch.context() as patch:
        for name in list(os.environ):
            if name.startswith("KEEL_"):
                patch.delenv(name)
        yield config.load_settings(conftest.CONFIG_FILE, env_file=None)


@pytest.fixture(scope="module")
def index_dir(
    module_settings: config.Settings,
    tmp_path_factory: pytest.TempPathFactory,
) -> pathlib.Path:
    out = tmp_path_factory.mktemp("index")
    indexer.build_index(
        module_settings,
        conftest.MINI_CORPUS,
        out,
        lambda: numpy_dense.SentenceEmbedder.from_settings(module_settings),
    )
    return out


@pytest.fixture(scope="module")
def step(
    module_settings: config.Settings, index_dir: pathlib.Path
) -> retriever.Retriever:
    return retriever.Retriever.open(module_settings, index_dir)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = cli.main(["--config", str(conftest.CONFIG_FILE), *args])
    return code, capsys.readouterr().out


def test_models_load_once(step: retriever.Retriever) -> None:
    assert isinstance(step.reranker, retriever.CrossEncoderReranker)
    assert isinstance(step.embedder, numpy_dense.SentenceEmbedder)
    assert step.degraded == ()
    assert step.catalog.indexed_tickers == ["AAPL", "JPM", "NVDA"]


def test_reranker_returns_logits(step: retriever.Retriever) -> None:
    # score() applies the sigmoid, so the model itself must return raw
    # logits under every sentence-transformers line (3.4 on the Intel
    # laptop, 6.x on Linux). A model that already applied a sigmoid would
    # squash the scores and let the section weights dominate the ranking.
    assert isinstance(step.reranker, retriever.CrossEncoderReranker)
    raw = step.reranker.model.predict(
        [
            ["Apple risk factors", "Apple faces supply chain risk in China."],
            ["Apple risk factors", "The weather in Paris was sunny."],
        ],
        show_progress_bar=False,
    )
    relevant, irrelevant = (float(v) for v in raw)
    assert relevant > 0.0
    assert irrelevant < -1.0
    scores = step.reranker.score([("q", "Apple faces supply chain risk.")])
    assert 0.0 < scores[0] < 1.0


def test_comparison_on_mini_corpus(
    step: retriever.Retriever, module_settings: config.Settings
) -> None:
    understander = understanding.Understander.from_settings(
        module_settings, step.catalog
    )
    analysis = understander.analyze(
        "What are the primary risk factors facing Apple and JPMorgan?"
    )
    result = step.retrieve(analysis)
    chunks = [c.candidate for c in result.context.chunks]
    assert {c.ticker for c in chunks} == {"AAPL", "JPM"}
    # Question order: Apple first, JPMorgan after.
    tickers = [c.ticker for c in chunks]
    assert tickers == sorted(tickers, key=["AAPL", "JPM"].index)
    assert result.reranked > 0
    reranked = [c.rerank for c in chunks if c.rerank is not None]
    assert reranked
    assert all(0.0 < r < 1.0 for r in reranked)
    assert result.context.token_estimate <= 32000
    assert result.timings.rerank_ms > 0


def test_retrieve_command_summary(
    clean_env: pytest.MonkeyPatch,
    index_dir: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del clean_env
    code, out = run(
        capsys,
        "retrieve",
        "What are the primary risk factors facing Apple and JPMorgan?",
        "--summary",
        "--index",
        str(index_dir),
    )
    assert code == 0
    assert "sub-queries: 2" in out
    assert "quota fills" in out
    assert "  AAPL: " in out
    assert "time ms: lexical" in out


def test_retrieve_command_context(
    clean_env: pytest.MonkeyPatch,
    index_dir: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clean_env.setenv("KEEL_INDEX__DIR", str(index_dir))
    code, out = run(capsys, "retrieve", "--question", "2")
    assert code == 0
    assert "type: trend" in out
    assert "NVDA_10K_2025-01-26__" in out
    assert '<chunk id="NVDA_10K_2025-01-26__' in out


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--question", "4"], "--question takes 1 to 3"),
        ([], "give a question or --question N"),
        (["ab"], "HTTP 400"),
        (["What is the weather in Paris?"], "out of scope: off_topic"),
    ],
)
def test_retrieve_command_refusals(
    clean_env: pytest.MonkeyPatch,
    index_dir: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    expected: str,
) -> None:
    clean_env.setenv("KEEL_INDEX__DIR", str(index_dir))
    code, out = run(capsys, "retrieve", *args)
    assert code == 1
    assert expected in out


def test_retrieve_command_no_index(
    clean_env: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del clean_env
    code, _ = run(
        capsys, "retrieve", "--question", "1", "--index", str(tmp_path)
    )
    assert code == 2


def test_understand_reads_the_index(
    clean_env: pytest.MonkeyPatch,
    index_dir: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clean_env.setenv("KEEL_INDEX__DIR", str(index_dir))

    def no_parse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the catalog comes from the index")

    clean_env.setattr(parser_corpus, "parse_corpus", no_parse)
    code, out = run(capsys, "understand", "What risks does NVIDIA face?")
    assert code == 0
    assert '"NVDA"' in out


def test_eval_command_ci_subset(
    clean_env: pytest.MonkeyPatch,
    index_dir: pathlib.Path,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The nightly eval workflow runs this subset on the mini corpus index.
    del clean_env
    report_path = tmp_path / "report.md"
    code, out = run(
        capsys,
        "eval",
        "--set",
        str(conftest.REPO_ROOT / "eval" / "golden.yaml"),
        "--subset",
        "ci",
        "--index",
        str(index_dir),
        "--report",
        str(report_path),
        "--no-ablation",
        "--gate",
    )
    data = json.loads(report_path.with_suffix(".json").read_text("utf-8"))
    blocked = any(g["status"] == "fail" for g in data["gates"])
    assert code == (1 if blocked else 0)
    assert "Refusal correctness: 1.00 (pass)" in out
    text = report_path.read_text(encoding="utf-8")
    assert "subset ci" in text
    outcomes = {r["question_id"]: r["outcome"] for r in data["results"]}
    assert outcomes["G-22"] == "refused"
    assert outcomes["G-24"] == "refused"
    assert outcomes["G-15"] == "scored"
    g15 = next(r for r in data["results"] if r["question_id"] == "G-15")
    # The mini index has other chunk IDs, so the section labels apply.
    assert g15["label_level"] == "section"
    assert g15["metrics"]["mrr"] is not None
    stamp = labels.IndexStamp.from_build(index_dir / "current")
    assert stamp.index_version == data["info"]["index_version"]
    assert stamp.chunks_sha256 == data["info"]["chunks_sha256"]


def test_eval_command_no_index(
    clean_env: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del clean_env
    code, _ = run(
        capsys,
        "eval",
        "--set",
        str(conftest.REPO_ROOT / "eval" / "golden.yaml"),
        "--index",
        str(tmp_path),
        "--report",
        str(tmp_path / "report.md"),
    )
    assert code == 2
