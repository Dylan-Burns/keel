#!/usr/bin/env python3
"""Judge saved answers with the eval judge (chapter 18.4).

Usage:
    uv run keel ask --json "question" > answer.json
    uv run python eval/judge.py answer.json [more.json ...]

Each file holds 1 `final` record of `keel ask --json`. The script prints
the faithfulness, the citation precision, and every verdict that is not
`supported`. It makes 1 request to `llm.judge_model` per answer; the judge
runs only here and in `keel eval --answers`, never at question time
(D-28). The code lives in `keel/evaluation/judge.py`.
"""

from __future__ import annotations

import json
import pathlib
import sys

from keel import config
from keel import indexer
from keel.evaluation import judge
from keel.stores import chunk_store


def main(argv: list[str]) -> int:
    """Judge each answer file and print the result.

    Args:
        argv: The answer files.

    Returns:
        0, or 2 without a file or without a published index.
    """
    if not argv:
        print(__doc__)
        return 2
    settings = config.load_settings(None)
    build = indexer.current_build(settings.index.dir)
    if build is None:
        print(f"no index at {settings.index.dir}/current; run keel index")
        return 2
    prices = config.load_prices(settings.llm.prices)
    step = judge.Judge(
        judge.AnthropicJudgeClient.from_settings(settings),
        judge.load_prompt(settings.llm.prompts_dir),
        prices.models.get(settings.llm.judge_model),
    )
    conn = chunk_store.open_read_only(build / chunk_store.FILE_NAME)
    try:
        for name in argv:
            record = json.loads(pathlib.Path(name).read_text(encoding="utf-8"))
            item = judge.judge_input(record)
            if item is None:
                print(f"{name}: no answer to judge")
                continue
            result = step.judge(item, judge.chunk_texts(conn, item.chunk_ids))
            faithfulness = result.faithfulness
            precision = result.citation_precision
            print(
                f"{name}: faithfulness {faithfulness}, citation precision "
                f"{precision}, judge ${result.cost_usd:.4f} {result.error}"
            )
            for verdict in (
                *result.claims.values(),
                *result.citations.values(),
            ):
                if verdict.verdict != judge.SUPPORTED:
                    print(f"  {verdict.id} {verdict.verdict}: {verdict.reason}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
