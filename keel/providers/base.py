"""The provider interface and its events (chapter 17.1).

A provider sends exactly 1 request per call of `answer` and yields events:
`JsonDelta` for each fragment of the answer JSON (the `answer` tool input
or the structured output text), `TextDelta` for other text the model
writes, `UsageReport` with the token counts, and `Finished` with the stop
reason. A failure raises a
`ProviderError`; the caller knows whether content had arrived, so it alone
decides on a retry (decision D-04).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import dataclasses
from typing import Protocol

from keel import config
from keel import prompt


@dataclasses.dataclass(frozen=True)
class JsonDelta:
    """1 fragment of the tool input JSON.

    Attributes:
        text: The fragment.
    """

    text: str


@dataclasses.dataclass(frozen=True)
class TextDelta:
    """Text the model wrote outside the tool call.

    Attributes:
        text: The fragment.
    """

    text: str


@dataclasses.dataclass(frozen=True)
class UsageReport:
    """The token counts of 1 request (chapter 16.10).

    Attributes:
        input_tokens: The uncached input tokens.
        cache_read_tokens: The input tokens read from the prompt cache.
        cache_write_tokens: The input tokens written to the prompt cache.
        output_tokens: The output tokens.
    """

    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_input(self) -> int:
        """Every input token of the request, cached or not."""
        return (
            self.input_tokens + self.cache_read_tokens + self.cache_write_tokens
        )


@dataclasses.dataclass(frozen=True)
class Finished:
    """The end of the response.

    Attributes:
        stop_reason: The provider stop reason, such as `tool_use`.
        tool_called: True when the answer arrived: the model called the
            `answer` tool, or wrote the structured output text.
    """

    stop_reason: str | None
    tool_called: bool


ProviderEvent = JsonDelta | TextDelta | UsageReport | Finished


class LLMProvider(Protocol):
    """A model provider (chapter 17.1).

    Attributes:
        name: The provider name, such as `anthropic` or `mock`.
        model: The pinned model identifier.
    """

    name: str
    model: str

    def answer(
        self, bundle: prompt.PromptBundle
    ) -> AsyncIterator[ProviderEvent]:
        """Send exactly 1 request and yield its events.

        Args:
            bundle: The prompt.

        Returns:
            The events of the response.

        Raises:
            ProviderError: The request failed; a subclass names the cause.
        """
        raise NotImplementedError


def cost_usd(usage: UsageReport, prices: config.ModelPrices) -> float:
    """Price 1 request from its token counts (chapter 16.10).

    A prompt over the long-prompt threshold of the model (Haiku 5.5) takes
    the long-prompt prices for every token of the request.

    Args:
        usage: The token counts.
        prices: The prices of the model in USD per 1 million tokens.

    Returns:
        The cost in USD, rounded to 6 decimals.
    """
    table: config.ModelPrices | config.LongPromptPrices = prices
    threshold = prices.long_prompt_threshold
    if prices.long_prompt and threshold and usage.total_input > threshold:
        table = prices.long_prompt
    total = (
        usage.input_tokens * table.input
        + usage.cache_read_tokens * table.cache_read
        + usage.cache_write_tokens * table.cache_write
        + usage.output_tokens * table.output
    )
    return round(total / 1_000_000, 6)
