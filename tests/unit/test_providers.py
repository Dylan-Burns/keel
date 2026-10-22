"""Tests of the Anthropic adapter and the mock provider (chapter 17.1)."""

import asyncio
import json
import re
import types

import anthropic
import httpx2
import pytest
import test_prompt

from keel import config
from keel import errors
from keel import prompt
from keel.providers import anthropic as adapter
from keel.providers import base
from keel.providers import mock

pytestmark = pytest.mark.unit

ALIAS = re.compile(r"latest|-\d{8}$")


def bundle() -> prompt.PromptBundle:
    return prompt.build_bundle(
        prompt.PromptFiles.load("1.0.0"),
        test_prompt.analysis(),
        test_prompt.built(),
        [],
    )


def ns(**fields: object) -> types.SimpleNamespace:
    return types.SimpleNamespace(**fields)


class FakeStream:
    def __init__(self, events: list[object], fail: Exception | None = None):
        self.events = events
        self.fail = fail

    def __aiter__(self):
        return self._run()

    async def _run(self):
        for event in self.events:
            yield event
        if self.fail is not None:
            raise self.fail


class FakeMessages:
    def __init__(self, stream: FakeStream | Exception) -> None:
        self.stream = stream
        self.calls: list[dict[str, object]] = []

    async def create(self, **params: object) -> FakeStream:
        self.calls.append(params)
        if isinstance(self.stream, Exception):
            raise self.stream
        return self.stream


def fake_client(stream: FakeStream | Exception) -> types.SimpleNamespace:
    return ns(messages=FakeMessages(stream))


def provider(
    settings: config.Settings, stream: FakeStream | Exception, model=None
) -> adapter.AnthropicProvider:
    """The adapter in `tool` mode, the strict answer tool of stage 7."""
    llm = settings.llm.model_copy(update={"output_mode": "tool"})
    return adapter.AnthropicProvider(
        model or settings.llm.model, fake_client(stream), llm
    )


def events(answer: str) -> list[object]:
    usage = ns(
        input_tokens=30000,
        cache_read_input_tokens=1800,
        cache_creation_input_tokens=0,
        output_tokens=1,
    )
    out: list[object] = [
        ns(type="message_start", message=ns(usage=usage)),
        ns(type="content_block_start", index=0, content_block=ns(type="text")),
        ns(
            type="content_block_delta",
            index=0,
            delta=ns(type="text_delta", text="Calling the tool."),
        ),
        ns(type="content_block_stop", index=0),
        ns(
            type="content_block_start",
            index=1,
            content_block=ns(type="tool_use", name=prompt.ANSWER_TOOL),
        ),
    ]
    for start in range(0, len(answer), 50):
        out.append(
            ns(
                type="content_block_delta",
                index=1,
                delta=ns(
                    type="input_json_delta",
                    partial_json=answer[start : start + 50],
                ),
            )
        )
    out.append(
        ns(
            type="content_block_delta",
            index=1,
            delta=ns(type="input_json_delta", partial_json=""),
        )
    )
    out.append(
        ns(
            type="message_delta",
            delta=ns(stop_reason="tool_use"),
            usage=ns(
                input_tokens=None,
                cache_read_input_tokens=None,
                cache_creation_input_tokens=None,
                output_tokens=1650,
            ),
        )
    )
    out.append(ns(type="message_stop"))
    return out


async def collect(source) -> list[base.ProviderEvent]:
    return [event async for event in source]


def status_error(cls, status: int, headers=None, body=None):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, headers=headers or {}, request=request)
    return cls(f"HTTP {status}", response=response, body=body)


def test_model_pinned(settings: config.Settings) -> None:
    llm = settings.llm
    prices = config.load_prices(llm.prices)
    for model in (llm.model, llm.fallback_model, llm.judge_model):
        assert model.startswith("claude-")
        assert not ALIAS.search(model), model  # no alias, no date guess
        assert model in prices.models
    assert llm.model == "claude-sonnet-5-5"
    assert llm.fallback_model == "claude-haiku-5-5"
    chosen = provider(settings, FakeStream([]))
    assert chosen.model == llm.model
    assert chosen.request(bundle())["model"] == llm.model
    fallback = provider(settings, FakeStream([]), llm.fallback_model)
    assert fallback.request(bundle())["thinking"] == {"type": "disabled"}


def test_request_shape(settings: config.Settings) -> None:
    built = bundle()
    params = provider(settings, FakeStream([])).request(built)
    assert params["system"] == [
        {
            "type": "text",
            "text": built.system,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert params["tools"] == [built.tool]
    assert params["tools"][0]["input_schema"] == dict(
        prompt.PromptFiles.load("1.0.0").schema
    )
    assert params["tool_choice"] == {
        "type": "auto",
        "disable_parallel_tool_use": True,
    }
    assert params["thinking"] == {"type": "between_tools"}
    assert params["max_tokens"] == settings.llm.max_output_tokens
    assert "temperature" not in params
    assert "extra_body" not in params
    assert params["messages"] == [{"role": "user", "content": built.user}]
    assert "input_schema" not in built.system
    llm = settings.llm.model_copy(
        update={
            "temperature": 0.0,
            "cache_system_block": False,
            "thinking": {},
            "output_mode": "tool",
        }
    )
    plain = adapter.AnthropicProvider("m", fake_client(FakeStream([])), llm)
    params = plain.request(built)
    assert "cache_control" not in params["system"][0]
    assert params["extra_body"] == {"temperature": 0.0}
    assert "thinking" not in params


def test_stream_events(settings: config.Settings) -> None:
    answer = json.dumps(test_prompt.sample())
    chosen = provider(settings, FakeStream(events(answer)))
    out = asyncio.run(collect(chosen.answer(bundle())))
    text = "".join(e.text for e in out if isinstance(e, base.JsonDelta))
    assert text == answer
    assert [e.text for e in out if isinstance(e, base.TextDelta)] == [
        "Calling the tool."
    ]
    assert out[-2] == base.UsageReport(30000, 1800, 0, 1650)
    assert out[-1] == base.Finished(stop_reason="tool_use", tool_called=True)
    assert chosen.client.messages.calls[0]["stream"] is True


def structured_events(answer: str) -> list[object]:
    """The stream of a `json_schema` answer: 1 text block of JSON."""
    usage = ns(
        input_tokens=30000,
        cache_read_input_tokens=2500,
        cache_creation_input_tokens=0,
        output_tokens=1,
    )
    out: list[object] = [
        ns(type="message_start", message=ns(usage=usage)),
        ns(type="content_block_start", index=0, content_block=ns(type="text")),
    ]
    for start in range(0, len(answer), 50):
        out.append(
            ns(
                type="content_block_delta",
                index=0,
                delta=ns(type="text_delta", text=answer[start : start + 50]),
            )
        )
    out.append(
        ns(
            type="content_block_delta",
            index=0,
            delta=ns(type="text_delta", text=""),
        )
    )
    out.append(
        ns(
            type="message_delta",
            delta=ns(stop_reason="end_turn"),
            usage=ns(
                input_tokens=None,
                cache_read_input_tokens=None,
                cache_creation_input_tokens=None,
                output_tokens=1200,
            ),
        )
    )
    return out


def structured(
    settings: config.Settings, stream: FakeStream
) -> adapter.AnthropicProvider:
    """The adapter in `json_schema` mode (stage 8)."""
    llm = settings.llm.model_copy(update={"output_mode": "json_schema"})
    return adapter.AnthropicProvider(llm.model, fake_client(stream), llm)


def test_structured_output_request(settings: config.Settings) -> None:
    built = bundle()
    params = structured(settings, FakeStream([])).request(built)
    assert "tools" not in params
    assert "tool_choice" not in params
    assert params["output_config"] == {
        "format": {
            "type": "json_schema",
            "schema": dict(prompt.PromptFiles.load("1.0.0").schema),
        }
    }
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["thinking"] == {"type": "between_tools"}
    # 2 builds send the same bytes, so the cached prefix stays stable.
    again = structured(settings, FakeStream([])).request(bundle())
    assert json.dumps(params, sort_keys=True) == json.dumps(
        again, sort_keys=True
    )


def test_structured_output_stream(settings: config.Settings) -> None:
    answer = json.dumps(test_prompt.sample())
    chosen = structured(settings, FakeStream(structured_events(answer)))
    out = asyncio.run(collect(chosen.answer(bundle())))
    text = "".join(e.text for e in out if isinstance(e, base.JsonDelta))
    assert text == answer
    assert not [e for e in out if isinstance(e, base.TextDelta)]
    assert out[-2] == base.UsageReport(30000, 2500, 0, 1200)
    assert out[-1] == base.Finished(stop_reason="end_turn", tool_called=True)
    # No text block: the answer never arrived.
    empty = structured(settings, FakeStream(structured_events("")[:1]))
    last = asyncio.run(collect(empty.answer(bundle())))[-1]
    assert last == base.Finished(stop_reason=None, tool_called=False)


@pytest.mark.parametrize(
    ("error", "expected", "retryable"),
    [
        (
            status_error(anthropic.RateLimitError, 429, {"retry-after": "3"}),
            errors.ProviderRateLimitedError,
            True,
        ),
        (
            status_error(anthropic.OverloadedError, 529),
            errors.ProviderRateLimitedError,
            True,
        ),
        (
            status_error(anthropic.InternalServerError, 500),
            errors.ProviderUnavailableError,
            True,
        ),
        (
            status_error(
                anthropic.APIStatusError,
                200,
                body={"error": {"type": "overloaded_error"}},
            ),
            errors.ProviderRateLimitedError,
            True,
        ),
        (
            status_error(
                anthropic.APIStatusError,
                200,
                body={"error": {"type": "api_error"}},
            ),
            errors.ProviderUnavailableError,
            True,
        ),
        (
            status_error(anthropic.BadRequestError, 400),
            errors.ProviderRequestError,
            False,
        ),
        (
            status_error(anthropic.RequestTooLargeError, 413),
            errors.ContextOverflowError,
            False,
        ),
        (TimeoutError(), errors.ProviderTimeoutError, True),
        (ValueError("x"), errors.ProviderUnavailableError, True),
    ],
)
def test_classify(error, expected, retryable) -> None:
    mapped = adapter.classify(error)
    assert type(mapped) is expected
    assert mapped.retryable is retryable


def test_classify_details() -> None:
    limited = adapter.classify(
        status_error(anthropic.RateLimitError, 429, {"retry-after": "3"})
    )
    assert limited.retry_after == 3.0
    odd = adapter.classify(
        status_error(anthropic.RateLimitError, 429, {"retry-after": "soon"})
    )
    assert odd.retry_after is None
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    timeout = adapter.classify(anthropic.APITimeoutError(request=request))
    assert isinstance(timeout, errors.ProviderTimeoutError)
    lost = adapter.classify(anthropic.APIConnectionError(request=request))
    assert isinstance(lost, errors.ProviderUnavailableError)
    response = httpx2.Response(400, request=request)
    long = anthropic.BadRequestError(
        "prompt is too long: 1200000 tokens > 1000000",
        response=response,
        body=None,
    )
    assert isinstance(adapter.classify(long), errors.ContextOverflowError)


def test_errors_raise_from_create_and_stream(settings: config.Settings) -> None:
    failing = provider(settings, status_error(anthropic.OverloadedError, 529))
    with pytest.raises(errors.ProviderRateLimitedError):
        asyncio.run(collect(failing.answer(bundle())))
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    broken = provider(
        settings,
        FakeStream(
            events('{"direct_answer": "x')[:6],
            fail=anthropic.APIConnectionError(request=request),
        ),
    )
    with pytest.raises(errors.ProviderUnavailableError):
        asyncio.run(collect(broken.answer(bundle())))


def test_from_settings(settings: config.Settings, monkeypatch) -> None:
    with pytest.raises(errors.ProviderRequestError, match="ANTHROPIC_API_KEY"):
        adapter.AnthropicProvider.from_settings(settings)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    keyed = config.load_settings(env_file=None)
    built = adapter.AnthropicProvider.from_settings(keyed)
    assert built.client.max_retries == 0
    assert built.model == keyed.llm.model
    haiku = adapter.AnthropicProvider.from_settings(keyed, "claude-haiku-5-5")
    assert haiku.thinking == "disabled"


def test_mock_counts_and_streams() -> None:
    fake = mock.MockProvider("m", chunk_size=7)
    out = asyncio.run(collect(fake.answer(bundle())))
    text = "".join(e.text for e in out if isinstance(e, base.JsonDelta))
    parsed = json.loads(text)
    assert parsed["citations"][0]["chunk_id"] == bundle().chunk_ids[0]
    assert (
        prompt.validate(prompt.PromptFiles.load("1.0.0").schema, parsed) == []
    )
    assert fake.requests == 1
    assert isinstance(out[-1], base.Finished)
    asyncio.run(collect(fake.answer(bundle())))
    assert fake.requests == 2
    usage = next(e for e in out if isinstance(e, base.UsageReport))
    assert usage.cache_write_tokens > 0


@pytest.mark.parametrize(
    ("fault", "error"),
    [
        ("529-before-content", errors.ProviderRateLimitedError),
        ("429-before-content", errors.ProviderRateLimitedError),
        ("500-before-content", errors.ProviderUnavailableError),
        ("context-overflow", errors.ContextOverflowError),
    ],
)
def test_mock_faults_before_content(fault: str, error) -> None:
    fake = mock.MockProvider(fault=fault)
    with pytest.raises(error):
        asyncio.run(collect(fake.answer(bundle())))
    out = asyncio.run(collect(fake.answer(bundle())))
    assert isinstance(out[-1], base.Finished)
    always = mock.MockProvider(fault=f"{fault}:3")
    for _ in range(3):
        with pytest.raises(error):
            asyncio.run(collect(always.answer(bundle())))
    assert always.requests == 3


def test_mock_faults_after_content() -> None:
    fake = mock.MockProvider(fault="disconnect-after-content")
    seen: list[base.ProviderEvent] = []

    async def run() -> None:
        async for event in fake.answer(bundle()):
            seen.append(event)

    with pytest.raises(errors.ProviderUnavailableError):
        asyncio.run(run())
    assert any(isinstance(e, base.JsonDelta) for e in seen)
    bad = asyncio.run(
        collect(mock.MockProvider(fault="malformed-json").answer(bundle()))
    )
    text = "".join(e.text for e in bad if isinstance(e, base.JsonDelta))
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)
    plain = asyncio.run(
        collect(mock.MockProvider(fault="no-tool-call").answer(bundle()))
    )
    assert plain[-1] == base.Finished(stop_reason="end_turn", tool_called=False)
    assert mock.MockProvider(fault="slow-stream").delay == 0.05
    with pytest.raises(errors.ConfigError, match="unknown mock fault"):
        mock.MockProvider(fault="nope")
    replay = mock.MockProvider(answers=['{"a": 1}'])
    out = asyncio.run(collect(replay.answer(bundle())))
    assert (
        "".join(e.text for e in out if isinstance(e, base.JsonDelta))
        == '{"a": 1}'
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx2.ReadTimeout("idle"), errors.ProviderTimeoutError),
        (httpx2.RemoteProtocolError("cut"), errors.ProviderUnavailableError),
        (httpx2.ReadError("reset"), errors.ProviderUnavailableError),
    ],
)
def test_transport_errors_inside_the_stream(
    settings: config.Settings, failure, expected
) -> None:
    broken = provider(
        settings,
        FakeStream(events('{"direct_answer": "abc')[:6], fail=failure),
    )
    seen: list[base.ProviderEvent] = []

    async def run() -> None:
        async for event in broken.answer(bundle()):
            seen.append(event)

    with pytest.raises(expected):
        asyncio.run(run())
    assert any(isinstance(e, base.JsonDelta) for e in seen)


def test_total_deadline(settings: config.Settings) -> None:
    class SlowStream(FakeStream):
        async def _run(self):
            for event in self.events:
                await asyncio.sleep(0.05)
                yield event

    slow = provider(settings, SlowStream(events('{"direct_answer": "abc"}')))
    slow.total_timeout = 0.12
    with pytest.raises(errors.ProviderTimeoutError):
        asyncio.run(collect(slow.answer(bundle())))
