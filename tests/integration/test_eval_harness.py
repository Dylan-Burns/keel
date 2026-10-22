"""The eval harness on a synthetic index with a fake embedder and reranker.

The runner, the gates, and the report run on the 2-company index and the
questions of `test_eval_labels`, without loading a model.
"""

import json
import pathlib

import pytest
import test_eval_labels as fixtures

from keel import config
from keel.evaluation import golden
from keel.evaluation import labels
from keel.evaluation import report
from keel.evaluation import runner

pytestmark = pytest.mark.integration

AAPL = fixtures.AAPL
QUESTIONS = fixtures.QUESTIONS


def harness(
    index_dir: pathlib.Path, settings: config.Settings
) -> runner.Harness:
    by_name = {v.name: v for v in runner.ABLATION}
    conn, steps = fixtures.open_steps(
        index_dir,
        settings,
        [(v.name, v.mode, v.rerank) for v in runner.ABLATION],
    )
    return runner.Harness(
        conn=conn,
        understander=fixtures.analyzer(steps["hybrid"], settings),
        retrievers={by_name[name]: step for name, step in steps.items()},
    )


def test_run_scores_refuses_and_skips(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    setup = harness(fixtures.build(tmp_path), settings)
    graded = labels.section_labels(QUESTIONS[0], setup.conn, fixtures.stamp())
    graded = graded.model_copy(
        update={
            "chunks": (
                golden.ChunkLabel(
                    chunk_id=f"{AAPL.filing_id}__risk_factors__0001",
                    grade=2,
                    filing_id=AAPL.filing_id,
                    section="risk_factors",
                ),
            )
        }
    )
    lines: list[str] = []
    results = runner.run(
        QUESTIONS, {"G-01": graded}, setup, progress=lines.append
    )
    by_key = {(r.question_id, r.variant): r for r in results}
    assert len(lines) == len(QUESTIONS)
    main = by_key["G-01", "hybrid"]
    assert main.outcome == runner.SCORED
    assert main.label_level == "chunk"
    assert main.relevant == 1
    assert main.chunks > 0
    assert main.sections
    assert main.metrics["recall_at_48"] == 1.0
    comparison = by_key["G-06", "hybrid"]
    assert comparison.label_level == "section"
    assert comparison.relevant == 12
    assert comparison.metrics["coverage_recall"] == 1.0
    assert {r.variant for r in results if r.question_id == "G-06"} == {
        v.name for v in runner.ABLATION
    }
    assert by_key["G-22", ""].outcome == runner.REFUSED
    assert by_key["G-23", ""].outcome == runner.MISSED_REFUSAL
    wrong = by_key["G-25", "hybrid"]
    assert wrong.outcome == runner.WRONG_REFUSAL
    assert wrong.metrics["recall_at_25"] == 0.0
    assert by_key["G-28", ""].outcome == runner.ANSWER_ONLY

    run = runner.EvalRun(
        info=runner.RunInfo(
            "eval-x", "t", "1.0.0", "1.0.0", "b", "sha", "1.0.0", "model"
        ),
        variants=runner.ABLATION,
        results=tuple(results),
        stale_labels=runner.stale_labels({"G-01": graded}, "other"),
    )
    assert run.stale_labels == ("G-01",)
    assert run.refusal_correctness() == 0.5
    path = tmp_path / "out" / "report.md"
    json_path = report.write(run, QUESTIONS, path)
    text = path.read_text(encoding="utf-8")
    assert "| Recall at 25 | >= 0.85 |" in text
    assert "pending stage 7" in text
    assert "## Ablation" in text
    assert "| dense, no reranker |" in text
    assert "| G-23 | out_of_corpus | missed_refusal |" in text
    assert "## Weakest questions" in text
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data["gates"]) == 10
    assert data["summary"]["hybrid"]["recall_at_48"] is not None


def test_input_error_scores_zero(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    setup = harness(fixtures.build(tmp_path), settings)
    empty = fixtures.question(
        "G-02",
        "?",
        expected=[
            {
                "filing_id": AAPL.filing_id,
                "ticker": "AAPL",
                "form": "10-K",
                "fiscal_period": "FY2025",
                "sections": ["mdna"],
            }
        ],
    )
    results = runner.run([empty], {}, setup)
    assert {r.outcome for r in results} == {runner.INPUT_ERROR}
    assert results[0].metrics["mrr"] == 0.0
    assert "EmptyQuestionError" in results[0].detail
    run = runner.EvalRun(
        info=runner.RunInfo("e", "t", "1", "1", "b", "s", "1", "m"),
        variants=runner.ABLATION,
        results=tuple(results),
    )
    # The input error counts as a 0 in the gate means.
    assert run.gate_values()["recall_at_25"] == 0.0
    assert run.gate_values()["mrr"] == 0.0
