"""Canonical section detection for 10-K and 10-Q filings (chapter 8).

The detector extracts every `Item` label of the clean text, classifies
each candidate as a table-of-contents row, a cross-reference, or a real
heading candidate, and selects the real headings with the item order of
the form. It maps the items of both forms to 1 canonical taxonomy keyed on
the form and the Part (chapter 8.5). A detection failure never raises: the
span without a heading becomes `unknown` and the result carries a warning.
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import logging
import re
from typing import Literal

import pydantic
from rapidfuzz import fuzz

from keel import tables

logger = logging.getLogger(__name__)

CORE_10K = ("risk_factors", "mdna", "financial_statements")
CORE_10Q = ("mdna", "financial_statements")
CANONICAL = (
    "business",
    "risk_factors",
    "legal_proceedings",
    "mdna",
    "market_risk",
    "financial_statements",
    "controls",
    "other",
    "excluded",
    "unknown",
)

PART_LABEL = re.compile(
    r"(?m)(?:^[ \t|]*[Pp][Aa][Rr][Tt]|(?<![a-z])PART|(?<=[.\d)])Part)"
    r"[ \t]+(IV|I{1,3})\b"
)
# A label starts a line (rule R4 of chapter 7), or it is fused after a
# period, a page number, or a capital heading, which R4 does not split:
# `...made.2PART I. FINANCIAL INFORMATIONItem 1: Financial Statements`.
_FUSED = r"(?<=[.\d)A-Z\]])"
ITEM_LABEL = re.compile(
    r"(?m)(?:^[ \t]*[Ii][Tt][Ee][Mm]|(?<![a-z])ITEM|" + _FUSED + r"Item)"
    r"[ \t]*(\d{1,2}(?:[A-C](?![a-z]))?)(?![0-9])[ \t]*[.:]?"
)
TOC_HEADING = re.compile(r"(?im)^[ \t]*(?:table of contents|index)[ \t|]*$")
SIGNATURES = re.compile(r"(?m)^[ \t\d]*SIGNATURES?\b")
FORWARD_HEADING = re.compile(
    r"(?im)^[ \t]*(?:cautionary\s+(?:note|statement|language)"
    r"|special\s+note|forward[- ]looking\s+(?:statements|information))"
    r"[^\n]{0,100}$"
)
TITLE_LINE = re.compile(r"(?m)^[ \t\d|]*[A-Z][^\n]{0,100}$")
MDNA_HEADING = re.compile(
    r"(?im)^[ \t\d|]*MANAGEMENT.S\s+DISCUSSION\s+AND\s+ANALYSIS"
)
AUDITOR_REPORT = re.compile(
    r"(?im)^[ \t|]*Report\s+of\s+Independent\s+Registered\s+Public"
)
EXHIBIT_INDEX = re.compile(
    r"(?im)^[ \t|]*(?:exhibit\s+index|index\s+to\s+exhibits)"
)
PAGE_CELL = re.compile(r"\|\s*(\d{1,3})\s*\|?\s*$")
REFERENCE_CUES = (
    "see",
    "refer to",
    "described in",
    "discussed in",
    "included in",
    "set forth in",
    "under",
    "in part",
    "and",
    "or",
    "in",
)
TRAILING_CUES = re.compile(r"\b(?:of this|above|below|herein)\b", re.I)
_NORM = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")

TITLE_WINDOW = 150
REFERENCE_WINDOW = 60
TRAILING_WINDOW = 40
TOC_ZONE_PROSE = 600
CLUSTER_SIZE = 5
CLUSTER_CHARS = 3_000
CLUSTER_GAP = 300
MAX_PAGE_NUMBER = 300
BODY_MIN = 500
SHORT_BODY_MIN = 2
SHORT_TITLE_MIN = 0.95
TITLE_MIN = 0.80
RISK_SHORT = 300
UNKNOWN_MAX = 20_000
FORWARD_MIN = 300
FORWARD_MAX = 8_000
HEADING_LINE_MAX = 90
TIE_SHARE = 0.10
NO_PART_CONFIDENCE = 0.5
FORWARD_LOOKING = "forward_looking"

Kind = Literal["toc", "cross_reference", "heading", "rejected"]

# Expected titles per form, Part, and item (chapter 8.3, `title_match`).
# A tuple holds the accepted variants.
_FORM_K_TITLES: dict[str, tuple[str, ...]] = {
    "1": ("Business",),
    "1A": ("Risk Factors",),
    "1B": ("Unresolved Staff Comments",),
    "1C": ("Cybersecurity",),
    "2": ("Properties",),
    "3": ("Legal Proceedings",),
    "4": ("Mine Safety Disclosures", "Submission of Matters to a Vote"),
    "5": (
        "Market for Registrant's Common Equity, Related Stockholder Matters "
        "and Issuer Purchases of Equity Securities",
        "Market for the Registrant's Common Equity",
    ),
    "6": ("[Reserved]", "Reserved", "Selected Financial Data"),
    "7": (
        "Management's Discussion and Analysis of Financial Condition and "
        "Results of Operations",
        "Management's Discussion and Analysis",
    ),
    "7A": ("Quantitative and Qualitative Disclosures About Market Risk",),
    "8": (
        "Financial Statements and Supplementary Data",
        "Financial Statements",
    ),
    "9": (
        "Changes in and Disagreements with Accountants on Accounting and "
        "Financial Disclosure",
    ),
    "9A": ("Controls and Procedures",),
    "9B": ("Other Information",),
    "9C": (
        "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
    ),
    "10": ("Directors, Executive Officers and Corporate Governance",),
    "11": ("Executive Compensation",),
    "12": (
        "Security Ownership of Certain Beneficial Owners and Management and "
        "Related Stockholder Matters",
    ),
    "13": (
        "Certain Relationships and Related Transactions, and Director "
        "Independence",
    ),
    "14": ("Principal Accountant Fees and Services",),
    "15": (
        "Exhibits and Financial Statement Schedules",
        "Exhibits, Financial Statement Schedules",
        "Exhibits",
    ),
    "16": ("Form 10-K Summary",),
}
_FORM_Q_TITLES: dict[tuple[str, str], tuple[str, ...]] = {
    ("I", "1"): ("Financial Statements",),
    ("I", "2"): _FORM_K_TITLES["7"],
    ("I", "3"): _FORM_K_TITLES["7A"],
    ("I", "4"): ("Controls and Procedures",),
    ("II", "1"): ("Legal Proceedings",),
    ("II", "1A"): ("Risk Factors",),
    ("II", "2"): (
        "Unregistered Sales of Equity Securities and Use of Proceeds",
        "Purchases of Equity Securities",
    ),
    ("II", "3"): ("Defaults Upon Senior Securities",),
    ("II", "4"): ("Mine Safety Disclosures",),
    ("II", "5"): ("Other Information",),
    ("II", "6"): ("Exhibits",),
}
_FORM_K_SECTIONS = {
    "1": "business",
    "1A": "risk_factors",
    "3": "legal_proceedings",
    "7": "mdna",
    "7A": "market_risk",
    "8": "financial_statements",
    "9A": "controls",
    "15": "excluded",
}
_FORM_Q_SECTIONS = {
    ("I", "1"): "financial_statements",
    ("I", "2"): "mdna",
    ("I", "3"): "market_risk",
    ("I", "4"): "controls",
    ("II", "1"): "legal_proceedings",
    ("II", "1A"): "risk_factors",
    ("II", "6"): "excluded",
}
# Items whose bodies are short by design (chapter 8.3, `body_ok`). The data
# adds 10-K Items 8, 10 to 14, and 15 and 10-Q Part II Item 6: many 10-Ks
# state only that the statements follow Item 15, Part III items are
# incorporated by reference, and an exhibits item can be a short list.
_FORM_K_SHORT = frozenset(
    {"1B", "3", "4", "6", "8", "9", "9B", "9C", "10", "11", "12", "13", "14"}
    | {"15", "16"}
)
_FORM_Q_SHORT = frozenset({("II", "3"), ("II", "4"), ("II", "5"), ("II", "6")})
_FORM_K_ORDER = tuple(_FORM_K_TITLES)
_FORM_Q_ORDER = tuple(_FORM_Q_TITLES)


class Section(pydantic.BaseModel):
    """1 canonical section span of the clean text.

    Attributes:
        section: The canonical section name of chapter 8.5.
        item_label: The raw label such as `Item 1A` or `Part II Item 1A`,
            or None for a span without a heading.
        start: The offset of the span start in the clean text.
        end: The offset just after the span.
        confidence: The title match ratio of the selected heading.
        delta_only: True for a 10-Q `risk_factors` span.
        boilerplate_flag: `forward_looking`, or None.
        title: The display title for the chunk prefix line.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    section: str
    item_label: str | None
    start: int
    end: int
    confidence: float
    delta_only: bool = False
    boilerplate_flag: str | None = None
    title: str = ""

    @property
    def excluded(self) -> bool:
        """True when the chunker skips the span."""
        return self.section == "excluded"


class Candidate(pydantic.BaseModel):
    """1 `Item` label match with its features and its class.

    Attributes:
        start: The offset of the label.
        item: The item number such as `1A`.
        part: The Part numeral, `I` to `IV`.
        title_text: The text after the label, up to 150 characters.
        score: The best title match ratio, 0 to 1.
        body_chars: The characters up to the next candidate.
        kind: The class: `toc`, `cross_reference`, `heading`, or `rejected`.
        reason: The feature that decided the class.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    start: int
    item: str
    part: str
    title_text: str
    score: float
    body_chars: int
    kind: Kind
    reason: str


class SectionResult(pydantic.BaseModel):
    """The section detection of 1 filing.

    Attributes:
        sections: The spans in text order, covering the whole text.
        candidates: Every item label match with its class.
        warnings: Warning codes such as `sections_incomplete`.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    sections: tuple[Section, ...]
    candidates: tuple[Candidate, ...]
    warnings: tuple[str, ...] = ()

    def names(self) -> set[str]:
        """Return the canonical names present in the result."""
        return {s.section for s in self.sections}

    def of(self, name: str) -> list[Section]:
        """Return the spans of 1 canonical section.

        Args:
            name: The canonical section name.

        Returns:
            The spans in text order.
        """
        return [s for s in self.sections if s.section == name]


@dataclasses.dataclass(frozen=True)
class _Raw:
    start: int
    item: str
    part: str
    title_text: str
    line_rest: str
    title_end: int


def normalize_title(text: str) -> str:
    """Normalize a title for matching: lower case, letters and digits.

    Args:
        text: The raw title.

    Returns:
        The normalized title with single spaces.
    """
    text = text.lower().replace("&", " and ")
    return _SPACES.sub(" ", _NORM.sub(" ", text)).strip()


def title_score(expected: Sequence[str], rest: str, line_rest: str) -> float:
    """Score the text after a label against the expected titles.

    The text may run into the body on the same line (a fused heading), so
    the score compares the expected title with the prefix of the same
    length. A line that ends soon after the label also gets the token set
    ratio of the whole line.

    Args:
        expected: The accepted title variants.
        rest: The text after the label, up to 150 characters.
        line_rest: The rest of the label line.

    Returns:
        The best ratio, 0 to 1.
    """
    text = normalize_title(rest)
    line = normalize_title(line_rest)
    best = 0.0
    for title in expected:
        want = normalize_title(title)
        if not want:
            continue
        prefix = text[: len(want)]
        score = max(
            fuzz.ratio(want, prefix), fuzz.token_sort_ratio(want, prefix)
        )
        if line and len(line_rest) <= HEADING_LINE_MAX:
            score = max(score, fuzz.token_set_ratio(want, line))
        best = max(best, score / 100.0)
    return best


def _expected(form: str, part: str, item: str) -> tuple[str, ...]:
    if form == "10-Q":
        return _FORM_Q_TITLES.get((part, item), ())
    return _FORM_K_TITLES.get(item, ())


def _order_key(form: str, part: str, item: str) -> int | None:
    if form == "10-Q":
        key = (part, item)
        return _FORM_Q_ORDER.index(key) if key in _FORM_Q_TITLES else None
    return _FORM_K_ORDER.index(item) if item in _FORM_K_TITLES else None


def _is_short(form: str, part: str, item: str) -> bool:
    if form == "10-Q":
        return (part, item) in _FORM_Q_SHORT
    return item in _FORM_K_SHORT


def canonical(form: str, part: str, item: str) -> str:
    """Map a form, Part, and item to the canonical section (chapter 8.5).

    Args:
        form: `10-K` or `10-Q`.
        part: The Part numeral; ignored for a 10-K.
        item: The item number such as `1A`.

    Returns:
        The canonical section name.
    """
    if form == "10-Q":
        return _FORM_Q_SECTIONS.get((part, item), "other")
    return _FORM_K_SECTIONS.get(item, "other")


def _parts(text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1).upper()) for m in PART_LABEL.finditer(text)]


def _raw_candidates(text: str, form: str) -> list[_Raw]:
    parts = _parts(text)
    found: list[_Raw] = []
    for match in ITEM_LABEL.finditer(text):
        start = (
            match.start() + len(match.group(0)) - len(match.group(0).lstrip())
        )
        line_end = text.find("\n", match.end())
        line_end = len(text) if line_end < 0 else line_end
        rest = text[match.end() : match.end() + TITLE_WINDOW]
        rest = rest.split("\n", 1)[0].lstrip(" \t|")
        line_rest = text[match.end() : line_end].strip(" \t|")
        part = "I"
        for position, numeral in parts:
            if position > start:
                break
            part = numeral
        found.append(
            _Raw(
                start=start,
                item=match.group(1).upper(),
                part=part if form == "10-Q" else "",
                title_text=rest,
                line_rest=line_rest,
                title_end=(
                    line_end
                    if len(line_rest) <= HEADING_LINE_MAX
                    else match.end()
                ),
            )
        )
    if form == "10-Q" and not any(p == "II" for _, p in parts):
        found = _parts_by_order(found)
    return found


def _parts_by_order(found: list[_Raw]) -> list[_Raw]:
    """Assign Part II to the items after Part I Item 4 (chapter 8.6)."""
    seen_four = False
    result: list[_Raw] = []
    for raw in found:
        part = "II" if seen_four and raw.item != "4" else "I"
        if raw.item == "4" and not seen_four:
            seen_four, part = True, "I"
        elif raw.item in {"1A", "5", "6"} and seen_four:
            part = "II"
        result.append(dataclasses.replace(raw, part=part))
    return result


def _has_reference_cue(text: str, start: int) -> bool:
    window = text[max(0, start - REFERENCE_WINDOW) : start]
    before = window.rstrip(" \t\n")
    if before.lower().endswith("table of contents"):
        # A running page header left before the heading is not a cue.
        return False
    if not before or "\n\n" in window[len(before) :]:
        # A blank line before the label ends the sentence: no cue.
        return False
    before_end = start - (len(window) - len(before))
    line_start = text.rfind("\n", 0, before_end) + 1
    fused = "\n" not in window[len(before) :]
    prose_line = before_end - line_start > HEADING_LINE_MAX
    if fused and (before[-1] in ",(\"'" or before[-1].islower()):
        return True
    if prose_line and before[-1] in ",(\"'":
        return True
    words = normalize_title(before[-REFERENCE_WINDOW:])
    return any(
        words.endswith(" " + cue) or words == cue for cue in REFERENCE_CUES
    )


def _toc_zone_starts(text: str) -> list[int]:
    return [m.start() for m in TOC_HEADING.finditer(text)]


def _in_cluster(starts: Sequence[int], index: int) -> bool:
    """True when the candidate sits in a run of 5 close candidates."""
    lo = hi = index
    while lo > 0 and starts[lo] - starts[lo - 1] < CLUSTER_GAP:
        lo -= 1
    while hi + 1 < len(starts) and starts[hi + 1] - starts[hi] < CLUSTER_GAP:
        hi += 1
    run = hi - lo + 1
    return run >= CLUSTER_SIZE and starts[hi] - starts[lo] <= CLUSTER_CHARS * (
        run // CLUSTER_SIZE + 1
    )


@dataclasses.dataclass(frozen=True)
class Features:
    """The classification features of 1 candidate (chapter 8.3).

    Attributes:
        has_page_cell: The line ends with a page number cell.
        in_toc_zone: The candidate sits in the table-of-contents zone.
        in_cluster: The candidate sits in a run of close candidates.
        reference_cue: A reference cue precedes the label.
        trailing_cue: A cue such as `of this` follows the title.
        known_item: The form has this item.
        score: The title match ratio.
        body_chars: The characters up to the next candidate.
        short_item: The item has a short body by design.
    """

    has_page_cell: bool
    in_toc_zone: bool
    in_cluster: bool
    reference_cue: bool
    trailing_cue: bool
    known_item: bool
    score: float
    body_chars: int
    short_item: bool


def decide(features: Features) -> tuple[Kind, str]:
    """Classify 1 candidate from its features (chapter 8.3).

    Args:
        features: The features.

    Returns:
        The kind and the feature that decided it.
    """
    body_ok = features.body_chars >= BODY_MIN or (
        features.short_item
        and features.body_chars >= SHORT_BODY_MIN
        and features.score >= SHORT_TITLE_MIN
    )
    rules: tuple[tuple[bool, Kind, str], ...] = (
        (features.has_page_cell, "toc", "has_page_cell"),
        (features.in_toc_zone, "toc", "in_toc_zone"),
        (features.in_cluster, "toc", "in_cluster"),
        (features.reference_cue, "cross_reference", "reference_cue"),
        (
            features.trailing_cue and features.body_chars < BODY_MIN,
            "cross_reference",
            "trailing_cue",
        ),
        (not features.known_item, "rejected", "unknown_item"),
        (features.score < TITLE_MIN, "rejected", "title_match"),
        (body_ok, "heading", "title_match"),
    )
    for matched, kind, reason in rules:
        if matched:
            return kind, reason
    return "rejected", "body_ok"


def classify(text: str, form: str) -> list[Candidate]:
    """Extract and classify every item candidate (chapter 8.2 and 8.3).

    Args:
        text: The clean text of the filing.
        form: `10-K` or `10-Q`.

    Returns:
        The candidates in text order.
    """
    raws = _raw_candidates(text, form)
    starts = [r.start for r in raws]
    cues = [_has_reference_cue(text, r.start) for r in raws]
    # A body runs to the next candidate that is not a cross-reference, so
    # a reference inside a section does not cut the section short.
    bodies: list[int] = []
    following = len(text)
    for index in range(len(raws) - 1, -1, -1):
        bodies.append(following - raws[index].title_end)
        if not cues[index]:
            following = raws[index].start
    bodies.reverse()
    zone_starts = _toc_zone_starts(text)
    toc_zone_open = False
    zone_index = 0
    result: list[Candidate] = []
    for index, raw in enumerate(raws):
        while (
            zone_index < len(zone_starts)
            and zone_starts[zone_index] < raw.start
        ):
            toc_zone_open = True
            zone_index += 1
        body = max(bodies[index], 0)
        in_zone = toc_zone_open
        if toc_zone_open and body >= TOC_ZONE_PROSE:
            toc_zone_open = False
        expected = _expected(form, raw.part, raw.item)
        score = (
            title_score(expected, raw.title_text, raw.line_rest)
            if expected
            else 0.0
        )
        page = (
            PAGE_CELL.search(raw.line_rest + " |")
            if "|" in raw.line_rest
            else None
        )
        has_page = page is not None and int(page.group(1)) <= MAX_PAGE_NUMBER
        kind, reason = decide(
            Features(
                has_page_cell=has_page and len(raw.line_rest) <= TITLE_WINDOW,
                in_toc_zone=in_zone and body < TOC_ZONE_PROSE,
                in_cluster=_in_cluster(starts, index) and body < TOC_ZONE_PROSE,
                reference_cue=cues[index],
                trailing_cue=_trailing_cue(raw, expected),
                known_item=bool(expected),
                score=score,
                body_chars=body,
                short_item=_is_short(form, raw.part, raw.item),
            )
        )
        result.append(
            Candidate(
                start=raw.start,
                item=raw.item,
                part=raw.part,
                title_text=raw.title_text,
                score=round(score, 4),
                body_chars=body,
                kind=kind,
                reason=reason,
            )
        )
    return result


def _trailing_cue(raw: _Raw, expected: Sequence[str]) -> bool:
    longest = max((len(t) for t in expected), default=0)
    after = raw.title_text[longest : longest + TRAILING_WINDOW]
    return bool(TRAILING_CUES.search(after))


def select(candidates: Sequence[Candidate], form: str) -> list[Candidate]:
    """Select the real headings with the order constraint (chapter 8.4).

    The selection is the longest run of heading candidates whose item keys
    increase in the order of the form, with the sum of scores and then the
    body lengths as the tie-breaks.

    Args:
        candidates: The classified candidates in text order.
        form: `10-K` or `10-Q`.

    Returns:
        The selected headings in text order.
    """
    heads = [c for c in candidates if c.kind == "heading"]
    keys = [_order_key(form, c.part, c.item) for c in heads]
    best: list[tuple[int, float, int]] = []
    back: list[int] = []
    for i, head in enumerate(heads):
        value = (1, head.score, head.body_chars)
        link = -1
        for j in range(i):
            key_i, key_j = keys[i], keys[j]
            if key_i is None or key_j is None or key_j >= key_i:
                continue
            count, score, body = best[j]
            option = (count + 1, score + head.score, body + head.body_chars)
            if option > value:
                value, link = option, j
        best.append(value)
        back.append(link)
    if not heads:
        return []
    index = max(range(len(heads)), key=lambda k: best[k])
    chosen: list[Candidate] = []
    while index >= 0:
        chosen.append(heads[index])
        index = back[index]
    return chosen[::-1]


def _label(form: str, head: Candidate) -> str:
    if form == "10-Q":
        return f"Part {head.part} Item {head.item}"
    return f"Item {head.item}"


def _title(form: str, head: Candidate) -> str:
    expected = _expected(form, head.part, head.item)
    return expected[0] if expected else "Unknown section"


def _unknown_spans(start: int, end: int) -> list[Section]:
    spans: list[Section] = []
    for first in range(start, end, UNKNOWN_MAX):
        spans.append(
            Section(
                section="unknown",
                item_label=None,
                start=first,
                end=min(first + UNKNOWN_MAX, end),
                confidence=0.0,
                title="Unknown section",
            )
        )
    return spans


def _marker(pattern: re.Pattern[str], text: str, start: int, end: int) -> int:
    """Return the first match that is not a table row, or -1."""
    for match in pattern.finditer(text, start, end):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.start())
        line = text[line_start : line_end if line_end >= 0 else len(text)]
        if not tables.is_table_row(line):
            return match.start()
    return -1


def carve(
    sections: Sequence[Section], start: int, end: int, new: Section
) -> list[Section]:
    """Replace the range [start, end) of a span list with a new span.

    Args:
        sections: The spans in text order, without overlaps.
        start: The range start.
        end: The range end.
        new: The span to put there; its offsets are set to the range.

    Returns:
        The spans in text order with the overlapped parts trimmed.
    """
    result: list[Section] = []
    for span in sections:
        if span.end <= start or span.start >= end:
            result.append(span)
            continue
        if span.start < start:
            result.append(span.model_copy(update={"end": start}))
        if span.end > end:
            result.append(span.model_copy(update={"start": end}))
    result.append(new.model_copy(update={"start": start, "end": end}))
    return sorted(result, key=lambda s: s.start)


def _stop_after(text: str, sections: Sequence[Section], position: int) -> int:
    """The end of relocated content: exhibit index, signatures, or end."""
    stops = [
        _marker(EXHIBIT_INDEX, text, position, len(text)),
        _marker(SIGNATURES, text, position, len(text)),
    ]
    stops.extend(
        s.start
        for s in sections
        if s.section == "excluded" and s.start > position
    )
    return min((m for m in stops if m > position), default=len(text))


def _anchor(candidates: Sequence[Candidate], item: str) -> int:
    found = [
        c.start
        for c in candidates
        if c.item == item and c.kind not in {"toc", "cross_reference"}
    ]
    return found[-1] if found else 0


def _relocated(name: str, item: str) -> Section:
    return Section(
        section=name,
        item_label=f"Item {item}",
        start=0,
        end=0,
        confidence=TITLE_MIN,
        title=_FORM_K_TITLES[item][0],
    )


def relocate_10k_content(
    text: str,
    sections: Sequence[Section],
    candidates: Sequence[Candidate],
) -> list[Section]:
    """Find a 10-K's MD&A and statements when Items 7 and 8 only point.

    Some 10-Ks keep the MD&A and the statements in a financial section
    under a later item or after the exhibits heading (CVX, XOM, NVDA, DE),
    and Items 7 and 8 only point there. When a core section has no body of
    500 characters, the first MD&A heading line after Item 7 starts
    `mdna`, and the first auditor's report after it starts
    `financial_statements`. Each runs to the next of these markers, the
    exhibit index, the signatures, or the next excluded span.

    Args:
        text: The clean text.
        sections: The spans after the selection and the exclusion.
        candidates: The classified candidates.

    Returns:
        The spans with the relocated content carved in.
    """
    spans = list(sections)

    def has_body(name: str) -> bool:
        return any(
            s.section == name and s.end - s.start >= BODY_MIN for s in spans
        )

    mdna = -1
    if not has_body("mdna"):
        mdna = _marker(MDNA_HEADING, text, _anchor(candidates, "7"), len(text))
    if mdna >= 0:
        report = _marker(AUDITOR_REPORT, text, mdna, len(text))
        stop = _stop_after(text, spans, mdna)
        if 0 <= report < stop:
            stop = report
        spans = carve(spans, mdna, stop, _relocated("mdna", "7"))
    if not has_body("financial_statements"):
        start = max(mdna, _anchor(candidates, "8"))
        report = _marker(AUDITOR_REPORT, text, start, len(text))
        if report >= 0:
            stop = _stop_after(text, spans, report)
            spans = carve(
                spans, report, stop, _relocated("financial_statements", "8")
            )
    return spans


def _standalone_titles(text: str) -> list[tuple[int, str]]:
    """Every line that holds only a 10-K item title, with its title."""
    titles = {
        normalize_title(t): t
        for variants in _FORM_K_TITLES.values()
        for t in variants
    }
    found: list[tuple[int, str]] = []
    for match in TITLE_LINE.finditer(text):
        line = match.group(0)
        if line.count("|") >= 2:
            continue
        key = normalize_title(line)
        if key in titles:
            found.append((match.start(), key))
    return found


def relocate_risk_factors(
    text: str, sections: Sequence[Section]
) -> list[Section]:
    """Find the risk factors of a 10-K laid out as an annual report.

    Some 10-Ks (INTC, MCD, MS) put the items in an annual report layout
    with a cross-reference index, so `Item 1A` never heads the section.
    When no `risk_factors` span exists, the first line that holds only the
    title Risk Factors starts it, and the next title-only line of another
    item, or the end of the span that holds it, ends it.

    Args:
        text: The clean text.
        sections: The spans in text order.

    Returns:
        The spans with the risk factors carved in, when found.
    """
    if any(s.section == "risk_factors" for s in sections):
        return list(sections)
    lines = _standalone_titles(text)
    key = normalize_title(_FORM_K_TITLES["1A"][0])
    start = next((p for p, k in lines if k == key), -1)
    if start < 0:
        return list(sections)
    holder = next(s for s in sections if s.start <= start < s.end)
    end = next(
        (p for p, k in lines if k != key and p >= start + BODY_MIN),
        holder.end,
    )
    end = min(end, holder.end)
    if holder.excluded or end - start < BODY_MIN:
        return list(sections)
    new = Section(
        section="risk_factors",
        item_label="Item 1A",
        start=start,
        end=end,
        confidence=TITLE_MIN,
        title=_FORM_K_TITLES["1A"][0],
    )
    return carve(sections, start, end, new)


def _flag_forward_looking(text: str, sections: list[Section]) -> list[Section]:
    """Split out the forward-looking spans with their flag (chapter 8.4)."""
    result: list[Section] = []
    for span in sections:
        if span.excluded:
            result.append(span)
            continue
        cursor = span.start
        for match in FORWARD_HEADING.finditer(text, span.start, span.end):
            begin = (
                match.start()
                + len(match.group(0))
                - len(match.group(0).lstrip())
            )
            if begin < cursor:
                continue
            finish = _forward_end(text, match.end(), span.end)
            if begin > cursor:
                result.append(
                    span.model_copy(update={"start": cursor, "end": begin})
                )
            result.append(
                span.model_copy(
                    update={
                        "start": begin,
                        "end": finish,
                        "boilerplate_flag": FORWARD_LOOKING,
                    }
                )
            )
            cursor = finish
        if cursor < span.end:
            result.append(span.model_copy(update={"start": cursor}))
    return result


def _forward_end(text: str, start: int, limit: int) -> int:
    """Find the next heading-like line after a forward-looking heading."""
    position = text.find("\n", start)
    while 0 <= position < limit:
        line_end = text.find("\n", position + 1)
        line_end = limit if line_end < 0 else min(line_end, limit)
        line = text[position + 1 : line_end].strip()
        if (
            position + 1 - start >= FORWARD_MIN
            and line
            and len(line) <= HEADING_LINE_MAX
            and line[0].isupper()
            and line[-1] not in ".:;,|"
        ):
            return position + 1
        if position + 1 - start >= FORWARD_MAX:
            return position + 1
        position = line_end if line_end < limit else -1
    return limit


def detect(text: str, form: str) -> SectionResult:
    """Detect the canonical sections of 1 filing.

    Args:
        text: The clean text of the filing (chapter 7).
        form: `10-K` or `10-Q`.

    Returns:
        The sections in text order with the candidates and warnings. The
        span before the first heading and any span without a heading are
        `unknown`.
    """
    candidates = classify(text, form)
    chosen = select(candidates, form)
    warnings: list[str] = []
    no_part_two = form == "10-Q" and not any(p == "II" for _, p in _parts(text))
    sections: list[Section] = []
    if chosen and chosen[0].start > 0:
        sections.extend(_unknown_spans(0, chosen[0].start))
    elif not chosen:
        sections.extend(_unknown_spans(0, len(text)))
    for index, head in enumerate(chosen):
        end = chosen[index + 1].start if index + 1 < len(chosen) else len(text)
        name = canonical(form, head.part, head.item)
        confidence = head.score
        if no_part_two and head.part == "II":
            confidence = NO_PART_CONFIDENCE
        sections.append(
            Section(
                section=name,
                item_label=_label(form, head),
                start=head.start,
                end=end,
                confidence=confidence,
                delta_only=form == "10-Q" and name == "risk_factors",
                title=_title(form, head),
            )
        )
    sections = _exclude_after(text, sections, form)
    if form == "10-K":
        sections = relocate_10k_content(text, sections, candidates)
        sections = relocate_risk_factors(text, sections)
    sections = _flag_forward_looking(text, sections)
    sections = [s for s in sections if s.end > s.start]
    warnings.extend(_coverage_warnings(form, sections, candidates, chosen))
    if no_part_two:
        warnings.append("no_part_ii")
    return SectionResult(
        sections=tuple(sections),
        candidates=tuple(candidates),
        warnings=tuple(warnings),
    )


def _exclude_after(
    text: str, sections: list[Section], form: str
) -> list[Section]:
    """Exclude the exhibits span to the end and the signature page."""
    result: list[Section] = []
    excluded_from: int | None = None
    for span in sections:
        if excluded_from is not None:
            continue
        if span.section == "excluded":
            excluded_from = span.start
        result.append(span)
    if excluded_from is not None and result:
        last = result[-1]
        result[-1] = last.model_copy(update={"end": len(text)})
        # A 10-K Item 16 after the exhibits stays excluded with the rest.
        return result
    signature = None
    for match in SIGNATURES.finditer(text):
        if result and match.start() > result[0].start:
            signature = match.start()
    if signature is None or form not in {"10-K", "10-Q"}:
        return result
    trimmed: list[Section] = []
    for span in result:
        if span.start >= signature:
            continue
        trimmed.append(
            span.model_copy(update={"end": min(span.end, signature)})
        )
    trimmed.append(
        Section(
            section="excluded",
            item_label="Signatures",
            start=signature,
            end=len(text),
            confidence=1.0,
            title="Signatures",
        )
    )
    return trimmed


def _coverage_warnings(
    form: str,
    sections: Sequence[Section],
    candidates: Sequence[Candidate],
    chosen: Sequence[Candidate],
) -> list[str]:
    """The warnings of chapter 8.6 for 1 filing."""
    warnings: list[str] = []
    names = {s.section for s in sections}
    core = CORE_10K if form == "10-K" else CORE_10Q
    if any(name not in names for name in core):
        warnings.append("sections_incomplete")
    risk = [s for s in sections if s.section == "risk_factors"]
    if form == "10-K" and 0 < sum(s.end - s.start for s in risk) < RISK_SHORT:
        warnings.append("risk_factors_short")
    for head in chosen:
        rivals = [
            c
            for c in candidates
            if c.kind == "heading"
            and c.start != head.start
            and (c.part, c.item) == (head.part, head.item)
        ]
        if any(
            abs(c.body_chars - head.body_chars)
            <= TIE_SHARE * max(head.body_chars, 1)
            for c in rivals
        ):
            warnings.append("section_tie")
            break
    return warnings


class SectionsReport(pydantic.BaseModel):
    """The section coverage of a corpus (chapter 8.6).

    Attributes:
        filings: The filings per form.
        core_complete: The filings per form with every core section.
        core_share: The share per form with every core section.
        present: Per form, the filings in which each section is present.
        spans: Per form, the span count of each section.
        warnings: The count per warning code.
        incomplete: The files without every core section, with the absent
            sections.
    """

    filings: dict[str, int]
    core_complete: dict[str, int]
    core_share: dict[str, float]
    present: dict[str, dict[str, int]]
    spans: dict[str, dict[str, int]]
    warnings: dict[str, int]
    incomplete: list[tuple[str, list[str]]]


def coverage_report(
    results: Sequence[tuple[str, str, SectionResult]],
) -> SectionsReport:
    """Build the section coverage of a corpus.

    Args:
        results: 1 (file name, form, detection) per indexable filing.

    Returns:
        The report the build report records.
    """
    filings: dict[str, int] = {}
    complete: dict[str, int] = {}
    present: dict[str, dict[str, int]] = {}
    spans: dict[str, dict[str, int]] = {}
    warnings: dict[str, int] = {}
    incomplete: list[tuple[str, list[str]]] = []
    for file_name, form, result in results:
        filings[form] = filings.get(form, 0) + 1
        names = result.names()
        core = CORE_10K if form == "10-K" else CORE_10Q
        absent = [name for name in core if name not in names]
        if absent:
            incomplete.append((file_name, absent))
        else:
            complete[form] = complete.get(form, 0) + 1
        form_present = present.setdefault(form, dict.fromkeys(CANONICAL, 0))
        form_spans = spans.setdefault(form, dict.fromkeys(CANONICAL, 0))
        for name in names:
            form_present[name] += 1
        for span in result.sections:
            form_spans[span.section] += 1
        for code in result.warnings:
            warnings[code] = warnings.get(code, 0) + 1
    return SectionsReport(
        filings=filings,
        core_complete={form: complete.get(form, 0) for form in filings},
        core_share={
            form: complete.get(form, 0) / count
            for form, count in filings.items()
        },
        present=present,
        spans=spans,
        warnings=dict(sorted(warnings.items())),
        incomplete=incomplete,
    )
