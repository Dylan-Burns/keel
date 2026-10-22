"""Tests of the citation validator (chapter 12.9) and the stream reader."""

import dataclasses
import json

import pytest
import test_context
import test_prompt

from keel import citations
from keel import context
from keel import errors
from keel import partial_json

pytestmark = pytest.mark.unit

AAPL = "AAPL_10K_2025-09-27__risk_factors__0000"
OUTSIDE = "MSFT_10K_2025-06-30__risk_factors__0007"


def context_of(*candidates: context.Candidate) -> context.Context:
    return test_context.build(
        list(candidates), test_context.groups(["AAPL", "TSLA"], 10)
    )


def apple(
    text: str = "AAPL | 10-K\nNet sales were $391,035 million.",
) -> context.Candidate:
    return test_context.candidate("AAPL", 0, text=text)


def answer(**fields: object) -> citations.Answer:
    data = test_prompt.sample()
    data.update(fields)
    return citations.Answer.model_validate(data)


def cite(chunk_id: str, quote: str = "risk") -> dict[str, str]:
    return {"chunk_id": chunk_id, "claim": "a claim", "quote": quote}


def test_citation_drift_removed() -> None:
    result = citations.validate(
        answer(
            direct_answer=(
                f"Apple [{AAPL}] and Microsoft [{OUTSIDE}] both say so."
            ),
            citations=[cite(AAPL), cite(OUTSIDE), cite(AAPL), cite(AAPL)],
        ),
        context_of(apple()),
        {},
    )
    assert [c.chunk_id for c in result.answer.citations] == [AAPL] * 3
    assert result.report.citation_drift == 1
    assert result.report.inline_drift == 1
    assert OUTSIDE not in result.answer.direct_answer
    assert result.answer.direct_answer == (
        f"Apple [{AAPL}] and Microsoft both say so."
    )
    assert not result.report.confidence_lowered


def test_unverified_finding() -> None:
    data = test_prompt.sample()
    data["company_findings"] = [
        {
            "ticker": "AAPL",
            "company": "Apple Inc.",
            "findings": [
                {"point": "Grounded.", "citations": [AAPL]},
                {"point": f"From memory [{OUTSIDE}].", "citations": [OUTSIDE]},
                {"point": "No citation at all.", "citations": []},
            ],
        }
    ]
    result = citations.validate(
        citations.Answer.model_validate(data), context_of(apple()), {}
    )
    findings = result.answer.company_findings[0].findings
    assert [f.unverified for f in findings] == [False, True, True]
    assert findings[1].citations == []
    assert findings[1].point == "From memory."
    assert result.report.unverified == 2
    assert result.report.citation_drift == 1


def test_quote_mismatch() -> None:
    result = citations.validate(
        answer(
            citations=[
                cite(AAPL, "Net sales were $391,035 million."),
                cite(AAPL, "Net sales were $391,036 million."),
                cite(AAPL, "no numbers here"),
            ]
        ),
        context_of(apple()),
        {},
    )
    flags = [c.quote_mismatch for c in result.citations_resolved]
    assert flags == [False, True, False]
    assert result.report.quote_mismatch == 1
    assert not citations.quote_mismatch("1,250.5 units", "about 1250.5 units")
    assert citations.quote_mismatch("1,250 units", "about 1250.5 units")
    assert not citations.quote_mismatch("12.5%.", "rose 12.5% in")


def test_truncated_citation_marker() -> None:
    cut = context.ContextChunk(
        candidate=apple(), truncated=True, estimated_tokens=100
    )
    built = dataclasses.replace(context_of(apple()), chunks=(cut,))
    result = citations.validate(
        answer(citations=[cite(AAPL)]),
        built,
        {"AAPL_10K_2025-09-27": "https://www.sec.gov/Archives/x.htm"},
    )
    resolved = result.citations_resolved[0]
    assert resolved.valid
    assert resolved.truncated
    assert result.report.citation_drift == 0
    assert resolved.sec_url == "https://www.sec.gov/Archives/x.htm"
    assert resolved.filing_name == "AAPL Inc 10-K FY2025"
    assert resolved.section_title == "Risk Factors"
    assert resolved.fiscal_label == "FY2025"


def test_invalid_share_lowers_confidence() -> None:
    result = citations.validate(
        answer(citations=[cite(AAPL), cite(OUTSIDE), cite(OUTSIDE)]),
        context_of(apple()),
        {},
    )
    assert result.report.confidence_lowered
    assert result.answer.confidence == "low"
    assert result.answer.gaps[-1].startswith("The citations were incomplete: 2")


def test_period_mismatch() -> None:
    q3 = test_context.candidate(
        "AAPL", 1, fiscal_period="Q3", period="2025-06-28", fiscal_year=2025
    )
    built = context_of(apple(), q3)
    text = (
        "In fiscal 2025 and Q3 fiscal 2025 and Q4 FY2025 sales grew, but "
        "fiscal 2027 and Q2 fiscal 2025 are absent."
    )
    assert citations.period_mismatches(text, built) == [
        "Q2 fiscal 2025",
        "fiscal 2027",
    ]
    result = citations.validate(answer(direct_answer=text), built, {})
    assert result.report.period_mismatch == ["Q2 fiscal 2025", "fiscal 2027"]


def test_next_questions_capped_and_markers_kept() -> None:
    result = citations.validate(
        answer(
            next_questions=["a", "b", "c", "d", "e"],
            direct_answer="See [note 3] and [AAPL, TSLA].",
        ),
        context_of(apple()),
        {},
    )
    assert result.answer.next_questions == ["a", "b", "c", "d"]
    assert result.answer.direct_answer == "See [note 3] and [AAPL, TSLA]."


def test_parse_answer() -> None:
    text = json.dumps(test_prompt.sample())
    assert citations.parse_answer(text).citations[0].chunk_id == AAPL
    with pytest.raises(errors.SchemaViolationError):
        citations.parse_answer(text[:-10])
    with pytest.raises(errors.SchemaViolationError):
        citations.parse_answer(json.dumps({"direct_answer": "x"}))


def feed_all(text: str, step: int) -> tuple[str, list[dict[str, object]]]:
    reader = partial_json.AnswerStream()
    out, found = "", []
    for start in range(0, len(text), step):
        update = reader.feed(text[start : start + step])
        out += update.answer_delta
        found.extend(update.findings)
    assert reader.text == text
    return out, found


@pytest.mark.parametrize("step", [1, 2, 5, 13, 1000])
def test_stream_reader(step: int) -> None:
    data = test_prompt.sample()
    data["direct_answer"] = 'Say "hi" \\ and é✓ {[,]} 😀\nnext'
    data["company_findings"].append(
        {"ticker": "T", "company": "{x}", "findings": []}
    )
    for ascii_only in (True, False):
        text = json.dumps(data, ensure_ascii=ascii_only)
        out, found = feed_all(text, step)
        assert out == data["direct_answer"]
        assert found == data["company_findings"]


def test_stream_reader_without_answer_key() -> None:
    out, found = feed_all('{"gaps": ["direct_answer"], "x": {"a": 1}}', 3)
    assert out == ""
    assert found == []
    reader = partial_json.AnswerStream()
    assert reader.feed('{"direct_answer": "abc\\').answer_delta == "abc"
    assert reader.feed("u00").answer_delta == ""
    assert reader.feed('e9 d"').answer_delta == "é d"
