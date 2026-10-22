"""The data of the `/api/eval` page (chapter 25.2, W-02).

The page shows `eval/report.md` (written by `keel eval`) and
`docs/PROMPT_LOG.md` read-only. The service sends the markdown as text; the
front-end renders it through the same `marked` and DOMPurify path as the
answers, with the allow list of chapter 15, so no HTML leaves the server.
The only parsing here reads the regression gates table of chapter 18.8 for
the metric bars. A missing file is an empty state, never an error.
"""

from __future__ import annotations

import logging
import operator
import pathlib
import re

import pydantic

logger = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024  # a report larger than this is cut
REPORT_LABEL = "eval/report.md"
PROMPT_LOG_LABEL = "docs/PROMPT_LOG.md"
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_COMPARATOR = re.compile(r"^\s*(>=|<=|>|<)")
_AT_MOST = re.compile(r"\b(or less|at most|or lower|or below)\b", re.IGNORECASE)
_COMPARE = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}


class EvalDocument(pydantic.BaseModel):
    """1 markdown file of the page.

    Attributes:
        source: The repository path the file comes from.
        markdown: The file text, or None when the file does not exist.
        truncated: True when the file was over `MAX_BYTES`.
    """

    source: str
    markdown: str | None
    truncated: bool = False


class Gate(pydantic.BaseModel):
    """1 regression gate of chapter 18.8, read from the report.

    Attributes:
        name: The gate name, such as `Recall at 25`.
        comparator: `>=`, `<=`, `>`, or `<` (a value passes when it
            compares true). A leading symbol names it; without one, the
            words of chapter 18.8 do ("40 seconds or less" is `<=`), and
            a bare number or "or more" is `>=`.
        threshold: The threshold number.
        threshold_text: The threshold cell as the report writes it.
        value: The measured value, or None while pending.
        value_text: The value cell as the report writes it.
        status: The status cell of the report, such as `pass`.
        passed: Whether the value meets the gate; None without a value.
    """

    name: str
    comparator: str
    threshold: float
    threshold_text: str
    value: float | None
    value_text: str
    status: str | None
    passed: bool | None


class EvalPage(pydantic.BaseModel):
    """The response of `GET /api/eval`.

    Attributes:
        report: The eval report.
        prompt_log: The prompt log.
        gates: The gates of the report, in report order.
    """

    report: EvalDocument
    prompt_log: EvalDocument
    gates: list[Gate]


def read_document(path: pathlib.Path, source: str) -> EvalDocument:
    """Read 1 markdown file, or report it as absent.

    Args:
        path: The file.
        source: The label the page shows.

    Returns:
        The document; `markdown` is None when the file is missing or
        unreadable.
    """
    try:
        if not path.is_file():
            return EvalDocument(source=source, markdown=None)
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError as error:
        logger.warning("the eval page cannot read %s: %s", source, error)
        return EvalDocument(source=source, markdown=None)
    truncated = len(raw) > MAX_BYTES
    text = raw[:MAX_BYTES].decode("utf-8", errors="replace")
    return EvalDocument(source=source, markdown=text, truncated=truncated)


def _cells(line: str) -> list[str]:
    """Split 1 markdown table row into its trimmed cells."""
    inner = line.strip()
    inner = inner.removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in inner.split("|")]


def _number(text: str) -> float | None:
    found = _NUMBER.search(text.replace(",", ""))
    return float(found.group()) if found else None


def _gate(row: dict[str, str]) -> Gate | None:
    """Build 1 gate from a row of the gates table, or None."""
    threshold_text = row.get("threshold", "")
    threshold = _number(threshold_text)
    name = row.get("gate", "")
    if threshold is None or not name:
        return None
    found = _COMPARATOR.match(threshold_text)
    if found:
        comparator = found.group(1)
    elif _AT_MOST.search(threshold_text):
        comparator = "<="
    else:
        comparator = ">="
    value_text = row.get("value", "")
    value = _number(value_text)
    status = row.get("status") or None
    passed = None
    # A pending gate (no value, or a value on too small a sample) has no
    # verdict, even when the report prints its value.
    if value is not None and not (status or "").startswith("pending"):
        passed = bool(_COMPARE[comparator](value, threshold))
    return Gate(
        name=name,
        comparator=comparator,
        threshold=threshold,
        threshold_text=threshold_text,
        value=value,
        value_text=value_text,
        status=status,
        passed=passed,
    )


def parse_gates(markdown: str | None) -> list[Gate]:
    """Read the regression gates table of an eval report.

    The table is the first one whose header names the columns `Gate`,
    `Threshold`, and `Value` (chapter 18.8; `keel eval` writes it).

    Args:
        markdown: The report text, or None.

    Returns:
        The gates in table order; empty when the report has no such table.
    """
    if not markdown:
        return []
    lines = markdown.splitlines()
    for start, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        header = [cell.lower() for cell in _cells(line)]
        if not {"gate", "threshold", "value"} <= set(header):
            continue
        gates: list[Gate] = []
        for row_line in lines[start + 2 :]:
            if not row_line.lstrip().startswith("|"):
                break
            row = dict(zip(header, _cells(row_line), strict=False))
            gate = _gate(row)
            if gate is not None:
                gates.append(gate)
        return gates
    return []


def load(report: pathlib.Path, prompt_log: pathlib.Path) -> EvalPage:
    """Read both files and the gates for `GET /api/eval`.

    Args:
        report: The eval report path (`server.eval_report`).
        prompt_log: The prompt log path (`server.prompt_log`).

    Returns:
        The page data.
    """
    document = read_document(report, REPORT_LABEL)
    return EvalPage(
        report=document,
        prompt_log=read_document(prompt_log, PROMPT_LOG_LABEL),
        gates=parse_gates(document.markdown),
    )
