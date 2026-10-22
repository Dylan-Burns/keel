"""The API of chapter 14.1 with the mock provider on a synthetic index.

Each test builds a small published index of AAPL, TSLA, and JPM risk
chunks (the same shape as tests/integration/test_answer.py), opens the
pipeline with the fake embedder and reranker, and serves it through the
FastAPI app with the Starlette test client. The SSE stream, the JSON
answer, the auth, the rate limit, the input limits, the lookups, the
stored results, and the X-Keel-Mock faults run as they do in `keel serve`.
"""

import asyncio
from collections.abc import Iterator
import json
import pathlib
import socket
import sqlite3

import httpx
import pydantic
import pytest
from starlette import testclient

import conftest
from keel import answer
from keel import cli
from keel import config
from keel import doctor
from keel import errors
from keel import indexer
from keel import reliability
from keel import retriever
from keel.api import app as api_app
from keel.api import routes
from keel.providers import mock
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

TOKEN = "test-token"  # noqa: S105
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SSE = {**AUTH, "Accept": "text/event-stream"}
FakeFiling = conftest.FakeFiling
FILINGS = (
    FakeFiling("AAPL", "10-K", "2025-09-27", "2025-10-31", 2025),
    FakeFiling("TSLA", "10-K", "2025-12-31", "2026-01-29", 2025),
    FakeFiling("JPM", "10-K", "2025-12-31", "2026-02-13", 2025),
)
WORDS = ("supply", "tariffs", "privacy", "antitrust", "credit", "labor")
TRUSTED_URL = "https://www.sec.gov/Archives/edgar/data/320193/aapl.htm"


@pytest.fixture(autouse=True)
def no_pace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "MOCK_PACE_SECONDS", 0.0)


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
    directory = conftest.build_store(tmp_path / "index", FILINGS, chunks)
    store = directory / "current" / chunk_store.FILE_NAME
    with sqlite3.connect(store) as conn:
        conn.execute(
            "UPDATE filings SET url_trusted = 1, source_url = ? "
            "WHERE ticker = 'AAPL'",
            (TRUSTED_URL,),
        )
    return directory


@pytest.fixture
def api_settings(
    settings: config.Settings, tmp_path: pathlib.Path, index_dir: pathlib.Path
) -> config.Settings:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Keel</title>")
    (dist / "assets" / "app.js").write_text("console.log('keel');")
    return settings.model_copy(
        update={
            "api_token": pydantic.SecretStr(TOKEN),
            "llm": settings.llm.model_copy(update={"provider": "mock"}),
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "index": config.IndexConfig(dir=index_dir),
            "server": config.ServerConfig(web_dist=dist),
            "corpus": settings.corpus.model_copy(
                update={"dir": tmp_path / "no-corpus"}
            ),
        }
    )


class NoSleep:
    async def __call__(self, _seconds: float) -> None:
        return None


def make_answerer(
    settings: config.Settings,
    index_dir: pathlib.Path,
    provider: mock.MockProvider | None = None,
) -> answer.Answerer:
    build = index_dir / "current"
    step = retriever.Retriever(
        chunk_store.open_read_only(build / chunk_store.FILE_NAME),
        numpy_dense.load(build / numpy_dense.FILE_NAME),
        conftest.FakeEmbedder(),
        conftest.FakeReranker(),
        settings,
    )
    return answer.Answerer(
        settings,
        step,
        provider or mock.MockProvider(settings.llm.model),
        "1.0.0",
        sleep=NoSleep(),
    )


@pytest.fixture
def services(api_settings, index_dir) -> api_app.Services:
    return api_app.Services(
        api_settings, make_answerer(api_settings, index_dir)
    )


@pytest.fixture
def client(services) -> Iterator[testclient.TestClient]:
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        yield test_client


def question(settings: config.Settings) -> str:
    return settings.demo.example_questions[0]


def parse_sse(text: str) -> list[tuple[str, dict | None]]:
    events = []
    for block in text.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = line.removeprefix("data: ")
                data = json.loads(payload) if payload else None
        if name is not None:
            events.append((name, data))
    return events


def stream(
    client: testclient.TestClient,
    text: str,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Response, list[tuple[str, dict | None]]]:
    response = client.post(
        "/api/ask", json={"question": text}, headers={**SSE, **(headers or {})}
    )
    return response, parse_sse(response.text)


def test_ask_stream_events(client, api_settings) -> None:
    response, events = stream(
        client, question(api_settings), {"Idempotency-Key": "key-1"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    names = [name for name, _ in events]
    assert names[:3] == ["meta", "analysis", "retrieval"]
    assert names[-2:] == ["final", "done"]
    first_delta = names.index("answer_delta")
    assert names.index("retrieval") < first_delta < names.index("final")
    assert set(names) <= {
        "meta",
        "analysis",
        "retrieval",
        "answer_delta",
        "findings",
        "final",
        "done",
    }
    meta = events[0][1]
    assert meta["request_id"] == "key-1"
    assert meta["index_version"] == "1.0.0"
    final = dict(events)["final"]
    text = "".join(d["text"] for n, d in events if n == "answer_delta")
    assert text == final["answer"]["direct_answer"]
    assert final["meta"]["model_requests"] == 1


def test_ask_stream_server_request_id(client, api_settings) -> None:
    _, events = stream(client, question(api_settings))
    request_id = events[0][1]["request_id"]
    assert len(request_id) == 32
    assert dict(events)["final"]["request_id"] == request_id


class AskResponse(pydantic.BaseModel):
    """The response schema of chapter 14.2 for the JSON test."""

    model_config = pydantic.ConfigDict(extra="allow")

    request_id: str
    analysis: dict
    retrieval: dict
    answer: dict
    citations_resolved: list[dict]
    meta: dict


class Meta(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    model: str
    prompt_version: str
    index_version: str
    prompt_hash: str
    latency_ms: dict[str, float | None]
    usage: dict[str, int]
    cost_usd: float
    degraded: bool
    from_cache: bool
    flags: dict


def test_ask_json(client, api_settings) -> None:
    response = client.post(
        "/api/ask",
        json={"question": question(api_settings), "options": {"stream": False}},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = AskResponse.model_validate(response.json())
    Meta.model_validate(body.meta)
    answer.citations.Answer.model_validate(body.answer)
    for key in ("chunks", "collapsed_near_duplicates", "token_estimate"):
        assert key in body.retrieval
    assert {"tickers", "primary_type", "time_scope"} <= set(body.analysis)
    assert body.citations_resolved
    assert all(c["valid"] for c in body.citations_resolved)
    # Without Accept: text/event-stream the answer is JSON too.
    plain = client.post(
        "/api/ask", json={"question": question(api_settings)}, headers=AUTH
    )
    assert plain.headers["content-type"] == "application/json"
    AskResponse.model_validate(plain.json())


def test_ask_json_out_of_scope(client) -> None:
    response = client.post(
        "/api/ask",
        json={"question": "What will the NVIDIA share price be next year?"},
        headers=AUTH,
    )
    body = response.json()
    assert response.status_code == 200
    assert body["outcome"] == "out_of_scope"
    assert body["answer"]["refusal"]["reason"].startswith("Out of scope")
    assert body["retrieval"]["chunks"] == []


def test_auth_required(client, api_settings) -> None:
    body = {"question": question(api_settings)}
    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": TOKEN},
    ):
        response = client.post("/api/ask", json=body, headers=headers)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    for path in (
        "/api/coverage",
        "/api/examples",
        "/api/index/status",
        "/api/chunks/x",
        "/api/results/x",
    ):
        assert client.get(path).status_code == 401
    assert client.post("/api/feedback").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/ready").status_code == 200


def test_auth_without_configured_token(api_settings, index_dir) -> None:
    settings = api_settings.model_copy(update={"api_token": None})
    services = api_app.Services(settings, make_answerer(settings, index_dir))
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        response = test_client.get("/api/coverage", headers=AUTH)
    assert response.status_code == 401
    assert "KEEL_API_TOKEN" in response.json()["detail"]["message"]


def test_rate_limit(client, api_settings) -> None:
    body = {"question": question(api_settings), "options": {"stream": False}}
    for _ in range(api_settings.limits.rate_per_minute):
        assert (
            client.post("/api/ask", json=body, headers=AUTH).status_code == 200
        )
    response = client.post("/api/ask", json=body, headers=AUTH)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
    detail = response.json()["detail"]
    assert detail["code"] == "rate_limited"
    assert detail["retry_after"] == int(response.headers["retry-after"])


def test_question_limits(client, api_settings) -> None:
    limit = api_settings.limits.question_max_chars
    cases = (
        ("", 400),
        ("  ", 400),
        ("ab", 400),
        ("x" * (limit + 1), 413),
        ("Quels sont les risques pour la société et les marchés?", 400),
    )
    for text, status in cases:
        response = client.post("/api/ask", json={"question": text}, headers=SSE)
        assert response.status_code == status, text
        assert response.json()["detail"]["code"] == "invalid_question"
    for raw in (b"not json", b'{"q": "x"}', b'{"question": 3}'):
        response = client.post(
            "/api/ask",
            content=raw,
            headers={**AUTH, "Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "invalid_request"
    big = json.dumps({"question": "x" * (routes.MAX_BODY_BYTES + 1)})
    response = client.post(
        "/api/ask",
        content=big,
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "body_too_large"

    def chunks() -> Iterator[bytes]:
        yield b'{"question": "'
        for _ in range(20):
            yield b"x" * 1024
        yield b'"}'

    chunked = client.post(
        "/api/ask",
        content=chunks(),
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert chunked.status_code == 413


def test_ready_without_index(api_settings, tmp_path) -> None:
    settings = api_settings.model_copy(
        update={"index": config.IndexConfig(dir=tmp_path / "no-index")}
    )
    services = api_app.Services(settings)
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        ready = test_client.get("/api/ready").json()
        assert ready["ready"] is False
        assert ready["checks"]["index_loaded"] is False
        assert ready["index_version"] is None
        assert test_client.get("/api/health").json()["status"] == "ok"
        response = test_client.post(
            "/api/ask", json={"question": "Apple risks?"}, headers=AUTH
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "index_not_built"
        status = test_client.get("/api/index/status", headers=AUTH).json()
        assert status["index_version"] is None
        assert "run keel index" in status["warnings"][0]
        coverage = test_client.get("/api/coverage", headers=AUTH)
        assert coverage.status_code == 503


def test_missing_key_ready(api_settings, index_dir) -> None:
    settings = api_settings.model_copy(
        update={
            "anthropic_api_key": None,
            "llm": api_settings.llm.model_copy(
                update={"provider": "anthropic"}
            ),
        }
    )
    keyless = make_answerer(settings, index_dir).with_provider(
        api_app.MissingKeyProvider(settings.llm.model)
    )
    services = api_app.Services(settings, keyless)
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        ready = test_client.get("/api/ready").json()
        assert ready["checks"]["provider_key"] is False
        assert ready["checks"]["index_loaded"] is True
        assert ready["ready"] is False
        # The service still answers: the degraded mode, with no retry.
        _, events = stream(test_client, question(settings))
    error = dict(events)["error"]
    assert error["code"] == "provider_request_rejected"
    final = dict(events)["final"]
    assert final["meta"]["degraded"] is True
    assert final["meta"]["model_requests"] == 1
    assert final["retrieval"]["chunks"]


def test_missing_key_at_startup(api_settings, tmp_path) -> None:
    settings = api_settings.model_copy(
        update={
            "anthropic_api_key": None,
            "llm": api_settings.llm.model_copy(
                update={"provider": "anthropic"}
            ),
            "index": config.IndexConfig(dir=tmp_path / "none"),
        }
    )
    services = api_app.Services(settings)
    services.load()
    services.load()  # once only
    assert services.provider_key is False
    assert services.answerer is None
    assert "run keel index" in (services.index_error or "")


def test_chunk_lookup(client) -> None:
    chunk_id = "JPM_10K_2025-12-31__risk_factors__0002"
    response = client.get(f"/api/chunks/{chunk_id}", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["chunk_id"] == chunk_id
    assert body["ticker"] == "JPM"
    assert body["form"] == "10-K"
    assert body["fiscal_label"] == "FY2025"
    assert body["section"] == "risk_factors"
    assert body["section_title"] == "Risk Factors"
    assert body["filing_name"] == "JPM Inc 10-K FY2025"
    assert "privacy risk" in body["text"]
    missing = client.get("/api/chunks/JPM_10K_2025-12-31__x__9", headers=AUTH)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "not_found"


def test_sec_url_only(client) -> None:
    untrusted = client.get(
        "/api/chunks/JPM_10K_2025-12-31__risk_factors__0000", headers=AUTH
    ).json()
    assert untrusted["sec_url"] is None
    trusted = client.get(
        "/api/chunks/AAPL_10K_2025-09-27__risk_factors__0000", headers=AUTH
    ).json()
    assert trusted["sec_url"] == TRUSTED_URL


def test_result_by_request_id(client, services, api_settings) -> None:
    _, events = stream(
        client, question(api_settings), {"Idempotency-Key": "refresh-1"}
    )
    final = dict(events)["final"]
    response = client.get("/api/results/refresh-1", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == final
    # A repeated key replays the stored answer, as JSON or as a stream.
    again = client.post(
        "/api/ask",
        json={"question": question(api_settings), "options": {"stream": False}},
        headers={**AUTH, "Idempotency-Key": "refresh-1"},
    )
    assert again.json() == final
    _, replay = stream(
        client, question(api_settings), {"Idempotency-Key": "refresh-1"}
    )
    assert [name for name, _ in replay] == ["meta", "final", "done"]
    # While the answer runs, the result is 404 and the key is busy.
    assert services.results.start("running-1")
    pending = client.get("/api/results/running-1", headers=AUTH)
    assert pending.status_code == 404
    assert pending.json()["detail"]["code"] == "pending"
    busy = client.post(
        "/api/ask",
        json={"question": question(api_settings)},
        headers={**AUTH, "Idempotency-Key": "running-1"},
    )
    assert busy.status_code == 409
    unknown = client.get("/api/results/nothing", headers=AUTH)
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "not_found"
    bad_key = client.post(
        "/api/ask",
        json={"question": question(api_settings)},
        headers={**AUTH, "Idempotency-Key": "a b"},
    )
    assert bad_key.status_code == 400


def test_result_from_answer_cache(client, services) -> None:
    record = {"request_id": "cached-1", "answer": None, "outcome": "answered"}
    services.answerer.cache.put("k" * 64, record)
    response = client.get("/api/results/cached-1", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "cached-1"
    assert body["answer"]["direct_answer"]
    assert body["retrieval"]["chunks"] == []


def test_result_store_expiry() -> None:
    now = [0.0]
    store = api_app.ResultStore(ttl=600.0, clock=lambda: now[0], max_entries=2)
    assert store.start("a")
    assert not store.start("a")
    store.finish("a", {"request_id": "a"})
    assert store.state("a") == (True, {"request_id": "a"})
    now[0] = 601.0
    assert store.state("a") == (False, None)
    assert store.start("b")
    assert store.start("c")
    assert store.start("d")
    assert store.state("b") == (False, None)  # the oldest went first
    store.drop("c")
    assert store.state("c") == (False, None)


def test_copy_partial_header(client, api_settings, services) -> None:
    """The server half of E-F-05: the copy header names the request ID and
    the partial text, which the stream carries when it ends mid-answer.
    The client half is the Vitest test of the same name."""
    services.answerer = services.answerer.with_provider(
        mock.MockProvider(
            api_settings.llm.model,
            fault="disconnect-after-content",
            chunk_size=5,
        )
    )
    _, events = stream(
        client, question(api_settings), {"Idempotency-Key": "copy-1"}
    )
    names = [name for name, _ in events]
    assert names.index("answer_delta") < names.index("error")
    partial = "".join(d["text"] for n, d in events if n == "answer_delta")
    error = dict(events)["error"]
    assert partial
    assert error["partial"] == partial
    assert events[0][1]["request_id"] == "copy-1"


def test_mock_faults(client, api_settings) -> None:
    text = question(api_settings)
    _, events = stream(client, text, {"X-Keel-Mock": "partial_coverage"})
    coverage = dict(events)["final"]["answer"]["coverage"]
    assert "TSLA" in coverage["companies_missing"]
    _, events = stream(client, text, {"X-Keel-Mock": "out_of_scope"})
    assert dict(events)["final"]["answer"]["refusal"]["reason"]
    limited = client.post(
        "/api/ask",
        json={"question": text},
        headers={**SSE, "X-Keel-Mock": "rate_limited"},
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3"
    assert limited.json()["detail"]["retry_after"] == 3
    _, events = stream(client, text, {"X-Keel-Mock": "provider_unavailable"})
    names = [name for name, _ in events]
    assert names[:4] == ["meta", "analysis", "retrieval", "error"]
    assert dict(events)["error"]["code"] == "provider_unavailable"
    # 3 requests to the primary model, then 3 to the fallback model.
    assert dict(events)["final"]["meta"]["model_requests"] == 6
    assert dict(events)["final"]["meta"]["degraded"] is True
    _, events = stream(client, text, {"X-Keel-Mock": "script_injection"})
    final = dict(events)["final"]
    assert mock.INJECTED_SCRIPT in final["answer"]["direct_answer"]
    retrieval = dict(events)["retrieval"]
    assert {c["sec_url"] for c in retrieval["chunks"]} == {routes.UNTRUSTED_URL}
    assert {c["sec_url"] for c in final["retrieval"]["chunks"]} == {
        routes.UNTRUSTED_URL
    }
    ready = client.get("/api/ready", headers={"X-Keel-Mock": "index_not_built"})
    assert ready.json()["checks"]["index_loaded"] is False
    status = client.get(
        "/api/index/status", headers={**AUTH, "X-Keel-Mock": "stale_index"}
    )
    assert status.json()["corpus_checksum_match"] is False
    # An unknown fault is ignored; a raw mock fault name passes through.
    _, events = stream(client, text, {"X-Keel-Mock": "nonsense"})
    assert dict(events)["final"]["outcome"] == "answered"
    _, events = stream(client, text, {"X-Keel-Mock": "no-tool-call"})
    assert dict(events)["final"]["outcome"] == "schema_violation"


def test_fault_header_ignored_without_mock(api_settings, index_dir) -> None:
    settings = api_settings.model_copy(
        update={
            "anthropic_api_key": pydantic.SecretStr("sk-test"),
            "llm": api_settings.llm.model_copy(
                update={"provider": "anthropic"}
            ),
        }
    )
    services = api_app.Services(settings, make_answerer(settings, index_dir))
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        response = test_client.post(
            "/api/ask",
            json={"question": question(settings)},
            headers={**SSE, "X-Keel-Mock": "rate_limited"},
        )
        ready = test_client.get(
            "/api/ready", headers={"X-Keel-Mock": "index_not_built"}
        ).json()
    assert response.status_code == 200
    assert ready["checks"]["index_loaded"] is True


def test_read_routes(client, api_settings) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    ready = client.get("/api/ready").json()
    assert ready["ready"] is True
    assert ready["index_version"] == "1.0.0"
    assert ready["checks"] == {
        "index_loaded": True,
        "index_verified": True,
        "models_loaded": True,
        "provider_key": True,
    }
    assert ready["index_corrupt"] is False
    assert ready["breaker"] == "closed"
    assert ready["budget_stopped"] is False
    details = client.get("/api/status", headers=AUTH).json()
    assert details["breaker"] == {
        "state": "closed",
        "failures": 0,
        "retry_in": 0,
    }
    assert details["budget"] == {
        "daily_usd": api_settings.limits.daily_budget_usd,
        "spent_usd": 0.0,
        "stopped": False,
    }
    assert details["model"] == api_settings.llm.model
    assert client.get("/api/status").status_code == 401
    coverage = client.get("/api/coverage", headers=AUTH).json()
    assert [c["ticker"] for c in coverage["companies"]] == [
        "AAPL",
        "JPM",
        "TSLA",
    ]
    assert coverage["companies"][0] == {
        "ticker": "AAPL",
        "company": "AAPL Inc",
        "forms": ["10-K"],
        "fiscal_periods": ["FY2025"],
    }
    assert coverage["filing_count"] == 3
    assert coverage["quarantined"] == []
    examples = client.get("/api/examples", headers=AUTH).json()
    assert examples["examples"] == api_settings.demo.example_questions
    status = client.get("/api/index/status", headers=AUTH).json()
    assert status["corpus_checksum_match"] is True
    assert status["index_version"] == "1.0.0"
    feedback = client.post("/api/feedback", headers=AUTH)
    assert feedback.status_code == 501
    assert feedback.json()["code"] == "not_implemented"


def test_golden_questions(tmp_path) -> None:
    assert routes.golden_questions(tmp_path / "absent.yaml") == []
    path = tmp_path / "golden.yaml"
    path.write_text(
        "questions:\n  - id: G-01\n    question: Apple risks?\n  - id: x\n"
    )
    assert routes.golden_questions(path) == [
        {"id": "G-01", "question": "Apple risks?"}
    ]
    path.write_text("[unclosed")
    assert routes.golden_questions(path) == []
    path.write_text("just text")
    assert routes.golden_questions(path) == []


def test_frontend_fallback(client) -> None:
    for path in ("/", "/a/req-1", "/history"):
        response = client.get(path)
        assert response.status_code == 200
        assert "<title>Keel</title>" in response.text
        policy = response.headers["content-security-policy"]
        assert "script-src 'self'" in policy
        assert "access-control-allow-origin" not in response.headers
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "keel" in asset.text
    missing = client.get("/api/nothing")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    # A path outside web/dist falls back to index.html, never the file.
    secret = client.app.state.services.settings.server.web_dist.parent
    (secret / "secret.txt").write_text("secret")
    escaped = client.get("/%2e%2e/secret.txt")
    assert "secret" not in escaped.text
    assert escaped.text.startswith("<!doctype")


def test_frontend_not_built(api_settings, index_dir, tmp_path) -> None:
    settings = api_settings.model_copy(
        update={"server": config.ServerConfig(web_dist=tmp_path / "nodist")}
    )
    services = api_app.Services(settings, make_answerer(settings, index_dir))
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        response = test_client.get("/")
    assert response.status_code == 404
    assert response.json()["code"] == "frontend_not_built"


def test_two_concurrent_questions(services, api_settings) -> None:
    app = api_app.create_app(services)

    async def both() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            body = {"question": question(api_settings)}
            return await asyncio.gather(
                client.post("/api/ask", json=body, headers=AUTH),
                client.post("/api/ask", json=body, headers=AUTH),
            )

    responses = asyncio.run(both())
    assert [r.status_code for r in responses] == [200, 200]
    assert {r.json()["outcome"] for r in responses} == {"answered"}
    assert (
        responses[0].json()["request_id"] != responses[1].json()["request_id"]
    )
    # 1 request each, 2 audit lines, and the shared breaker stays closed.
    assert [r.json()["meta"]["model_requests"] for r in responses] == [1, 1]
    audit = (api_settings.logs.dir / "audit.jsonl").read_text().splitlines()
    assert len(audit) == 2
    assert services.answerer.breaker.snapshot().state == "closed"


def test_stale_index_flag(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "A.txt").write_text("filing a")
    digest = indexer.corpus_sha256([indexer.file_sha256(corpus / "A.txt")])
    manifest = indexer.Manifest.model_construct(corpus_sha256=digest)
    assert routes.corpus_check(corpus, manifest) == (True, None)
    (corpus / "B.txt").write_text("filing b")
    assert routes.corpus_check(corpus, manifest) == (False, None)
    match, note = routes.corpus_check(tmp_path / "absent", manifest)
    assert match is True
    assert "not compared" in note
    assert routes.corpus_check(corpus, None)[0] is None


def test_stale_index_served_with_flag(
    api_settings, index_dir, tmp_path, monkeypatch
) -> None:
    """E-F-02: a new corpus file flags the index; the index still serves."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "A.txt").write_text("filing a")
    digest = indexer.corpus_sha256([indexer.file_sha256(corpus / "A.txt")])
    (corpus / "B.txt").write_text("filing b")
    settings = api_settings.model_copy(
        update={
            "corpus": api_settings.corpus.model_copy(update={"dir": corpus})
        }
    )
    opened = make_answerer(settings, index_dir)
    monkeypatch.setattr(
        answer.Answerer, "open", classmethod(lambda cls, s, **kw: opened)
    )
    monkeypatch.setattr(
        reliability,
        "check_index",
        lambda path: indexer.Manifest.model_construct(corpus_sha256=digest),
    )
    services = api_app.Services(settings)
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        status = test_client.get("/api/index/status", headers=AUTH).json()
        ready = test_client.get("/api/ready")
        response = test_client.post(
            "/api/ask", json={"question": question(settings)}, headers=AUTH
        )
    assert status["corpus_checksum_match"] is False
    assert ready.status_code == 200
    assert response.status_code == 200
    assert response.json()["outcome"] == "answered"


def test_port_fallback() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        chosen = api_app.pick_port("127.0.0.1", port)
    assert port < chosen <= port + 10
    # A free port is kept.
    assert api_app.pick_port("127.0.0.1", chosen) == chosen


def test_port_fallback_all_busy(monkeypatch) -> None:
    monkeypatch.setattr(doctor, "port_free", lambda host, port: False)
    with pytest.raises(errors.ConfigError, match="all in use"):
        api_app.pick_port("127.0.0.1", 8000)


def test_serve_command(monkeypatch, settings) -> None:
    calls = []
    monkeypatch.setattr(
        api_app.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs)
    )
    monkeypatch.setattr(api_app, "pick_port", lambda host, port: port + 1)
    monkeypatch.setattr(cli.config, "load_settings", lambda path: settings)
    assert cli.main(["serve", "--port", "8100"]) == 0
    assert calls == [
        {
            "host": settings.server.host,
            "port": 8101,
            "log_level": "info",
            "proxy_headers": False,
            "log_config": None,
            "access_log": False,
        }
    ]


def test_services_load_index(api_settings, index_dir, monkeypatch) -> None:
    """The startup path: the index, the manifest check, the corpus check."""
    opened = make_answerer(api_settings, index_dir)
    monkeypatch.setattr(
        answer.Answerer, "open", classmethod(lambda cls, s, **kw: opened)
    )
    monkeypatch.setattr(
        indexer,
        "verify",
        lambda path: indexer.Manifest.model_construct(corpus_sha256="x"),
    )
    services = api_app.Services(api_settings)
    services.load()
    assert services.answerer is opened
    assert services.index_verified is True
    # The corpus directory is absent: the checksum is not compared.
    assert services.corpus_match is True
    assert "not compared" in (services.corpus_note or "")


def test_services_load_corrupt_index(
    api_settings, index_dir, monkeypatch
) -> None:
    opened = make_answerer(api_settings, index_dir)
    monkeypatch.setattr(
        answer.Answerer, "open", classmethod(lambda cls, s, **kw: opened)
    )

    def corrupt(path):
        raise errors.IndexCorruptError("vectors.npy does not match")

    monkeypatch.setattr(indexer, "verify", corrupt)
    services = api_app.Services(api_settings)
    services.load()
    assert services.index_verified is False
    assert "does not match" in (services.index_error or "")


def test_ready_exposes_no_spend_or_models(client, api_settings) -> None:
    """S-06: /api/ready needs no token, so it holds no amount or model."""
    response = client.get("/api/ready")
    assert response.status_code == 200
    text = response.text
    for hidden in (
        api_settings.llm.model,
        api_settings.llm.fallback_model,
        "spent",
        "daily_usd",
        "failures",
        "retry_in",
    ):
        assert hidden not in text
    assert set(response.json()) == {
        "ready",
        "index_version",
        "checks",
        "index_corrupt",
        "offline",
        "breaker",
        "budget_stopped",
        "answer_cache",
    }
