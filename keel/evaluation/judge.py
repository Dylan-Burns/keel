"""The LLM-as-judge pass of the eval (chapter 18.4).

The judge reads each claim of an answer (the sentences of the direct answer
and every finding) with the chunks it cites, and each citation with its 1
chunk, and returns a verdict per item: supported, partly supported, or not
supported, with a reason of 1 sentence. It runs only in `keel eval`, never
at question time (D-28), and it is a different model from the answer model
(D-35): `llm.judge_model`.

Faithfulness is the mean claim score and citation precision the mean
citation score, with supported 1, partly supported 0.5, and not supported
0. A finding with no valid citation (`unverified`) scores 0 without a
judge verdict, an item the judge returned no verdict for scores 0, and
each citation the validator removed (the server drift count) counts as an
unsupported citation.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import json
import pathlib
import re
import sqlite3
from typing import Any
from typing import Final
from typing import Literal
from typing import Protocol

import anthropic
import pydantic

from keel import config
from keel import errors
from keel.providers import base

JUDGE_VERSION = "1.0.0"
JUDGE_EFFORT = "medium"
JUDGE_MAX_TOKENS = 16_000
MIN_SENTENCE = 15
STOPPED = frozenset({"refusal", "max_tokens"})
NO_VERDICT = "The judge returned no verdict for this item."
SUPPORTED: Final = "supported"
PARTLY: Final = "partly_supported"
NOT_SUPPORTED: Final = "not_supported"
VERDICTS = (SUPPORTED, PARTLY, NOT_SUPPORTED)
SCORES = {SUPPORTED: 1.0, PARTLY: 0.5, NOT_SUPPORTED: 0.0}
Verdict = Literal["supported", "partly_supported", "not_supported"]

_MARKER = re.compile(r"\[([^\[\]\n]{1,400})\]")
_CHUNK_ID = re.compile(
    r"^[A-Z0-9][A-Z0-9.\-]*_10[KQ]_\d{4}-\d{2}-\d{2}__[a-z_]+__\d{4,}$"
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\"'])")

_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "verdict", "reason"],
    "properties": {
        "id": {"type": "string"},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
    },
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims", "citations"],
    "properties": {
        "claims": {"type": "array", "items": _ITEM_SCHEMA},
        "citations": {"type": "array", "items": _ITEM_SCHEMA},
    },
}


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class ItemVerdict(_Model):
    """The verdict of 1 claim or citation.

    Attributes:
        id: The claim ID (`C1`) or citation ID (`K1`).
        verdict: `supported`, `partly_supported`, or `not_supported`.
        reason: 1 sentence.
    """

    id: str
    verdict: Verdict
    reason: str


class JudgeOutput(_Model):
    """The JSON the judge returns (the schema of `SCHEMA`).

    Attributes:
        claims: 1 verdict per claim.
        citations: 1 verdict per citation.
    """

    claims: tuple[ItemVerdict, ...]
    citations: tuple[ItemVerdict, ...]


def parse_output(text: str) -> JudgeOutput:
    """Parse and validate the judge JSON.

    Args:
        text: The text the judge returned.

    Returns:
        The verdicts.

    Raises:
        SchemaViolationError: The text is not JSON of the judge schema.
    """
    try:
        return JudgeOutput.model_validate_json(text)
    except pydantic.ValidationError as error:
        raise errors.SchemaViolationError(
            f"judge output: {error.error_count()} schema error(s)"
        ) from error


@dataclasses.dataclass(frozen=True)
class Claim:
    """1 claim or citation to judge.

    Attributes:
        id: `C1`, `C2`, ... for claims, `K1`, ... for citations.
        text: The claim (with the quote for a citation).
        chunk_ids: The cited chunks; empty for an unverified finding.
    """

    id: str
    text: str
    chunk_ids: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class JudgeInput:
    """What the judge reads for 1 answer.

    Attributes:
        question: The question.
        claims: The claims of the direct answer and the findings.
        citations: The citations.
        drift: The citations the validator removed (server drift count).
    """

    question: str
    claims: tuple[Claim, ...]
    citations: tuple[Claim, ...]
    drift: int = 0

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        """Every chunk a claim or a citation cites, in first-use order."""
        seen: dict[str, None] = {}
        for item in (*self.claims, *self.citations):
            for chunk_id in item.chunk_ids:
                seen.setdefault(chunk_id, None)
        return tuple(seen)


def _markers(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _MARKER.finditer(text):
        ids = [part.strip() for part in re.split(r"[,;]", match.group(1))]
        found += [i for i in ids if _CHUNK_ID.match(i) and i not in found]
    return tuple(found)


def _plain(text: str) -> str:
    def drop(match: re.Match[str]) -> str:
        ids = [part.strip() for part in re.split(r"[,;]", match.group(1))]
        return "" if all(_CHUNK_ID.match(i) for i in ids) else match.group(0)

    text = re.sub(r" +([.,;:])", r"\1", _MARKER.sub(drop, text))
    return re.sub(r" {2,}", " ", text).strip()


def judge_input(record: Mapping[str, Any]) -> JudgeInput | None:
    """Collect the claims and citations of 1 answer record.

    A sentence of the direct answer cites the chunks of its markers, or,
    without a marker, every chunk the answer cites. A finding cites its
    `citations` list; an unverified finding keeps no chunk.

    Args:
        record: The `final` record of `keel ask --json`.

    Returns:
        The judge input, or None when the record holds no answer.
    """
    answer = record.get("answer")
    if not answer:
        return None
    resolved = record.get("citations_resolved") or []
    every: dict[str, None] = {}
    for finding in _findings(answer):
        for chunk_id in finding.get("citations", []):
            every.setdefault(chunk_id, None)
    for cited in resolved:
        every.setdefault(cited["chunk_id"], None)
    claims: list[Claim] = []
    for sentence in _sentences(str(answer.get("direct_answer", ""))):
        text = _plain(sentence)
        cites = _markers(sentence) or tuple(every)
        claims.append(Claim(f"C{len(claims) + 1}", text, cites))
    for finding in _findings(answer):
        cites = () if finding.get("unverified") else finding["citations"]
        text = _finding_text(finding)
        claims.append(Claim(f"C{len(claims) + 1}", text, tuple(cites)))
    citations = tuple(
        Claim(
            f"K{index}",
            _citation_text(cited),
            (cited["chunk_id"],),
        )
        for index, cited in enumerate(resolved, start=1)
    )
    flags = (record.get("meta") or {}).get("flags") or {}
    return JudgeInput(
        question=str(record.get("question", "")),
        claims=tuple(claims),
        citations=citations,
        drift=int(flags.get("citation_drift", 0)),
    )


def _sentences(text: str) -> list[str]:
    """Split the direct answer into sentences.

    A piece shorter than `MIN_SENTENCE` characters (an abbreviation such
    as `U.S.` that the split cut off) joins the next piece.
    """
    found: list[str] = []
    carry = ""
    for piece in _SENTENCE.split(text.strip()):
        joined = f"{carry} {piece}".strip() if carry else piece
        if len(_plain(joined)) < MIN_SENTENCE:
            carry = joined
            continue
        found.append(joined)
        carry = ""
    if carry and len(_plain(carry)) >= 3:
        found.append(carry)
    return found


def _citation_text(cited: Mapping[str, Any]) -> str:
    claim, quote = cited["claim"], cited["quote"]
    return f'{claim} (quote: "{quote}")'


def _finding_text(finding: Mapping[str, Any]) -> str:
    ticker, point = finding["ticker"], _plain(finding["point"])
    return f"{ticker}: {point}"


def _findings(answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    found = []
    for company in answer.get("company_findings", []):
        for finding in company.get("findings", []):
            found.append({"ticker": company.get("ticker", ""), **finding})
    return found


def _escape(text: str) -> str:
    """Keep untrusted text from closing a wrapper element."""
    return text.replace("<", "&lt;")


def render_user(
    item: JudgeInput, chunks: Mapping[str, str], judged: Sequence[Claim]
) -> str:
    """Render the user message of the judge.

    Args:
        item: The judge input.
        chunks: The chunk text by chunk ID.
        judged: The claims sent to the judge (the unverified left out).

    Returns:
        The message text.
    """
    lines = [f"<question>{_escape(item.question)}</question>", "<chunks>"]
    for chunk_id in item.chunk_ids:
        text = chunks.get(chunk_id, "(chunk text not found)")
        lines.append(f'<chunk id="{chunk_id}">\n{_escape(text)}\n</chunk>')
    lines += ["</chunks>", "<claims>"]
    for claim in judged:
        cites = " ".join(claim.chunk_ids)
        lines.append(
            f'<claim id="{claim.id}" cites="{cites}">'
            f"{_escape(claim.text)}</claim>"
        )
    lines += ["</claims>", "<citations>"]
    for cited in item.citations:
        lines.append(
            f'<citation id="{cited.id}" chunk="{cited.chunk_ids[0]}">'
            f"{_escape(cited.text)}</citation>"
        )
    lines.append("</citations>")
    return "\n".join(lines)


def load_prompt(directory: pathlib.Path, version: str = JUDGE_VERSION) -> str:
    """Read the judge prompt `judge_v<version>.md`.

    Args:
        directory: The prompts directory.
        version: The judge prompt version.

    Returns:
        The prompt text.

    Raises:
        ConfigError: The file is absent.
    """
    path = directory / f"judge_v{version}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise errors.ConfigError(f"judge prompt {version}: {error}") from error


def chunk_texts(
    conn: sqlite3.Connection, chunk_ids: Sequence[str]
) -> dict[str, str]:
    """Read the text of the cited chunks from the chunk store.

    Args:
        conn: The read-only chunk store.
        chunk_ids: The chunk IDs.

    Returns:
        The text by chunk ID; an unknown ID is absent.
    """
    if not chunk_ids:
        return {}
    rows = conn.execute(
        "SELECT chunk_id, text FROM chunks "
        "WHERE chunk_id IN (SELECT value FROM json_each(?))",
        (json.dumps(list(chunk_ids)),),
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


@dataclasses.dataclass(frozen=True)
class JudgeResult:  # pylint: disable=too-many-instance-attributes
    """The verdicts of 1 answer and the metrics they give.

    Attributes:
        claims: The verdict per claim ID; an unverified finding gets
            `not_supported` without a judge call.
        citations: The verdict per citation ID.
        drift: The citations the validator removed.
        missing: Claim or citation IDs the judge returned no verdict for;
            they count as not supported.
        usage: The judge tokens.
        cost_usd: The judge cost.
        error: The judge failure, or empty.
    """

    claims: Mapping[str, ItemVerdict]
    citations: Mapping[str, ItemVerdict]
    drift: int = 0
    missing: tuple[str, ...] = ()
    usage: base.UsageReport = dataclasses.field(
        default_factory=base.UsageReport
    )
    cost_usd: float = 0.0
    error: str = ""

    @property
    def faithfulness(self) -> float | None:
        """The mean claim score, or None without a judged claim."""
        scores = [SCORES[v.verdict] for v in self.claims.values()]
        return sum(scores) / len(scores) if scores else None

    @property
    def citation_precision(self) -> float | None:
        """The mean citation score with the drift as unsupported."""
        scores = [SCORES[v.verdict] for v in self.citations.values()]
        total = len(scores) + self.drift
        return sum(scores) / total if total else None


@dataclasses.dataclass(frozen=True)
class JudgeReply:
    """1 reply of the judge model.

    Attributes:
        text: The JSON text.
        usage: The tokens, billed even when the reply stopped early.
        stop_reason: The stop reason, such as `end_turn` or `refusal`.
    """

    text: str
    usage: base.UsageReport
    stop_reason: str | None = None


class JudgeClient(Protocol):
    """What the judge needs from a model client: 1 request, 1 reply."""

    def complete(self, system: str, user: str) -> JudgeReply:
        """Send 1 request and return the reply.

        Args:
            system: The judge prompt.
            user: The user message.

        Returns:
            The reply text, its usage, and the stop reason.
        """


class AnthropicJudgeClient:
    """The judge model through the Messages API with structured output.

    Args:
        client: The SDK client.
        model: The judge model, `llm.judge_model`.
        effort: The effort level (thinking stays on for Opus 5.5).
    """

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        effort: str = JUDGE_EFFORT,
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort

    @classmethod
    def from_settings(cls, settings: config.Settings) -> AnthropicJudgeClient:
        """Build the client with the key from the environment.

        Args:
            settings: The loaded settings.

        Returns:
            The client for `llm.judge_model`.

        Raises:
            ProviderRequestError: `ANTHROPIC_API_KEY` is not set.
        """
        if settings.anthropic_api_key is None:
            raise errors.ProviderRequestError("ANTHROPIC_API_KEY is not set")
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            max_retries=2,
            timeout=600.0,
        )
        return cls(client, settings.llm.judge_model)

    def request(self, system: str, user: str) -> dict[str, Any]:
        """Build the keyword arguments of `messages.create`.

        Args:
            system: The judge prompt.
            user: The user message.

        Returns:
            The request.
        """
        return {
            "model": self.model,
            "max_tokens": JUDGE_MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
        }

    def complete(self, system: str, user: str) -> JudgeReply:
        """Send 1 request and return the reply.

        Args:
            system: The judge prompt.
            user: The user message.

        Returns:
            The JSON text, the usage, and the stop reason.

        Raises:
            ProviderError: The request failed.
        """
        try:
            message = self.client.messages.create(**self.request(system, user))
        except anthropic.APIError as error:
            raise errors.ProviderError(f"judge request: {error}") from error
        usage = base.UsageReport(
            input_tokens=message.usage.input_tokens or 0,
            cache_read_tokens=message.usage.cache_read_input_tokens or 0,
            cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
            output_tokens=message.usage.output_tokens or 0,
        )
        text = "".join(
            block.text for block in message.content if block.type == "text"
        )
        return JudgeReply(text, usage, message.stop_reason)


class Judge:
    """Judge answers with 1 request each.

    Args:
        client: The judge client.
        prompt: The judge prompt text.
        prices: The prices of the judge model, or None.
    """

    def __init__(
        self,
        client: JudgeClient,
        prompt: str,
        prices: config.ModelPrices | None = None,
    ) -> None:
        self.client = client
        self.prompt = prompt
        self.prices = prices

    def judge(self, item: JudgeInput, chunks: Mapping[str, str]) -> JudgeResult:
        """Judge 1 answer; a judge failure leaves the metrics empty.

        Args:
            item: The claims and citations.
            chunks: The text of the cited chunks.

        Returns:
            The verdicts, the cost, and the error when the call failed.
        """
        unverified = {
            c.id: ItemVerdict(
                id=c.id,
                verdict=NOT_SUPPORTED,
                reason="The finding has no valid citation (unverified).",
            )
            for c in item.claims
            if not c.chunk_ids
        }
        judged = [c for c in item.claims if c.chunk_ids]
        if not judged and not item.citations:
            return JudgeResult(unverified, {}, drift=item.drift)
        user = render_user(item, chunks, judged)
        try:
            reply = self.client.complete(self.prompt, user)
        except errors.ProviderError as error:
            return JudgeResult({}, {}, drift=item.drift, error=str(error))
        usage = reply.usage
        cost = base.cost_usd(usage, self.prices) if self.prices else 0.0
        try:
            if reply.stop_reason in STOPPED:
                raise errors.SchemaViolationError(
                    f"judge stopped with {reply.stop_reason}"
                )
            output = parse_output(reply.text)
        except errors.SchemaViolationError as error:
            return JudgeResult(
                {},
                {},
                drift=item.drift,
                usage=usage,
                cost_usd=cost,
                error=str(error),
            )
        claims = _verdicts(output.claims, [c.id for c in judged])
        citations = _verdicts(output.citations, [c.id for c in item.citations])
        missing = [
            v.id
            for v in (*claims.values(), *citations.values())
            if v.reason == NO_VERDICT
        ]
        return JudgeResult(
            claims={**claims, **unverified},
            citations=citations,
            drift=item.drift,
            missing=tuple(missing),
            usage=usage,
            cost_usd=cost,
        )


def _verdicts(
    found: Sequence[ItemVerdict], ids: Sequence[str]
) -> dict[str, ItemVerdict]:
    """Keep the verdicts of the given IDs; an ID without one is unsupported."""
    by_id = {v.id: v for v in found if v.id in ids}
    return {
        i: by_id.get(i)
        or ItemVerdict(id=i, verdict=NOT_SUPPORTED, reason=NO_VERDICT)
        for i in ids
    }
