"""The parser of the 10-K and 10-Q filings (chapter 7).

The parser runs the stages of chapter 7.1 in order: decode, header and
separator, normalization, XBRL removal, artifact removal, boundary repair,
table rebuild, cover page, and the metadata checks. A failed check never
raises: the file comes back with a quarantine record and the build goes on
(E-D-22). The parser is deterministic: a repeat run on the same bytes gives
the same output.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
import dataclasses
import datetime
import logging
import pathlib
import re
import time
import urllib.parse

import numpy as np

from keel import errors
from keel import inventory
from keel import tables
from keel.parsers import base

logger = logging.getLogger(__name__)

# Chapter 7.2: the header keys. The 9-key header of 192 corpus files adds
# `Report Period` and `Quarter` (stage 1 finding); both shapes are accepted.
HEADER_LINE = re.compile(
    r"^(Company|Ticker|Filing Type|Filing Date|Report Period|Quarter|CIK"
    r"|Source|URL)\s*:\s*(.*)$"
)
REQUIRED_KEYS = (
    "Company",
    "Ticker",
    "Filing Type",
    "Filing Date",
    "CIK",
    "Source",
    "URL",
)
FORM_MAP = {"10-K (Annual Report)": "10-K", "10-Q (Quarterly Report)": "10-Q"}
SEPARATOR = re.compile(r"^={60}$")
SEPARATOR_SCAN_LINES = 20
TRUSTED_SCHEME = "https"
TRUSTED_HOST = "www.sec.gov"
TRUSTED_PREFIX = "https://www.sec.gov/"

# Chapter 7.4: the XBRL block.
COVER_MARKER = re.compile(
    r"UNITED\s+STATES\s*SECURITIES\s+AND\s+EXCHANGE\s+COMMISSION",
    re.IGNORECASE,
)
PROSE_WINDOW = 300
PROSE_MIN_SPACES = 25
PROSE_MIN_WORDS = 3
PROSE_WORD = re.compile(r"(?<![A-Za-z])[a-z]{4,}(?![A-Za-z])")
XBRL_SIGNS = ("us-gaap:", "xbrli:", "iso4217", "dei:")
MAX_BLOCK = 400_000
MAX_UNSIGNED_CUT = 200
SHORT_BLOCK = 1_000

# Chapter 7.6: page-number and Table-of-Contents artifacts.
A1_FUSED_PAGE_BREAK = re.compile(r"\b\d{1,3}\s*Table of Contents\s*")
A2_BARE_PAGE_NUMBER = re.compile(r"^[ \t]*\d{1,4}[ \t]*$", re.MULTILINE)
A3_STATEMENT_PAGE = re.compile(r"^[ \t]*F-\d{1,3}[ \t]*$", re.MULTILINE)
# A4 is not in chapter 7.6: AAPL and PFE fuse a page footer such as
# `Apple Inc. | 2025 Form 10-K | 1` into the prose (838 times), which makes
# a prose line look like a table row.
A4_FOOTER_TAIL = re.compile(
    r"\|\s*(?:Q[1-4]\s+)?\d{4}\s+Form\s+10-[KQ]\s*\|\s*\d{1,3}"
)
A4_FOOTER_NAME = re.compile(r"(?:[A-Z][A-Za-z&'.,]*\s?){1,4}$")
A4_NAME_REACH = 60


# Chapter 7.5: the boundary repair rules R1 to R5.
R1_FUSED_PERIOD = re.compile(r"(?<=[a-z0-9\)\]\"'%])\.(?=[A-Z][a-z])")
R2_US_BOUNDARY = re.compile(r"(?<=\bU\.S\.)(?=[A-Z][a-z])")
# R3 splits before a capital that starts a word of 3 or more letters, so
# `BusinessesNVIDIA` splits as the chapter describes; `[a-z]{2}` would miss
# an all-capital second token.
R3_FUSED_HEADING = re.compile(r"(?<=[a-z]{4})(?=[A-Z][A-Za-z]{2})")
R4_ITEM_LABEL = re.compile(r"(?<!\n)(?=Item\s*\d{1,2}[A-C]?\.)")
R5_SPACES = re.compile(r"[ \t]{2,}")
R5_LINE_EDGES = re.compile(r"[ \t]*\n[ \t]*")
R5_NEWLINES = re.compile(r"\n{3,}")
_TOKEN_BEFORE = re.compile(r"(\S+)$")
_LETTERS = re.compile(r"[A-Za-z']+")

# Chapter 7.9: the cover page. PERIOD_END is the pattern of the chapter
# with 2 more phrases the corpus uses: `year ended` (IBM, MS) and `quarter
# ended`. PERIOD_END_SPLIT reads covers that put the phrase and the date in
# separate table cells (the JPM 10-K filed 2026-02-13).
COVER_WINDOW = 10_000
MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_PHRASE = r"(fiscal\s+year|quarterly\s+period|year|quarter)\s+ended"
PHRASE = re.compile(rf"(?i){_PHRASE}")
PERIOD_END = re.compile(
    rf"(?i){_PHRASE}\s*:?\s*([A-Z][a-z]+\.?\s+\d{{1,2}},?\s*\d{{4}})"
)
PERIOD_END_SPLIT = re.compile(
    rf"(?i){_PHRASE}\b[^\n]{{0,120}}?\n?[^\n]{{0,120}}?"
    rf"\b((?:{MONTHS})\.?\s+\d{{1,2}},?\s*\d{{4}})"
)
DATE_PARTS = re.compile(r"(?i)([a-z]+)\.?\s+(\d{1,2}),?\s*(\d{4})")
# REGISTRANT is the pattern of the chapter; only the label is case-blind
# (MS writes `Registrant`). REGISTRANT_AFTER reads covers that put the name
# after the label (BAC). REGISTRANT_FILE_NO reads covers without the label
# that put the name after the commission file number (MSFT, MRK, PG).
# Table cells may sit between the name and the label (BA, MA).
# REGISTRANT_NOISE strips cover text that runs into
# the name on 1 line, up to and including the commission file number.
REGISTRANT = re.compile(
    r"([A-Z][A-Za-z0-9&.,' -]{2,80}?)[\s|]*\(?\s*(?i:Exact name of registrant)"
)
REGISTRANT_AFTER = re.compile(
    r"(?i:Exact name of registrant)[^:\n)]{0,60}\)?\s*:\s*"
    r"([A-Z][A-Za-z0-9&.,' -]{2,80}?)\s*(?=\(|\||\n|State\b|$)"
)
REGISTRANT_FILE_NO = re.compile(
    r"(?i:commission\s+file\s+(?:number|no\.?))\s*[:.]?\s*\d[\d-]*[\s|]*"
    r"([A-Z][A-Za-z0-9&.,' -]{2,80}?)\s*(?=\||\n|$)"
)
REGISTRANT_NOISE = re.compile(
    r"^.*(?:file\s+(?:number|no\.?)|act\s+of\s+1934)\s*[:.]?\s*[\d-]*\s*",
    re.IGNORECASE,
)
FORM_BY_PHRASE = {
    "fiscal year": "10-K",
    "year": "10-K",
    "quarterly period": "10-Q",
    "quarter": "10-Q",
}
MAX_FILING_LAG_DAYS = 120


@dataclasses.dataclass(frozen=True)
class Header:
    """The header keys of 1 filing.

    Attributes:
        values: The value per key, in file order.
        form: The form code from `FORM_MAP`.
        url_trusted: True when the URL is https on `www.sec.gov`.
    """

    values: dict[str, str]
    form: str
    url_trusted: bool


@dataclasses.dataclass(frozen=True)
class XbrlCut:
    """The result of the XBRL block detection.

    Attributes:
        cut: The offset where the kept body starts.
        block_chars: The characters removed as XBRL, 0 without a block.
        xbrl_present: True when the removed block holds an XBRL sign.
        cover_marker: The offset of the cover marker, or None.
        warnings: The warning codes.
    """

    cut: int
    block_chars: int
    xbrl_present: bool
    cover_marker: int | None
    warnings: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class CoverPage:
    """What the cover page states.

    Attributes:
        marker_found: True when the cover marker is in the text.
        form_phrase: `fiscal year` or `quarterly period`, or None.
        period_end: The period end date, or None.
        split_layout: True when only the split-cell pattern matched.
        registrant: The registrant name, or None.
        registrant_labeled: True when the name sits next to the label
            `Exact name of registrant`; False for the weaker read after
            the commission file number.
    """

    marker_found: bool
    form_phrase: str | None
    period_end: datetime.date | None
    split_layout: bool
    registrant: str | None
    registrant_labeled: bool = True


def find_separator(lines: Sequence[str]) -> int:
    """Find the separator line (chapter 7.3).

    Args:
        lines: The lines of the decoded file.

    Returns:
        The index of the first separator line in the first 20 lines.

    Raises:
        SeparatorMissingError: No line of 60 equals signs in the first 20.
    """
    for index, line in enumerate(lines[:SEPARATOR_SCAN_LINES]):
        if SEPARATOR.match(line):
            return index
    raise errors.SeparatorMissingError(
        f"no separator line in the first {SEPARATOR_SCAN_LINES} lines"
    )


def url_trusted(url: str) -> bool:
    """Tell whether a source URL may render as a link (E-D-28).

    The check is strict so that no URL parser downstream (a browser, the
    front-end) can read another host from a URL this parser trusts.

    Args:
        url: The header URL.

    Returns:
        True only for `https://www.sec.gov/...` with no whitespace or
        control character, no backslash, no `@`, no user, password, or
        port, the https scheme, and the exact host `www.sec.gov`.
    """
    if any(
        char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in url
    ):
        return False
    if "\\" in url or "@" in url or not url.startswith(TRUSTED_PREFIX):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == TRUSTED_SCHEME
        and parts.hostname == TRUSTED_HOST
        and parts.username is None
        and parts.password is None
        and port is None
    )


def parse_header(lines: Sequence[str]) -> Header:
    """Read the header keys (chapter 7.2, check CK-01).

    Args:
        lines: The lines before the separator.

    Returns:
        The header.

    Raises:
        HeaderError: A required key is absent, the form is unknown, or the
            filing date is not an ISO date.
    """
    values: dict[str, str] = {}
    for line in lines:
        match = HEADER_LINE.match(line.strip())
        if match and match[1] not in values:
            values[match[1]] = match[2].strip()
    absent = [key for key in REQUIRED_KEYS if not values.get(key)]
    if absent:
        raise errors.HeaderError("header lacks " + ", ".join(absent))
    form = FORM_MAP.get(values["Filing Type"])
    if form is None:
        raise errors.HeaderError(
            "unknown filing type " + repr(values["Filing Type"])
        )
    if _date(values["Filing Date"]) is None:
        raise errors.HeaderError(
            "filing date is not an ISO date: " + repr(values["Filing Date"])
        )
    return Header(
        values=values, form=form, url_trusted=url_trusted(values["URL"])
    )


def prose_window_start(text: str, limit: int) -> int | None:
    """Find the first position where a prose window starts (chapter 7.4).

    A prose window is 300 characters with at least 25 spaces and at least
    3 lower-case words of 4 or more letters.

    Args:
        text: The normalized body.
        limit: Only positions before this offset count.

    Returns:
        The first such position, or None.
    """
    count = min(limit, len(text))
    if count <= 0:
        return None
    head = text[: count + PROSE_WINDOW]
    codes = np.frombuffer(head.encode("utf-32-le"), dtype=np.uint32)
    spaces = np.concatenate(([0], np.cumsum(codes == ord(" "))))
    starts_at = np.arange(count)
    ends_at = np.minimum(starts_at + PROSE_WINDOW, len(head))
    space_counts = spaces[ends_at] - spaces[starts_at]
    words = [(m.start(), m.end()) for m in PROSE_WORD.finditer(head)]
    if not words:
        return None
    word_starts = np.array([start for start, _ in words])
    word_ends = np.array([end for _, end in words])
    word_counts = np.searchsorted(
        word_ends, ends_at, side="right"
    ) - np.searchsorted(word_starts, starts_at, side="left")
    hits = np.flatnonzero(
        (space_counts >= PROSE_MIN_SPACES) & (word_counts >= PROSE_MIN_WORDS)
    )
    return int(hits[0]) if hits.size else None


def cut_xbrl(body: str) -> XbrlCut:
    """Detect the XBRL block after the separator (chapter 7.4).

    The cover marker is the cut point, and the prose window is the
    fallback for a body without the marker. Chapter 7.4 takes the earlier
    of the 2 points; on the corpus the window starts before the marker in
    205 of 245 files, because a window that ends past the marker counts
    the spaces of the cover text, or the hidden facts at the top of the
    block hold text with spaces (DIS, MCD, MSFT, XOM). That rule leaves
    XBRL in the body (15 to about 100 characters, or the whole block).
    The data wins. A prefix of 200 characters or less without an XBRL
    sign is still cut (GE: `10-K`, `1`, the document name) and counts as
    0 XBRL characters.

    Args:
        body: The normalized body, from the end of the separator line.

    Returns:
        The cut. Without a cut point, or when a long removed block holds no
        XBRL sign, the body stays whole and the warning `no_xbrl_block`
        records it.
    """
    marker = COVER_MARKER.search(body)
    cover = marker.start() if marker else None
    cut = cover if cover is not None else prose_window_start(body, len(body))
    if cut is None:
        return XbrlCut(0, 0, False, cover, ("no_xbrl_block",))
    block = body[:cut]
    if not any(sign in block for sign in XBRL_SIGNS):
        kept = cut if cut <= MAX_UNSIGNED_CUT else 0
        return XbrlCut(kept, 0, False, cover, ("no_xbrl_block",))
    found: list[str] = []
    if cut > MAX_BLOCK:
        found.append("xbrl_block_over_max")
    if cut < SHORT_BLOCK:
        found.append("xbrl_block_short")
    return XbrlCut(cut, cut, True, cover, tuple(found))


def _footer_start(text: str, name: re.Match[str]) -> int:
    """Start the footer name right after a period, a line end, or a pipe.

    The corpus fuses the footer to the sentence before it
    (`accessories.Apple Inc. | 2025 Form 10-K | 1`). The name match may
    take capital words of the prose (`grew In Fiscal Apple Inc.`); words
    drop from the left until the name follows such a boundary. Without
    one, only the tail after the name is removed.
    """
    start = name.start()
    while start < name.end():
        if start == 0 or text[start - 1] in ".\n|":
            return start
        space = text.find(" ", start, name.end())
        if space < 0:
            break
        start = space + 1
    return name.end()


def _remove_footers(text: str) -> tuple[str, int]:
    """Replace each fused page footer (rule A4) with a line break."""
    parts: list[str] = []
    position = count = 0
    for tail in A4_FOOTER_TAIL.finditer(text):
        reach = max(position, tail.start() - A4_NAME_REACH)
        name = A4_FOOTER_NAME.search(text, reach, tail.start())
        start = _footer_start(text, name) if name else tail.start()
        parts.extend((text[position:start], "\n"))
        position = tail.end()
        count += 1
    parts.append(text[position:])
    return "".join(parts), count


def remove_artifacts(text: str) -> tuple[str, int]:
    """Remove page-number, contents, and footer artifacts (A1 to A4).

    Args:
        text: The body after the XBRL cut.

    Returns:
        The text and the number of removals.
    """
    text, footers = _remove_footers(text)
    text, fused = A1_FUSED_PAGE_BREAK.subn("\n", text)
    text, bare = A2_BARE_PAGE_NUMBER.subn("", text)
    text, statement = A3_STATEMENT_PAGE.subn("", text)
    return text, fused + bare + statement + footers


def _r1(abbreviations: frozenset[str]) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        start = max(0, match.start() - 24)
        token = _TOKEN_BEFORE.search(match.string, start, match.start())
        if token:
            word = token.group(1).lstrip("(\"'[") + "."
            if word in abbreviations:
                return "."
        return ". "

    return replace


def _r3(protected: Sequence[str]) -> Callable[[re.Match[str]], str]:
    def replace(match: re.Match[str]) -> str:
        text, point = match.string, match.start()
        left = point
        while left > 0 and (text[left - 1].isalpha() or text[left - 1] == "'"):
            left -= 1
        token = _LETTERS.match(text, left)
        word = token.group(0) if token else ""
        offset = point - left
        for name in protected:
            found = word.find(name)
            while found >= 0:
                if found < offset < found + len(name):
                    return ""
                found = word.find(name, found + 1)
        return "\n"

    return replace


def repair_boundaries(
    text: str,
    abbreviations: frozenset[str],
    protected_names: Sequence[str],
) -> str:
    """Insert sentence and heading boundaries (rules R1 to R5).

    Table rows keep their bytes: the rules R1 to R4 skip a line with 2 or
    more pipes, so a cell never breaks across lines.

    Args:
        text: The body after the artifact removal.
        abbreviations: The abbreviations R1 never treats as an end.
        protected_names: The names R3 never splits.

    Returns:
        The repaired text.
    """
    r1, r3 = _r1(abbreviations), _r3(protected_names)
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if tables.is_table_row(line):
            continue
        fixed = R1_FUSED_PERIOD.sub(r1, line)
        fixed = R2_US_BOUNDARY.sub(" ", fixed)
        fixed = R3_FUSED_HEADING.sub(r3, fixed)
        lines[index] = R4_ITEM_LABEL.sub("\n", fixed)
    repaired = "\n".join(lines)
    repaired = R5_SPACES.sub(" ", repaired)
    repaired = R5_LINE_EDGES.sub("\n", repaired)
    return R5_NEWLINES.sub("\n\n", repaired).strip("\n ")


def parse_date(text: str) -> datetime.date | None:
    """Read a cover page date such as `January 26, 2025`.

    Args:
        text: The date text.

    Returns:
        The date, or None when the month or the day is not valid.
    """
    match = DATE_PARTS.search(text)
    if match is None:
        return None
    name = match[1].lower()
    for month, full in enumerate(MONTHS.split("|")[:12], start=1):
        if full == name or (len(name) >= 3 and full.startswith(name)):
            try:
                return datetime.date(int(match[3]), month, int(match[2]))
            except ValueError:
                return None
    return None


def _registrant(window: str) -> tuple[str | None, bool]:
    """Read the registrant name and tell whether the label was next to it."""
    match = REGISTRANT.search(window)
    if match:
        name = REGISTRANT_NOISE.sub("", match[1].strip()).strip(" ,.")
        if name:
            return name, True
    match = REGISTRANT_AFTER.search(window)
    if match:
        return match[1].strip(" ,."), True
    match = REGISTRANT_FILE_NO.search(window)
    if match:
        return match[1].strip(" ,."), False
    return None, False


def _period_end(
    window: str,
) -> tuple[str | None, datetime.date | None, bool]:
    """Read the first cover phrase that gives a valid period end date.

    Each phrase occurrence tries PERIOD_END first, then PERIOD_END_SPLIT,
    so a split-cell cover never borrows a date from a later sentence.
    """
    for phrase in PHRASE.finditer(window):
        for pattern, split in ((PERIOD_END, False), (PERIOD_END_SPLIT, True)):
            match = pattern.match(window, phrase.start())
            day = parse_date(match[2]) if match else None
            if match and day:
                return " ".join(match[1].lower().split()), day, split
    return None, None, False


def read_cover(text: str) -> CoverPage:
    """Read the form phrase, the period end, and the registrant (7.9).

    Args:
        text: The clean text, which starts at or near the cover page.

    Returns:
        What the cover page states. The search starts at the cover marker,
        or at the text start without one, and covers 10,000 characters.
    """
    marker = COVER_MARKER.search(text)
    start = marker.start() if marker else 0
    window = text[start : start + COVER_WINDOW]
    phrase, period, split = _period_end(window)
    registrant, labeled = _registrant(window)
    return CoverPage(
        marker_found=marker is not None,
        form_phrase=phrase,
        period_end=period,
        split_layout=split,
        registrant=registrant,
        registrant_labeled=labeled,
    )


class _Checks:
    """Collects the check results and the first quarantine."""

    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        self.results: list[base.CheckResult] = []
        self.warnings: list[str] = []
        self.quarantine: base.QuarantineRecord | None = None

    def passed(self, check: str) -> None:
        self.results.append(base.CheckResult(check=check, status="pass"))

    def warn(self, check: str, code: str, detail: str) -> None:
        self.results.append(
            base.CheckResult(check=check, status="warning", detail=detail)
        )
        self.warnings.append(code)

    def fallback(self, check: str, code: str, detail: str) -> None:
        self.results.append(
            base.CheckResult(check=check, status="fallback", detail=detail)
        )
        self.warnings.append(code)

    def block(
        self,
        check: str,
        reason: str,
        detail: str,
        evidence: dict[str, str] | None = None,
    ) -> None:
        self.results.append(
            base.CheckResult(check=check, status="quarantine", detail=detail)
        )
        if self.quarantine is None:
            self.quarantine = base.QuarantineRecord(
                file_name=self.file_name,
                reason=reason,
                detail=detail,
                evidence=evidence or {},
            )


def _quarantined(
    meta: base.FilingMetadata,
    check: str,
    reason: str,
    detail: str,
    started: float,
) -> base.ParsedFiling:
    record = base.QuarantineRecord(
        file_name=meta.file_name, reason=reason, detail=detail
    )
    logger.warning("quarantine %s: %s (%s)", meta.file_name, reason, detail)
    return base.ParsedFiling(
        metadata=meta,
        checks=(
            base.CheckResult(check=check, status="quarantine", detail=detail),
        ),
        quarantine=record,
        parse_seconds=time.perf_counter() - started,
    )


def _date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def _check_identity(
    checks: _Checks,
    name: inventory.FileName | None,
    meta: base.FilingMetadata,
    cover: CoverPage,
) -> str | None:
    """Run CK-03 to CK-06 and return the registrant to record.

    A name read without the registrant label (after the commission file
    number) that does not match is not evidence of a conflict: the read
    may have caught the state of incorporation (DIS). It gives the warning
    `registrant_not_found` and no registrant.
    """
    if name is None:
        checks.warn("CK-03", "filename_unmatched", "file name has no pattern")
    elif name.ticker != meta.ticker:
        checks.block(
            "CK-03",
            "ticker_mismatch",
            f"file name ticker {name.ticker}, header {meta.ticker}",
        )
    else:
        checks.passed("CK-03")
    forms = {meta.form}
    if name is not None:
        forms.add(name.form)
    if cover.form_phrase:
        forms.add(FORM_BY_PHRASE[cover.form_phrase])
    if len(forms) > 1:
        checks.block(
            "CK-04",
            "form_mismatch",
            "forms disagree: " + ", ".join(sorted(f or "" for f in forms)),
        )
    else:
        checks.passed("CK-04")
    if name is None or name.filing_date == meta.filing_date:
        checks.passed("CK-05")
    else:
        checks.warn(
            "CK-05",
            "filing_date_mismatch",
            f"file name date {name.filing_date}, header {meta.filing_date}",
        )
    matched = cover.registrant is not None and base.names_match(
        meta.company or "", cover.registrant
    )
    if cover.registrant is None or (
        not matched and not cover.registrant_labeled
    ):
        checks.warn(
            "CK-06",
            "registrant_not_found",
            "no labeled registrant on the cover page"
            + (
                f" (unlabeled read {cover.registrant!r})"
                if cover.registrant
                else ""
            ),
        )
        return None
    if not matched:
        checks.block(
            "CK-06",
            "registrant_mismatch",
            f"cover registrant {cover.registrant!r}, header company "
            f"{meta.company!r}",
            {
                "header_company": meta.company or "",
                "cover_registrant": cover.registrant,
                "url": meta.url or "",
                "filing_date": str(meta.filing_date),
            },
        )
    else:
        checks.passed("CK-06")
    return cover.registrant


def _check_period(
    checks: _Checks,
    name: inventory.FileName | None,
    meta: base.FilingMetadata,
    cover: CoverPage,
    override_end: datetime.date | None,
) -> tuple[datetime.date | None, base.PeriodSource | None]:
    """Run CK-07 to CK-09 and return the period end and its source."""
    period_end: datetime.date | None
    source: base.PeriodSource | None
    code = name.period_code if name else None
    if override_end is not None:
        period_end, source = override_end, "override"
        checks.passed("CK-07")
    elif cover.period_end is not None:
        period_end, source = cover.period_end, "cover"
        checks.passed("CK-07")
    elif cover.marker_found and code:
        period_end, source = base.quarter_end(code), "filename"
        checks.fallback(
            "CK-07",
            "period_source_filename",
            f"no period end on the cover page; period code {code}",
        )
    else:
        detail = (
            "no cover page"
            if not cover.marker_found
            else "no period end on the cover page and no period code"
        )
        checks.block("CK-07", "cover_page_not_found", detail)
        return None, None
    if code is None:
        checks.results.append(base.CheckResult(check="CK-08", status="skipped"))
    elif base.calendar_quarter(period_end) == code:
        checks.passed("CK-08")
    else:
        checks.warn(
            "CK-08",
            "period_code_mismatch",
            f"period code {code}, period end {period_end}",
        )
    lag = (meta.filing_date - period_end).days if meta.filing_date else None
    if lag is not None and 0 <= lag <= MAX_FILING_LAG_DAYS:
        checks.passed("CK-09")
    else:
        checks.warn(
            "CK-09",
            "filing_lag",
            f"filed {lag} days after the period end {period_end}",
        )
    return period_end, source


class TenKTenQParser:
    """The parser of 10-K and 10-Q filings.

    Attributes:
        forms: The header forms the parser reads.
    """

    forms: tuple[str, ...] = ("10-K", "10-Q")

    def parse(
        self, path: pathlib.Path, context: base.ParseContext
    ) -> base.ParsedFiling:
        """Parse 1 file through the stages of chapter 7.1.

        Args:
            path: The filing file.
            context: The dictionaries and corpus facts.

        Returns:
            The parsed filing. A failed check gives a quarantine record;
            the fiscal fields use the fiscal-year-end month of the context
            until the corpus pass sets the month from the ticker's 10-K.
        """
        started = time.perf_counter()
        try:
            data = path.read_bytes()
        except OSError as error:
            meta = base.FilingMetadata(
                file_name=path.name,
                file_sha256="",
                parser_version=context.parser_version,
            )
            return _quarantined(
                meta, "CK-01", "read_error", str(error), started
            )
        meta = base.FilingMetadata(
            file_name=path.name,
            file_sha256=base.sha256_hex(data),
            parser_version=context.parser_version,
        )
        try:
            text = base.decode(data)
        except errors.FilingDecodeError as error:
            return _quarantined(
                meta, "CK-01", "decode_error", str(error), started
            )
        return self._parse_text(text, meta, context, started)

    def _parse_text(
        self,
        text: str,
        meta: base.FilingMetadata,
        context: base.ParseContext,
        started: float,
    ) -> base.ParsedFiling:
        lines = text.split("\n", SEPARATOR_SCAN_LINES + 1)
        try:
            separator = find_separator(lines)
        except errors.SeparatorMissingError as error:
            return _quarantined(
                meta, "CK-02", "separator_missing", str(error), started
            )
        try:
            header = parse_header(lines[:separator])
        except errors.HeaderError as error:
            return _quarantined(
                meta, "CK-01", "header_error", str(error), started
            )
        override = context.overrides.get(meta.file_name, {})
        values = header.values
        meta = meta.model_copy(
            update={
                "ticker": override.get("ticker", values["Ticker"]),
                "company": override.get("company", values["Company"]),
                "cik": values["CIK"],
                "form": override.get("form", header.form),
                "filing_date": _date(values["Filing Date"]),
                "url": values["URL"],
                "url_trusted": header.url_trusted,
                "header_report_period": values.get("Report Period"),
                "header_quarter": values.get("Quarter"),
            }
        )
        checks = _Checks(meta.file_name)
        checks.passed("CK-01")
        checks.passed("CK-02")
        body_start = sum(len(line) + 1 for line in lines[:separator]) + 60
        body = base.normalize_text(text[body_start:])
        xbrl = cut_xbrl(body)
        checks.warnings.extend(xbrl.warnings)
        if not xbrl.xbrl_present:
            logger.info("no_xbrl_block in %s", meta.file_name)
        body, removals = remove_artifacts(body[xbrl.cut :])
        # The cover page reads the text before the boundary repair, so a
        # rule R3 split never breaks a registrant name across lines.
        cover = read_cover(body)
        clean = repair_boundaries(
            body, context.abbreviations, context.protected_names
        )
        found_tables = tuple(tables.find_tables(clean))
        if cover.split_layout:
            checks.warnings.append("cover_period_split_layout")
        name = inventory.parse_filename(meta.file_name)
        registrant = _check_identity(checks, name, meta, cover)
        period_end, source = _check_period(
            checks, name, meta, cover, _date(override.get("period_end_date"))
        )
        _check_manifest(checks, meta.file_name, context.manifest_files)
        meta = meta.model_copy(
            update={
                "period_code": name.period_code if name else None,
                "cover_form_phrase": cover.form_phrase,
                "registrant": registrant,
                "period_end_date": period_end,
                "period_source": source,
                "xbrl_block_chars": xbrl.block_chars,
                "xbrl_present": xbrl.xbrl_present,
                "artifact_removals": removals,
            }
        )
        meta = with_fiscal_period(
            meta,
            context.fiscal_year_ends.get(meta.ticker or "", base.DECEMBER),
        )
        if checks.quarantine is not None:
            logger.warning(
                "quarantine %s: %s (%s)",
                meta.file_name,
                checks.quarantine.reason,
                checks.quarantine.detail,
            )
        return base.ParsedFiling(
            metadata=meta,
            text=clean,
            tables=found_tables,
            checks=tuple(checks.results),
            warnings=tuple(checks.warnings),
            quarantine=checks.quarantine,
            parse_seconds=time.perf_counter() - started,
        )


def _check_manifest(
    checks: _Checks, file_name: str, manifest: frozenset[str] | None
) -> None:
    """Run CK-10: the file is in the manifest list."""
    if manifest is None:
        checks.results.append(base.CheckResult(check="CK-10", status="skipped"))
    elif file_name in manifest:
        checks.passed("CK-10")
    else:
        checks.warn("CK-10", "unmanifested", "file not in the manifest")


def with_fiscal_period(
    meta: base.FilingMetadata, fallback_month: int
) -> base.FilingMetadata:
    """Set the fiscal-year-end month, the fiscal year, and the period.

    Args:
        meta: The metadata with the form and the period end date.
        fallback_month: The fiscal-year-end month of the ticker. A 10-K uses
            the nominal month of its own period end instead.

    Returns:
        The metadata with the 3 fiscal fields, unchanged without a period.
    """
    if meta.period_end_date is None or meta.form not in base.FORM_CODES:
        return meta
    month = fallback_month
    if meta.form == "10-K":
        month = base.nominal_month(meta.period_end_date)[1]
    year, period = base.fiscal_period(meta.form, meta.period_end_date, month)
    return meta.model_copy(
        update={
            "fiscal_year_end_month": month,
            "fiscal_year": year,
            "fiscal_period": period,
        }
    )
