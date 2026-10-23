"""The answer model and the server-side citation validator (chapter 12.9).

The validator runs on every answer after the stream. It parses the tool
input with the pydantic model of the schema, removes every citation to a
chunk outside the context and counts it as drift, marks a finding with no
valid citation `unverified`, checks the numbers of each quote against the
cited chunk (`quote_mismatch`) and the fiscal labels of the direct answer
against the context (`period_mismatch`), lowers the confidence when more
than 30% of the citations were invalid, and resolves each valid citation
to its filing name, section title, fiscal label, and SEC URL.

From prompt 1.4.0 a citation can also name a fact ID of the `<facts>`
block (chapter 26.1, step 6). A known fact ID resolves to the filing that
reported the value, with a link to its EDGAR filing index; an unknown fact
ID is removed and counted as drift, like a chunk outside the context.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import json
import re
from typing import Literal

import pydantic

from keel import context
from keel import edgar
from keel import errors
from keel import locations

MAX_NEXT_QUESTIONS = 4
INVALID_SHARE_LIMIT = 0.30
INCOMPLETE_GAP = (
    "The citations were incomplete: {invalid} of {total} pointed to text "
    "outside the context and were removed."
)
SECTION_TITLES = locations.SECTION_TITLES
FACTS_SECTION = "XBRL company facts"
SEC_URL_PREFIX = "https://www.sec.gov/"
CHUNK_ID = re.compile(
    r"^[A-Z0-9][A-Z0-9.\-]*_10[KQ]_\d{4}-\d{2}-\d{2}__[a-z_]+__\d{4,}$"
)
FACT_ID = re.compile(
    r"^facts:[A-Z0-9][A-Z0-9.\-]*:[A-Za-z][A-Za-z0-9_]*:(?:Q[1-4])?FY\d{4}$"
)
_MARKER = re.compile(r"\[([^\[\]\n]{1,400})\]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_QUARTER = re.compile(
    r"\b(Q[1-4])\s+(?:of\s+)?(?:fiscal(?:\s+year)?\s+|FY\s?)(\d{4})\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:fiscal(?:\s+year)?\s+|FY\s?)(\d{4})\b", re.IGNORECASE)


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")


class Finding(_Model):
    """1 finding of a company.

    Attributes:
        point: The finding in 1 or 2 sentences.
        citations: The chunk IDs that support it.
        unverified: Set by the validator when no citation is valid.
    """

    point: str
    citations: list[str]
    unverified: bool = False


class CompanyFindings(_Model):
    """The findings of 1 company.

    Attributes:
        ticker: The ticker.
        company: The company name.
        findings: The findings.
    """

    ticker: str
    company: str
    findings: list[Finding]


class ComparisonTable(_Model):
    """The comparison table.

    Attributes:
        columns: The column headers.
        rows: The rows of cells.
    """

    columns: list[str]
    rows: list[list[str]]


class Citation(_Model):
    """1 citation the model wrote.

    Attributes:
        chunk_id: The cited chunk.
        claim: The claim the chunk supports.
        quote: At most 25 words of the chunk.
    """

    chunk_id: str
    claim: str
    quote: str


class CompanyCoverage(_Model):
    """The filings used for 1 company.

    Attributes:
        ticker: The ticker.
        forms: The forms cited.
        fiscal_periods: The fiscal periods cited.
    """

    ticker: str
    forms: list[str]
    fiscal_periods: list[str]


class Coverage(_Model):
    """The coverage statement.

    Attributes:
        companies_used: The companies used.
        companies_missing: The requested companies with no chunks.
        data_as_of: The latest filing date used.
    """

    companies_used: list[CompanyCoverage]
    companies_missing: list[str]
    data_as_of: str


class Refusal(_Model):
    """A refusal.

    Attributes:
        reason: Why the model gave no answer.
    """

    reason: str


class Answer(_Model):
    """The answer object of the schema (chapter 12.4).

    Attributes:
        direct_answer: 3 to 6 sentences with inline citations.
        company_findings: The findings per company.
        comparison_table: The table, or None.
        citations: The citations.
        coverage: The coverage statement.
        gaps: What the filings cannot answer.
        confidence: `high`, `medium`, or `low`.
        confidence_reason: Why.
        next_questions: At most 4 follow-up questions.
        refusal: The refusal, or None.
    """

    direct_answer: str
    company_findings: list[CompanyFindings]
    comparison_table: ComparisonTable | None
    citations: list[Citation]
    coverage: Coverage
    gaps: list[str]
    confidence: Literal["high", "medium", "low"]
    confidence_reason: str
    next_questions: list[str]
    refusal: Refusal | None


class ResolvedCitation(_Model):
    """1 valid citation with its source (chapter 14.2).

    Attributes:
        chunk_id: The chunk ID, or the fact ID of a fact citation.
        claim: The claim.
        quote: The quote.
        ticker: The ticker.
        filing_name: Such as `Apple Inc. 10-K FY2025`.
        section_title: Such as `Risk Factors`.
        fiscal_label: Such as `FY2025`.
        period_end: The period end date.
        filing_date: The filing date.
        sec_url: The SEC URL, or None when the header URL is not trusted.
        truncated: True when the chunk was cut at a row (E-C-03).
        quote_mismatch: True when a number of the quote is not in the chunk.
        valid: Always True; invalid citations are removed.
        kind: `chunk`, or `fact` for a fact ID of the `<facts>` block.
        location: The part, item, and passage of the chunk in its filing;
            the response adds it from the chunk store, None for a fact.
    """

    chunk_id: str
    claim: str
    quote: str
    ticker: str
    filing_name: str
    section_title: str
    fiscal_label: str
    period_end: str
    filing_date: str
    sec_url: str | None
    truncated: bool
    quote_mismatch: bool
    valid: bool = True
    kind: Literal["chunk", "fact"] = "chunk"
    location: locations.Location | None = None


class ValidationReport(_Model):
    """The counts the audit record and the front-end show.

    Attributes:
        citations: The citations the model wrote.
        citation_drift: The citations and finding references removed.
        inline_drift: The inline markers removed from the prose.
        quote_mismatch: The citations with a number not in the chunk.
        period_mismatch: The fiscal labels of the direct answer that are
            not in the context.
        unverified: The findings with no valid citation.
        confidence_lowered: True when more than 30% were invalid.
    """

    citations: int = 0
    citation_drift: int = 0
    inline_drift: int = 0
    quote_mismatch: int = 0
    period_mismatch: list[str] = pydantic.Field(default_factory=list)
    unverified: int = 0
    confidence_lowered: bool = False


class ValidatedAnswer(_Model):
    """The validator output.

    Attributes:
        answer: The answer with the invalid citations removed.
        citations_resolved: The valid citations with their sources.
        report: The counts.
    """

    answer: Answer
    citations_resolved: list[ResolvedCitation]
    report: ValidationReport


def parse_answer(text: str) -> Answer:
    """Parse the tool input JSON with the answer model (12.9 step 1).

    Args:
        text: The full tool input.

    Returns:
        The answer.

    Raises:
        SchemaViolationError: The text is not JSON or not the schema.
    """
    try:
        return Answer.model_validate(json.loads(text))
    except (json.JSONDecodeError, pydantic.ValidationError) as error:
        raise errors.SchemaViolationError(
            f"the answer does not match the schema: {error}"
        ) from None


def _numbers(text: str) -> set[str]:
    return {
        m.group(0).replace(",", "").rstrip(".") for m in _NUMBER.finditer(text)
    }


def quote_mismatch(quote: str, chunk_text: str) -> bool:
    """Check that every number of a quote appears in the chunk (12.5).

    Args:
        quote: The quote.
        chunk_text: The text of the cited chunk.

    Returns:
        True when a number of the quote is absent from the chunk.
    """
    return not _numbers(quote) <= _numbers(chunk_text)


def period_mismatches(
    answer_text: str,
    built: context.Context,
    facts: Sequence[edgar.FactLine] = (),
) -> list[str]:
    """List the fiscal labels of the prose that the context does not hold.

    Args:
        answer_text: The direct answer.
        built: The context.
        facts: The fact lines of the prompt; their labels count as held.

    Returns:
        The labels, such as `fiscal 2027`, in order of appearance.
    """
    years = set()
    quarters = set()
    for line in facts:
        quarter, _, fiscal_year = line.fiscal_label.rpartition("FY")
        if quarter.strip():
            quarters.add((quarter.strip(), int(fiscal_year)))
        years.add(int(fiscal_year))  # as a quarter chunk adds its year
    for chunk in built.chunks:
        c = chunk.candidate
        if c.fiscal_year is None:
            continue
        years.add(c.fiscal_year)
        if c.fiscal_period and c.fiscal_period.startswith("Q"):
            quarters.add((c.fiscal_period, c.fiscal_year))
    found = []
    for match in _QUARTER.finditer(answer_text):
        period, year = match.group(1).upper(), int(match.group(2))
        if (period, year) not in quarters and not (
            period == "Q4" and year in years
        ):
            found.append(match.group(0))
    spans = [m.span() for m in _QUARTER.finditer(answer_text)]
    for match in _YEAR.finditer(answer_text):
        inside = any(a <= match.start() < b for a, b in spans)
        if not inside and int(match.group(1)) not in years:
            found.append(match.group(0))
    return list(dict.fromkeys(found))


def _strip_markers(text: str, valid: set[str]) -> tuple[str, int]:
    """Remove inline references to chunks outside the context."""
    removed = 0

    def keep(match: re.Match[str]) -> str:
        nonlocal removed
        ids = [part.strip() for part in re.split(r"[,;]", match.group(1))]
        if not all(CHUNK_ID.match(i) or FACT_ID.match(i) for i in ids):
            return match.group(0)  # not a citation marker
        kept = [i for i in ids if i in valid]
        removed += len(ids) - len(kept)
        return "[" + ", ".join(kept) + "]" if kept else ""

    cleaned = _MARKER.sub(keep, text)
    if removed:
        cleaned = re.sub(r" {2,}", " ", re.sub(r" +([.,;])", r"\1", cleaned))
        cleaned = cleaned.strip()
    return cleaned, removed


def filing_name(candidate: context.Candidate) -> str:
    """Name a filing as the citation panel shows it.

    Args:
        candidate: A chunk of the filing.

    Returns:
        Such as `Apple Inc. 10-K FY2025`.
    """
    return f"{candidate.company} {candidate.form} {candidate.fiscal_label}"


def resolve_fact(citation: Citation, line: edgar.FactLine) -> ResolvedCitation:
    """Resolve a fact citation to the filing that reported the value.

    Args:
        citation: The citation the model wrote.
        line: The fact line of the cited fact ID.

    Returns:
        The resolved citation; the link is the EDGAR filing index, kept
        only on `https://www.sec.gov/` and only when the CIK is known.
    """
    url = line.filing_index_url if line.cik else ""
    return ResolvedCitation(
        chunk_id=line.fact_id,
        claim=citation.claim,
        quote=citation.quote,
        ticker=line.ticker,
        filing_name=f"{line.ticker} {line.form} filed {line.filed.isoformat()}",
        section_title=FACTS_SECTION,
        fiscal_label=line.fiscal_label,
        period_end=line.period_end.isoformat(),
        filing_date=line.filed.isoformat(),
        sec_url=url if url.startswith(SEC_URL_PREFIX) else None,
        truncated=False,
        quote_mismatch=quote_mismatch(citation.quote, line.text()),
        kind="fact",
    )


def validate(
    answer: Answer,
    built: context.Context,
    sec_urls: Mapping[str, str | None],
    facts: Mapping[str, edgar.FactLine] | None = None,
) -> ValidatedAnswer:
    """Validate the citations of an answer (chapter 12.9).

    Args:
        answer: The parsed answer.
        built: The context of the request.
        sec_urls: The trusted SEC URL per filing ID; an untrusted or
            unknown filing maps to None, and the link is never shown.
        facts: The fact lines of the `<facts>` block by fact ID; any other
            fact ID is drift.

    Returns:
        The cleaned answer, the resolved citations, and the counts.
    """
    facts = facts or {}
    chunks = {c.candidate.chunk_id: c for c in built.chunks}
    valid_ids = set(chunks) | set(facts)
    report = ValidationReport(citations=len(answer.citations))
    kept = [c for c in answer.citations if c.chunk_id in valid_ids]
    report.citation_drift = len(answer.citations) - len(kept)
    findings = []
    for company in answer.company_findings:
        cleaned = []
        for finding in company.findings:
            good = [c for c in finding.citations if c in valid_ids]
            report.citation_drift += len(finding.citations) - len(good)
            point, removed = _strip_markers(finding.point, valid_ids)
            report.inline_drift += removed
            cleaned.append(
                Finding(point=point, citations=good, unverified=not good)
            )
            report.unverified += not good
        findings.append(company.model_copy(update={"findings": cleaned}))
    direct, removed = _strip_markers(answer.direct_answer, valid_ids)
    report.inline_drift += removed
    resolved = []
    for citation in kept:
        if citation.chunk_id in facts:
            fact = resolve_fact(citation, facts[citation.chunk_id])
            report.quote_mismatch += fact.quote_mismatch
            resolved.append(fact)
            continue
        chunk = chunks[citation.chunk_id]
        c = chunk.candidate
        mismatch = quote_mismatch(citation.quote, c.text)
        report.quote_mismatch += mismatch
        resolved.append(
            ResolvedCitation(
                chunk_id=c.chunk_id,
                claim=citation.claim,
                quote=citation.quote,
                ticker=c.ticker,
                filing_name=filing_name(c),
                section_title=SECTION_TITLES.get(c.section, c.section),
                fiscal_label=c.fiscal_label,
                period_end=c.period_end_date,
                filing_date=c.filing_date,
                sec_url=sec_urls.get(c.filing_id),
                truncated=chunk.truncated,
                quote_mismatch=mismatch,
            )
        )
    report.period_mismatch = period_mismatches(
        direct, built, tuple(facts.values())
    )
    table = answer.comparison_table
    if table is not None:
        rows = []
        for row in table.rows:
            cells = []
            for cell in row:
                cleaned_cell, removed = _strip_markers(cell, valid_ids)
                report.inline_drift += removed
                cells.append(cleaned_cell)
            rows.append(cells)
        table = table.model_copy(update={"rows": rows})
    update: dict[str, object] = {
        "direct_answer": direct,
        "company_findings": findings,
        "citations": kept,
        "comparison_table": table,
        "next_questions": answer.next_questions[:MAX_NEXT_QUESTIONS],
    }
    total = report.citations
    invalid = total - len(kept)
    if total and invalid / total > INVALID_SHARE_LIMIT:
        report.confidence_lowered = True
        update["confidence"] = "low"
        update["gaps"] = [
            *answer.gaps,
            INCOMPLETE_GAP.format(invalid=invalid, total=total),
        ]
    return ValidatedAnswer(
        answer=answer.model_copy(update=update),
        citations_resolved=resolved,
        report=report,
    )
