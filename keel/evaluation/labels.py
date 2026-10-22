"""Label work for chapter 18.2: section labels, candidate pools, grades.

`scripts/label_helper.py` drives these functions:

1. `sections` writes 1 label file per question with expected sources: the
   expected (filing, section) pairs and their chunk counts, stamped with
   the index version. Graded chunks already in a file stay.
2. `pool` writes the candidates of 1 question to `eval/labels/G-NN.pool.tmp`
   for a person to read: the top 30 of each sub-query of the hybrid
   pipeline, the top 10 of each sub-query of lexical only and of dense
   only (so the ablation variants do not meet unjudged chunks at their
   top ranks), and the top 10 lexical hits in the expected filings with no
   section filter (so a relevant chunk outside the weighted sections can
   be judged).
3. The person writes `eval/labels/G-NN.grades.tmp`, 1 line per candidate:
   `<chunk_id> <grade> <note>`, with the grade 2, 1, or 0.
4. `save` checks the grades against the pool and the index and writes them
   into the label file.

The `.tmp` files are ignored by git; the label files are committed.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import datetime
import json
import pathlib
import re
import sqlite3

import yaml

from keel import errors
from keel import indexer
from keel import retriever
from keel import understanding
from keel.evaluation import golden
from keel.stores import sqlite_fts

POOL_SUFFIX = ".pool.tmp"
GRADES_SUFFIX = ".grades.tmp"
HYBRID_DEPTH = 30
SINGLE_MODE_DEPTH = 10
UNFILTERED_DEPTH = 10
POOL_DESCRIPTION = (
    f"hybrid top {HYBRID_DEPTH}, lexical top {SINGLE_MODE_DEPTH}, and dense "
    f"top {SINGLE_MODE_DEPTH} per sub-query, with the reranker; plus the "
    f"lexical top {UNFILTERED_DEPTH} in the expected filings without a "
    "section filter"
)
_POOL_HEADER = re.compile(r"^=== (\S+) \|", re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class PoolItem:
    """1 candidate to grade.

    Attributes:
        chunk_id: The chunk ID.
        filing_id: The filing ID.
        section: The section.
        found_by: Where the pool found it, such as `hybrid AAPL #3`.
        text: The chunk text with its prefix line.
    """

    chunk_id: str
    filing_id: str
    section: str
    found_by: tuple[str, ...]
    text: str


@dataclasses.dataclass(frozen=True)
class IndexStamp:
    """The index the labels come from.

    Attributes:
        index_version: The index version.
        build_id: The build ID.
        chunks_sha256: The chunk digest.
    """

    index_version: str
    build_id: str
    chunks_sha256: str

    @classmethod
    def from_build(cls, build_dir: pathlib.Path) -> IndexStamp:
        """Read the stamp from the manifest of a build.

        Args:
            build_dir: The build directory.

        Returns:
            The stamp.
        """
        manifest = indexer.load_manifest(build_dir)
        return cls(
            manifest.index_version,
            manifest.build.build_id,
            manifest.chunks_sha256,
        )


def _today() -> str:
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def section_labels(
    question: golden.GoldenQuestion,
    conn: sqlite3.Connection,
    stamp: IndexStamp,
    existing: golden.QuestionLabels | None = None,
) -> golden.QuestionLabels:
    """Build the section-level labels of 1 question from the index.

    Args:
        question: The golden question.
        conn: An open chunk store.
        stamp: The index stamp.
        existing: The current labels, whose graded chunks stay.

    Returns:
        The labels.
    """
    counts = {
        (str(f), str(s)): int(n)
        for f, s, n in conn.execute(
            "SELECT filing_id, section, count(*) FROM chunks "
            "GROUP BY filing_id, section"
        )
    }
    sections = tuple(
        golden.SectionLabel(
            filing_id=source.filing_id,
            section=section,
            chunks=counts.get((source.filing_id, section), 0),
        )
        for source in question.expected
        for section in source.sections
    )
    keep = existing.chunks if existing is not None else ()
    return golden.QuestionLabels(
        question_id=question.id,
        level=question.labels,
        index_version=stamp.index_version,
        build_id=stamp.build_id,
        chunks_sha256=stamp.chunks_sha256,
        created=existing.created if existing and keep else _today(),
        pool=existing.pool if existing is not None else "",
        sections=sections,
        chunks=keep,
    )


class _IndentedDumper(yaml.SafeDumper):  # pylint: disable=too-many-ancestors
    """A YAML dumper that indents block sequences (yamllint default)."""

    def increase_indent(
        self, flow: bool = False, indentless: bool = False
    ) -> None:
        """Indent a sequence inside a mapping as yamllint expects.

        Args:
            flow: True inside a flow collection.
            indentless: Ignored; sequences are always indented.
        """
        del indentless
        super().increase_indent(flow, False)


def write_labels(path: pathlib.Path, labels: golden.QuestionLabels) -> None:
    """Write 1 label file as YAML.

    Args:
        path: The file.
        labels: The labels.
    """
    data = labels.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            data,
            Dumper=_IndentedDumper,
            sort_keys=False,
            allow_unicode=True,
            width=200,
        ),
        encoding="utf-8",
    )


def _add(
    pool: dict[str, PoolItem],
    candidate_id: str,
    row: tuple[str, str, str],
    found_by: str,
) -> None:
    known = pool.get(candidate_id)
    if known is None:
        pool[candidate_id] = PoolItem(
            candidate_id, row[0], row[1], (found_by,), row[2]
        )
    else:
        pool[candidate_id] = dataclasses.replace(
            known, found_by=(*known.found_by, found_by)
        )


def _unfiltered(
    conn: sqlite3.Connection, terms: Sequence[str], filing_ids: Sequence[str]
) -> list[tuple[str, str, str, str]]:
    expression = sqlite_fts.match_expression(terms)
    if not expression or not filing_ids:
        return []
    rows = conn.execute(
        "SELECT c.chunk_id, c.filing_id, c.section, c.text FROM chunks_fts "
        "JOIN chunks AS c ON c.id = chunks_fts.rowid WHERE chunks_fts MATCH ? "
        "AND c.filing_id IN (SELECT value FROM json_each(?)) "
        "ORDER BY bm25(chunks_fts), c.chunk_id LIMIT ?",
        (expression, json.dumps(list(filing_ids)), UNFILTERED_DEPTH),
    )
    return [(str(a), str(b), str(c), str(d)) for a, b, c, d in rows]


def pool_candidates(
    question: golden.GoldenQuestion,
    analysis: understanding.QuestionAnalysis,
    retrievers: Mapping[str, retriever.Retriever],
    conn: sqlite3.Connection,
) -> list[PoolItem]:
    """Pool the candidates of 1 question for grading.

    Args:
        question: The golden question.
        analysis: Its analysis.
        retrievers: The retriever per mode (`hybrid`, `lexical`, `dense`).
        conn: An open chunk store.

    Returns:
        The candidates, in the order found.
    """
    pool: dict[str, PoolItem] = {}
    terms: list[str] = []
    for mode, step in retrievers.items():
        result = step.retrieve(analysis)
        depth = HYBRID_DEPTH if mode == retriever.HYBRID else SINGLE_MODE_DEPTH
        taken: dict[int, int] = {}
        for candidate in result.ranked:
            rank = taken.get(candidate.query, 0) + 1
            if rank > depth:
                continue
            taken[candidate.query] = rank
            label = result.plan.sub_queries[candidate.query].label
            _add(
                pool,
                candidate.chunk_id,
                (candidate.filing_id, candidate.section, candidate.text),
                f"{mode} {label} #{rank}",
            )
        for sub in result.plan.sub_queries:
            terms += [t for t in sub.terms if t not in terms]
    filings = [s.filing_id for s in question.expected]
    for rank, row in enumerate(_unfiltered(conn, terms, filings), start=1):
        _add(pool, row[0], (row[1], row[2], row[3]), f"unfiltered #{rank}")
    return list(pool.values())


def render_pool(
    question: golden.GoldenQuestion, items: Sequence[PoolItem]
) -> str:
    """Render the pool for a person to read.

    Args:
        question: The golden question.
        items: The candidates.

    Returns:
        The text of the pool file.
    """
    expected = "; ".join(
        f"{s.filing_id} ({s.fiscal_period}) " + ", ".join(s.sections)
        for s in question.expected
    )
    lines = [
        f"# {question.id}: {question.question}",
        f"# Expected sources: {expected}",
        f"# {len(items)} candidates. Grade each in {question.id}"
        f"{GRADES_SUFFIX} as `<chunk_id> <grade> <note>`:",
        "# 2 relevant, 1 partly relevant, 0 not relevant.",
        "",
    ]
    for item in items:
        lines.append(
            f"=== {item.chunk_id} | {item.section} | found by: "
            + ", ".join(item.found_by)
        )
        lines += [item.text, ""]
    return "\n".join(lines)


def pool_ids(text: str) -> list[str]:
    """Read the chunk IDs of a pool file.

    Args:
        text: The pool file text.

    Returns:
        The chunk IDs in file order.
    """
    return _POOL_HEADER.findall(text)


def parse_grades(text: str) -> dict[str, tuple[int, str]]:
    """Read a grades file: `<chunk_id> <grade> <note>` per line.

    Args:
        text: The file text; blank lines and `#` lines are skipped.

    Returns:
        The grade and the note per chunk ID.

    Raises:
        GoldenSetError: A line has no valid grade or repeats a chunk.
    """
    grades: dict[str, tuple[int, str]] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 2 or parts[1] not in {"0", "1", "2"}:
            raise errors.GoldenSetError(f"line {number}: no grade 0, 1, or 2")
        if parts[0] in grades:
            raise errors.GoldenSetError(f"line {number}: {parts[0]} repeats")
        grades[parts[0]] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    return grades


def merge_grades(
    labels: golden.QuestionLabels,
    grades: Mapping[str, tuple[int, str]],
    pooled: Sequence[str],
    conn: sqlite3.Connection,
) -> golden.QuestionLabels:
    """Put the grades of the pool into the labels of 1 question.

    Args:
        labels: The section-level labels of the question.
        grades: The grade and note per chunk ID.
        pooled: The chunk IDs of the pool; each needs a grade.
        conn: An open chunk store.

    Returns:
        The labels with the graded chunks, sorted by chunk ID.

    Raises:
        GoldenSetError: A pooled chunk has no grade, or a graded chunk is
            not in the index.
    """
    missing = [c for c in pooled if c not in grades]
    if missing:
        raise errors.GoldenSetError(
            f"{len(missing)} pooled chunks have no grade, first {missing[0]}"
        )
    rows = {
        str(chunk_id): (str(filing_id), str(section))
        for chunk_id, filing_id, section in conn.execute(
            "SELECT chunk_id, filing_id, section FROM chunks "
            "WHERE chunk_id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(grades)),),
        )
    }
    unknown = sorted(set(grades) - set(rows))
    if unknown:
        raise errors.GoldenSetError(f"not in the index: {unknown[0]}")
    chunks = tuple(
        golden.ChunkLabel.model_validate(
            {
                "chunk_id": chunk_id,
                "grade": grade,
                "filing_id": rows[chunk_id][0],
                "section": rows[chunk_id][1],
                "note": note,
            }
        )
        for chunk_id, (grade, note) in sorted(grades.items())
    )
    return labels.model_copy(
        update={
            "level": "chunk",
            "chunks": chunks,
            "pool": POOL_DESCRIPTION,
            "created": _today(),
        }
    )
