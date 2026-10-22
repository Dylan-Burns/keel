"""The reliability layer of chapter 16 on a synthetic index.

The breaker, the fallback model, the degraded mode, the budget stop, the
refusal path, and the index checks run through `Answerer.ask` and the API
with the mock provider, the fake embedder, and the fake reranker, as in
tests/integration/test_answer.py.
"""

import asyncio
from collections.abc import AsyncIterator
import datetime
import json
import pathlib

import pydantic
import pytest
from starlette import testclient

import conftest
from keel import answer
from keel import config
from keel import errors
from keel import indexer
from keel import prompt
from keel import reliability
from keel import retriever
from keel.api import app as api_app
from keel.api import routes
from keel.providers import base
from keel.providers import mock
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

TOKEN = "test-token"  # noqa: S105
AUTH = {"Authorization": f"Bearer {TOKEN}"}
FakeFiling = conftest.FakeFiling
FILINGS = (
    FakeFiling("AAPL", "10-K", "2025-09-27", "2025-10-31", 2025),
    FakeFiling("TSLA", "10-K", "2025-12-31", "2026-01-29", 2025),
    FakeFiling("JPM", "10-K", "2025-12-31", "2026-02-13", 2025),
)
WORDS = ("supply", "tariffs", "privacy", "antitrust", "credit", "labor")
DOWN = "500-before-content:99"


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
    settings: config.Settings, tmp_path: pathlib.Path, index_dir
) -> config.Settings:
    return settings.model_copy(
        update={
            "api_token": pydantic.SecretStr(TOKEN),
            "llm": settings.llm.model_copy(update={"provider": "mock"}),
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "index": config.IndexConfig(dir=index_dir),
            "corpus": settings.corpus.model_copy(
                update={"dir": tmp_path / "no-corpus"}
            ),
        }
    )


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def no_sleep(_seconds: float) -> None:
    return None


def make(
    index_dir: pathlib.Path,
    run_settings: config.Settings,
    provider: mock.MockProvider | None = None,
    fallback: mock.MockProvider | None = None,
    breaker: reliability.CircuitBreaker | None = None,
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
        sleep=no_sleep,
        fallback=fallback,
        breaker=breaker,
    )


def ask(answerer: answer.Answerer, text: str, **kwargs) -> list[answer.Event]:
    async def run() -> list[answer.Event]:
        return [event async for event in answerer.ask(text, **kwargs)]

    return asyncio.run(run())


def final(events: list[answer.Event]) -> dict:
    return next(e.data for e in events if e.name == "final")


def audit_lines(run_settings: config.Settings) -> list[dict]:
    path = run_settings.logs.dir / "audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def question(run_settings: config.Settings) -> str:
    return run_settings.demo.example_questions[0]


def models(run_settings: config.Settings) -> tuple[str, str]:
    return run_settings.llm.model, run_settings.llm.fallback_model


def test_breaker_opens(index_dir, run_settings) -> None:
    """3 failures open the breaker; the next question uses the fallback."""
    primary_model, fallback_model = models(run_settings)
    clock = Clock()
    breaker = reliability.CircuitBreaker(clock=clock)
    primary = mock.MockProvider(primary_model, fault=DOWN)
    fallback = mock.MockProvider(fallback_model)
    answerer = make(index_dir, run_settings, primary, fallback, breaker)
    first = final(ask(answerer, question(run_settings)))
    # The first question: 3 failed requests open the breaker, and the
    # fallback answers it.
    assert primary.requests == 3
    assert breaker.snapshot().state == reliability.OPEN
    assert first["meta"]["model"] == fallback_model
    assert first["meta"]["model_requests"] == 4
    # While open, the primary model gets no request.
    for _ in range(3):
        record = final(ask(answerer, question(run_settings)))
        assert record["meta"]["model"] == fallback_model
        assert record["meta"]["model_requests"] == 1
    assert primary.requests == 3
    assert fallback.requests == 4
    # After 30 s, 1 probe goes through; it fails and the breaker reopens.
    clock.now += reliability.OPEN_SECONDS
    assert breaker.snapshot().state == reliability.HALF_OPEN
    record = final(ask(answerer, question(run_settings)))
    assert primary.requests == 4
    assert record["meta"]["model"] == fallback_model
    assert breaker.snapshot().state == reliability.OPEN
    assert breaker.snapshot().retry_in == reliability.OPEN_SECONDS
    # The primary model recovers: the next probe closes the breaker.
    answerer.provider = mock.MockProvider(primary_model)
    clock.now += reliability.OPEN_SECONDS
    record = final(ask(answerer, question(run_settings)))
    assert record["meta"]["model"] == primary_model
    assert record["meta"]["fallback"] is False
    assert breaker.snapshot() == reliability.BreakerState("closed", 0, 0.0)


def test_breaker_window_and_kinds() -> None:
    clock = Clock()
    breaker = reliability.CircuitBreaker(clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.now += reliability.FAILURE_WINDOW_SECONDS
    breaker.record_failure()
    # 2 of the 3 failures fell out of the 60 s window.
    assert breaker.snapshot().state == reliability.CLOSED
    assert breaker.snapshot().failures == 1
    breaker.record_success()
    assert breaker.snapshot().failures == 0
    for _ in range(3):
        breaker.record_failure()
    assert not breaker.allow()
    clock.now += reliability.OPEN_SECONDS
    assert breaker.allow()  # the probe
    assert not breaker.allow()  # only 1 probe at a time
    breaker.record_success()
    assert breaker.allow()
    assert breaker.snapshot().as_dict() == {
        "state": "closed",
        "failures": 0,
        "retry_in": 0.0,
    }
    # A rejected request and a context overflow do not count.
    assert reliability.counts_as_failure(errors.ProviderUnavailableError("x"))
    assert reliability.counts_as_failure(errors.ProviderTimeoutError("x"))
    assert not reliability.counts_as_failure(
        errors.ProviderRequestError("bad request")
    )
    assert not reliability.counts_as_failure(errors.ContextOverflowError("x"))


def test_fallback_model_named(index_dir, run_settings) -> None:
    """16.4: after 3 failed requests the fallback answers, and is named."""
    primary_model, fallback_model = models(run_settings)
    primary = mock.MockProvider(primary_model, fault="529-before-content:3")
    fallback = mock.MockProvider(fallback_model)
    answerer = make(index_dir, run_settings, primary, fallback)
    events = ask(answerer, question(run_settings))
    record = final(events)
    assert record["outcome"] == "answered"
    assert record["meta"]["model"] == fallback_model
    assert record["meta"]["fallback"] is True
    assert record["meta"]["model_requests"] == 4
    assert "error" not in [e.name for e in events]
    line = audit_lines(run_settings)[-1]
    assert line["model"] == fallback_model
    assert line["model_requests"] == 4
    # The fallback answer never enters the cache under the primary key.
    assert (
        answerer.cache.get(answerer.cache_key(question(run_settings))) is None
    )
    # The fallback uses the same prompt (the system block and the schema).
    assert fallback.bundles[0].system == primary.bundles[0].system
    assert fallback.bundles[0].tool == primary.bundles[0].tool


def test_fallback_through_the_api(run_settings, index_dir) -> None:
    answerer = make(index_dir, run_settings)
    services = api_app.Services(run_settings, answerer)
    with testclient.TestClient(api_app.create_app(services)) as client:
        response = client.post(
            "/api/ask",
            json={
                "question": question(run_settings),
                "options": {"stream": False},
            },
            headers={**AUTH, "X-Keel-Mock": routes.FALLBACK_FAULT},
        )
        ready = client.get("/api/ready").json()
    body = response.json()
    assert body["outcome"] == "answered"
    assert body["meta"]["model"] == run_settings.llm.fallback_model
    # The drill runs on its own breaker; the service breaker stays closed.
    assert ready["breaker"] == "closed"


def test_fallback_request_matches_the_primary(run_settings) -> None:
    """The fallback request: same output mode, Haiku's thinking setting."""
    live = run_settings.model_copy(
        update={
            "anthropic_api_key": pydantic.SecretStr("sk-test-key-0000"),
            "llm": run_settings.llm.model_copy(
                update={"provider": "anthropic"}
            ),
        }
    )
    fallback = answer.fallback_from_settings(live)
    primary = answer.provider_from_settings(live)
    assert fallback is not None
    assert fallback.model == live.llm.fallback_model
    assert fallback.output_mode == primary.output_mode == "json_schema"
    assert fallback.thinking == live.llm.thinking[live.llm.fallback_model]
    keyless = live.model_copy(update={"anthropic_api_key": None})
    assert answer.fallback_from_settings(keyless) is None
    same = live.model_copy(
        update={
            "llm": live.llm.model_copy(
                update={"fallback_model": live.llm.model}
            )
        }
    )
    assert answer.fallback_from_settings(same) is None
    mocked = answer.fallback_from_settings(run_settings)
    assert isinstance(mocked, mock.MockProvider)
    other = run_settings.model_copy(
        update={"llm": run_settings.llm.model_copy(update={"provider": "x"})}
    )
    assert answer.fallback_from_settings(other) is None


def test_degraded_mode(index_dir, run_settings) -> None:
    """16.5: both models down gives the chunks and `degraded: true`."""
    primary_model, fallback_model = models(run_settings)
    primary = mock.MockProvider(primary_model, fault=DOWN)
    fallback = mock.MockProvider(fallback_model, fault=DOWN)
    events = ask(
        make(index_dir, run_settings, primary, fallback),
        question(run_settings),
    )
    assert primary.requests == 3
    assert fallback.requests == 3
    error = next(e.data for e in events if e.name == "error")
    assert error["code"] == "provider_unavailable"
    record = final(events)
    assert record["outcome"] == "provider_error"
    assert record["answer"] is None
    assert record["meta"]["degraded"] is True
    assert record["meta"]["model_requests"] == 6
    chunks = record["retrieval"]["chunks"]
    assert {c["ticker"] for c in chunks} == {"AAPL", "TSLA", "JPM"}
    assert all("sec_url" in c for c in chunks)
    line = audit_lines(run_settings)[-1]
    assert line["degraded"] is True
    assert line["flags"]["degraded"] is True
    assert line["chunk_ids"]


def test_degraded_mode_without_fallback(index_dir, run_settings) -> None:
    """The breaker is open and no fallback is set: no request at all."""
    clock = Clock()
    breaker = reliability.CircuitBreaker(clock=clock)
    for _ in range(3):
        breaker.record_failure()
    primary = mock.MockProvider(run_settings.llm.model)
    events = ask(
        make(index_dir, run_settings, primary, None, breaker),
        question(run_settings),
    )
    assert primary.requests == 0
    record = final(events)
    assert record["meta"]["degraded"] is True
    assert (
        "circuit breaker"
        in next(e.data for e in events if e.name == "error")["message"]
    )


def test_degraded_mode_through_the_api(run_settings, index_dir) -> None:
    services = api_app.Services(run_settings, make(index_dir, run_settings))
    with testclient.TestClient(api_app.create_app(services)) as client:
        body = client.post(
            "/api/ask",
            json={
                "question": question(run_settings),
                "options": {"stream": False},
            },
            headers={**AUTH, "X-Keel-Mock": "provider_unavailable"},
        ).json()
    assert body["meta"]["degraded"] is True
    assert body["retrieval"]["chunks"]
    assert body["error"]["code"] == "provider_unavailable"


def test_budget_stop(index_dir, run_settings) -> None:
    """A daily budget of $0 serves only cached answers."""
    online = make(index_dir, run_settings)
    record = final(ask(online, question(run_settings)))
    online.cache.put(online.cache_key(question(run_settings)), record)
    broke = run_settings.model_copy(
        update={
            "limits": run_settings.limits.model_copy(
                update={"daily_budget_usd": 0.0}
            )
        }
    )
    provider = mock.MockProvider(run_settings.llm.model)
    answerer = make(index_dir, broke, provider)
    cached = final(ask(answerer, question(run_settings)))
    assert cached["meta"]["from_cache"] is True
    assert cached["answer"] == record["answer"]
    missed = final(ask(answerer, "What are the risk factors of Tesla?"))
    assert missed["outcome"] == "budget_stop"
    assert missed["message"] == answer.BUDGET_MESSAGE
    assert missed["meta"]["degraded"] is True
    assert missed["retrieval"]["chunks"]
    assert provider.requests == 0


def test_budget_from_the_audit_log(index_dir, run_settings) -> None:
    """The spend of the day sums `cost_usd` of today's audit records."""
    run_settings.logs.dir.mkdir(parents=True)
    path = run_settings.logs.dir / "audit.jsonl"
    today = datetime.date(2026, 10, 21)
    lines = [
        {"timestamp": "2026-10-21T09:00:00+00:00", "cost_usd": 0.75},
        {"timestamp": "2026-10-21T10:00:00+00:00", "cost_usd": 0.5},
        {"timestamp": "2026-10-20T23:59:59+00:00", "cost_usd": 9.0},
        {"timestamp": "2026-10-21T11:00:00+00:00", "cost_usd": None},
        ["not", "a", "record"],
    ]
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\nnot json\n"
    )
    guard = reliability.BudgetGuard(path, 1.0, today=lambda: today)
    assert guard.spent() == 1.25
    assert guard.exhausted()
    assert (
        reliability.BudgetGuard(path, 2.0, today=lambda: today).spent() == 1.25
    )
    assert not reliability.BudgetGuard(
        path, 2.0, today=lambda: today
    ).exhausted()
    absent = reliability.BudgetGuard(path.with_name("none"), 0.5)
    assert absent.spent() == 0.0
    # An answer adds its cost to the log, and the guard reads it again.
    answerer = make(index_dir, run_settings)
    final(ask(answerer, question(run_settings)))
    assert answerer.budget.spent() > 0


def test_budget_in_ready(run_settings, index_dir) -> None:
    broke = run_settings.model_copy(
        update={
            "limits": run_settings.limits.model_copy(
                update={"daily_budget_usd": 0.0}
            )
        }
    )
    services = api_app.Services(broke, make(index_dir, broke))
    with testclient.TestClient(api_app.create_app(services)) as client:
        ready = client.get("/api/ready").json()
        details = client.get("/api/status", headers=AUTH).json()
    assert ready["budget_stopped"] is True
    assert details["budget"]["stopped"] is True
    assert details["fallback_model"] is None


def test_refusal_path(index_dir, run_settings) -> None:
    """E-C-06: the refusal reason and the retrieved chunks are shown."""
    provider = mock.MockProvider(run_settings.llm.model, fault="refusal")
    record = final(
        ask(make(index_dir, run_settings, provider), question(run_settings))
    )
    assert record["answer"]["refusal"]["reason"] == mock.REFUSAL_REASON
    assert record["retrieval"]["chunks"]
    services = api_app.Services(run_settings, make(index_dir, run_settings))
    with testclient.TestClient(api_app.create_app(services)) as client:
        body = client.post(
            "/api/ask",
            json={
                "question": question(run_settings),
                "options": {"stream": False},
            },
            headers={**AUTH, "X-Keel-Mock": "out_of_scope"},
        ).json()
    assert body["answer"]["refusal"]["reason"] == mock.REFUSAL_REASON
    assert body["retrieval"]["chunks"]


class RefusingProvider:
    """A provider whose response stops with the `refusal` stop reason."""

    name = "anthropic"

    def __init__(self, model: str) -> None:
        self.model = model
        self.requests = 0

    async def answer(
        self, bundle: prompt.PromptBundle
    ) -> AsyncIterator[base.ProviderEvent]:
        del bundle
        self.requests += 1
        yield base.JsonDelta('{"direct_answer": "')
        yield base.UsageReport(input_tokens=10, output_tokens=2)
        yield base.Finished(stop_reason="refusal", tool_called=True)


def test_refusal_stop_reason(index_dir, run_settings) -> None:
    """A model that stops with `refusal` gets the message and the chunks."""
    provider = RefusingProvider(run_settings.llm.model)
    answerer = make(index_dir, run_settings)
    answerer = answerer.with_provider(provider)
    record = final(ask(answerer, question(run_settings)))
    assert provider.requests == 1
    assert record["outcome"] == "refused"
    assert record["message"] == answer.REFUSED_MESSAGE
    assert record["answer"] is None
    assert record["retrieval"]["chunks"]
    assert record["meta"]["flags"]["stop_reason"] == "refusal"


def write_manifest(build: pathlib.Path, monkeypatch) -> None:
    files = {
        name: indexer.file_sha256(build / name)
        for name in (chunk_store.FILE_NAME, numpy_dense.FILE_NAME)
    }
    manifest = indexer.Manifest.model_construct(
        index_version="1.0.0", corpus_sha256="x", files=files
    )
    monkeypatch.setattr(indexer, "load_manifest", lambda path: manifest)


def test_index_checksum_mismatch(run_settings, index_dir, monkeypatch) -> None:
    """16.7: a changed byte in vectors.npy makes /api/ready return 503."""
    build = indexer.current_build(index_dir)
    write_manifest(build, monkeypatch)
    assert reliability.check_index(build).index_version == "1.0.0"
    vectors = build / numpy_dense.FILE_NAME
    data = bytearray(vectors.read_bytes())
    data[-1] ^= 0xFF
    vectors.write_bytes(bytes(data))
    with pytest.raises(errors.IndexCorruptError, match=r"vectors\.npy"):
        reliability.check_index(build)
    opened = make(index_dir, run_settings)
    monkeypatch.setattr(
        answer.Answerer, "open", classmethod(lambda cls, s, **kw: opened)
    )
    services = api_app.Services(run_settings)
    with testclient.TestClient(api_app.create_app(services)) as client:
        ready = client.get("/api/ready")
        asked = client.post(
            "/api/ask", json={"question": question(run_settings)}, headers=AUTH
        )
        coverage = client.get("/api/coverage", headers=AUTH)
    assert ready.status_code == 503
    assert ready.json()["index_corrupt"] is True
    assert ready.json()["checks"]["index_verified"] is False
    assert asked.status_code == 503
    assert asked.json()["detail"]["code"] == "index_corrupt"
    assert coverage.status_code == 503


def test_index_row_count_mismatch(index_dir, monkeypatch) -> None:
    """16.7 step 2: the chunk rows must equal the vector rows."""
    build = indexer.current_build(index_dir)
    vectors = numpy_dense.load(build / numpy_dense.FILE_NAME)
    shorter = build / "short.npy"
    numpy_dense.numpy.save(shorter, vectors[:-1])
    shorter.replace(build / numpy_dense.FILE_NAME)
    write_manifest(build, monkeypatch)
    with pytest.raises(errors.IndexCorruptError, match="17 vectors"):
        reliability.check_index(build)
    # A lexical-only build has no vectors to count.
    (build / numpy_dense.FILE_NAME).unlink()
    monkeypatch.setattr(
        indexer,
        "verify",
        lambda path: indexer.Manifest.model_construct(index_version="1.0.0"),
    )
    assert reliability.check_index(build).index_version == "1.0.0"
    (build / chunk_store.FILE_NAME).write_bytes(b"not sqlite")
    numpy_dense.numpy.save(build / numpy_dense.FILE_NAME, vectors)
    with pytest.raises(errors.IndexCorruptError, match="unreadable"):
        reliability.check_index(build)


def test_halve_context_keeps_the_best(index_dir, run_settings) -> None:
    answerer = make(index_dir, run_settings)
    analysis = answerer.understander.analyze(question(run_settings))
    result = answerer.retriever.retrieve(analysis)
    built = result.context
    halved = reliability.halve_context(built)
    assert 0 < len(halved.chunks) < len(built.chunks)
    assert halved.token_estimate <= built.token_estimate // 2
    assert halved.dropped == built.dropped + len(built.chunks) - len(
        halved.chunks
    )
    best = min(built.chunks, key=lambda c: c.candidate.rank_key)
    assert best in halved.chunks
    order = [c.candidate.chunk_id for c in built.chunks]
    kept = [c.candidate.chunk_id for c in halved.chunks]
    assert kept == [c for c in order if c in kept]


def test_probe_released_without_a_verdict(index_dir, run_settings) -> None:
    """A probe that ends in a context overflow keeps the breaker half open."""
    clock = Clock()
    breaker = reliability.CircuitBreaker(clock=clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now += reliability.OPEN_SECONDS
    primary = mock.MockProvider(
        run_settings.llm.model, fault="context-overflow"
    )
    record = final(
        ask(
            make(index_dir, run_settings, primary, None, breaker),
            question(run_settings),
        )
    )
    # The overflow freed the probe, the halved retry was the next probe,
    # and its success closed the breaker.
    assert primary.requests == 2
    assert record["outcome"] == "answered"
    assert breaker.snapshot().state == reliability.CLOSED
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_failure()
    clock.now += reliability.OPEN_SECONDS
    assert breaker.allow()
    breaker.release()
    assert breaker.allow()


def test_breaker_state_in_ready(run_settings, index_dir) -> None:
    """16.3 step 4: the breaker state in `/api/ready` and `/api/status`."""
    answerer = make(index_dir, run_settings)
    for _ in range(3):
        answerer.breaker.record_failure()
    services = api_app.Services(run_settings, answerer)
    with testclient.TestClient(api_app.create_app(services)) as client:
        ready = client.get("/api/ready").json()
        details = client.get("/api/status", headers=AUTH).json()
    assert ready["breaker"] == "open"
    assert details["breaker"]["state"] == "open"
    assert details["breaker"]["failures"] == 3
    assert 0 < details["breaker"]["retry_in"] <= reliability.OPEN_SECONDS


class Waits:
    def __init__(self) -> None:
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


def test_failed_probe_goes_straight_to_the_fallback(
    index_dir, run_settings
) -> None:
    """A failed probe reopens the breaker; no backoff wait follows it."""
    primary_model, fallback_model = models(run_settings)
    clock = Clock()
    breaker = reliability.CircuitBreaker(clock=clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now += reliability.OPEN_SECONDS
    primary = mock.MockProvider(primary_model, fault=DOWN)
    fallback = mock.MockProvider(fallback_model)
    answerer = make(index_dir, run_settings, primary, fallback, breaker)
    waits = Waits()
    answerer.sleep = waits
    record = final(ask(answerer, question(run_settings)))
    assert primary.requests == 1
    assert waits.seconds == []
    assert record["meta"]["model"] == fallback_model


def test_no_fallback_with_max_retries_zero(index_dir, run_settings) -> None:
    """D-04 reversal: `max_retries: 0` allows exactly 1 request."""
    strict = run_settings.model_copy(
        update={"llm": run_settings.llm.model_copy(update={"max_retries": 0})}
    )
    primary_model, fallback_model = models(strict)
    primary = mock.MockProvider(primary_model, fault=DOWN)
    fallback = mock.MockProvider(fallback_model)
    record = final(
        ask(make(index_dir, strict, primary, fallback), question(strict))
    )
    assert primary.requests == 1
    assert fallback.requests == 0
    assert record["meta"]["model_requests"] == 1
    assert record["meta"]["degraded"] is True


def test_probe_is_held_by_1_request() -> None:
    clock = Clock()
    breaker = reliability.CircuitBreaker(clock=clock)
    assert breaker.allow() == reliability.CLOSED
    assert breaker.closed
    for _ in range(3):
        breaker.record_failure()
    assert breaker.allow() is None
    assert not breaker.closed
    clock.now += reliability.OPEN_SECONDS
    assert breaker.allow() == reliability.HALF_OPEN
    assert breaker.allow() is None


def test_budget_logs_once(tmp_path, caplog) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text("{}\n")
    guard = reliability.BudgetGuard(path, 0.0)
    for _ in range(5):
        assert guard.exhausted()
    assert caplog.text.count("daily budget reached") == 1
