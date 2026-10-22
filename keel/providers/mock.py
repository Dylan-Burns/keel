"""The mock provider: canned streams, a request counter, and faults.

Tests and the offline front-end use it in place of the Anthropic adapter.
Every call of `answer` counts as 1 request, so `test_single_request` proves
decision D-01 on the real pipeline. A fault name, such as the one the
`X-Keel-Mock` header of stage 9 carries, makes a request fail in the way
chapter 16 drills: before content, after content, or with bad output.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Sequence
import json
import math
import re
from typing import Any

from keel import errors
from keel import prompt
from keel.providers import base

FAULTS = (
    "none",
    "529-before-content",
    "429-before-content",
    "500-before-content",
    "context-overflow",
    "disconnect-after-content",
    "malformed-json",
    "no-tool-call",
    "slow-stream",
    "partial-coverage",
    "refusal",
    "script-injection",
)
# Faults before content hit the first request only, so the retry succeeds.
_FIRST_ONLY = frozenset(
    {
        "529-before-content",
        "429-before-content",
        "500-before-content",
        "context-overflow",
    }
)
# Faults that change the answer content; the request itself succeeds.
CONTENT_FAULTS = frozenset({"partial-coverage", "refusal", "script-injection"})
MISSING_TICKER = "TSLA"
INJECTED_SCRIPT = "<script>window.keelPwned = true</script>"
REFUSAL_REASON = (
    "The question asks for something the filings do not hold, such as a "
    "price forecast."
)
_CHUNK = re.compile(r'<chunk id="([^"]+)"[^>]*>\n(.*?)\n</chunk>', re.DOTALL)
QUOTE_WORDS = 12


def _chunk_texts(user: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _CHUNK.finditer(user)}


def sample_answer(bundle: prompt.PromptBundle) -> dict[str, Any]:
    """Build a valid answer that cites the first chunk of each company.

    With a `<facts>` block, the answer also cites the first fact ID.

    Args:
        bundle: The prompt.

    Returns:
        An answer object that matches the schema.
    """
    texts = _chunk_texts(bundle.user)
    findings = []
    citations = []
    for ticker in bundle.tickers:
        chunk_id = next(
            (c for c in bundle.chunk_ids if c.startswith(f"{ticker}_")), None
        )
        if chunk_id is None:
            continue
        body = texts.get(chunk_id, "").split("\n")[-1]
        quote = " ".join(body.split()[:QUOTE_WORDS])
        findings.append(
            {
                "ticker": ticker,
                "company": ticker,
                "findings": [
                    {
                        "point": f"{ticker} names risks in its filing "
                        f"[{chunk_id}].",
                        "citations": [chunk_id],
                    }
                ],
            }
        )
        citations.append(
            {
                "chunk_id": chunk_id,
                "claim": f"{ticker} names risks.",
                "quote": quote,
            }
        )
    for fact_id in bundle.fact_ids[:1]:
        # A fact line reads `<fact id> | <value> | <unit> | ...`.
        row = next(r for r in bundle.user.splitlines() if r.startswith(fact_id))
        value = row.split(" | ")[1]
        citations.append(
            {"chunk_id": fact_id, "claim": "A reported value.", "quote": value}
        )
    cited = ", ".join("[" + c["chunk_id"] + "]" for c in citations)
    return {
        "direct_answer": f"The filings name the risks of each company {cited}.",
        "company_findings": findings,
        "comparison_table": None,
        "citations": citations,
        "coverage": {
            "companies_used": [
                {"ticker": f["ticker"], "forms": [], "fiscal_periods": []}
                for f in findings
            ],
            "companies_missing": [],
            "data_as_of": "",
        },
        "gaps": [],
        "confidence": "medium",
        "confidence_reason": "The mock provider wrote this answer.",
        "next_questions": [],
        "refusal": None,
    }


def faulted_answer(answer: dict[str, Any], fault: str) -> dict[str, Any]:
    """Change a sample answer the way a content fault asks.

    `partial-coverage` lists TSLA as a missing company (and drops its
    findings), `refusal` turns the answer into a refusal, and
    `script-injection` puts a script tag into the direct answer, so the
    front-end tests can check that the page renders it as text.

    Args:
        answer: An answer object from `sample_answer`.
        fault: 1 of `CONTENT_FAULTS`.

    Returns:
        A new answer object that still matches the schema.
    """
    changed: dict[str, Any] = json.loads(json.dumps(answer))
    if fault == "partial-coverage":
        changed["company_findings"] = [
            f
            for f in changed["company_findings"]
            if f["ticker"] != MISSING_TICKER
        ]
        changed["citations"] = [
            c
            for c in changed["citations"]
            if not c["chunk_id"].startswith(f"{MISSING_TICKER}_")
        ]
        coverage = changed["coverage"]
        coverage["companies_used"] = [
            c
            for c in coverage["companies_used"]
            if c["ticker"] != MISSING_TICKER
        ]
        coverage["companies_missing"] = [MISSING_TICKER]
        changed["gaps"] = [f"The index holds no filing of {MISSING_TICKER}."]
    elif fault == "refusal":
        changed.update(
            direct_answer=REFUSAL_REASON,
            company_findings=[],
            comparison_table=None,
            citations=[],
            gaps=[],
            confidence="low",
            confidence_reason="The question is out of scope.",
            next_questions=[],
            refusal={"reason": REFUSAL_REASON},
        )
        changed["coverage"]["companies_used"] = []
    elif fault == "script-injection":
        changed["direct_answer"] = (
            f"Revenue grew. {INJECTED_SCRIPT} " + changed["direct_answer"]
        )
    return changed


class MockProvider:  # pylint: disable=too-many-instance-attributes
    """A provider that streams canned answers and counts requests.

    Args:
        model: The model name to report.
        fault: 1 of `FAULTS`, optionally with `:N`, the number of requests
            the fault hits (default 1 for the faults before content, every
            request for the others).
        answers: Raw JSON texts to stream, 1 per request; None builds
            `sample_answer` from each prompt.
        chunk_size: The characters per JSON delta.
        delay: Seconds between deltas (the `slow-stream` fault sets 0.05).
    """

    name = "mock"

    def __init__(
        self,
        model: str = "mock",
        *,
        fault: str = "none",
        answers: Sequence[str] | None = None,
        chunk_size: int = 40,
        delay: float = 0.0,
    ) -> None:
        kind, _, count = fault.partition(":")
        if kind not in FAULTS:
            raise errors.ConfigError(
                f"unknown mock fault {fault!r}; use 1 of {FAULTS}"
            )
        self.model = model
        self.fault = kind
        self.fault_count = int(count) if count else None
        self.answers = list(answers) if answers is not None else None
        self.chunk_size = chunk_size
        self.delay = 0.05 if kind == "slow-stream" and not delay else delay
        self.requests = 0
        self.bundles: list[prompt.PromptBundle] = []

    def _hits(self) -> bool:
        if self.fault in {"none", "slow-stream"}:
            return False
        if self.fault_count is None:
            return self.fault not in _FIRST_ONLY or self.requests == 1
        return self.requests <= self.fault_count

    def _text(self, bundle: prompt.PromptBundle, hit: bool) -> str:
        if self.answers:
            return self.answers[min(self.requests, len(self.answers)) - 1]
        answer = sample_answer(bundle)
        if hit and self.fault in CONTENT_FAULTS:
            answer = faulted_answer(answer, self.fault)
        return json.dumps(answer)

    async def answer(
        self, bundle: prompt.PromptBundle
    ) -> AsyncIterator[base.ProviderEvent]:
        """Count 1 request and stream the canned answer or the fault.

        Args:
            bundle: The prompt.

        Yields:
            The JSON deltas, the usage, and the end.

        Raises:
            ProviderError: The fault of this request.
        """
        self.requests += 1
        self.bundles.append(bundle)
        hit = self._hits()
        if hit:
            self._raise_before_content()
        text = self._text(bundle, hit)
        if hit and self.fault == "no-tool-call":
            yield base.TextDelta("I cannot call the tool. " + text[:200])
            yield self._usage(bundle, text)
            yield base.Finished(stop_reason="end_turn", tool_called=False)
            return
        if hit and self.fault == "malformed-json":
            text = text[: len(text) // 2] + ', "broken": ]'
        cut = len(text) // 3 if hit and "after-content" in self.fault else None
        for start in range(0, len(text), self.chunk_size):
            if cut is not None and start >= cut:
                raise errors.ProviderUnavailableError(
                    "mock disconnect after content"
                )
            if self.delay:
                await asyncio.sleep(self.delay)
            yield base.JsonDelta(text[start : start + self.chunk_size])
        yield self._usage(bundle, text)
        yield base.Finished(stop_reason="tool_use", tool_called=True)

    def _raise_before_content(self) -> None:
        if self.fault == "529-before-content":
            raise errors.ProviderRateLimitedError(
                "mock HTTP 529: overloaded", retry_after=0.0
            )
        if self.fault == "429-before-content":
            raise errors.ProviderRateLimitedError(
                "mock HTTP 429: rate limited", retry_after=0.0
            )
        if self.fault == "500-before-content":
            raise errors.ProviderUnavailableError("mock HTTP 500")
        if self.fault == "context-overflow":
            raise errors.ContextOverflowError("mock: prompt is too long")

    def _usage(
        self, bundle: prompt.PromptBundle, text: str
    ) -> base.UsageReport:
        static = prompt.estimate_tokens(bundle.system + json.dumps(bundle.tool))
        cached = static if self.requests > 1 else 0
        return base.UsageReport(
            input_tokens=bundle.estimated_tokens - static,
            cache_read_tokens=cached,
            cache_write_tokens=0 if cached else static,
            output_tokens=math.ceil(len(text) / prompt.CHARS_PER_TOKEN),
        )
