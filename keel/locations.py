"""Where a cited chunk sits in its filing, and a deep link to its text.

A citation names a chunk. The reader wants the place in the filing: the
part and item (`Part I, Item 1A. Risk Factors`), the passage within the
item (`passage 3 of 36`), whether the passage is a table, the filing date,
and the accession number. The chunk store holds all of it, so
`locate` reads it for the cited chunk IDs at response time; no chunk ID
and no index format changes (D-23).

The deep link adds a URL text fragment (WICG scroll-to-text) to the SEC
URL, so a browser lands on the quoted text and highlights it. The rule,
shared with `web/src/lib/fragment.ts`:

1. Drop markdown marks (`*`, `_`, backticks, `#`) and a `TABLE:` tag.
2. A quote with `|` is a table row: each cell is a candidate. Otherwise
   the whole quote is the 1 candidate.
3. Split each candidate on whitespace into runs of safe words: letters
   and digits only. A word with 1 trailing `,` `.` `;` `:` `?` `!` keeps
   its core and ends the run; any other word ends the run and is left out,
   because filing HTML may differ from the parsed text in quotes, dashes,
   and other punctuation.
4. Prose: the start is the first 6 words of the first run of 4 or more
   words, else of the first run of 3 words; the end is the last 4 words
   of the last later run of 3 or more words, never overlapping the start.
   Table: the start is the anchor (the table title) when given, because
   row labels repeat across a filing; else the first 6 words of the
   longest cell run of 2 or more words. A table fragment has no end.
5. No run qualifies: the anchor when given, else no fragment and the
   plain URL. An anchor is the longest safe run of its text, up to 8
   words.
6. Percent-encode every character but letters and digits, including
   `-`, `,`, and `&`, and join as `#:~:text=<start>,<end>`.
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
import logging
import re
import sqlite3
from typing import Any

import pydantic

logger = logging.getLogger(__name__)

SEC_PREFIX = "https://www.sec.gov/"
MAX_NEIGHBOURS = 20
START_WORDS = 6
ANCHOR_WORDS = 8
END_WORDS = 4
MIN_PROSE_WORDS = 3
MIN_CELL_WORDS = 2
UNKNOWN_HEADING = "Unknown section"
SECTION_TITLES = {
    "business": "Business",
    "risk_factors": "Risk Factors",
    "legal_proceedings": "Legal Proceedings",
    "mdna": "Management's Discussion and Analysis",
    "market_risk": "Quantitative and Qualitative Disclosures About Market Risk",
    "financial_statements": "Financial Statements",
    "controls": "Controls and Procedures",
    "other": "Other",
    "unknown": "Unclassified section",
}

_SAFE = re.compile(r"^[A-Za-z0-9]+$")
_TRAILING = re.compile(r"^([A-Za-z0-9]+)[,.;:?!]$")
_MARKS = re.compile(r"[*_`#]+")
_TABLE_TAG = re.compile(r"^\s*TABLE:\s*")
_ACCESSION = re.compile(r"/Archives/edgar/data/\d+/(\d{10})(\d{2})(\d{6})/")
_ITEM = re.compile(r"^(?:Part\s+([IV]+)\s+)?Item\s+(\d+)([A-Z]?)$")
# The parts of a 10-K by item number (Form 10-K, General Instructions).
_PARTS_10K = (
    (range(1, 5), "Part I"),
    (range(5, 10), "Part II"),
    (range(10, 15), "Part III"),
    (range(15, 17), "Part IV"),
)


class Location(pydantic.BaseModel):
    """The place of 1 chunk in its filing.

    Attributes:
        section_label: Such as `Part I, Item 1A. Risk Factors`.
        heading: The item heading, such as `Risk Factors`.
        item_label: The raw item label, such as `Item 1A`, or None.
        passage: The 1-based position of the chunk within its item.
        passages: The chunks of the item.
        is_table: True for a table passage.
        anchor: The table title for the deep link of a table passage,
            such as `Third Quarter of Fiscal Year 2026 Summary`, or None.
        filing_date: The filing date.
        accession: Such as `0000320193-25-000079`, or None.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    section_label: str
    heading: str
    item_label: str | None
    passage: int
    passages: int
    is_table: bool
    anchor: str | None = None
    filing_date: str
    accession: str | None


def heading_of(text: str) -> str:
    """Read the item heading from the prefix line of a chunk text.

    Args:
        text: The chunk text, `Company | form | label | heading` first.

    Returns:
        The heading, or `Unknown section` when the prefix has none.
    """
    first = text.split("\n", 1)[0]
    parts = [part.strip() for part in first.split(" | ")]
    return parts[3] if len(parts) >= 4 and parts[3] else UNKNOWN_HEADING


def table_title(text: str) -> str | None:
    """Read the deep link anchor of a table chunk: its title.

    The title is the text after `TABLE:` up to the first ` | `. It may
    start with the end of the paragraph before the table, so the anchor is
    the last safe run of 2 or more words of the title.

    Args:
        text: The chunk text.

    Returns:
        Such as `Revenue by Reportable Segments`, or None.
    """
    for line in text.split("\n"):
        if line.startswith("TABLE:"):
            title = line.removeprefix("TABLE:").split(" | ", 1)[0]
            runs = [run for run in _runs(title) if len(run) >= MIN_CELL_WORDS]
            return " ".join(runs[-1][:ANCHOR_WORDS]) if runs else None
    return None


def part_of(form: str, item_label: str | None) -> tuple[str, str] | None:
    """Split an item label into its part and its item.

    Args:
        form: `10-K` or `10-Q`.
        item_label: Such as `Item 1A` or `Part II Item 1A`.

    Returns:
        (part, item), such as (`Part I`, `Item 1A`), or None when the
        label is not an item label. A 10-K label gets its part from the
        item number; a 10-Q label carries its part.
    """
    match = _ITEM.match((item_label or "").strip())
    if match is None:
        return None
    roman, number, letter = match.groups()
    item = f"Item {number}{letter}"
    if roman:
        return f"Part {roman}", item
    if form.upper().startswith("10-K"):
        for numbers, part in _PARTS_10K:
            if int(number) in numbers:
                return part, item
    return "", item


def section_label(form: str, item_label: str | None, heading: str) -> str:
    """Name a section with its part and item number.

    Args:
        form: `10-K` or `10-Q`.
        item_label: The raw item label, or None.
        heading: The item heading.

    Returns:
        Such as `Part I, Item 1A. Risk Factors`, or the heading alone when
        the label is not an item label.
    """
    split = part_of(form, item_label)
    if split is None:
        return heading
    part, item = split
    prefix = f"{part}, {item}" if part else item
    return f"{prefix}. {heading}"


def accession_of(url: str | None) -> str | None:
    """Read the accession number from an EDGAR archive URL.

    Args:
        url: Such as `.../edgar/data/320193/000032019325000079/x.htm`.

    Returns:
        Such as `0000320193-25-000079`, or None.
    """
    match = _ACCESSION.search(url or "")
    return "-".join(match.groups()) if match else None


_LOCATE = (
    "SELECT c.chunk_id, c.form, c.section, c.item_label, c.is_table, "
    "c.filing_date, "
    "c.text, f.source_url, f.url_trusted, "
    "(SELECT COUNT(*) FROM chunks o WHERE o.ticker = c.ticker "
    "AND o.form = c.form AND o.period_end_date = c.period_end_date "
    "AND o.section = c.section AND o.filing_id = c.filing_id "
    "AND o.item_label IS c.item_label AND o.sequence <= c.sequence), "
    "(SELECT COUNT(*) FROM chunks o WHERE o.ticker = c.ticker "
    "AND o.form = c.form AND o.period_end_date = c.period_end_date "
    "AND o.section = c.section AND o.filing_id = c.filing_id "
    "AND o.item_label IS c.item_label) "
    "FROM chunks c JOIN filings f ON f.filing_id = c.filing_id "
    "WHERE c.chunk_id IN ({marks})"
)


def locate(
    conn: sqlite3.Connection, chunk_ids: Iterable[str]
) -> dict[str, Location]:
    """Read the location of each chunk from the chunk store.

    Args:
        conn: The chunk store.
        chunk_ids: The chunk IDs; fact IDs and unknown IDs are skipped.

    Returns:
        The location per known chunk ID.
    """
    wanted = sorted(set(chunk_ids))
    if not wanted:
        return {}
    marks = ",".join("?" * len(wanted))
    rows = conn.execute(_LOCATE.format(marks=marks), wanted).fetchall()
    found = {}
    for row in rows:
        (chunk_id, form, section, item, table, filed) = row[:6]
        text, url, trusted = row[6:9]
        heading = heading_of(str(text))
        if heading == UNKNOWN_HEADING or heading in SECTION_TITLES:
            heading = SECTION_TITLES.get(str(section), heading)
        trusted_url = str(url) if trusted and url else None
        found[str(chunk_id)] = Location(
            section_label=section_label(str(form), item, heading),
            heading=heading,
            item_label=item,
            passage=int(row[9]),
            passages=int(row[10]),
            is_table=bool(table),
            anchor=table_title(str(text)) if table else None,
            filing_date=str(filed),
            accession=accession_of(trusted_url),
        )
    return found


def annotate(
    conn: sqlite3.Connection, resolved: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Add the location of each chunk citation to the resolved citations.

    A cached or stored answer from before this field gets it here too.
    A store error never fails the answer: the citations keep no location.

    Args:
        conn: The chunk store.
        resolved: The resolved citations as dicts.

    Returns:
        New dicts; a chunk citation gets `location`, a fact citation and
        an unknown chunk keep `location` None.
    """
    try:
        found = locate(conn, [str(c.get("chunk_id")) for c in resolved])
    except sqlite3.Error as error:
        logger.warning("no chunk locations: %s", error)
        found = {}
    out = []
    for cited in resolved:
        place = found.get(str(cited.get("chunk_id")))
        out.append(
            {
                **cited,
                "location": place.model_dump() if place is not None else None,
            }
        )
    return out


class Passage(pydantic.BaseModel):
    """1 chunk of the filing reader, its overlap with the previous trimmed.

    Attributes:
        chunk_id: The chunk ID.
        sequence: The sequence inside the section.
        is_table: True for a table passage.
        text: The body without the prefix line. Chunks overlap by a few
            sentences; the reader shows each sentence once, so the shared
            text stays with the cited passage and is cut from its
            neighbour.
        cited: True for the requested chunk.
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    sequence: int
    is_table: bool
    text: str
    cited: bool


def _body(text: str) -> str:
    """The chunk text without its prefix line."""
    first, _, rest = text.partition("\n")
    return rest if len(first.split(" | ")) >= 4 and rest else text


def _overlap(prev: tuple[int, str], start: int, body: str) -> int:
    """The characters at the start of `body` that end the previous body."""
    prev_end, prev_body = prev
    shared = prev_end - start
    if shared <= 0 or shared > min(len(body), len(prev_body)):
        return 0
    return shared if prev_body[-shared:] == body[:shared] else 0


def passages(
    conn: sqlite3.Connection, chunk_id: str, before: int, after: int
) -> list[Passage] | None:
    """Read the cited chunk and its neighbours in the same item, in order.

    Args:
        conn: The chunk store.
        chunk_id: The cited chunk ID.
        before: The chunks to read before it, at most `MAX_NEIGHBOURS`.
        after: The chunks to read after it, at most `MAX_NEIGHBOURS`.

    Returns:
        The passages, or None for an unknown chunk ID.
    """
    row = conn.execute(
        "SELECT filing_id, section, item_label, sequence FROM chunks "
        "WHERE chunk_id = ?",
        (chunk_id,),
    ).fetchone()
    if row is None:
        return None
    filing_id, section, item, sequence = row
    before = max(0, min(before, MAX_NEIGHBOURS))
    after = max(0, min(after, MAX_NEIGHBOURS))
    rows = conn.execute(
        "SELECT * FROM (SELECT chunk_id, sequence, is_table, text, "
        "char_start, char_end FROM chunks WHERE filing_id = ? "
        "AND section = ? AND item_label IS ? AND sequence < ? "
        "ORDER BY sequence DESC LIMIT ?) "
        "UNION ALL SELECT chunk_id, sequence, is_table, text, char_start, "
        "char_end FROM (SELECT * FROM chunks WHERE filing_id = ? "
        "AND section = ? AND item_label IS ? AND sequence >= ? "
        "ORDER BY sequence LIMIT ?) ORDER BY sequence",
        (
            filing_id,
            section,
            item,
            sequence,
            before,
            filing_id,
            section,
            item,
            sequence,
            after + 1,
        ),
    ).fetchall()
    bodies = [_body(str(r[3])) for r in rows]
    lead = [0] * len(rows)
    tail = [0] * len(rows)
    for i in range(1, len(rows)):
        if rows[i][2] or rows[i - 1][2]:
            continue  # a table never overlaps
        prev = (int(rows[i - 1][5]), bodies[i - 1])
        shared = _overlap(prev, int(rows[i][4]), bodies[i])
        if rows[i][0] == chunk_id:
            tail[i - 1] = shared  # the cited passage keeps its full text
        else:
            lead[i] = shared
    return [
        Passage(
            chunk_id=str(r[0]),
            sequence=int(r[1]),
            is_table=bool(r[2]),
            text=bodies[i][lead[i] : len(bodies[i]) - tail[i]].strip(),
            cited=r[0] == chunk_id,
        )
        for i, r in enumerate(rows)
    ]


def describe(place: Mapping[str, Any] | None) -> str:
    """Name the place of a chunk in 1 line, for a memo footnote.

    Args:
        place: A `Location` as a dict, or None.

    Returns:
        Such as `Part I, Item 1A. Risk Factors, passage 3 of 36,
        accession 0000320193-25-000079`, or an empty string.
    """
    if not place or not place.get("section_label"):
        return ""
    parts = [str(place["section_label"])]
    if place.get("is_table"):
        parts.append("table")
    if place.get("passage") and place.get("passages"):
        number, total = place["passage"], place["passages"]
        parts.append(f"passage {number} of {total}")
    if place.get("accession"):
        parts.append("accession " + str(place["accession"]))
    return ", ".join(parts)


def _runs(text: str) -> list[list[str]]:
    """Split a text into runs of safe words (rule step 3)."""
    runs: list[list[str]] = [[]]
    for token in text.split():
        if _SAFE.match(token):
            runs[-1].append(token)
            continue
        trailing = _TRAILING.match(token)
        if trailing is not None:
            runs[-1].append(trailing.group(1))
        runs.append([])
    return [run for run in runs if run]


def _encode(words: Sequence[str]) -> str:
    """Percent-encode a phrase; letters and digits stay (rule step 6)."""
    return "".join(
        c if c.isascii() and c.isalnum() else f"%{ord(c):02X}"
        for c in " ".join(words)
    )


def _prose(text: str) -> tuple[list[str], list[str]] | None:
    """The start and end words of a prose quote (rule step 4)."""
    runs = [run for run in _runs(text) if len(run) >= MIN_PROSE_WORDS]
    if not runs:
        return None
    longer = [i for i, run in enumerate(runs) if len(run) > MIN_PROSE_WORDS]
    index = longer[0] if longer else 0
    first = runs[index]
    start = first[:START_WORDS]
    rest = [first[len(start) :], *runs[index + 1 :]]
    later = [run for run in rest if len(run) >= MIN_PROSE_WORDS]
    end = later[-1][-END_WORDS:] if later else []
    return start, end


def _anchor(text: str | None) -> list[str] | None:
    """The words of an anchor: its longest safe run (rule step 5)."""
    runs = _runs(_MARKS.sub(" ", text or ""))
    return max(runs, key=len)[:ANCHOR_WORDS] if runs else None


def _table(text: str) -> list[str] | None:
    """The start words of a table quote (rule step 4)."""
    runs = [run for cell in text.split("|") for run in _runs(cell)]
    runs = [run for run in runs if len(run) >= MIN_CELL_WORDS]
    if not runs:
        return None
    longest = max(runs, key=len)
    return longest[:START_WORDS]


def text_fragment(quote: str, anchor: str | None = None) -> str | None:
    """Build the text directive that scrolls to a quote.

    Args:
        quote: The cited quote, verbatim from the chunk.
        anchor: The table title of a table passage: the start of a table
            quote, and the fallback of a prose quote with no safe run.

    Returns:
        Such as `:~:text=Start%20words,end%20words`, or None.
    """
    clean = _TABLE_TAG.sub("", _MARKS.sub(" ", quote))
    start: list[str] | None
    end: list[str] = []
    if "|" in clean:
        start = _anchor(anchor) or _table(clean)
    else:
        prose = _prose(clean)
        start, end = prose if prose is not None else (None, [])
    if start is None:
        start = _anchor(anchor)
    if not start:
        return None
    directive = f":~:text={_encode(start)}"
    return f"{directive},{_encode(end)}" if end else directive


def deep_link(
    url: str | None, quote: str, anchor: str | None = None
) -> str | None:
    """Add the text fragment of a quote to an SEC URL.

    Args:
        url: The trusted SEC URL, or None.
        quote: The cited quote.
        anchor: The anchor of `text_fragment`.

    Returns:
        The URL with `#:~:text=...`, the plain URL when no fragment can be
        built or the URL is not on `https://www.sec.gov/`, or None.
    """
    if not url:
        return None
    if not url.startswith(SEC_PREFIX):
        return url
    fragment = text_fragment(quote, anchor)
    if fragment is None:
        return url
    base = url.split("#", 1)[0]
    return f"{base}#{fragment}"
