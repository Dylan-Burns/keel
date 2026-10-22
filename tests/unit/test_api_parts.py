"""The pure parts of the API: auth, the rate limit, SSE frames, faults."""

import asyncio
import json

import fastapi
import pydantic
import pytest

from keel import cache
from keel import config
from keel import prompt
from keel.api import auth
from keel.api import ratelimit
from keel.api import routes
from keel.api import sse
from keel.providers import base
from keel.providers import mock

pytestmark = pytest.mark.unit


def test_bearer_token() -> None:
    assert auth.bearer_token("Bearer s3cret") == "s3cret"
    assert auth.bearer_token("bearer  s3cret ") == "s3cret"
    assert auth.bearer_token("Basic s3cret") is None
    assert auth.bearer_token("s3cret") is None
    assert auth.bearer_token(None) is None
    assert auth.bearer_token("Bearer ") is None


def test_authenticate(settings: config.Settings) -> None:
    with_token = settings.model_copy(
        update={"api_token": pydantic.SecretStr("s3cret")}
    )
    principal = auth.authenticate(with_token, "Bearer s3cret")
    assert principal.tenant_id == "default"
    assert principal.allowed_tickers is None
    with pytest.raises(fastapi.HTTPException) as raised:
        auth.authenticate(with_token, "Bearer nope")
    assert raised.value.status_code == 401
    assert "s3cret" not in json.dumps(raised.value.detail)


def test_rate_limiter_minute_and_hour() -> None:
    now = [0.0]
    limiter = ratelimit.RateLimiter(10, 100, clock=lambda: now[0])
    assert all(limiter.check("a").allowed for _ in range(10))
    decision = limiter.check("a")
    assert not decision.allowed
    assert decision.retry_after == 6  # 1 token refills in 6 s
    assert limiter.check("b").allowed  # per client
    now[0] = 6.0
    assert limiter.check("a").allowed
    # The hour bucket: 100 questions, then a wait of 36 s.
    hourly = ratelimit.RateLimiter(1000, 100, clock=lambda: now[0])
    for _ in range(100):
        assert hourly.check("c").allowed
    blocked = hourly.check("c")
    assert not blocked.allowed
    assert blocked.retry_after == 36


def test_rate_limiter_drops_idle_clients(monkeypatch) -> None:
    monkeypatch.setattr(ratelimit, "MAX_CLIENTS", 2)
    now = [0.0]
    limiter = ratelimit.RateLimiter(10, 100, clock=lambda: now[0])
    limiter.check("a")
    limiter.check("b")
    now[0] = 3600.0
    limiter.check("c")
    assert set(limiter._clients) == {"c"}


def test_sse_frame() -> None:
    assert sse.frame("done", {}) == "event: done\ndata: {}\n\n"
    assert sse.frame("done", None) == "event: done\ndata: \n\n"
    text = sse.frame("answer_delta", {"text": "a\nb"})
    assert text.count("\n") == 3  # the newline is escaped in the JSON


def test_channel_pings_and_closes() -> None:
    async def run() -> list[str]:
        channel = sse.Channel(ping_seconds=0.01)
        frames = []

        async def produce() -> None:
            await asyncio.sleep(0.05)
            channel.send("meta", {"request_id": "r"})
            channel.close()

        task = asyncio.create_task(produce())
        async for item in channel.frames():
            frames.append(item)
        await asyncio.gather(task)
        return frames

    frames = asyncio.run(run())
    assert frames[0] == sse.PING_FRAME
    assert frames[-1].startswith("event: meta\n")
    response = sse.response(sse.Channel())
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"


def test_response_body_fills_the_shape() -> None:
    body = routes.response_body(
        {"request_id": "r", "outcome": "no_context", "message": "Nothing."}
    )
    assert body["answer"]["direct_answer"] == "Nothing."
    assert body["answer"]["refusal"] is None
    assert body["analysis"]["tickers"] == []
    assert body["retrieval"]["chunks"] == []
    refused = routes.response_body(
        {"outcome": "out_of_scope", "message": "Out of scope: price."}
    )
    assert refused["answer"]["refusal"] == {"reason": "Out of scope: price."}


def bundle() -> prompt.PromptBundle:
    chunk = (
        '<chunk id="TSLA_10K_2025-12-31__risk_factors__0000" n="1">\n'
        "TSLA | 10-K\nTesla names supply risk in its plants.\n</chunk>\n"
        '<chunk id="AAPL_10K_2025-09-27__risk_factors__0000" n="2">\n'
        "AAPL | 10-K\nApple names supply risk in its chain.\n</chunk>"
    )
    return prompt.PromptBundle(
        system="s",
        user=chunk,
        tool={},
        prompt_version="1.0.0",
        prompt_hash="sha256:x",
        tickers=("AAPL", "TSLA"),
        chunk_ids=(
            "AAPL_10K_2025-09-27__risk_factors__0000",
            "TSLA_10K_2025-12-31__risk_factors__0000",
        ),
        estimated_tokens=100,
    )


def streamed(provider: mock.MockProvider) -> dict:
    async def run() -> str:
        parts = []
        async for event in provider.answer(bundle()):
            if isinstance(event, base.JsonDelta):
                parts.append(event.text)
        return "".join(parts)

    return json.loads(asyncio.run(run()))


def test_mock_content_faults() -> None:
    partial = streamed(mock.MockProvider(fault="partial-coverage"))
    assert partial["coverage"]["companies_missing"] == ["TSLA"]
    assert [f["ticker"] for f in partial["company_findings"]] == ["AAPL"]
    assert all(
        not c["chunk_id"].startswith("TSLA_") for c in partial["citations"]
    )
    refusal = streamed(mock.MockProvider(fault="refusal"))
    assert refusal["refusal"] == {"reason": mock.REFUSAL_REASON}
    assert refusal["citations"] == []
    injected = streamed(mock.MockProvider(fault="script-injection"))
    assert mock.INJECTED_SCRIPT in injected["direct_answer"]
    plain = streamed(mock.MockProvider())
    assert plain["refusal"] is None
    assert plain["coverage"]["companies_missing"] == []


def test_cache_find(tmp_path) -> None:
    store = cache.AnswerCache(tmp_path / "answers")
    assert store.find("r-1") is None
    store.put("a" * 64, {"request_id": "r-1", "answer": None})
    store.put("b" * 64, {"request_id": "r-2", "answer": None})
    (tmp_path / "answers" / ".tmp-x.json").write_text("{}")
    assert store.find("r-2") == {"request_id": "r-2", "answer": None}
    assert store.find("r-3") is None
