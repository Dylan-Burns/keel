"""Memo export (chapter 27.2): 1 stored answer as a Markdown memo.

`keel export REQUEST_ID` finds the stored answer of a request ID and writes
a Markdown memo: the question as the title, the direct answer, the findings per
company, the comparison table, the gaps, the coverage, and numbered
footnotes with the filing, the section, the fiscal label, the period end,
and the SEC link.

The lookup reads, in order: a saved result JSON (`--record`, the footer
Export JSON or `keel ask --json`), the audit record of the request ID (its
question, index version, prompt version, and model give the answer cache
key of decision D-29), and the answer cache entry that the request filled.

The text of the answer stays as the model wrote it and the validator kept
it, so every number keeps its fiscal label and period end date. Each
inline marker `[chunk_id]` becomes a footnote number; numbers follow the
order of first reference in the memo, and a validated citation that the
text never references comes after them. A link renders only for a URL that
passes the `www.sec.gov` check of control S-05 (E-D-28), checked again here
because a saved result JSON comes from outside the pipeline.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from collections.abc import Mapping
import dataclasses
import json
import logging
import pathlib
import re
import sys
from typing import Any

from keel import audit
from keel import cache
from keel import citations
from keel import config
from keel import errors
from keel.parsers import form_10k_10q

logger = logging.getLogger(__name__)

MARKDOWN = "markdown"
FORMATS = (MARKDOWN,)
SUFFIXES = {MARKDOWN: ".md"}
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
NO_GAPS = "The answer names no gaps."
_MARKER = re.compile(r"\s*\[([^\[\]\n]{1,400})\]")

# A run of memo text: strings and footnote numbers in reading order.
Text = tuple[str | int, ...]


class ExportError(errors.KeelError):
    """No stored answer to export, or the memo cannot be written."""


@dataclasses.dataclass(frozen=True)
class Source:
    """1 numbered footnote: 1 cited chunk.

    Attributes:
        number: The footnote number.
        chunk_id: The chunk ID.
        filing_name: Such as `Apple Inc. 10-K FY2025`.
        section_title: Such as `Risk Factors`.
        fiscal_label: Such as `FY2025`.
        period_end: The period end date.
        filing_date: The filing date, or an empty string.
        sec_url: The trusted SEC URL, or None.
        quotes: The quotes the citations of the chunk carry.
    """

    number: int
    chunk_id: str
    filing_name: str
    section_title: str
    fiscal_label: str
    period_end: str
    filing_date: str
    sec_url: str | None
    quotes: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Finding:
    """1 finding line.

    Attributes:
        text: The point with its footnote numbers.
        unverified: True when no citation was valid.
    """

    text: Text
    unverified: bool


@dataclasses.dataclass(frozen=True)
class Company:
    """The findings of 1 company.

    Attributes:
        heading: Such as `Apple Inc. (AAPL)`.
        findings: The findings.
    """

    heading: str
    findings: tuple[Finding, ...]


@dataclasses.dataclass(frozen=True)
class Memo:  # pylint: disable=too-many-instance-attributes
    """The parts of a memo, shared by the memo writers.

    Attributes:
        title: The question.
        request_id: The request ID.
        details: The request, model, version, and data lines.
        direct_answer: The direct answer.
        confidence: Such as `medium: 2 of 3 companies covered`.
        refusal: The refusal reason, or None.
        companies: The findings per company.
        columns: The comparison table headers (empty without a table).
        rows: The comparison table rows.
        gaps: The gaps.
        coverage: The coverage lines.
        sources: The footnotes in number order.
    """

    title: str
    request_id: str
    details: tuple[str, ...]
    direct_answer: Text
    confidence: str
    refusal: str | None
    companies: tuple[Company, ...]
    columns: tuple[str, ...]
    rows: tuple[tuple[Text, ...], ...]
    gaps: tuple[str, ...]
    coverage: tuple[str, ...]
    sources: tuple[Source, ...]


def _trusted(url: object) -> str | None:
    """Keep a URL only when it passes the SEC check (control S-05)."""
    if isinstance(url, str) and form_10k_10q.url_trusted(url):
        return url
    return None


def _source_facts(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The facts of every chunk the record names, by chunk ID."""
    facts: dict[str, dict[str, Any]] = {}
    retrieval = record.get("retrieval") or {}
    for chunk in retrieval.get("chunks") or []:
        section = str(chunk.get("section", ""))
        facts[str(chunk.get("chunk_id"))] = {
            "filing_name": str(chunk.get("filing_name", "")),
            "section_title": citations.SECTION_TITLES.get(section, section),
            "fiscal_label": str(chunk.get("fiscal_label", "")),
            "period_end": str(chunk.get("period_end", "")),
            "filing_date": "",
            "sec_url": _trusted(chunk.get("sec_url")),
            "quotes": [],
        }
    for cited in record.get("citations_resolved") or []:
        chunk_id = str(cited.get("chunk_id"))
        known = facts.get(chunk_id, {})
        quotes = list(known.get("quotes", []))
        quote = str(cited.get("quote", "")).strip()
        if quote and quote not in quotes:
            quotes.append(quote)
        facts[chunk_id] = {
            "filing_name": str(cited.get("filing_name", "")),
            "section_title": str(cited.get("section_title", "")),
            "fiscal_label": str(cited.get("fiscal_label", "")),
            "period_end": str(cited.get("period_end", "")),
            "filing_date": str(cited.get("filing_date", "")),
            "sec_url": _trusted(cited.get("sec_url")),
            "quotes": quotes,
        }
    return facts


class _Numbering:
    """Give each cited chunk its footnote number at first reference."""

    def __init__(self) -> None:
        self.numbers: dict[str, int] = {}

    def number(self, chunk_id: str) -> int:
        """Return the number of a chunk, giving the next one when new."""
        if chunk_id not in self.numbers:
            self.numbers[chunk_id] = len(self.numbers) + 1
        return self.numbers[chunk_id]

    def text(self, raw: str, extra: Iterable[str] = ()) -> Text:
        """Replace the inline markers of a text with footnote numbers.

        Args:
            raw: The text with `[chunk_id, ...]` markers.
            extra: Chunk IDs to reference at the end when the text does
                not already reference them (the citations of a finding).

        Returns:
            The text pieces and the numbers.
        """
        pieces: list[str | int] = []
        seen: list[str] = []
        position = 0
        for match in _MARKER.finditer(raw):
            ids = [p.strip() for p in re.split(r"[,;]", match.group(1))]
            if not all(citations.CHUNK_ID.match(i) for i in ids):
                continue  # brackets that are not a citation marker
            pieces.append(raw[position : match.start()])
            for chunk_id in ids:
                pieces.append(self.number(chunk_id))
                seen.append(chunk_id)
            position = match.end()
        pieces.append(raw[position:])
        for chunk_id in extra:
            if chunk_id not in seen:
                pieces.append(self.number(chunk_id))
                seen.append(chunk_id)
        return tuple(p for p in pieces if p != "")


def _details(record: Mapping[str, Any], request_id: str) -> tuple[str, ...]:
    meta = record.get("meta") or {}
    answer = record.get("answer") or {}
    lines = [f"Request {request_id}"]
    first = record.get("request_id")
    if first and first != request_id:
        lines.append(f"Answer first given in request {first}")
    parts = [
        f"{label} {meta[key]}"
        for label, key in (
            ("Model", "model"),
            ("prompt", "prompt_version"),
            ("index", "index_version"),
        )
        if meta.get(key)
    ]
    if parts:
        lines.append(", ".join(parts))
    data_as_of = (answer.get("coverage") or {}).get("data_as_of")
    if data_as_of:
        lines.append(f"Data as of: {data_as_of}")
    return tuple(lines)


def _coverage(answer: Mapping[str, Any]) -> tuple[str, ...]:
    coverage = answer.get("coverage") or {}
    lines = []
    for used in coverage.get("companies_used") or []:
        forms = ", ".join(used.get("forms") or [])
        periods = ", ".join(used.get("fiscal_periods") or [])
        ticker = used.get("ticker", "")
        lines.append(f"{ticker}: {forms}; {periods}")
    missing = coverage.get("companies_missing") or []
    if missing:
        lines.append("Not covered: " + ", ".join(missing))
    return tuple(lines)


def build_memo(record: Mapping[str, Any], request_id: str) -> Memo:
    """Build the memo parts of a stored answer record.

    Args:
        record: The answer record of chapter 14.2 (the `final` event).
        request_id: The request ID the memo names.

    Returns:
        The memo.

    Raises:
        ExportError: The record holds no model answer.
    """
    answer = record.get("answer")
    if not isinstance(answer, Mapping):
        outcome = record.get("outcome")
        raise ExportError(
            f"request {request_id} has no model answer to export "
            f"(outcome {outcome})"
        )
    numbering = _Numbering()
    direct = numbering.text(str(answer.get("direct_answer", "")))
    companies = []
    for company in answer.get("company_findings") or []:
        findings = tuple(
            Finding(
                text=numbering.text(
                    str(f.get("point", "")), f.get("citations") or []
                ),
                unverified=bool(f.get("unverified")),
            )
            for f in company.get("findings") or []
        )
        name, ticker = company.get("company", ""), company.get("ticker", "")
        heading = f"{name} ({ticker})"
        companies.append(Company(heading=heading, findings=findings))
    table = answer.get("comparison_table") or {}
    columns = tuple(str(c) for c in table.get("columns") or [])
    rows = tuple(
        tuple(numbering.text(str(cell)) for cell in row)
        for row in table.get("rows") or []
    )
    facts = _source_facts(record)
    for cited in record.get("citations_resolved") or []:
        numbering.number(str(cited.get("chunk_id")))
    sources = []
    for chunk_id, number in numbering.numbers.items():
        fact = facts.get(chunk_id, {})
        sources.append(
            Source(
                number=number,
                chunk_id=chunk_id,
                filing_name=fact.get("filing_name") or chunk_id,
                section_title=fact.get("section_title", ""),
                fiscal_label=fact.get("fiscal_label", ""),
                period_end=fact.get("period_end", ""),
                filing_date=fact.get("filing_date", ""),
                sec_url=fact.get("sec_url"),
                quotes=tuple(fact.get("quotes", [])),
            )
        )
    refusal = answer.get("refusal") or {}
    confidence = str(answer.get("confidence", ""))
    reason = str(answer.get("confidence_reason", "")).strip()
    question = " ".join(str(record.get("question") or "").split())
    return Memo(
        title=question or f"Answer {request_id}",
        request_id=request_id,
        details=_details(record, request_id),
        direct_answer=direct,
        confidence=f"{confidence}: {reason}" if reason else confidence,
        refusal=refusal.get("reason") if refusal else None,
        companies=tuple(companies),
        columns=columns,
        rows=rows,
        gaps=tuple(str(g) for g in answer.get("gaps") or []),
        coverage=_coverage(answer),
        sources=tuple(sources),
    )


def source_note(source: Source) -> str:
    """The text of 1 footnote without the link.

    Args:
        source: The source.

    Returns:
        Such as `Apple Inc. 10-K FY2025, Risk Factors, FY2025, period
        ended 2025-09-27, filed 2025-10-31. Quote: "..."`.
    """
    parts = [source.filing_name]
    if source.section_title:
        parts.append(source.section_title)
    if source.fiscal_label:
        parts.append(source.fiscal_label)
    if source.period_end:
        parts.append(f"period ended {source.period_end}")
    if source.filing_date:
        parts.append(f"filed {source.filing_date}")
    note = ", ".join(parts) + "."
    for quote in source.quotes:
        note += f' Quote: "{quote}".'
    if source.filing_name != source.chunk_id:
        note += f" Chunk {source.chunk_id}."
    return note


def _escape(text: str) -> str:
    """Keep model text inert in Markdown: no HTML, no footnote syntax."""
    return text.replace("<", "&lt;").replace("[^", "[\\^")


def _cell(text: str) -> str:
    return _escape(" ".join(text.split())).replace("|", "\\|")


def _markdown_text(text: Text, escape: bool = True) -> str:
    out = []
    for piece in text:
        if isinstance(piece, int):
            out.append(f"[^{piece}]")
        else:
            out.append(_escape(piece) if escape else piece)
    return "".join(out)


def render_markdown(memo: Memo) -> str:
    """Write the memo as Markdown with numbered footnotes.

    Args:
        memo: The memo.

    Returns:
        The Markdown text.
    """
    lines = [f"# {_escape(memo.title)}", ""]
    lines += [f"_{_escape(line)}_  " for line in memo.details]
    lines += ["", "## Answer", "", _markdown_text(memo.direct_answer), ""]
    if memo.refusal:
        lines += [f"**Declined:** {_escape(memo.refusal)}", ""]
    lines += [f"**Confidence:** {_escape(memo.confidence)}", ""]
    if memo.companies:
        lines += ["## Findings by company", ""]
        for company in memo.companies:
            lines += [f"### {_escape(company.heading)}", ""]
            for finding in company.findings:
                mark = " (unverified)" if finding.unverified else ""
                lines.append(f"- {_markdown_text(finding.text)}{mark}")
            lines.append("")
    if memo.columns:
        lines += ["## Comparison table", ""]
        lines.append("| " + " | ".join(_cell(c) for c in memo.columns) + " |")
        lines.append("| " + " | ".join("---" for _ in memo.columns) + " |")
        for row in memo.rows:
            cells = [_cell_text(cell) for cell in row]
            cells = (cells + [""] * len(memo.columns))[: len(memo.columns)]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    lines += ["## Gaps", ""]
    lines += [f"- {_escape(g)}" for g in memo.gaps] or [f"- {NO_GAPS}"]
    lines.append("")
    if memo.coverage:
        lines += ["## Coverage", ""]
        lines += [f"- {_escape(line)}" for line in memo.coverage]
        lines.append("")
    if memo.sources:
        lines += ["## Sources", ""]
        for source in memo.sources:
            note = _escape(source_note(source))
            if source.sec_url:
                note += f" SEC filing: <{source.sec_url}>"
            lines.append(f"[^{source.number}]: {note}")
        lines.append("")
    return "\n".join(lines)


def _cell_text(text: Text) -> str:
    return "".join(f"[^{p}]" if isinstance(p, int) else _cell(p) for p in text)


def _audit_entry(
    directory: pathlib.Path, request_id: str
) -> dict[str, Any] | None:
    """The audit record of a request ID, newest file first."""
    files = [directory / audit.FILE_NAME]
    files += sorted(directory.glob("audit-*.jsonl"), reverse=True)
    needle = json.dumps(request_id)
    for path in files:
        if not path.is_file():
            continue
        found = None
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if needle not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and (
                    entry.get("request_id") == request_id
                ):
                    found = entry
        if found is not None:
            return found
    return None


def _from_cache(
    settings: config.Settings, request_id: str
) -> dict[str, Any] | None:
    """The answer cache entry of a request ID, through its audit record."""
    answers = cache.AnswerCache(settings.cache.answers_dir)
    entry = _audit_entry(settings.logs.dir, request_id)
    if entry is not None:
        parts = [
            entry.get(k)
            for k in ("question", "index_version", "prompt_version", "model")
        ]
        if all(isinstance(p, str) for p in parts):
            key = cache.cache_key(*[str(p) for p in parts])
            record = answers.get(key)
            if record is not None:
                return record
        logger.info("no answer cache entry for the audit record")
    return answers.find(request_id)


def find_record(
    settings: config.Settings,
    request_id: str,
    record_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Find the stored answer of a request ID.

    Args:
        settings: The loaded settings (`logs.dir`, `cache.answers_dir`).
        request_id: The request ID.
        record_path: A saved result JSON, or None to read the audit log
            and the answer cache.

    Returns:
        The answer record.

    Raises:
        ExportError: The request ID is malformed, the file does not hold
            the request, or no stored answer exists.
    """
    if not REQUEST_ID.match(request_id):
        raise ExportError(f"not a request ID: {request_id!r}")
    if record_path is not None:
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ExportError(f"cannot read {record_path}: {error}") from None
        if not isinstance(record, dict):
            raise ExportError(f"{record_path} does not hold an answer record")
        if record.get("request_id") != request_id:
            held = record.get("request_id")
            raise ExportError(
                f"{record_path} holds request {held}, not {request_id}"
            )
        return record
    found = _from_cache(settings, request_id)
    if found is None:
        raise ExportError(
            f"no stored answer for request {request_id}: the audit log and "
            "the answer cache hold none (only a primary model answer of a "
            "real provider enters the cache)"
        )
    return found


def render(memo: Memo, fmt: str) -> bytes:
    """Write a memo in a format.

    Args:
        memo: The memo.
        fmt: `markdown`.

    Returns:
        The file bytes.

    Raises:
        ExportError: An unknown format.
    """
    if fmt == MARKDOWN:
        return render_markdown(memo).encode("utf-8")
    raise ExportError(f"unknown memo format {fmt!r}")


def file_name(request_id: str, fmt: str) -> str:
    """The default file name of a memo.

    Args:
        request_id: The request ID (checked by `find_record`).
        fmt: `markdown`.

    Returns:
        Such as `memo-abc123.md`.
    """
    return f"memo-{request_id}{SUFFIXES[fmt]}"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the arguments of `keel export` to its parser.

    Args:
        parser: The `export` subcommand parser.
    """
    parser.add_argument("request_id", help="the request ID of the answer")
    parser.add_argument(
        "--format",
        dest="memo_format",
        choices=FORMATS,
        default=MARKDOWN,
        help="markdown (the default)",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the memo file (default: memo-<request_id>.md)",
    )
    parser.add_argument(
        "--record",
        type=pathlib.Path,
        default=None,
        help="a saved result JSON instead of the audit log and the cache",
    )


def run(settings: config.Settings, args: argparse.Namespace) -> int:
    """Run `keel export`: find the answer, write the memo, print its path.

    Args:
        settings: The loaded settings.
        args: The parsed arguments of the `export` command.

    Returns:
        0 after the memo is written.

    Raises:
        ExportError: No stored answer, or the file cannot be written.
    """
    record = find_record(settings, args.request_id, args.record)
    memo = build_memo(record, args.request_id)
    data = render(memo, args.memo_format)
    out: pathlib.Path = args.out or pathlib.Path(
        file_name(args.request_id, args.memo_format)
    )
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    except OSError as error:
        raise ExportError(f"cannot write {out}: {error}") from None
    sys.stdout.write(
        f"memo {out} ({len(memo.sources)} sources, {len(data)} bytes)\n"
    )
    return 0
