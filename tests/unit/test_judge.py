"""Tests of the judge pass and the answer metrics (chapter 18.4).

No model is called: a fake judge client returns canned JSON.
"""

from collections.abc import AsyncIterator
from collections.abc import Callable
import datetime
import decimal
import json
import pathlib
import types
from typing import Any
from typing import cast

import pytest

from keel import answer
from keel import config
from keel import context
from keel import edgar
from keel import errors
from keel import retriever
from keel.evaluation import answers
from keel.evaluation import golden
from keel.evaluation import judge
from keel.providers import base

AAPL_RISK = "AAPL_10K_2025-09-27__risk_factors__0001"
AAPL_MDNA = "AAPL_10K_2025-09-27__mdna__0002"
PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "prompts"


def record(**answer_fields: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "direct_answer": (
            f"Apple names supply chain risks [{AAPL_RISK}]. "
            "Its net sales were $391.0 billion in fiscal 2024."
        ),
        "company_findings": [
            {
                "ticker": "AAPL",
                "company": "Apple Inc.",
                "findings": [
                    {
                        "point": f"Supply chain risk [{AAPL_RISK}].",
                        "citations": [AAPL_RISK],
                        "unverified": False,
                    },
                    {
                        "point": "A claim with no valid citation.",
                        "citations": [],
                        "unverified": True,
                    },
                ],
            }
        ],
        "comparison_table": None,
        "citations": [],
        "coverage": {
            "companies_used": [
                {"ticker": "AAPL", "forms": ["10-K"], "fiscal_periods": []}
            ],
            "companies_missing": [],
            "data_as_of": "2025-10-31",
        },
        "gaps": ["TSLA has no filing in the window."],
        "confidence": "high",
        "confidence_reason": "r",
        "next_questions": [],
        "refusal": None,
    }
    result.update(answer_fields)
    return {
        "request_id": "r1",
        "question": "What are Apple's risks?",
        "outcome": "answered",
        "answer": result,
        "citations_resolved": [
            {"chunk_id": AAPL_MDNA, "claim": "Net sales", "quote": "391,035"}
        ],
        "retrieval": {"chunks": [{"ticker": "AAPL"}]},
        "meta": {"flags": {"citation_drift": 1}},
    }


class FakeClient:
    def __init__(self, reply: str, stop_reason: str = "end_turn") -> None:
        self.reply = reply
        self.stop_reason = stop_reason
        self.users: list[str] = []

    def complete(self, system: str, user: str) -> judge.JudgeReply:
        assert system.startswith("You are the evaluation judge")
        self.users.append(user)
        usage = base.UsageReport(input_tokens=1_000_000, output_tokens=100_000)
        return judge.JudgeReply(self.reply, usage, self.stop_reason)


def verdict(item_id: str, value: str) -> dict[str, str]:
    return {"id": item_id, "verdict": value, "reason": "r."}


def test_judge_schema() -> None:
    # The schema fits the structured output rules: every object closed,
    # every property required, the verdict an enum: 3 values for a
    # citation, plus `about_keel` for a claim.
    claim = judge.SCHEMA["properties"]["claims"]["items"]
    for node in (judge.SCHEMA, claim):
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
    item = judge.SCHEMA["properties"]["citations"]["items"]
    assert item["properties"]["verdict"]["enum"] == list(judge.VERDICTS)
    assert claim["properties"]["verdict"]["enum"] == [
        *judge.VERDICTS,
        judge.ABOUT_KEEL,
    ]
    good = {
        "claims": [verdict("C1", "supported")],
        "citations": [verdict("K1", "partly_supported")],
    }
    parsed = judge.parse_output(json.dumps(good))
    assert parsed.claims[0].verdict == "supported"
    bad = [
        {"claims": [verdict("C1", "maybe")], "citations": []},
        {"claims": [{"id": "C1", "verdict": "supported"}], "citations": []},
        {"claims": [], "citations": [], "extra": 1},
        {"claims": [], "citations": [verdict("K1", "about_keel")]},
        "not json",
    ]
    for value in bad:
        text = value if isinstance(value, str) else json.dumps(value)
        with pytest.raises(errors.SchemaViolationError):
            judge.parse_output(text)
    prompt = judge.load_prompt(PROMPTS)
    for name in judge.CLAIM_VERDICTS:
        assert f"`{name}`" in prompt
    with pytest.raises(errors.ConfigError):
        judge.load_prompt(PROMPTS, "0.0.0")


def test_judge_input_claims() -> None:
    item = judge.judge_input(record())
    assert item is not None
    texts = [c.text for c in item.claims]
    assert texts[0] == "Apple names supply chain risks."
    # A sentence with no marker cites every chunk of the answer.
    assert item.claims[1].chunk_ids == (AAPL_RISK, AAPL_MDNA)
    assert item.claims[2].text == "AAPL: Supply chain risk."
    assert item.claims[3].chunk_ids == ()
    assert item.citations[0].chunk_ids == (AAPL_MDNA,)
    assert item.drift == 1
    assert item.chunk_ids == (AAPL_RISK, AAPL_MDNA)
    assert judge.judge_input({"answer": None}) is None
    # An abbreviation the split cuts off joins the next sentence.
    short = judge.judge_input(
        record(direct_answer=f"U.S. Revenue grew in the year [{AAPL_RISK}].")
    )
    assert short is not None
    assert short.claims[0].text == "U.S. Revenue grew in the year."


def test_judge_scores(settings: config.Settings) -> None:
    item = judge.judge_input(record())
    assert item is not None
    reply = {
        "claims": [
            verdict("C1", "supported"),
            verdict("C2", "partly_supported"),
            verdict("C3", "supported"),
            verdict("C9", "supported"),  # an unknown ID is ignored
        ],
        "citations": [verdict("K1", "supported")],
    }
    client = FakeClient(json.dumps(reply))
    prices = config.load_prices(settings.llm.prices).models["claude-opus-5-5"]
    result = judge.Judge(client, judge.load_prompt(PROMPTS), prices).judge(
        item, {AAPL_RISK: "risk <text>", AAPL_MDNA: "391,035"}
    )
    # The unverified finding C4 scores 0 without being sent.
    assert 'id="C4"' not in client.users[0]
    assert "risk &lt;text>" in client.users[0]
    assert result.faithfulness == pytest.approx((1 + 0.5 + 1 + 0) / 4)
    # 1 supported citation and 1 removed by the validator.
    assert result.citation_precision == pytest.approx(0.5)
    assert result.missing == ()
    assert result.cost_usd == pytest.approx(4.0 + 2.0)
    failed = judge.Judge(FakeClient("{}"), "You are the evaluation judge")
    broken = failed.judge(item, {})
    assert broken.error
    assert broken.faithfulness is None
    # A stop on refusal is billed: the usage and cost stay on the result.
    stopped = judge.Judge(
        FakeClient(json.dumps(reply), "refusal"),
        "You are the evaluation judge",
        prices,
    ).judge(item, {})
    assert "refusal" in stopped.error
    assert stopped.cost_usd == pytest.approx(6.0)
    # An ID the judge leaves out counts as not supported.
    partial = {"claims": [verdict("C1", "supported")], "citations": []}
    short = judge.Judge(
        FakeClient(json.dumps(partial)), "You are the evaluation judge"
    ).judge(item, {})
    assert short.missing == ("C2", "C3", "K1")
    assert short.faithfulness == pytest.approx(1 / 4)
    assert short.citation_precision == 0.0


def test_judge_client_request() -> None:
    client = judge.AnthropicJudgeClient(None, "claude-opus-5-5")  # type: ignore[arg-type]
    request = client.request("system", "user")
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"]["format"]["schema"] == judge.SCHEMA
    assert request["output_config"]["effort"] == judge.JUDGE_EFFORT
    assert "thinking" not in request
    assert "temperature" not in request


def gold(label: str, value: float) -> golden.GoldValue:
    return golden.GoldValue(
        value=value, unit="USD millions", chunk_id=AAPL_MDNA, label=label
    )


def test_numeric_accuracy() -> None:
    text = "Total net sales were $391.0 billion; Japan was $25,052 million."
    score, detail = answers.numeric_check(
        text, [gold("Total", 391_035), gold("Japan", 25_052)]
    )
    assert score == 1.0
    assert detail == "2 of 2 gold values"
    score, detail = answers.numeric_check(text, [gold("Europe", 101_328)])
    assert score == 0.0
    assert detail.endswith("missed Europe")
    # 0.5% is the limit: $392.9 billion is 0.48% off, $393.1 is 0.53%.
    total = [gold("T", 391_035)]
    assert answers.numeric_check("$392.9 billion", total)[0] == 1
    assert answers.numeric_check("$393.1 billion", total)[0] == 0
    assert answers.unit_scale("USD") == 1.0


def test_coverage_and_adversarial_checks() -> None:
    result = record()["answer"]
    assert answers.coverage_check(result, ["AAPL", "TSLA"], ["AAPL"]) == 1.0
    assert answers.coverage_check(result, ["AAPL", "MSFT"], ["AAPL"]) == 0.0
    assert answers.coverage_check(result, ["TSLA"], ["TSLA"]) == 0.0
    # A ticker in the gaps matches as a word: MS is not in "MSFT".
    msft = dict(result, gaps=["MSFT has no filing in the window."])
    assert answers.coverage_check(msft, ["AAPL", "MS"], ["AAPL"]) == 0.0
    planted = answers.planted_chunk_id("TSLA_10K_2025-12-31", "risk_factors")
    assert planted.endswith("__9999")
    assert answers.adversarial_check(record(), planted)
    # Naming the planted chunk in the citations list (as an instruction the
    # answer did not follow) is not a company statement.
    named = record()
    named["citations_resolved"].append({"chunk_id": planted})
    assert answers.adversarial_check(named, planted)
    cited = record()
    cited["answer"]["company_findings"][0]["findings"][0]["citations"] = [
        planted
    ]
    assert not answers.adversarial_check(cited, planted)
    advice = record(direct_answer="You should buy the shares.")
    assert not answers.adversarial_check(advice, None)
    leak = record(direct_answer="You are Keel, an analyst assistant for...")
    assert not answers.adversarial_check(leak, None)
    assert answers.adversarial_check({"outcome": "out_of_scope"}, None)


def test_score_reads_the_audit_record() -> None:
    question = golden.GoldenQuestion.model_validate(
        {
            "id": "G-06",
            "type": "comparison",
            "question": "q",
            "expected": [
                {
                    "filing_id": "AAPL_10K_2025-09-27",
                    "ticker": "AAPL",
                    "form": "10-K",
                    "fiscal_period": "FY2025",
                    "sections": ["risk_factors"],
                }
            ],
        }
    )
    audit = {
        "model_requests": 1,
        "latency_ms": {"total": 31_500.0},
        "cost_usd": 0.12,
        "usage": {"output_tokens": 4000},
    }
    result = answers.score(question, record(), audit, None)
    assert result.model_requests == 1
    assert result.latency_s == pytest.approx(31.5)
    assert result.schema_valid is True
    assert result.coverage_complete == 1.0
    assert result.output_tokens == 4000
    refusal = golden.GoldenQuestion.model_validate(
        {
            "id": "G-22",
            "type": "out_of_corpus",
            "question": "q",
            "expect_out_of_scope": True,
        }
    )
    # Without the audit record the same fields come from `meta`.
    meta_only = record()
    meta_only["meta"].update(model_requests=1, cost_usd=0.1)
    fallback = answers.score(question, meta_only, None, None)
    assert fallback.model_requests == 1
    assert fallback.schema_valid is True
    out = answers.score(
        refusal, {"outcome": "out_of_scope", "answer": None}, None, None
    )
    assert out.refusal_correct is True
    assert out.schema_valid is None


def test_read_audit(tmp_path: pathlib.Path) -> None:
    lines = [
        json.dumps({"request_id": "a", "cost_usd": 1}),
        "not json",
        json.dumps({"request_id": "b", "cost_usd": 2}),
    ]
    (tmp_path / "audit.jsonl").write_text("\n".join(lines), encoding="utf-8")
    found = answers.read_audit(tmp_path, ["a"])
    assert list(found) == ["a"]


class FakeMessages:
    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason
        self.requests: list[dict[str, Any]] = []

    def create(self, **request: Any) -> types.SimpleNamespace:
        self.requests.append(request)
        usage = types.SimpleNamespace(
            input_tokens=10,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=0,
            output_tokens=5,
        )
        content = [
            types.SimpleNamespace(type="thinking", thinking=""),
            types.SimpleNamespace(type="text", text='{"claims": []'),
            types.SimpleNamespace(type="text", text=', "citations": []}'),
        ]
        return types.SimpleNamespace(
            usage=usage, stop_reason=self.stop_reason, content=content
        )


def test_judge_client_complete() -> None:
    messages = FakeMessages("end_turn")
    sdk = types.SimpleNamespace(messages=messages)
    client = judge.AnthropicJudgeClient(sdk, "claude-opus-5-5")  # type: ignore[arg-type]
    reply = client.complete("system", "user")
    assert judge.parse_output(reply.text).claims == ()
    assert reply.usage.input_tokens == 10
    assert reply.usage.output_tokens == 5
    assert len(messages.requests) == 1
    refused = types.SimpleNamespace(messages=FakeMessages("refusal"))
    client = judge.AnthropicJudgeClient(refused, "claude-opus-5-5")  # type: ignore[arg-type]
    assert client.complete("system", "user").stop_reason == "refusal"


def test_judge_client_needs_the_key(settings: config.Settings) -> None:
    with pytest.raises(errors.ProviderRequestError):
        judge.AnthropicJudgeClient.from_settings(settings)


def test_chunk_text_carries_the_filing_line() -> None:
    row = (
        "NVDA_10K_2025-01-26__mdna__0001",
        "NVIDIA Corporation",
        "NVDA",
        "10-K",
        2025,
        "FY",
        "2025-01-26",
        "2025-02-26",
        "mdna",
        "Revenue was $130.5 billion.",
    )
    text = judge._with_filing_line(row)  # pylint: disable=protected-access
    first, body = text.split("\n", 1)
    assert first == (
        "filing: NVIDIA Corporation (NVDA), 10-K, fiscal FY2025, period end "
        "2025-01-26, filed 2025-02-26, section mdna"
    )
    assert body == "Revenue was $130.5 billion."


def _fact_line() -> edgar.FactLine:
    return edgar.FactLine(
        fact_id="facts:AAPL:Revenues:FY2025",
        ticker="AAPL",
        cik="0000320193",
        concept="revenue",
        xbrl_name="Revenues",
        value=decimal.Decimal(416_161_000_000),
        unit="USD",
        display_value="416,161",
        display_unit="USD millions",
        fiscal_label="FY2025",
        period_kind="annual",
        period_start=datetime.date(2024, 9, 29),
        period_end=datetime.date(2025, 9, 27),
        form="10-K",
        filed=datetime.date(2025, 10, 31),
        accession="0000320193-25-000079",
    )


class _FactsAnswerer:
    """Calls its facts loader once per question, as the pipeline does."""

    def __init__(self, result: edgar.FactsResult) -> None:
        self.calibration = context.Calibration(1.0)
        self.result = result
        self.facts_loader: Callable[[Any], edgar.FactsResult] = self.load
        self.retriever: Any = None

    def load(self, analysis: Any) -> edgar.FactsResult:
        del analysis
        return self.result

    async def ask(self, question: str) -> AsyncIterator[answer.Event]:
        if question == "numeric":
            self.facts_loader(None)
        if self.retriever is not None and question != "cached":
            self.retriever.retrieve(None)
        yield answer.Event("final", {"question": question})


def test_judge_reads_fact_citations() -> None:
    line = _fact_line()
    block = edgar.FactsBlock(
        ticker="AAPL", cik="0000320193", entity_name="Apple Inc.", lines=(line,)
    )
    fake = _FactsAnswerer(edgar.FactsResult(blocks=(block,), source="cache"))
    session = answers.AnswerSession(cast(answer.Answerer, fake))
    try:
        session.ask("numeric")
        text = session.facts[line.fact_id]
        assert "416,161 | USD millions | FY2025" in text
        assert text.startswith("filing: AAPL, 10-K, fiscal FY2025")
        session.ask("other")
        assert not session.facts
    finally:
        session.close()


def _context_chunk(
    text: str, *, truncated: bool = False
) -> context.ContextChunk:
    candidate = context.Candidate(
        chunk_id=AAPL_MDNA,
        filing_id="AAPL_10K_2024-09-28",
        ticker="AAPL",
        company="Apple Inc.",
        form="10-K",
        fiscal_year=2024,
        fiscal_period="FY",
        period_end_date="2024-09-28",
        filing_date="2024-11-01",
        section="mdna",
        item_label="Item 7",
        text=text,
        token_count=20,
        is_table=False,
        delta_only=False,
        boilerplate_flag=None,
        simhash=1,
        vector_row=1,
    )
    return context.ContextChunk(
        candidate=candidate, truncated=truncated, estimated_tokens=30
    )


def _retrieval(*chunks: context.ContextChunk) -> retriever.RetrievalResult:
    built = types.SimpleNamespace(chunks=chunks)
    return cast(retriever.RetrievalResult, types.SimpleNamespace(context=built))


def test_judge_reads_the_rendered_chunk() -> None:
    # The judge reads a context chunk as the answer prompt rendered it: the
    # same opening tag with the period end and the fiscal label, the cut
    # text, and only the body escaped for the judge wrapper.
    chunk = _context_chunk("Net sales <of> $391,035 million.", truncated=True)
    element = context.render_chunk(chunk)
    texts = answers.rendered_chunks(_retrieval(chunk))
    assert texts == {AAPL_MDNA: element}
    item = judge.JudgeInput(
        question="q",
        claims=(
            judge.Claim("C1", "Fiscal 2024 ended 2024-09-28.", (AAPL_MDNA,)),
        ),
        citations=(),
    )
    user = judge.render_user(item, texts, item.claims)
    head = element.split("\n", 1)[0]
    assert head in user.splitlines()
    assert 'period_end="2024-09-28"' in head
    assert 'fiscal="FY2024"' in head
    assert 'truncated="true"' in head
    assert "Net sales &lt;of> $391,035 million.\n</chunk>" in user
    assert user.count("<chunk ") == 1
    # A store text keeps its bare element with the `filing:` line.
    plain = judge.render_user(item, {AAPL_MDNA: "filing: x\nbody"}, item.claims)
    assert f'<chunk id="{AAPL_MDNA}">\nfiling: x\nbody\n</chunk>' in plain
    # An element of another chunk ID is text, not a trusted element.
    other = judge.render_user(
        item, {AAPL_MDNA: element.replace(AAPL_MDNA, AAPL_RISK)}, item.claims
    )
    assert f'<chunk id="{AAPL_MDNA}">\n&lt;chunk id="{AAPL_RISK}"' in other


def test_session_keeps_the_rendered_context() -> None:
    chunk = _context_chunk("Revenue text.")
    replay = answers.ReplayRetriever.__new__(answers.ReplayRetriever)
    fake = _FactsAnswerer(edgar.FactsResult())
    fake.retriever = replay
    session = answers.AnswerSession(cast(answer.Answerer, fake))
    try:
        replay.prepared = _retrieval(chunk)
        session.ask("question")
        assert session.chunks == {AAPL_MDNA: context.render_chunk(chunk)}
        assert replay.last is not None
        # A question with no retrieval leaves no chunk of the last one.
        session.ask("cached")
        assert not session.chunks
    finally:
        session.close()


def test_about_keel_leaves_the_claim_count() -> None:
    item = judge.judge_input(record())
    assert item is not None
    reply = {
        "claims": [
            verdict("C1", "about_keel"),
            verdict("C2", "partly_supported"),
            verdict("C3", "supported"),
        ],
        "citations": [verdict("K1", "supported")],
    }
    result = judge.Judge(
        FakeClient(json.dumps(reply)), "You are the evaluation judge"
    ).judge(item, {})
    # C1 is out of the count; C4 (unverified) still scores 0.
    assert result.faithfulness == pytest.approx((0.5 + 1 + 0) / 3)
    assert result.claims["C1"].verdict == judge.ABOUT_KEEL
    assert result.missing == ()
    only = judge.JudgeResult(
        claims={
            "C1": judge.ItemVerdict(id="C1", verdict="about_keel", reason="r.")
        },
        citations={},
    )
    assert only.faithfulness is None
