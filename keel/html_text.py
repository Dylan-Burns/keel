"""Inline XBRL HTML to the corpus text format (chapter 26.2, step 4).

`keel add` downloads the primary document of a filing, an inline XBRL HTML
file of 1 to 15 MB, and writes it in the format of the corpus files, so the
parser of chapter 7 reads it unchanged: the 7-line header, the line of 60
equals signs, and the body text. The converter drops `script`, `style`,
`head`, and every hidden container (`display:none`, which holds the
`ix:header` with the hidden XBRL facts), renders each table row as its cells
joined by ` | ` on 1 line, puts every other block element on its own line,
and collapses whitespace. It uses the standard library HTML parser, so it
needs no new dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import datetime
import html.parser
import re

from keel import errors

SEPARATOR = "=" * 60
SOURCE = "edgar"
FILING_TYPES = {
    "10-K": "10-K (Annual Report)",
    "10-Q": "10-Q (Quarterly Report)",
}

# Elements whose whole content is dropped.
SKIP = frozenset(
    {"script", "style", "head", "title", "noscript", "template", "ix:header"}
)
# Elements that end a line of text. Table rows and cells have their own
# rules; inline elements (`span`, `a`, `font`, `ix:*`) join their text.
BLOCK = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "body",
        "br",
        "caption",
        "center",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
)
VOID = frozenset(
    {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "wbr"}
)
CELLS = frozenset({"td", "th"})
HIDDEN = re.compile(r"display\s*:\s*none", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")
# Inline elements split a date as `December 31</span> <span>, 2025`; the
# space before the comma would hide the date from the cover page pattern.
SPACE_BEFORE_COMMA = re.compile(r"(?<=\w) (?=,)")
# The same split writes a negative number as `( 12 )`; the corpus has `(12)`.
PAREN_OPEN = re.compile(r"\( (?=[\d.$])")
PAREN_CLOSE = re.compile(r"(?<=[\d%]) \)")


@dataclasses.dataclass(frozen=True)
class FilingHeader:
    """The values of the 7-line header of a corpus file (chapter 7.2).

    Attributes:
        company: The company name, as the submissions JSON states it.
        ticker: The ticker.
        form: `10-K` or `10-Q`.
        filing_date: The filing date.
        cik: The CIK, 10 digits.
        url: The archive URL of the primary document.
    """

    company: str
    ticker: str
    form: str
    filing_date: datetime.date
    cik: str
    url: str

    def lines(self) -> list[str]:
        """Render the header and the separator.

        Returns:
            The 7 header lines with `Source: edgar`, then the separator.

        Raises:
            HeaderError: The form has no corpus filing type, or a value
                holds a line break.
        """
        filing_type = FILING_TYPES.get(self.form)
        if filing_type is None:
            raise errors.HeaderError(f"no corpus filing type for {self.form}")
        values = (
            ("Company", self.company),
            ("Ticker", self.ticker),
            ("Filing Type", filing_type),
            ("Filing Date", self.filing_date.isoformat()),
            ("CIK", self.cik),
            ("Source", SOURCE),
            ("URL", self.url),
        )
        for key, value in values:
            if not value.strip() or "\n" in value or "\r" in value:
                raise errors.HeaderError(f"bad header value for {key}")
        return [f"{key}: {value.strip()}" for key, value in values] + [
            SEPARATOR
        ]


class _Converter(html.parser.HTMLParser):
    """Collect the text lines of an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._stack: list[tuple[str, bool]] = []
        self._hidden = 0
        self._text: list[str] = []
        self._tables = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    # The tree: a stack of open elements, each with a flag that tells
    # whether it opened a hidden or skipped region.

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        style = next((v or "" for k, v in attrs if k == "style"), "")
        hides = tag in SKIP or bool(HIDDEN.search(style))
        if tag not in VOID:
            self._stack.append((tag, hides))
            if hides:
                self._hidden += 1
        if self._hidden:
            return
        self._open(tag)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if not self._hidden:
            self._open(tag)
            if tag not in VOID:
                self._close(tag)

    def handle_endtag(self, tag: str) -> None:
        if not any(name == tag for name, _ in self._stack):
            return
        while self._stack:
            name, hides = self._stack.pop()
            if hides:
                self._hidden -= 1
            elif not self._hidden:
                self._close(name)
            if name == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._hidden:
            return
        target = self._cell if self._cell is not None else self._text
        target.append(data)

    def _open(self, tag: str) -> None:
        if tag == "table":
            self._flush()
            self._tables += 1
            return
        if self._tables == 1 and tag == "tr":
            self._end_row()
            self._row = []
            return
        if self._tables == 1 and tag in CELLS and self._row is not None:
            self._end_cell()
            self._cell = []
            return
        if self._cell is not None:
            # A block inside a cell (or an inner table) is a space.
            self._cell.append(" ")
        elif tag in BLOCK:
            self._flush()

    def _close(self, tag: str) -> None:
        if tag == "table":
            if self._tables == 1:
                self._end_row()
            self._tables = max(self._tables - 1, 0)
            return
        if self._tables == 1 and tag == "tr":
            self._end_row()
            return
        if self._tables == 1 and tag in CELLS:
            self._end_cell()
            return
        if self._cell is not None:
            self._cell.append(" ")
        elif tag in BLOCK:
            self._flush()

    def _flush(self) -> None:
        line = collapse("".join(self._text))
        self._text = []
        if line:
            self.lines.append(line)

    def _end_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(collapse("".join(self._cell)))
        self._cell = None

    def _end_row(self) -> None:
        self._end_cell()
        if self._row is not None:
            line = table_row(self._row)
            if line:
                self._flush()
                self.lines.append(line)
        self._row = None

    def close(self) -> None:
        super().close()
        self._end_row()
        self._flush()


def collapse(text: str) -> str:
    """Collapse runs of whitespace (no-break spaces too) to 1 space.

    Args:
        text: The text.

    Returns:
        The text with single spaces, no space at either end, no space
        between a word and a comma, and none inside the parentheses of a
        negative number.
    """
    text = WHITESPACE.sub(" ", text)
    text = SPACE_BEFORE_COMMA.sub("", text)
    text = PAREN_CLOSE.sub(")", PAREN_OPEN.sub("(", text))
    return text.strip()


def table_row(cells: Sequence[str]) -> str:
    """Render 1 table row as pipe-separated cells on 1 line.

    Empty cells at the start and the end of the row are dropped; empty
    cells between filled ones stay, as in the corpus files.

    Args:
        cells: The cell texts, collapsed.

    Returns:
        The cells joined by ` | `, 1 cell alone, or empty for an empty row.
    """
    filled = [index for index, cell in enumerate(cells) if cell]
    if not filled:
        return ""
    return " | ".join(cells[filled[0] : filled[-1] + 1])


def decode_html(data: bytes) -> str:
    """Decode the bytes of a filing document.

    EDGAR documents are ASCII with character references, UTF-8, or
    Windows-1252; the first that decodes wins.

    Args:
        data: The document bytes.

    Returns:
        The text.
    """
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def html_to_lines(document: str) -> list[str]:
    """Convert an HTML document to its text lines.

    Args:
        document: The HTML text.

    Returns:
        1 entry per block or table row, whitespace collapsed, no empty
        entries.
    """
    converter = _Converter()
    converter.feed(document)
    converter.close()
    return converter.lines


def to_corpus_text(document: bytes, header: FilingHeader) -> str:
    """Convert a filing document to a corpus file (chapter 26.2, step 4).

    Args:
        document: The HTML bytes of the primary document.
        header: The header values.

    Returns:
        The file text: the 7-line header, the separator, a blank line, and
        1 line per block or table row, ending in a line break.

    Raises:
        HeaderError: A header value is unusable.
        EdgarError: The document holds no text.
    """
    lines = html_to_lines(decode_html(document))
    if not lines:
        raise errors.EdgarError(f"no text in {header.url}")
    return "\n".join([*header.lines(), "", *lines]) + "\n"
