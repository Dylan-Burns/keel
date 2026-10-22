"""The golden set and its labels (chapters 18.1 and 18.2).

`eval/golden.yaml` holds the 28 questions with their expected sources. The
labels live in `eval/labels/`, 1 file per question, with the index version
of their creation. A section-level label counts every chunk of the expected
(filing, section) pairs as relevant; a chunk-level label grades the pooled
candidates 2 (relevant), 1 (partly relevant), or 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import json
import pathlib
import sqlite3
from typing import Literal

import pydantic

from keel import config
from keel import errors

QuestionKind = Literal[
    "single_company",
    "comparison",
    "trend",
    "numeric",
    "sector",
    "out_of_corpus",
    "ambiguous_entity",
    "adversarial",
]
LabelLevel = Literal["chunk", "section"]
RELEVANT = 2
PARTLY = 1
GRADES = (0, PARTLY, RELEVANT)
LABEL_SUFFIX = ".yaml"


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class ExpectedSource(_Model):
    """1 expected filing of a question and its canonical sections.

    Attributes:
        filing_id: The filing ID, resolved from the index.
        ticker: The ticker.
        form: `10-K` or `10-Q`.
        fiscal_period: The fiscal label of the index, such as `FY2025`.
        sections: The canonical sections.
    """

    filing_id: str
    ticker: str
    form: str
    fiscal_period: str
    sections: tuple[str, ...]


class GoldValue(_Model):
    """The gold value of a numeric question, read from a table chunk.

    Attributes:
        value: The value in `unit`.
        unit: The unit, such as `USD millions`.
        chunk_id: The chunk that states it.
        label: What the value is, such as `Total revenue`.
    """

    value: float
    unit: str
    chunk_id: str
    label: str


class GoldenQuestion(_Model):
    """1 golden question (chapter 18.1).

    Attributes:
        id: `G-01` to `G-28`.
        type: The question type of the chapter table.
        question: The question text.
        note: The note of the chapter table.
        labels: `chunk` or `section`.
        expected: The expected sources.
        expect_out_of_scope: True when the right response is the
            out-of-scope response, with no retrieval and no model call.
        answer_only: True when only the answer metrics apply (G-28).
        subsets: The subset tags.
        gold: The gold values of a numeric question.
    """

    id: str
    type: QuestionKind
    question: str
    note: str = ""
    labels: LabelLevel = "section"
    expected: tuple[ExpectedSource, ...] = ()
    expect_out_of_scope: bool = False
    answer_only: bool = False
    subsets: tuple[str, ...] = ()
    gold: tuple[GoldValue, ...] = ()

    @property
    def tickers(self) -> tuple[str, ...]:
        """The expected companies, in source order without duplicates."""
        return tuple(dict.fromkeys(s.ticker for s in self.expected))

    @property
    def scored(self) -> bool:
        """True when the retrieval metrics apply to the question."""
        return not (self.expect_out_of_scope or self.answer_only)


class GoldenSet(_Model):
    """The golden set file.

    Attributes:
        version: The golden set version (chapter 17.12).
        created: The creation date.
        index_version: The index the filing IDs were resolved from.
        questions: The questions.
    """

    version: str
    created: str
    index_version: str
    questions: tuple[GoldenQuestion, ...]

    @pydantic.model_validator(mode="after")
    def _unique_ids(self) -> GoldenSet:
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question IDs must be unique")
        return self

    def select(self, subset: str | None) -> tuple[GoldenQuestion, ...]:
        """Pick the questions of a subset.

        Args:
            subset: None for all, a subset tag such as `ci`, or a comma
                list of question IDs such as `G-01,G-06`.

        Returns:
            The questions in file order.

        Raises:
            GoldenSetError: The subset names no question.
        """
        if not subset:
            return self.questions
        wanted = {part.strip() for part in subset.split(",") if part.strip()}
        chosen = tuple(
            q
            for q in self.questions
            if q.id in wanted or wanted & set(q.subsets)
        )
        if not chosen:
            raise errors.GoldenSetError(f"no question in subset {subset!r}")
        return chosen


class SectionLabel(_Model):
    """1 expected (filing, section) pair with its chunk count.

    Attributes:
        filing_id: The filing ID.
        section: The canonical section.
        chunks: The chunks of the pair in the labeled index.
    """

    filing_id: str
    section: str
    chunks: int


class ChunkLabel(_Model):
    """1 graded chunk (chapter 18.2).

    Attributes:
        chunk_id: The chunk ID.
        grade: 2 relevant, 1 partly relevant, 0 not relevant.
        filing_id: The filing of the chunk.
        section: The section of the chunk.
        note: Why the grade, in a few words.
    """

    chunk_id: str
    grade: Literal[0, 1, 2]
    filing_id: str
    section: str
    note: str = ""


class QuestionLabels(_Model):
    """The labels of 1 question, stamped with the index they came from.

    Attributes:
        question_id: The question ID.
        level: `chunk` or `section`.
        index_version: The index version of the labels.
        build_id: The index build of the labels.
        chunks_sha256: The chunk digest of that index.
        created: The labeling date.
        pool: How the graded candidates were pooled.
        sections: The section-level labels.
        chunks: The chunk-level labels, empty for a section-level question.
    """

    question_id: str
    level: LabelLevel
    index_version: str
    build_id: str
    chunks_sha256: str
    created: str
    pool: str = ""
    sections: tuple[SectionLabel, ...] = ()
    chunks: tuple[ChunkLabel, ...] = ()

    @property
    def grades(self) -> dict[str, int]:
        """The grade per chunk ID of the chunk-level labels."""
        return {c.chunk_id: c.grade for c in self.chunks}


def load_golden(path: pathlib.Path) -> GoldenSet:
    """Read and validate the golden set.

    Args:
        path: The YAML file.

    Returns:
        The golden set.

    Raises:
        GoldenSetError: The file is absent or not valid.
    """
    try:
        return GoldenSet.model_validate(config.read_yaml(path))
    except errors.ConfigError as error:
        raise errors.GoldenSetError(str(error)) from error
    except pydantic.ValidationError as error:
        raise errors.GoldenSetError(
            f"{path} is not a valid golden set: {error.error_count()} errors"
        ) from error


def label_path(labels_dir: pathlib.Path, question_id: str) -> pathlib.Path:
    """Return the label file of 1 question.

    Args:
        labels_dir: The labels directory.
        question_id: The question ID.

    Returns:
        The path, such as `eval/labels/G-01.yaml`.
    """
    return labels_dir / f"{question_id}{LABEL_SUFFIX}"


def load_labels(
    labels_dir: pathlib.Path, question_ids: Sequence[str]
) -> dict[str, QuestionLabels]:
    """Read the label files of the questions that have one.

    Args:
        labels_dir: The labels directory.
        question_ids: The questions to read.

    Returns:
        The labels by question ID; a question without a file is absent.

    Raises:
        GoldenSetError: A label file is not valid.
    """
    found: dict[str, QuestionLabels] = {}
    for question_id in question_ids:
        path = label_path(labels_dir, question_id)
        if not path.is_file():
            continue
        try:
            labels = QuestionLabels.model_validate(config.read_yaml(path))
        except (errors.ConfigError, pydantic.ValidationError) as error:
            raise errors.GoldenSetError(
                f"{path} is not a valid label file"
            ) from error
        if labels.question_id != question_id:
            raise errors.GoldenSetError(
                f"{path} holds the labels of {labels.question_id}"
            )
        found[question_id] = labels
    return found


@dataclasses.dataclass(frozen=True)
class Judgments:
    """The relevance judgments of 1 question on 1 index.

    Attributes:
        grades: The grade per chunk ID; an absent chunk counts as 0.
        level: `chunk` when graded chunk labels apply, else `section`.
        tickers: The ticker of each judged chunk.
        note: Why the level differs from the label file, or empty.
    """

    grades: Mapping[str, int]
    level: LabelLevel
    tickers: Mapping[str, str]
    note: str = ""

    @property
    def relevant(self) -> frozenset[str]:
        """The chunks of grade 2 (every section-level chunk has grade 2)."""
        return frozenset(c for c, g in self.grades.items() if g >= RELEVANT)


def section_chunks(
    conn: sqlite3.Connection, pairs: Sequence[tuple[str, str]]
) -> dict[str, str]:
    """List the chunks of (filing, section) pairs with their tickers.

    Args:
        conn: An open chunk store.
        pairs: (filing ID, section) pairs.

    Returns:
        The ticker per chunk ID.
    """
    if not pairs:
        return {}
    rows = conn.execute(
        "SELECT c.chunk_id, c.ticker FROM chunks AS c JOIN json_each(?) AS p "
        "ON c.filing_id = json_extract(p.value, '$[0]') "
        "AND c.section = json_extract(p.value, '$[1]')",
        (json.dumps([list(pair) for pair in pairs]),),
    )
    return {str(chunk_id): str(ticker) for chunk_id, ticker in rows}


def chunk_tickers(
    conn: sqlite3.Connection, chunk_ids: Sequence[str]
) -> dict[str, str]:
    """Look up the ticker of chunks that exist in the index.

    Args:
        conn: An open chunk store.
        chunk_ids: The chunk IDs.

    Returns:
        The ticker per chunk ID found.
    """
    rows = conn.execute(
        "SELECT chunk_id, ticker FROM chunks "
        "WHERE chunk_id IN (SELECT value FROM json_each(?))",
        (json.dumps(list(chunk_ids)),),
    )
    return {str(chunk_id): str(ticker) for chunk_id, ticker in rows}


def judgments(
    question: GoldenQuestion,
    labels: QuestionLabels | None,
    conn: sqlite3.Connection,
) -> Judgments:
    """Resolve the judgments of 1 question against the open index.

    Graded chunk labels apply when the label file has them and at least 1
    chunk of grade 2 exists in this index (the mini index of the CI eval
    has other chunk IDs). Otherwise every chunk of the expected (filing,
    section) pairs counts as relevant.

    Args:
        question: The golden question.
        labels: Its labels, or None.
        conn: An open chunk store.

    Returns:
        The judgments.
    """
    pairs = [
        (s.filing_id, sec) for s in question.expected for sec in s.sections
    ]
    note = ""
    if labels is not None and labels.chunks:
        grades = labels.grades
        tickers = chunk_tickers(conn, list(grades))
        if tickers and any(grades[c] >= RELEVANT for c in tickers):
            return Judgments(
                grades={c: g for c, g in grades.items() if c in tickers},
                level="chunk",
                tickers=tickers,
            )
        note = "no grade 2 chunk in this index; section-level labels apply"
    section = section_chunks(conn, pairs)
    return Judgments(
        grades=dict.fromkeys(section, RELEVANT),
        level="section",
        tickers=section,
        note=note,
    )
