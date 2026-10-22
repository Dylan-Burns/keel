"""The question pipeline with the mock provider on a synthetic index.

Each test writes a small published index of AAPL, TSLA, and JPM risk
chunks, opens the retriever with the fake embedder and reranker, and runs
`Answerer.ask` with the mock provider, so the request counter, the stream,
the retries, the validator, the answer cache, and the audit log run as
they do in `keel ask`.
"""

import asyncio
import json
import pathlib
import shutil

import pytest

import conftest
from keel import answer
from keel import cache
from keel import cli
from keel import config
from keel import context
from keel import edgar
from keel import errors
from keel import retriever
from keel.providers import base
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
            # An empty EDGAR cache: no test reads the developer's cache.
            "edgar": settings.edgar.model_copy(
                update={"cache_dir": tmp_path / "edgar"}
            ),
        }
    )


class Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def no_facts(analysis) -> edgar.FactsResult:
    del analysis
    return edgar.FactsResult()


def make(
    index_dir: pathlib.Path,
    run_settings: config.Settings,
    provider: mock.MockProvider | None = None,
    sleeps: Sleeps | None = None,
    facts_loader: answer.FactsLoader | None = None,
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
        provider or mock.MockProvider(run_settings.llm.model),
        "1.0.0",
        sleep=sleeps or Sleeps(),
        # No test reaches the SEC: the default loader runs only when a test
        # calls `load_facts` itself, offline.
        facts_loader=facts_loader or no_facts,
    )


def question(run_settings: config.Settings) -> str:
    return run_settings.demo.example_questions[0]


def ask(answerer: answer.Answerer, text: str, **kwargs) -> list[answer.Event]:
    async def run() -> list[answer.Event]:
        return [event async for event in answerer.ask(text, **kwargs)]

    return asyncio.run(run())


def final(events: list[answer.Event]) -> dict:
    return next(e.data for e in events if e.name == "final")


def audit_lines(run_settings: config.Settings) -> list[dict]:
    path = run_settings.logs.dir / "audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_single_request(index_dir, run_settings) -> None:
    provider = mock.MockProvider(run_settings.llm.model)
    answerer = make(index_dir, run_settings, provider)
    events = ask(answerer, question(run_settings), request_id="r-1")
    assert provider.requests == 1
    record = final(events)
    assert record["outcome"] == "answered"
    assert record["meta"]["model_requests"] == 1
    assert record["request_id"] == "r-1"
    tickers = {c["ticker"] for c in record["citations_resolved"]}
    assert tickers == {"AAPL", "TSLA", "JPM"}
    assert all(c["valid"] for c in record["citations_resolved"])
    assert record["meta"]["flags"]["citation_drift"] == 0
    assert record["meta"]["cost_usd"] > 0
    assert record["meta"]["prompt_hash"].startswith("sha256:")
    lines = audit_lines(run_settings)
    assert len(lines) == 1
    line = lines[0]
    assert line["model_requests"] == 1
    assert line["request_id"] == "r-1"
    assert line["tickers"] == ["AAPL", "TSLA", "JPM"]
    assert len(line["chunk_ids"]) == len(provider.bundles[0].chunk_ids)
    assert line["model"] == run_settings.llm.model
    assert line["index_version"] == "1.0.0"
    assert "prompt" not in line
    assert provider.bundles[0].user not in json.dumps(line)


def test_stream_deltas(index_dir, run_settings) -> None:
    provider = mock.MockProvider(run_settings.llm.model, chunk_size=9)
    events = ask(
        make(index_dir, run_settings, provider), question(run_settings)
    )
    names = [e.name for e in events]
    assert names[:3] == ["meta", "analysis", "retrieval"]
    assert names[-2:] == ["final", "done"]
    first_delta = names.index("answer_delta")
    assert first_delta < names.index("findings") < names.index("final")
    assert names.count("answer_delta") > 3
    text = "".join(e.data["text"] for e in events if e.name == "answer_delta")
    record = final(events)
    assert text == record["answer"]["direct_answer"]
    found = [e.data["ticker"] for e in events if e.name == "findings"]
    assert found == ["AAPL", "TSLA", "JPM"]
    assert record["meta"]["latency_ms"]["first_token"] is not None
    assert events[0].data["model"] == run_settings.llm.model


def test_malformed_json_path(index_dir, run_settings, caplog) -> None:
    for fault in ("malformed-json", "no-tool-call"):
        provider = mock.MockProvider(run_settings.llm.model, fault=fault)
        events = ask(
            make(index_dir, run_settings, provider), question(run_settings)
        )
        record = final(events)
        assert provider.requests == 1  # no retry (D-04)
        assert record["outcome"] == "schema_violation"
        assert record["answer"] is None
        assert record["raw_text"]
        assert record["message"] == answer.SCHEMA_WARNING
        assert record["meta"]["flags"]["schema_violation"]
    assert "schema_violation" in caplog.text
    flags = [
        line["flags"]["schema_violation"] for line in audit_lines(run_settings)
    ]
    assert flags == [True, True]
    assert not list(run_settings.cache.answers_dir.glob("*.json"))


def test_retry_before_content(index_dir, run_settings) -> None:
    sleeps = Sleeps()
    provider = mock.MockProvider(
        run_settings.llm.model, fault="529-before-content"
    )
    events = ask(
        make(index_dir, run_settings, provider, sleeps), question(run_settings)
    )
    assert provider.requests == 2
    assert sleeps.waits == [0.0]  # the Retry-After of the mock
    record = final(events)
    assert record["outcome"] == "answered"
    assert record["meta"]["model_requests"] == 2
    assert "error" not in [e.name for e in events]
    assert audit_lines(run_settings)[-1]["model_requests"] == 2
    assert record["audit"]["failed_before_content"] == 1
    # 3 failures: the first request and 2 retries, then the error event.
    sleeps = Sleeps()
    down = mock.MockProvider(
        run_settings.llm.model, fault="500-before-content:3"
    )
    events = ask(
        make(index_dir, run_settings, down, sleeps), question(run_settings)
    )
    assert down.requests == 3
    assert sleeps.waits == [2.0, 6.0]
    error = next(e.data for e in events if e.name == "error")
    assert error["code"] == "provider_unavailable"
    record = final(events)
    assert record["outcome"] == "provider_error"
    assert record["meta"]["degraded"]
    assert record["retrieval"]["chunks"]


def test_no_retry_after_content(index_dir, run_settings) -> None:
    provider = mock.MockProvider(
        run_settings.llm.model, fault="disconnect-after-content", chunk_size=5
    )
    sleeps = Sleeps()
    events = ask(
        make(index_dir, run_settings, provider, sleeps), question(run_settings)
    )
    names = [e.name for e in events]
    assert provider.requests == 1
    assert sleeps.waits == []
    assert names.index("answer_delta") < names.index("error")
    error = next(e.data for e in events if e.name == "error")
    partial = "".join(
        e.data["text"] for e in events if e.name == "answer_delta"
    )
    assert error["partial"] == partial
    assert final(events)["outcome"] == "provider_error"
    assert audit_lines(run_settings)[-1]["error"] == "provider_unavailable"


def test_context_overflow_halves(index_dir, run_settings, caplog) -> None:
    """E-C-01: a context error before content halves the context once."""
    provider = mock.MockProvider(
        run_settings.llm.model, fault="context-overflow"
    )
    sleeps = Sleeps()
    answerer = make(index_dir, run_settings, provider, sleeps)
    factor = answerer.calibration.factor
    events = ask(answerer, question(run_settings))
    assert provider.requests == 2
    assert sleeps.waits == []
    first, second = provider.bundles
    assert len(second.chunk_ids) < len(first.chunk_ids)
    assert set(second.chunk_ids) <= set(first.chunk_ids)
    record = final(events)
    assert record["outcome"] == "answered"
    assert record["meta"]["model_requests"] == 2
    assert len(record["retrieval"]["chunks"]) == len(second.chunk_ids)
    before = next(e.data for e in events if e.name == "retrieval")
    halved = record["retrieval"]["token_estimate"]
    assert halved <= before["token_estimate"] // 2
    assert answerer.calibration.factor == round(factor * 1.05, 4)
    assert "context_overflow" in caplog.text
    # The halved retry is the only one: a second overflow ends the answer.
    again = mock.MockProvider(
        run_settings.llm.model, fault="context-overflow:3"
    )
    events = ask(make(index_dir, run_settings, again), question(run_settings))
    assert again.requests == 2
    error = next(e.data for e in events if e.name == "error")
    assert error["code"] == "context_overflow"
    assert final(events)["meta"]["degraded"] is True


def test_offline_cache_hit(index_dir, run_settings) -> None:
    online = make(index_dir, run_settings)
    record = final(ask(online, question(run_settings)))
    online.cache.put(online.cache_key(question(run_settings)), record)
    offline_settings = run_settings.model_copy(update={"offline": True})
    provider = mock.MockProvider(run_settings.llm.model)
    offline = make(index_dir, offline_settings, provider)
    events = ask(offline, question(run_settings))
    assert [e.name for e in events] == ["meta", "final", "done"]
    cached = final(events)
    assert cached["meta"]["from_cache"] is True
    assert cached["meta"]["model_requests"] == 0
    assert cached["answer"] == record["answer"]
    assert cached["request_id"] != record["request_id"]
    assert provider.requests == 0
    assert audit_lines(run_settings)[-1]["outcome"] == "cached"
    # The final event carries the audit record of this request, not the
    # record stored with the cached answer.
    assert cached["audit"] == audit_lines(run_settings)[-1]
    assert cached["audit"]["request_id"] == cached["request_id"]
    assert cached["audit"]["flags"]["from_cache"] is True
    # A question that is not in the cache gets the retrieval, no request.
    events = ask(offline, "What are the risk factors of Tesla?")
    missed = final(events)
    assert missed["outcome"] == "offline"
    assert missed["retrieval"]["chunks"]
    assert missed["meta"]["degraded"]
    assert provider.requests == 0


def test_cache_after_failure_and_on_request(index_dir, run_settings) -> None:
    online = make(index_dir, run_settings)
    record = final(ask(online, question(run_settings)))
    online.cache.put(online.cache_key(question(run_settings)), record)
    down = mock.MockProvider(
        run_settings.llm.model, fault="529-before-content:3"
    )
    events = ask(make(index_dir, run_settings, down), question(run_settings))
    names = [e.name for e in events]
    assert names[-3:] == ["error", "final", "done"]
    assert final(events)["meta"]["from_cache"] is True
    assert final(events)["meta"]["model_requests"] == 3
    line = audit_lines(run_settings)[-1]
    assert line["model_requests"] == 3
    assert line["outcome"] == "cached"
    assert line["error"] == "provider_rate_limited"
    # The trace names the cached context, not the retrieval of the failure.
    assert line["failed_before_content"] == 3
    assert line["filters"] == []
    assert line["tickers"] == record["analysis"]["tickers"]
    cached_ids = [c["chunk_id"] for c in record["retrieval"]["chunks"]]
    assert line["chunk_ids"] == cached_ids
    assert line["chunk_count"] == len(cached_ids)
    provider = mock.MockProvider(run_settings.llm.model)
    events = ask(
        make(index_dir, run_settings, provider),
        question(run_settings),
        use_cache=True,
    )
    assert final(events)["meta"]["from_cache"] is True
    assert provider.requests == 0


def test_cache_entry_without_audit(index_dir, run_settings) -> None:
    provider = mock.MockProvider(run_settings.llm.model)
    provider.name = "real"  # a non-mock provider writes the cache
    answerer = make(index_dir, run_settings, provider)
    record = final(ask(answerer, question(run_settings)))
    assert record["audit"]["model_requests"] == 1
    entry = answerer.cache.get(answerer.cache_key(question(run_settings)))
    assert entry is not None
    assert "audit" not in entry


def test_mock_answers_never_cached(index_dir, run_settings) -> None:
    answerer = make(index_dir, run_settings)
    ask(answerer, question(run_settings))
    assert (
        answerer.cache.get(answerer.cache_key(question(run_settings))) is None
    )


def test_no_request_paths(index_dir, run_settings, monkeypatch) -> None:
    provider = mock.MockProvider(run_settings.llm.model)
    answerer = make(index_dir, run_settings, provider)
    rejected = ask(answerer, "  ")
    assert rejected[1].name == "error"
    assert rejected[1].data["code"] == "invalid_question"
    outside = final(ask(answerer, "What is the weather in Paris tomorrow?"))
    assert outside["outcome"] == "out_of_scope"
    assert outside["message"].startswith("Out of scope")
    real = answerer.retriever.retrieve

    def empty(analysis, budget=None):
        result = real(analysis, budget)
        nothing = context.build_context(
            [], [], result.context.budget, company_order=(), section_weights={}
        )
        return retriever.RetrievalResult(
            plan=result.plan,
            context=nothing,
            candidates=0,
            collapsed=0,
            reranked=0,
            gaps=(),
            degraded=(),
            timings=result.timings,
        )

    monkeypatch.setattr(answerer.retriever, "retrieve", empty)
    blank = final(ask(answerer, question(run_settings)))
    assert blank["outcome"] == "no_context"
    assert blank["message"] == context.NO_CONTEXT_MESSAGE
    assert provider.requests == 0
    outcomes = [line["outcome"] for line in audit_lines(run_settings)]
    assert outcomes == ["rejected", "out_of_scope", "no_context"]


def test_calibration_wired(index_dir, run_settings) -> None:
    provider = mock.MockProvider(run_settings.llm.model)
    answerer = make(index_dir, run_settings, provider)
    real = provider._usage

    def doubled(bundle, text):
        usage = real(bundle, text)
        return usage.__class__(
            usage.input_tokens * 2, 0, usage.cache_write_tokens, 10
        )

    provider._usage = doubled
    ask(answerer, question(run_settings))
    factor = answerer.calibration.factor
    assert factor > run_settings.retrieval.calibration_factor
    first = provider.bundles[0].estimated_tokens
    ask(answerer, question(run_settings))
    # The next budget uses the session factor, so the estimate grows.
    assert provider.bundles[1].estimated_tokens > first


def test_helpers(run_settings) -> None:
    assert answer.prompt_supported("1.0.0", ">=1.0.0,<2.0.0")
    assert not answer.prompt_supported("2.0.0", ">=1.0.0,<2.0.0")
    assert answer.prompt_supported("1.2.0", "==1.2.0")
    assert not answer.prompt_supported("0.9.0", ">0.9.0")
    assert answer.prompt_supported("1.0.0", "<=1.0.0")
    limited = errors.ProviderRateLimitedError("x")
    assert answer.backoff(limited, 0) == 2.0
    assert answer.backoff(limited, 5) == 6.0
    assert answer.backoff(errors.ProviderRateLimitedError("x", 4.0), 0) == 4.0
    assert (
        answer.backoff(errors.ProviderRateLimitedError("x", 900.0), 0) == 30.0
    )
    slow = answer.backoff(errors.ProviderTimeoutError("t"), 1)
    assert 3.0 <= slow <= 3.5
    made = answer.provider_from_settings(
        run_settings.model_copy(
            update={
                "llm": run_settings.llm.model_copy(update={"provider": "mock"})
            }
        ),
        fault="slow-stream",
    )
    assert isinstance(made, mock.MockProvider)
    assert made.fault == "slow-stream"
    with pytest.raises(errors.ConfigError, match=r"unknown llm\.provider"):
        answer.provider_from_settings(
            run_settings.model_copy(
                update={
                    "llm": run_settings.llm.model_copy(update={"provider": "x"})
                }
            )
        )
    with pytest.raises(errors.ProviderRequestError):
        answer.provider_from_settings(run_settings)
    with pytest.raises(errors.IndexMissingError):
        answer.Answerer.open(run_settings, pathlib.Path("/nonexistent-index"))


def test_sec_urls(index_dir) -> None:
    conn = chunk_store.open_read_only(
        index_dir / "current" / chunk_store.FILE_NAME
    )
    ids = [f.filing_id for f in FILINGS]
    assert answer.sec_urls(conn, []) == {}
    assert answer.sec_urls(conn, ids) == dict.fromkeys(ids)


def test_cache_key_names_the_model(index_dir, run_settings) -> None:
    answerer = make(index_dir, run_settings)
    expected = cache.cache_key(
        question(run_settings),
        "1.0.0",
        run_settings.llm.prompt_version,
        run_settings.llm.model,
    )
    assert answerer.cache_key(question(run_settings)) == expected


def test_ask_command(index_dir, run_settings, monkeypatch, capsys) -> None:
    def opened(settings, index=None):
        return make(index_dir, run_settings)

    monkeypatch.setattr(answer.Answerer, "open", opened)
    code = cli.run_ask(
        run_settings,
        question(run_settings),
        as_json=False,
        cached=False,
        index_dir=None,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "citations:" in out
    assert "1 request(s)" in out
    assert "citation drift 0" in out
    code = cli.run_ask(
        run_settings,
        question(run_settings),
        as_json=True,
        cached=False,
        index_dir=None,
    )
    record = json.loads(capsys.readouterr().out)
    assert code == 0
    assert record["meta"]["model_requests"] == 1

    def failing(settings, index=None):
        return make(
            index_dir,
            run_settings,
            mock.MockProvider(run_settings.llm.model, fault="malformed-json"),
        )

    monkeypatch.setattr(answer.Answerer, "open", failing)
    cli.run_ask(
        run_settings,
        question(run_settings),
        as_json=False,
        cached=False,
        index_dir=None,
    )
    out = capsys.readouterr().out
    assert answer.SCHEMA_WARNING in out
    down = mock.MockProvider(
        run_settings.llm.model, fault="500-before-content:3"
    )

    def broken(settings, index=None):
        return make(index_dir, run_settings, down)

    monkeypatch.setattr(answer.Answerer, "open", broken)
    code = cli.run_ask(
        run_settings,
        question(run_settings),
        as_json=False,
        cached=False,
        index_dir=None,
    )
    assert code == 1
    assert "error provider_unavailable" in capsys.readouterr().out


class FindingsFirst(mock.MockProvider):
    """Streams a company object first, then fails: content was sent."""

    async def answer(self, bundle):
        self.requests += 1
        company = {"ticker": "AAPL", "company": "Apple", "findings": []}
        yield base.JsonDelta(
            '{"company_findings": [' + json.dumps(company) + "], "
        )
        raise errors.ProviderRateLimitedError("529 after findings", 0.0)


def test_no_retry_after_findings(index_dir, run_settings) -> None:
    provider = FindingsFirst(run_settings.llm.model)
    events = ask(
        make(index_dir, run_settings, provider), question(run_settings)
    )
    names = [e.name for e in events]
    assert provider.requests == 1
    assert names.index("findings") < names.index("error")
    assert final(events)["meta"]["latency_ms"]["first_token"] is not None


def test_prompt_and_output_mode_must_match(index_dir, run_settings) -> None:
    # Prompt 1.2.0 asks for the answer tool; json_schema sends no tool.
    mismatched = run_settings.model_copy(
        update={
            "llm": run_settings.llm.model_copy(
                update={"prompt_version": "1.2.0", "output_mode": "json_schema"}
            )
        }
    )
    with pytest.raises(errors.ConfigError, match="output mode"):
        make(index_dir, mismatched)
    matched = mismatched.model_copy(
        update={
            "llm": mismatched.llm.model_copy(update={"output_mode": "tool"})
        }
    )
    assert make(index_dir, matched).files.output_mode == "tool"


NUMERIC = "What was Apple's revenue in fiscal 2025?"
EDGAR_FIXTURES = conftest.FIXTURES / "edgar"


def nvda_result() -> edgar.FactsResult:
    """The NVDA facts of the recorded fixture, served as AAPL lines."""
    data = edgar.read_cached(
        EDGAR_FIXTURES / "companyfacts" / "CIK0001045810.json"
    ).data
    facts_config = edgar.load_facts_config(
        conftest.REPO_ROOT / "config" / "facts.yaml"
    )
    block = edgar.facts_lines(data, "AAPL", facts_config, max_lines=3)
    return edgar.FactsResult(blocks=(block,), source="cache", files=1)


def test_facts_in_the_answer(index_dir, run_settings) -> None:
    """A numeric question sends <facts>, cites a fact, and audits the count."""
    seen = []

    def loader(analysis):
        seen.append(analysis.tickers)
        return nvda_result()

    provider = mock.MockProvider(run_settings.llm.model)
    answerer = make(index_dir, run_settings, provider, facts_loader=loader)
    record = final(ask(answerer, NUMERIC))
    assert seen == [("AAPL",)]
    bundle = provider.bundles[0]
    assert "<facts>" in bundle.user
    assert len(bundle.fact_ids) == 3
    assert record["outcome"] == "answered"
    assert record["meta"]["facts"] == {
        "lines": 3,
        "source": "cache",
        "files": 1,
        "errors": [],
    }
    facts = [c for c in record["citations_resolved"] if c["kind"] == "fact"]
    assert [c["chunk_id"] for c in facts] == [bundle.fact_ids[0]]
    assert facts[0]["sec_url"].startswith("https://www.sec.gov/Archives/")
    assert record["meta"]["flags"]["citation_drift"] == 0
    line = audit_lines(run_settings)[0]
    assert line["facts_lines"] == 3
    assert line["facts_source"] == "cache"
    assert line["fact_ids"] == list(bundle.fact_ids)
    assert line["facts_errors"] == []
    # The cached prefix is the same with and without facts.
    plain = mock.MockProvider(run_settings.llm.model)
    ask(make(index_dir, run_settings, plain), question(run_settings))
    assert plain.bundles[0].system == bundle.system
    assert "<facts>" not in plain.bundles[0].user


def test_facts_never_block_the_answer(index_dir, run_settings) -> None:
    def broken(analysis):
        raise RuntimeError("the cache is on fire")

    provider = mock.MockProvider(run_settings.llm.model)
    answerer = make(index_dir, run_settings, provider, facts_loader=broken)
    record = final(ask(answerer, NUMERIC))
    assert record["outcome"] == "answered"
    assert provider.requests == 1
    assert "<facts>" not in provider.bundles[0].user
    assert record["meta"]["facts"]["source"] == "none"
    assert record["meta"]["facts"]["errors"] == [
        "RuntimeError: the cache is on fire"
    ]
    line = audit_lines(run_settings)[0]
    assert (line["facts_lines"], line["facts_source"]) == (0, "none")


def test_facts_only_for_numeric_questions(index_dir, run_settings) -> None:
    calls = []
    answerer = make(
        index_dir,
        run_settings,
        facts_loader=lambda analysis: calls.append(analysis) or nvda_result(),
    )
    record = final(ask(answerer, question(run_settings)))
    assert calls == []
    assert record["meta"]["facts"]["lines"] == 0
    older = run_settings.model_copy(
        update={
            "llm": run_settings.llm.model_copy(
                update={"prompt_version": "1.3.0"}
            )
        }
    )
    final(ask(make(index_dir, older, facts_loader=calls.append), NUMERIC))
    assert calls == []  # 1.3.0 has no <facts> slot


def test_load_facts_reads_the_cache_offline(
    index_dir, run_settings, tmp_path
) -> None:
    """The default loader reads the EDGAR cache; failures become errors."""
    cache_dir = tmp_path / "edgar"
    shutil.copytree(EDGAR_FIXTURES, cache_dir)
    offline = run_settings.model_copy(
        update={
            "offline": True,
            "edgar": run_settings.edgar.model_copy(
                update={"cache_dir": cache_dir}
            ),
        }
    )
    answerer = make(index_dir, offline)
    # The synthetic index has no NVDA, so the analysis names it directly.
    analysis = answerer.understander.analyze(NUMERIC).model_copy(
        update={"tickers": ("NVDA",), "windows": {}}
    )
    result = answerer.load_facts(analysis)
    assert result.source == "cache"
    assert "facts:NVDA:Revenues:FY2025" in result.by_id()
    client = answerer._edgar
    assert answerer.load_facts(analysis).lines == result.lines
    assert answerer._edgar is client  # 1 client keeps the rate limit
    missing = offline.model_copy(
        update={
            "edgar": offline.edgar.model_copy(
                update={"facts": tmp_path / "absent.yaml"}
            )
        }
    )
    failed = make(index_dir, missing).load_facts(analysis)
    assert failed.source == "none"
    assert len(failed.errors) == 1


def test_facts_line_of_ask() -> None:
    line = cli._facts_line
    assert line({"lines": 40, "source": "cache", "files": 1, "errors": []}) == (
        "facts: 40 lines from 1 cached file"
    )
    assert line({"lines": 9, "source": "network", "files": 2}) == (
        "facts: 9 lines from 2 fetched files"
    )
    assert line(
        {"lines": 0, "source": "none", "files": 0, "errors": ["x"]}
    ) == ("facts: 0 lines; facts error: x")
