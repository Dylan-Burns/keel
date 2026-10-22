"""The Anthropic adapter: 1 streamed Messages request per call.

The request carries the `answer` tool with the schema (decision D-13) and
the static system block with the `cache_control` marker (D-15). The 5.5
models reject a forced `tool_choice` and the `temperature` parameter, so
the tool choice is `auto` with 1 call at most, the system block asks for
the call, and `strict` keeps the input valid against the schema. The SDK
retries are off (`max_retries=0`): the caller retries only before content
(D-04), so the request counter stays exact.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import anthropic
import httpx2

from keel import config
from keel import errors
from keel import prompt
from keel.providers import base

_OVERFLOW_MARKERS = ("prompt is too long", "context window", "too many tokens")
_RATE_TYPES = frozenset({"rate_limit_error", "overloaded_error"})


def _retry_after(error: anthropic.APIStatusError) -> float | None:
    value = error.response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def classify(error: Exception) -> errors.ProviderError:
    """Map an SDK or timeout error to the Keel error of chapter 6.5.

    Args:
        error: The error the SDK or `asyncio.timeout` raised.

    Returns:
        The provider error; its class says whether a retry is allowed.
    """
    timeouts = (
        anthropic.APITimeoutError | httpx2.TimeoutException | TimeoutError
    )
    if isinstance(error, timeouts):
        return errors.ProviderTimeoutError(f"provider timeout: {error}")
    if isinstance(error, anthropic.APIConnectionError | httpx2.TransportError):
        return errors.ProviderUnavailableError(f"connection failed: {error}")
    if not isinstance(error, anthropic.APIStatusError):
        return errors.ProviderUnavailableError(f"provider error: {error}")
    return _classify_status(error)


def _classify_status(error: anthropic.APIStatusError) -> errors.ProviderError:
    """Map an HTTP status, or an error event inside the stream."""
    status = error.status_code
    message = f"HTTP {status}: {error.message}"
    if status in {429, 529} or error.type in _RATE_TYPES:
        return errors.ProviderRateLimitedError(
            message, retry_after=_retry_after(error)
        )
    lowered = message.lower()
    if status == 413 or (
        status == 400 and any(m in lowered for m in _OVERFLOW_MARKERS)
    ):
        return errors.ContextOverflowError(message)
    if status >= 500 or error.type == "api_error":
        return errors.ProviderUnavailableError(message)
    return errors.ProviderRequestError(message)


class AnthropicProvider:  # pylint: disable=too-many-instance-attributes
    """The Messages API adapter (chapter 17.1).

    Args:
        model: The pinned model identifier.
        client: The async client, built with `max_retries=0`.
        llm: The LLM settings.
    """

    name = "anthropic"

    def __init__(
        self,
        model: str,
        client: anthropic.AsyncAnthropic,
        llm: config.LlmConfig,
    ) -> None:
        self.model = model
        self.client = client
        self.max_tokens = llm.max_output_tokens
        self.total_timeout = llm.timeout_seconds
        self.cache_system_block = llm.cache_system_block
        self.thinking = llm.thinking.get(model)
        self.temperature = llm.temperature

    @classmethod
    def from_settings(
        cls, settings: config.Settings, model: str | None = None
    ) -> AnthropicProvider:
        """Build the adapter with the key from the environment.

        Args:
            settings: The loaded settings.
            model: The model, or None for `llm.model`.

        Returns:
            The adapter.

        Raises:
            ProviderRequestError: `ANTHROPIC_API_KEY` is not set.
        """
        if settings.anthropic_api_key is None:
            raise errors.ProviderRequestError("ANTHROPIC_API_KEY is not set")
        llm = settings.llm
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            max_retries=0,
            timeout=anthropic.Timeout(
                llm.timeout_seconds,
                connect=llm.connect_timeout_seconds,
                read=llm.idle_timeout_seconds,
            ),
        )
        return cls(model or llm.model, client, llm)

    def request(self, bundle: prompt.PromptBundle) -> dict[str, Any]:
        """Build the keyword arguments of `messages.create`.

        The tools render before the system block, so the 1 cache marker on
        the system block caches the tool schema too.

        Args:
            bundle: The prompt.

        Returns:
            The request without `stream`.
        """
        system: dict[str, Any] = {"type": "text", "text": bundle.system}
        if self.cache_system_block:
            system["cache_control"] = {"type": "ephemeral"}
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [system],
            "messages": [{"role": "user", "content": bundle.user}],
            "tools": [dict(bundle.tool)],
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
        }
        if self.thinking:
            params["thinking"] = {"type": self.thinking}
        if self.temperature is not None:
            params["extra_body"] = {"temperature": self.temperature}
        return params

    async def answer(
        self, bundle: prompt.PromptBundle
    ) -> AsyncIterator[base.ProviderEvent]:
        """Send 1 streamed request and yield its events.

        Args:
            bundle: The prompt.

        Yields:
            The JSON and text deltas, the usage, and the end.

        Raises:
            ProviderError: The request or the stream failed.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.total_timeout
        try:
            # The deadline applies to each await, never around a `yield`,
            # so the timeout cannot cancel the consumer of the events.
            stream = await asyncio.wait_for(
                self.client.messages.create(
                    **self.request(bundle), stream=True
                ),
                deadline - loop.time(),
            )
            events = aiter(self._events(stream))
            while True:
                try:
                    event = await asyncio.wait_for(
                        anext(events), max(0.0, deadline - loop.time())
                    )
                except StopAsyncIteration:
                    return
                yield event
        except (
            anthropic.APIError,
            httpx2.TransportError,
            TimeoutError,
        ) as error:
            raise classify(error) from error

    async def _events(
        self, stream: AsyncIterator[Any]
    ) -> AsyncIterator[base.ProviderEvent]:
        usage = base.UsageReport()
        tool_blocks: set[int] = set()
        text_blocks: set[int] = set()
        stop_reason: str | None = None
        async for event in stream:
            kind = event.type
            if kind == "message_start":
                start = event.message.usage
                usage = base.UsageReport(
                    input_tokens=start.input_tokens or 0,
                    cache_read_tokens=start.cache_read_input_tokens or 0,
                    cache_write_tokens=start.cache_creation_input_tokens or 0,
                    output_tokens=start.output_tokens or 0,
                )
            elif kind == "content_block_start":
                block = event.content_block
                if (
                    block.type == "tool_use"
                    and block.name == prompt.ANSWER_TOOL
                ):
                    tool_blocks.add(event.index)
                elif block.type == "text":
                    text_blocks.add(event.index)
            elif kind == "content_block_delta":
                delta = event.delta
                if (
                    delta.type == "input_json_delta"
                    and event.index in tool_blocks
                ):
                    if delta.partial_json:
                        yield base.JsonDelta(delta.partial_json)
                elif delta.type == "text_delta" and event.index in text_blocks:
                    yield base.TextDelta(delta.text)
            elif kind == "message_delta":
                stop_reason = event.delta.stop_reason
                usage = _merge(usage, event.usage)
        yield usage
        yield base.Finished(
            stop_reason=stop_reason, tool_called=bool(tool_blocks)
        )


def _merge(usage: base.UsageReport, delta: Any) -> base.UsageReport:  # noqa: ANN401
    """Take the cumulative counts of a `message_delta` over the start."""
    return base.UsageReport(
        input_tokens=delta.input_tokens or usage.input_tokens,
        cache_read_tokens=delta.cache_read_input_tokens
        or usage.cache_read_tokens,
        cache_write_tokens=(
            delta.cache_creation_input_tokens or usage.cache_write_tokens
        ),
        output_tokens=delta.output_tokens or usage.output_tokens,
    )
