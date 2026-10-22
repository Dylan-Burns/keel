"""`keel warm-cache`: the facts pre-fetch and the demo answer cache.

The answers run through `Answerer.ask` on a synthetic index of AAPL, TSLA,
and JPM risk chunks with a recorded provider (the mock stream under
another name, so the pipeline writes its answers into the cache as it
does for the real model). The facts pre-fetch runs on a mock transport;
no test reaches the network.
"""

import argparse
import asyncio
import dataclasses
import json
import pathlib
import socket

import httpx
import pytest

import conftest
from keel import answer
from keel import config
from keel import edgar
from keel import errors
from keel import retriever
from keel import understanding
from keel import warm_cache
from keel.evaluation import golden
from keel.providers import mock
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

FakeFiling = conftest.FakeFiling
FILINGS = (
    FakeFiling("AAPL", "10-K", "2025-09-27", "2025-10-31", 2025),
    FakeFiling("TSLA", "10-K", "2025-12-31", "2026-01-29", 2025),
    FakeFiling("JPM", "10-K", "2025-12-31", "2026-02-13", 2025),
)
WORDS = ("supply", "tariffs", "privacy", "antitrust", "credit", "labor")
EDGAR_FIXTURES = conftest.FIXTURES / "edgar"
NVDA_FACTS = EDGAR_FIXTURES / "companyfacts" / "CIK0001045810.json"
PUBLIC_IP = "93.184.215.14"
GOLDEN = """\
version: 1.0.0
created: "2026-10-22"
index_version: 1.0.0
questions:
  - id: G-01
    type: comparison
    question: >-
      What are the primary risk factors facing Apple, Tesla, and JPMorgan,
      and how do they compare?
  - id: G-02
    type: single_company
    question: What are the risk factors of Tesla?
  - id: G-03
    type: out_of_corpus
    question: What is Apple's stock price today?
    expect_out_of_scope: true
"""


class RecordedProvider(mock.MockProvider):
    """The mock stream under another name: its answers enter the cache."""

    name = "recorded"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise OSError(f"network access in a test: {args}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def index_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    chunks = [
        conftest.make_chunk(
            filing,
            "risk_factors",
            k,
            f"Risk factors: {filing.ticker} names {WORDS[k]} risk in "
            f"{2020 + k} with {k + 1},000 million exposure "
            + " ".join(f"{w}{k}{filing.ticker}" for w in WORDS),
        )
        for filing in FILINGS
        for k in range(len(WORDS))
    ]
    return conftest.build_store(tmp_path / "index", FILINGS, chunks)


@pytest.fixture
def run_settings(
    settings: config.Settings, tmp_path: pathlib.Path
) -> config.Settings:
    return settings.model_copy(
        update={
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "edgar": settings.edgar.model_copy(
                update={"cache_dir": tmp_path / "edgar"}
            ),
        }
    )


@pytest.fixture
def golden_path(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "golden.yaml"
    path.write_text(GOLDEN, encoding="utf-8")
    return path


async def _no_wait(_seconds: float) -> None:
    """Skip the pause between EDGAR requests."""


def make(
    index_dir: pathlib.Path,
    run_settings: config.Settings,
    provider: mock.MockProvider,
) -> answer.Answerer:
    build = index_dir / "current"
    step = retriever.Retriever(
        chunk_store.open_read_only(build / chunk_store.FILE_NAME),
        numpy_dense.load(build / numpy_dense.FILE_NAME),
        conftest.FakeEmbedder(),
        conftest.FakeReranker(),
        run_settings,
    )
    return answer.Answerer(
        run_settings,
        step,
        provider,
        "1.0.0",
        sleep=_no_wait,
        facts_loader=lambda analysis: edgar.FactsResult(),
    )


def questions(
    run_settings: config.Settings, golden_path: pathlib.Path
) -> tuple[warm_cache.DemoQuestion, ...]:
    return warm_cache.demo_questions(
        run_settings.demo.example_questions, golden.load_golden(golden_path)
    )


def offline_final(answerer: answer.Answerer, text: str) -> dict:
    async def run() -> dict:
        record: dict = {}
        async for event in answerer.ask(text):
            if event.name == "final":
                record = event.data
        return record

    return asyncio.run(run())


def facts_handler(request: httpx.Request) -> httpx.Response:
    """Serve NVDA's recorded facts, an empty body for MSFT, else 404."""
    if request.url.path.endswith("company_tickers.json"):
        cached = json.loads(
            (EDGAR_FIXTURES / "company_tickers.json").read_text()
        )
        return httpx.Response(200, json=cached["data"])
    if request.url.path.endswith("CIK0001045810.json"):
        body = json.loads(NVDA_FACTS.read_text())["data"]
        return httpx.Response(200, json=body)
    if request.url.path.endswith("CIK0000789019.json"):
        return httpx.Response(200, json={"cik": 789019, "facts": {}})
    return httpx.Response(404)


def facts_client(cache_dir: pathlib.Path) -> edgar.EdgarClient:
    return edgar.EdgarClient(
        "Keel Test test@example.com",
        cache_dir,
        transport=httpx.MockTransport(facts_handler),
        resolver=lambda host: [PUBLIC_IP],
        sleep=lambda seconds: None,
    )


def test_warm_cache_complete(
    index_dir: pathlib.Path,
    run_settings: config.Settings,
    golden_path: pathlib.Path,
) -> None:
    """Every demo question gets an entry; offline serves each one."""
    items = questions(run_settings, golden_path)
    # The example question equal to G-01 is listed once, under its ID.
    assert [q.label for q in items] == [
        "G-01",
        "example 2",
        "example 3",
        "G-02",
        "G-03",
    ]
    provider = RecordedProvider(run_settings.llm.model)
    answerer = make(index_dir, run_settings, provider)
    results = asyncio.run(warm_cache.warm_answers(answerer, items))
    status = {r.label: r.status for r in results}
    assert status["G-03"] == "refusal"
    assert next(r for r in results if r.label == "G-03").model_requests == 0
    assert all(answerer.cache.get(answerer.cache_key(q.text)) for q in items)
    assert provider.requests == sum(r.model_requests for r in results)
    assert all(r.model_requests == 1 for r in results if r.status == "answered")

    # Offline, every question comes from the cache with 0 model requests.
    offline_settings = run_settings.model_copy(update={"offline": True})
    silent = mock.MockProvider(run_settings.llm.model)
    offline = make(index_dir, offline_settings, silent)
    for item in items:
        record = offline_final(offline, item.text)
        assert record["meta"]["from_cache"] is True, item.label
        assert record["meta"]["model_requests"] == 0
    assert silent.requests == 0
    refusal = offline_final(offline, items[-1].text)
    assert refusal["outcome"] == "out_of_scope"

    # A second run skips every question; --refresh answers them again.
    again = asyncio.run(warm_cache.warm_answers(answerer, items))
    assert {r.status for r in again} == {"skipped"}
    before = provider.requests
    lines: list[str] = []
    fresh = asyncio.run(
        warm_cache.warm_answers(
            answerer, items, refresh=True, printer=lines.append
        )
    )
    assert {r.status for r in fresh} == {"answered", "refusal"}
    assert provider.requests > before
    assert len(lines) == len(items)


def test_warm_cache_failed_answer_is_reported(
    index_dir: pathlib.Path,
    run_settings: config.Settings,
    golden_path: pathlib.Path,
) -> None:
    """A provider failure leaves no entry and reads as failed."""
    items = questions(run_settings, golden_path)[:1]
    down = RecordedProvider(run_settings.llm.model, fault="529-before-content")
    answerer = make(index_dir, run_settings, down)
    answerer.fallback = None
    answerer.settings = run_settings.model_copy(
        update={"llm": run_settings.llm.model_copy(update={"max_retries": 0})}
    )
    (result,) = asyncio.run(warm_cache.warm_answers(answerer, items))
    assert result.status == "failed"
    assert answerer.cache.get(answerer.cache_key(items[0].text)) is None


def test_prefetch_facts(tmp_path: pathlib.Path) -> None:
    """Each ticker is fetched once, then served from the cache."""
    facts_config = edgar.load_facts_config(
        conftest.REPO_ROOT / "config" / "facts.yaml"
    )
    tickers = ("MSFT", "NVDA", "AAPL", "QQQQQ")
    with facts_client(tmp_path / "edgar") as client:
        first = warm_cache.prefetch_facts(client, facts_config, tickers)
    assert first.fetched == ("MSFT", "NVDA")
    assert first.no_lines == ("MSFT",)
    assert [f.split(":")[0] for f in first.failed] == ["AAPL", "QQQQQ"]
    # The ticker map, MSFT, NVDA, and the AAPL 404.
    assert first.requests == 4
    with facts_client(tmp_path / "edgar") as client:
        second = warm_cache.prefetch_facts(client, facts_config, ("NVDA",))
    assert second.cached == ("NVDA",)
    assert second.requests == 0


def test_corpus_tickers_include_quarantine_and_extras(
    index_dir: pathlib.Path, run_settings: config.Settings
) -> None:
    answerer = make(
        index_dir, run_settings, mock.MockProvider(run_settings.llm.model)
    )
    catalog = dataclasses.replace(
        answerer.retriever.catalog,
        quarantined=(
            understanding.QuarantineNote(
                "GE", "GE_10K_2015-02-27_full.txt", "registrant_mismatch", ""
            ),
        ),
    )
    tickers = warm_cache.corpus_tickers(catalog, ["zts", "WDAY"])
    assert tickers == ("AAPL", "GE", "JPM", "TSLA", "WDAY", "ZTS")


def _args(golden_path: pathlib.Path, **flags: bool) -> argparse.Namespace:
    return argparse.Namespace(
        golden=golden_path,
        refresh=flags.get("refresh", False),
        facts_only=flags.get("facts_only", False),
        index=None,
    )


def test_run_reports_facts_and_entries(
    index_dir: pathlib.Path,
    run_settings: config.Settings,
    golden_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`keel warm-cache` end to end with the open steps replaced."""
    provider = RecordedProvider(run_settings.llm.model)
    answerer = make(index_dir, run_settings, provider)
    settings = run_settings.model_copy(
        update={
            "demo": run_settings.demo.model_copy(
                update={"add_companies": ["NVDA"]}
            )
        }
    )
    monkeypatch.setattr(
        answer.Answerer, "open", lambda *args, **kwargs: answerer
    )
    monkeypatch.setattr(
        edgar.EdgarClient,
        "from_settings",
        lambda *args, **kwargs: facts_client(settings.edgar.cache_dir),
    )
    lines: list[str] = []
    code = warm_cache.run(
        settings, _args(golden_path, facts_only=True), lines.append
    )
    # AAPL, JPM, and TSLA have no file on the mock transport.
    assert code == 1
    assert lines[0].startswith("facts: 4 tickers, 1 fetched")
    lines.clear()
    code = warm_cache.run(settings, _args(golden_path), lines.append)
    assert lines[-1].startswith("answer cache: 5 of 5 questions")
    # Examples 2 and 3 name companies outside the synthetic index.
    assert "2 refusals stored" in lines[-1]
    assert code == 1  # the facts of 3 tickers are still missing


def test_run_refuses_offline(
    run_settings: config.Settings, golden_path: pathlib.Path
) -> None:
    offline = run_settings.model_copy(update={"offline": True})
    with pytest.raises(errors.ConfigError, match="KEEL_OFFLINE"):
        warm_cache.run(offline, _args(golden_path))
