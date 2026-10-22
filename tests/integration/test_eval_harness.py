"""The eval harness on a synthetic index with a fake embedder and reranker.

The runner, the gates, and the report run on the 2-company index and the
questions of `test_eval_labels`, without loading a model.
"""

import dataclasses
import json
import pathlib
import re

import pytest
import test_eval_labels as fixtures

from keel import answer
from keel import config
from keel.evaluation import answers
from keel.evaluation import golden
from keel.evaluation import judge
from keel.evaluation import labels
from keel.evaluation import report
from keel.evaluation import runner
from keel.providers import base
from keel.providers import mock

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
    results, _ = runner.run(
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
    assert "pending: run keel eval --answers" in text
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
    results, _ = runner.run([empty], {}, setup)
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


class AllSupported:
    """A judge client that marks every claim and citation supported."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str) -> judge.JudgeReply:
        del system
        self.calls += 1
        ids = re.findall(r'<(?:claim|citation) id="([CK]\d+)"', user)
        items = [{"id": i, "verdict": "supported", "reason": "r."} for i in ids]
        reply = {
            "claims": [v for v in items if v["id"].startswith("C")],
            "citations": [v for v in items if v["id"].startswith("K")],
        }
        usage = base.UsageReport(input_tokens=1000)
        return judge.JudgeReply(json.dumps(reply), usage, "end_turn")


def test_answer_step_with_mock_provider(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    run_settings = settings.model_copy(
        update={
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
        }
    )
    setup = harness(fixtures.build(tmp_path), run_settings)
    hybrid = setup.retrievers[runner.MAIN]
    replay = answers.ReplayRetriever.from_retriever(hybrid)
    provider = mock.MockProvider(run_settings.llm.model)
    client = AllSupported()
    setup = dataclasses.replace(
        setup,
        retrievers={runner.MAIN: hybrid},
        session=answers.AnswerSession(
            answer.Answerer(run_settings, replay, provider, "1.0.0")
        ),
        replay=replay,
        judge=judge.Judge(client, "You are the evaluation judge."),
    )
    lines: list[str] = []
    results, answered = runner.run(
        QUESTIONS,
        {},
        setup,
        progress=lines.append,
        logs_dir=run_settings.logs.dir,
    )
    assert setup.session is not None
    setup.session.close()
    by_id = {r.question_id: r for r in answered}
    assert set(by_id) == {q.id for q in QUESTIONS}
    # D-01: 1 request per answered question, none for a refusal.
    assert by_id["G-01"].model_requests == 1
    assert by_id["G-22"].model_requests == 0
    assert by_id["G-22"].refusal_correct is True
    assert by_id["G-23"].refusal_correct is False
    assert provider.requests == sum(r.model_requests for r in answered)
    assert by_id["G-01"].schema_valid is True
    assert by_id["G-01"].latency_s is not None
    assert by_id["G-01"].judge is not None
    assert by_id["G-01"].judge.faithfulness == 1.0
    assert by_id["G-06"].coverage_complete == 1.0
    # G-28 answers on the fixture context with the planted chunk.
    assert by_id["G-28"].model_requests == 1
    assert by_id["G-28"].adversarial_ok is True
    assert answers.PLANTED_TEXT in provider.bundles[-1].user
    # The answer of G-01 read the context of the hybrid run, not a new one.
    hybrid_ids = {
        c.candidate.chunk_id
        for c in hybrid.retrieve(
            setup.understander.analyze(QUESTIONS[0].question)
        ).context.chunks
    }
    assert set(provider.bundles[0].chunk_ids) == hybrid_ids
    assert "answer answered" in lines[0]
    run = runner.EvalRun(
        info=runner.RunInfo(
            "eval-x", "t", "1.0.0", "1.0.0", "b", "sha", "1.0.0", "model"
        ),
        variants=(runner.MAIN,),
        results=tuple(results),
        answers=tuple(answered),
    )
    values = run.gate_values()
    assert values["faithfulness"] == 1.0
    assert values["schema_validity"] == 1.0
    assert values["refusal_correctness"] == 0.5
    assert values["latency_p95_s"] is not None
    path = tmp_path / "out" / "report.md"
    json_path = report.write(run, QUESTIONS, path)
    text = path.read_text(encoding="utf-8")
    assert "## Answer metrics" in text
    assert "### Weakest answers" in text
    assert "| G-28 | adversarial | answered | 1 |" in text
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["answers"][0]["judge"]["faithfulness"] == 1.0
