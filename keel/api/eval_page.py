"""The data of the `/api/eval` page (chapter 25.2, W-02).

The page shows the newest report of the admin eval job (`<run id>.md`
in `eval.report_dir`, `<logs.dir>/eval` by default, which is writable on
the host) or, before the first run there, the committed `eval/report.md`
(written by `keel eval`), `docs/PROMPT_LOG.md`, and the text of each
answer prompt version (`prompts/answer_system_v*.md` and
`prompts/answer_user_v*.md`), all read-only. The
service sends the markdown as text; the front-end renders it through the
same `marked` and DOMPurify path as the answers, with the allow list of
chapter 15, so no HTML leaves the server.
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
RUN_REPORT_GLOB = "eval-*.md"
MAX_PROMPT_BYTES = 64 * 1024  # a prompt file is about 5 KB
_PROMPT_FILE = re.compile(r"^answer_system_v(\d+)\.(\d+)\.(\d+)\.md$")
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


class PromptVersion(pydantic.BaseModel):
    """The text of 1 answer prompt version.

    Attributes:
        version: The version, such as `1.5.1`.
        system: The system block (`answer_system_v<version>.md`).
        user: The user template (`answer_user_v<version>.md`), or None.
        current: True for the version the service answers with
            (`llm.prompt_version`).
    """

    version: str
    system: str
    user: str | None
    current: bool


class EvalPage(pydantic.BaseModel):
    """The response of `GET /api/eval`.

    Attributes:
        report: The eval report.
        prompt_log: The prompt log.
        gates: The gates of the report, in report order.
        prompts: The answer prompt versions, oldest first.
    """

    report: EvalDocument
    prompt_log: EvalDocument
    gates: list[Gate]
    prompts: list[PromptVersion] = pydantic.Field(default_factory=list)


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


def latest_run_report(report_dir: pathlib.Path | None) -> pathlib.Path | None:
    """The newest report the admin eval job wrote, if any.

    The run ID is `eval-<UTC time>`, so the newest name sorts last.

    Args:
        report_dir: The report directory of the eval job, or None.

    Returns:
        The newest `eval-*.md` file, or None when there is none or the
        directory cannot be read.
    """
    if report_dir is None:
        return None
    try:
        found = sorted(
            path
            for path in report_dir.glob(RUN_REPORT_GLOB)
            if path.is_file() and not path.is_symlink()
        )
    except OSError as error:
        logger.warning("the eval page cannot list %s: %s", report_dir, error)
        return None
    return found[-1] if found else None


def _read_text(path: pathlib.Path) -> str | None:
    """Read a small text file, or None when it is missing or too large."""
    try:
        if path.stat().st_size > MAX_PROMPT_BYTES:
            logger.warning("prompt file over the size limit skipped")
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_prompts(
    prompts_dir: pathlib.Path | None, current: str | None
) -> list[PromptVersion]:
    """Read the text of every answer prompt version.

    Args:
        prompts_dir: The prompt directory (`llm.prompts_dir`), or None.
        current: The version in use (`llm.prompt_version`), or None.

    Returns:
        The versions with a system block, oldest first; empty when the
        directory is missing.
    """
    if prompts_dir is None or not prompts_dir.is_dir():
        return []
    found: list[tuple[tuple[int, int, int], PromptVersion]] = []
    for path in prompts_dir.iterdir():
        match = _PROMPT_FILE.match(path.name)
        if match is None:
            continue
        system = _read_text(path)
        if system is None:
            continue
        major, minor, patch = (int(part) for part in match.groups())
        version = f"{major}.{minor}.{patch}"
        user = _read_text(prompts_dir / f"answer_user_v{version}.md")
        found.append(
            (
                (major, minor, patch),
                PromptVersion(
                    version=version,
                    system=system,
                    user=user,
                    current=version == current,
                ),
            )
        )
    return [prompt for _, prompt in sorted(found, key=operator.itemgetter(0))]


def load(
    report: pathlib.Path,
    prompt_log: pathlib.Path,
    report_dir: pathlib.Path | None = None,
    prompts_dir: pathlib.Path | None = None,
    current_prompt: str | None = None,
) -> EvalPage:
    """Read both files and the gates for `GET /api/eval`.

    Args:
        report: The committed eval report (`server.eval_report`), shown
            when the eval job has written no report yet.
        prompt_log: The prompt log path (`server.prompt_log`).
        report_dir: The report directory of the admin eval job, or None.
        prompts_dir: The prompt directory (`llm.prompts_dir`), or None.
        current_prompt: The prompt version in use, or None.

    Returns:
        The page data.
    """
    latest = latest_run_report(report_dir)
    if latest is not None:
        document = read_document(latest, f"eval run {latest.stem}")
    else:
        document = read_document(report, REPORT_LABEL)
    return EvalPage(
        report=document,
        prompt_log=read_document(prompt_log, PROMPT_LOG_LABEL),
        gates=parse_gates(document.markdown),
        prompts=read_prompts(prompts_dir, current_prompt),
    )
