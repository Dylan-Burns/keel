#!/usr/bin/env python3
"""Label helper for the golden set (chapter 18.2).

Usage:
    uv run python scripts/label_helper.py sections
    uv run python scripts/label_helper.py pool G-01 [G-03 ...]
    uv run python scripts/label_helper.py save G-01 [G-03 ...]

`sections` writes the section-level labels of every question with expected
sources into eval/labels/, stamped with the index version; graded chunks
already in a file stay. `pool` writes eval/labels/G-NN.pool.tmp with the
top 30 candidates of each sub-query (and the extra pool members that
keel/evaluation/labels.py describes) for a person to read. The person
writes eval/labels/G-NN.grades.tmp, 1 line per candidate:
`<chunk_id> <grade> <note>` with the grade 2 (relevant), 1 (partly
relevant), or 0. `save` checks the grades and writes them into the label
file. The script reads the index and never writes to it.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import contextlib
import pathlib
import sqlite3
import sys

from keel import config
from keel import errors
from keel import indexer
from keel import retriever
from keel import understanding
from keel.evaluation import golden
from keel.evaluation import labels
from keel.stores import chunk_store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["sections", "pool", "save"])
    parser.add_argument("ids", nargs="*", help="question IDs for pool, save")
    parser.add_argument(
        "--set",
        dest="golden",
        type=pathlib.Path,
        default=pathlib.Path("eval/golden.yaml"),
    )
    parser.add_argument(
        "--labels", type=pathlib.Path, default=pathlib.Path("eval/labels")
    )
    parser.add_argument("--index", type=pathlib.Path, default=None)
    return parser


def _questions(
    golden_set: golden.GoldenSet, ids: Sequence[str]
) -> list[golden.GoldenQuestion]:
    if not ids:
        raise errors.GoldenSetError("name at least 1 question ID")
    return list(golden_set.select(",".join(ids)))


def _sections(
    golden_set: golden.GoldenSet,
    labels_dir: pathlib.Path,
    stamp: labels.IndexStamp,
    conn: sqlite3.Connection,
) -> None:
    with_sources = [q for q in golden_set.questions if q.expected]
    existing = golden.load_labels(labels_dir, [q.id for q in with_sources])
    for question in with_sources:
        result = labels.section_labels(
            question, conn, stamp, existing.get(question.id)
        )
        labels.write_labels(golden.label_path(labels_dir, question.id), result)
        counts = ", ".join(
            f"{s.filing_id} {s.section} {s.chunks}" for s in result.sections
        )
        print(f"{question.id}: {counts}")


def _pool(
    settings: config.Settings,
    questions: Sequence[golden.GoldenQuestion],
    labels_dir: pathlib.Path,
    index_dir: pathlib.Path,
) -> None:
    base = retriever.Retriever.open(settings, index_dir)
    steps = {
        mode: retriever.Retriever(
            base.conn,
            base.vectors,
            base.embedder,
            base.reranker,
            settings,
            degraded=base.degraded,
            mode=mode,
        )
        for mode in retriever.MODES
    }
    understander = understanding.Understander.from_settings(
        settings, base.catalog
    )
    with contextlib.closing(base.conn):
        for question in questions:
            analysis = understander.analyze(question.question)
            items = labels.pool_candidates(question, analysis, steps, base.conn)
            path = labels_dir / f"{question.id}{labels.POOL_SUFFIX}"
            path.write_text(
                labels.render_pool(question, items), encoding="utf-8"
            )
            print(f"{question.id}: {len(items)} candidates in {path}")


def _save(
    questions: Sequence[golden.GoldenQuestion],
    labels_dir: pathlib.Path,
    stamp: labels.IndexStamp,
    conn: sqlite3.Connection,
) -> None:
    existing = golden.load_labels(labels_dir, [q.id for q in questions])
    for question in questions:
        pool_file = labels_dir / f"{question.id}{labels.POOL_SUFFIX}"
        grades_file = labels_dir / f"{question.id}{labels.GRADES_SUFFIX}"
        pooled = labels.pool_ids(pool_file.read_text(encoding="utf-8"))
        grades = labels.parse_grades(grades_file.read_text(encoding="utf-8"))
        base = labels.section_labels(
            question, conn, stamp, existing.get(question.id)
        )
        merged = labels.merge_grades(base, grades, pooled, conn)
        labels.write_labels(golden.label_path(labels_dir, question.id), merged)
        counts = [
            sum(1 for c in merged.chunks if c.grade == g) for g in (2, 1, 0)
        ]
        print(
            f"{question.id}: grades 2/1/0 = {counts[0]}/{counts[1]}/{counts[2]}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the label helper.

    Args:
        argv: The arguments, or None for sys.argv.

    Returns:
        The exit code.
    """
    args = _parser().parse_args(argv)
    settings = config.load_settings(None)
    index_dir = args.index or settings.index.dir
    build = indexer.current_build(index_dir)
    try:
        if build is None:
            raise errors.IndexMissingError(f"no index at {index_dir}/current")
        golden_set = golden.load_golden(args.golden)
        stamp = labels.IndexStamp.from_build(build)
        if args.command == "pool":
            _pool(
                settings,
                _questions(golden_set, args.ids),
                args.labels,
                index_dir,
            )
        else:
            with contextlib.closing(
                chunk_store.open_read_only(build / chunk_store.FILE_NAME)
            ) as conn:
                if args.command == "sections":
                    _sections(golden_set, args.labels, stamp, conn)
                else:
                    questions = _questions(golden_set, args.ids)
                    _save(questions, args.labels, stamp, conn)
    except (errors.KeelError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
