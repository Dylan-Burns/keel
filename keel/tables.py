"""Table row reconstruction with carried titles, labels, and units.

The filings hold tables as flat pipe-delimited rows. The title, the column
labels, and the units often sit apart from the numbers. This module groups
the rows, finds the label rows, the title, and the units phrase, and renders
each table as 1 caption line plus 1 line per data row (chapter 7.8). The
module never converts a number: the text keeps the numbers as written.
"""

from __future__ import annotations

from collections.abc import Sequence
import re

import pydantic

# A table row holds 2 or more pipe characters (chapter 7.8, step 1). A line
# over 2,000 characters is prose with stray pipes, not a row: the longest
# corpus lines with pipes are whole sections (up to 95,141 characters).
MIN_PIPES = 2
MAX_ROW_CHARS = 2_000
# 1 blank line may sit inside a table group (step 2).
MAX_BLANK_GAP = 1
# Up to 2 label rows; a row is a label row when at least half of its
# non-empty cells are not numeric (step 3).
MAX_LABEL_ROWS = 2
LABEL_SHARE = 0.5
# The units phrase and the title come from the 3 lines before the table.
CONTEXT_LINES = 3
MAX_TITLE_CHARS = 120
# A table with more than 40 data rows splits into parts of 40 (step 7).
ROWS_PER_PART = 40

YEAR_CELL = re.compile(r"^(?:19|20)\d{2}$")
# A cell that holds only a currency symbol belongs to the next cell.
CURRENCY_CELL = re.compile(r"^[$\u20ac\u00a3]$")
# `(in millions)`, `(dollars in millions)`, and `($ in millions, ...)`.
UNITS = re.compile(
    r"\((?:\$\s*)?(?:in|dollars in|amounts in)\s+"
    r"(?:thousands|millions|billions)[^)]*\)",
    re.IGNORECASE,
)
# A numeric cell: an optional sign, currency, or parenthesis around digits
# with separators, an optional percent sign, or a dash that stands for nil.
# The em dash and the en dash come from code points (no dashes in source).
NIL_DASHES = "-" + chr(0x2014) + chr(0x2013)
NUMERIC_CELL = re.compile(
    r"^[(\[]?[-+]?\s*[$\u20ac\u00a3]?\s*[(]?\d[\d,]*(?:\.\d+)?\s*[)%]*[)\]]?$"
    + f"|^[{NIL_DASHES}]+$"
)


class Table(pydantic.BaseModel):
    """1 reconstructed table.

    Attributes:
        start: The offset of the first row in the clean text.
        end: The offset just after the last row in the clean text.
        title: The title line before the table, or an empty string.
        units: The units phrase without parentheses, lower case, or empty.
        columns: The column labels from the label rows.
        rows: The data rows, each a tuple of its non-empty cells.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    start: int
    end: int
    title: str
    units: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def caption(self) -> str:
        """Render the caption line.

        Returns:
            `TABLE: <title> | units: <units> | columns: <labels>`, with the
            empty parts left out.
        """
        parts = [f"TABLE: {self.title}".rstrip()]
        if self.units:
            parts.append(f"units: {self.units}")
        if self.columns:
            parts.append("columns: " + " | ".join(self.columns))
        return " | ".join(parts)

    def render(self) -> list[str]:
        """Render the table for the chunker, split into parts of 40 rows.

        Returns:
            1 string per part: the caption line, then 1 line per data row.
            A table with no data rows renders as its caption alone.
        """
        caption = self.caption()
        if not self.rows:
            return [caption]
        parts: list[str] = []
        for first in range(0, len(self.rows), ROWS_PER_PART):
            chunk = self.rows[first : first + ROWS_PER_PART]
            lines = [caption, *(" | ".join(row) for row in chunk)]
            parts.append("\n".join(lines))
        return parts


def is_table_row(line: str) -> bool:
    """Tell whether a line is a pipe table row.

    Args:
        line: 1 line of clean text.

    Returns:
        True when the line holds 2 or more pipe characters and at most
        2,000 characters.
    """
    return len(line) <= MAX_ROW_CHARS and line.count("|") >= MIN_PIPES


def is_units_line(line: str) -> bool:
    """Tell whether a line holds only a units phrase, like `| ($ in millions)`.

    Args:
        line: 1 line of clean text.

    Returns:
        True when the line, without pipes and spaces, is 1 units phrase.
    """
    return UNITS.fullmatch(line.strip().strip("|").strip()) is not None


def split_cells(line: str) -> list[str]:
    """Split a table row into its stripped cells, keeping empty cells.

    Args:
        line: A table row.

    Returns:
        The cells in order. A leading or trailing pipe gives no edge cell.
    """
    cells = [cell.strip() for cell in line.split("|")]
    if cells and not cells[0] and line.lstrip().startswith("|"):
        cells = cells[1:]
    if cells and not cells[-1]:
        cells = cells[:-1]
    return cells


def is_numeric(cell: str) -> bool:
    """Tell whether a cell holds a number or a nil dash.

    Args:
        cell: A stripped cell.

    Returns:
        True for cells such as `130,497`, `$ 4.93`, `(1,234)`, `12 %`, or a
            nil dash.
    """
    return bool(NUMERIC_CELL.match(cell))


def is_label_row(cells: Sequence[str], strict: bool = False) -> bool:
    """Tell whether a row is a label row.

    Args:
        cells: The cells of the row.
        strict: Require that every cell is text or a year. The second row
            uses it: under the 50% rule alone, the first data row of a
            2-column table (`Revenue | 100`) would count as a label row.

    Returns:
        True when the row has a non-empty cell and at least half of the
        non-empty cells are not numeric. A currency symbol cell does not
        count. A bare year counts as a label when the row holds no other
        number, so a header row such as `Segment | 2025 | 2024` is a label
        row and a data row such as `2026 | $ | 354` is not.
    """
    filled = [cell for cell in cells if cell and not CURRENCY_CELL.match(cell)]
    if not filled:
        return False
    text_cells = sum(not is_numeric(cell) for cell in filled)
    years = sum(bool(YEAR_CELL.match(cell)) for cell in filled)
    if text_cells + years == len(filled):
        return True
    return not strict and text_cells / len(filled) >= LABEL_SHARE


def _title(before: Sequence[str]) -> str:
    """Pick the nearest acceptable title line from the lines before.

    A line with a pipe is a fragment of a label row, not a title. A units
    phrase inside the line is not part of the title.
    """
    for line in reversed(before):
        text = UNITS.sub("", line).strip()
        if (
            not text
            or "|" in text
            or len(text) > MAX_TITLE_CHARS
            or text.endswith(".")
        ):
            continue
        return text
    return ""


def merge_currency(cells: Sequence[str]) -> tuple[str, ...]:
    """Drop empty cells and join a currency symbol cell to the next cell.

    Args:
        cells: The cells of a data row.

    Returns:
        The non-empty cells, with `$` and `72,880` joined as `$ 72,880`.
    """
    merged: list[str] = []
    pending = ""
    for cell in cells:
        if not cell:
            continue
        if CURRENCY_CELL.match(cell):
            pending = cell
            continue
        merged.append(f"{pending} {cell}" if pending else cell)
        pending = ""
    if pending:
        merged.append(pending)
    return tuple(merged)


def _units(lines: Sequence[str]) -> str:
    """Find the first units phrase in the lines."""
    for line in lines:
        match = UNITS.search(line)
        if match:
            return match.group(0)[1:-1].strip().lower()
    return ""


def _columns(label_rows: Sequence[Sequence[str]]) -> tuple[str, ...]:
    """Merge 1 or 2 label rows into 1 label per column."""
    if not label_rows:
        return ()
    width = max(len(row) for row in label_rows)
    labels: list[str] = []
    for index in range(width):
        words = [row[index] for row in label_rows if index < len(row)]
        label = " ".join(word for word in words if word)
        if label:
            labels.append(label)
    return tuple(labels)


def _groups(lines: Sequence[str]) -> list[tuple[int, int]]:
    """Find the [first, last] line index of each table group."""
    groups: list[tuple[int, int]] = []
    first = last = -1
    blanks = 0
    for index, line in enumerate(lines):
        if is_table_row(line):
            if first < 0:
                first = index
            last = index
            blanks = 0
        elif first >= 0 and not line.strip() and blanks < MAX_BLANK_GAP:
            blanks += 1
        elif first >= 0 and is_units_line(line):
            # `| ($ in millions)` between the label rows and the data rows
            # belongs to the table; it must not split it.
            last = index
        elif first >= 0:
            groups.append((first, last))
            first = last = -1
            blanks = 0
    if first >= 0:
        groups.append((first, last))
    return groups


def find_tables(text: str) -> list[Table]:
    """Rebuild every table in a clean text.

    Args:
        text: The clean filing text after the boundary repair.

    Returns:
        The tables in text order, with offsets into `text`.
    """
    lines = text.split("\n")
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    tables: list[Table] = []
    for first, last in _groups(lines):
        group = lines[first : last + 1]
        units_lines = [line for line in group if is_units_line(line)]
        rows = [split_cells(line) for line in group if not is_units_line(line)]
        rows = [row for row in rows if any(row)]
        label_count = 0
        while label_count < min(MAX_LABEL_ROWS, len(rows) - 1) and is_label_row(
            rows[label_count], strict=label_count > 0
        ):
            label_count += 1
        label_rows = rows[:label_count]
        before = lines[max(0, first - CONTEXT_LINES) : first]
        units = _units(
            [*before, *units_lines, *(" ".join(row) for row in label_rows)]
        )
        tables.append(
            Table(
                start=offsets[first],
                end=offsets[last] + len(lines[last]),
                title=_title(before),
                units=units,
                columns=_columns(label_rows),
                rows=tuple(merge_currency(row) for row in rows[label_count:]),
            )
        )
    return tables
