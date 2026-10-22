"""Write `eval/report.md` and its JSON twin (chapter 18.9).

The report holds the run ID, the index version, the prompt version, the
model, and the golden set version; then the gates, the retrieval metrics
overall and per question type, the ablation, the refusals, and the result
of every question. The JSON file next to it holds the same results for the
eval page and for later runs to compare against.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import json
import pathlib
from typing import Any

from keel.evaluation import answers as answering
from keel.evaluation import gates
from keel.evaluation import golden
from keel.evaluation import judge as judging
from keel.evaluation import metrics
from keel.evaluation import runner

WEAKEST_SHOWN = 6
_METRICS = (
    ("recall_at_10", "R@10"),
    ("recall_at_25", "R@25"),
    ("recall_at_48", "R@48"),
    ("mrr", "MRR"),
    ("ndcg_at_10", "nDCG@10"),
    ("coverage_recall", "Coverage"),
)
_TYPES = (
    "single_company",
    "comparison",
    "trend",
    "numeric",
    "sector",
    "ambiguous_entity",
    "adversarial",
)
WEAKEST_ANSWERS = 3
_ANSWER_SOURCE = {
    "faithfulness": "judge, claims of the direct answer and the findings",
    "citation_precision": "judge, plus the validator drift count",
    "coverage_completeness": "coverage statement and gaps (code)",
    "numeric_accuracy": "answer values within 0.5% of the gold (code)",
    "schema_validity": "answer schema (code)",
    "latency_p95_s": "audit records, total latency",
    "mean_cost_usd": "audit records, answer cost",
}


def _number(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _source(result: gates.GateResult, answered: bool) -> str:
    key = result.gate.key
    if key in _ANSWER_SOURCE:
        if not answered:
            return "pending: run keel eval --answers"
        return _ANSWER_SOURCE[key]
    if key == "refusal_correctness":
        if answered:
            return "answer step: out-of-scope response and 0 model requests"
        return "understanding step (no retrieval, no call)"
    return "retrieval, main variant"


def _status(result: gates.GateResult) -> str:
    return result.status


def _gates(run: runner.EvalRun) -> list[str]:
    rows = []
    for result in run.gates():
        unit = result.gate.unit
        value = _number(result.value)
        if result.value is not None and unit:
            value = f"{value} {unit}"
        rows.append(
            [
                result.gate.name,
                result.gate.rule,
                value,
                _status(result),
                _source(result, bool(run.answers)),
            ]
        )
    verdict = (
        "blocked: a gate failed"
        if gates.blocked(run.gates())
        else "no gate failed"
    )
    return [
        "## Regression gates",
        "",
        *_table(["Gate", "Threshold", "Value", "Status", "Source"], rows),
        "",
        f"Verdict: {verdict}. A pending gate does not block on its own.",
    ]


def _metric_row(
    label: str, count: int, values: Mapping[str, float | None]
) -> list[str]:
    return [label, str(count), *(_number(values.get(k)) for k, _ in _METRICS)]


def _per_type(run: runner.EvalRun) -> list[str]:
    main = run.variants[0].name
    scored = run.scored(main)
    rows = [_metric_row("all", len(scored), run.summary(main))]
    for kind in _TYPES:
        count = sum(1 for r in scored if r.type == kind)
        if count:
            rows.append(_metric_row(kind, count, run.summary(main, kind)))
    return [
        f"## Retrieval metrics ({main})",
        "",
        *_table(["Type", "Questions", *(h for _, h in _METRICS)], rows),
    ]


def _ablation(run: runner.EvalRun) -> list[str]:
    rows = []
    for variant in run.variants:
        values = run.summary(variant.name)
        rows.append(
            [
                variant.name,
                _number(values["recall_at_25"]),
                _number(values["ndcg_at_10"]),
                _number(values["mrr"]),
                _number(values["recall_at_48"]),
                _number(values["retrieval_ms_p50"], 0),
                _number(values["retrieval_ms_p95"], 0),
            ]
        )
    return [
        "## Ablation: retrieval mode and reranker (chapter 18.7)",
        "",
        *_table(
            [
                "Variant",
                "R@25",
                "nDCG@10",
                "MRR",
                "R@48",
                "Retrieval p50 ms",
                "Retrieval p95 ms",
            ],
            rows,
        ),
    ]


def _refusals(run: runner.EvalRun) -> list[str]:
    rows = [
        [r.question_id, r.type, r.outcome, r.detail or "n/a"]
        for r in run.refusals()
    ]
    if not rows:
        return []
    return [
        "## Out-of-scope questions",
        "",
        *_table(["Question", "Type", "Outcome", "Reason"], rows),
    ]


def _answer_row(
    label: str, rows: Sequence[answering.AnswerResult]
) -> list[str]:
    judged = [r.judge for r in rows if r.judge is not None]
    called = [r for r in rows if r.model_requests > 0]
    valid = [r.schema_valid for r in rows if r.schema_valid is not None]
    times = [r.latency_s for r in called if r.latency_s is not None]
    return [
        label,
        str(len(rows)),
        str(len(called)),
        _number(metrics.mean(j.faithfulness for j in judged)),
        _number(metrics.mean(j.citation_precision for j in judged)),
        _number(metrics.mean(r.coverage_complete for r in rows)),
        _number(metrics.mean(r.numeric_correct for r in rows)),
        _number(sum(valid) / len(valid) if valid else None),
        _number(metrics.percentile(times, 0.5), 1),
        _number(metrics.percentile(times, 0.95), 1),
        _number(metrics.mean(r.cost_usd for r in called), 4),
    ]


def _first_problem(result: answering.AnswerResult) -> str:
    if result.judge is None:
        return ""
    if result.judge.error:
        return "judge failed: " + result.judge.error
    for verdict in (
        *result.judge.claims.values(),
        *result.judge.citations.values(),
    ):
        if verdict.verdict not in (judging.SUPPORTED, judging.ABOUT_KEEL):
            return f"{verdict.id} {verdict.verdict}: {verdict.reason}"
    return ""


def _answers(run: runner.EvalRun) -> list[str]:
    rows = run.answers
    if not rows:
        return []
    values = run.answer_values()
    header = ["Type", "Questions", "Questions with a call", "Faithfulness"]
    header += ["Citation precision", "Coverage", "Numeric", "Schema"]
    header += ["Latency p50 s", "Latency p95 s", "Mean cost USD"]
    table = [_answer_row("all", rows)]
    for kind in (*_TYPES, "out_of_corpus"):
        kind_rows = [r for r in rows if r.type == kind]
        if kind_rows:
            table.append(_answer_row(kind, kind_rows))
    per = []
    for r in rows:
        judged = r.judge
        checks = []
        if r.refusal_correct is not None:
            checks.append(
                "refusal ok" if r.refusal_correct else "refusal missed"
            )
        if r.adversarial_ok is not None:
            checks.append(
                "adversarial ok" if r.adversarial_ok else "adversarial failed"
            )
        if r.numeric_detail:
            checks.append(r.numeric_detail)
        per.append(
            [
                r.question_id,
                r.type,
                r.outcome,
                str(r.model_requests),
                _number(judged.faithfulness if judged else None),
                _number(judged.citation_precision if judged else None),
                _number(r.coverage_complete),
                _number(r.numeric_correct),
                "; ".join(checks) or "n/a",
                _number(r.latency_s, 1),
                _number(r.cost_usd, 4),
                str(r.output_tokens),
                str(r.words),
            ]
        )
    weakest = sorted(
        (r for r in rows if r.judge and r.judge.faithfulness is not None),
        key=lambda r: (r.judge.faithfulness if r.judge else 0.0, r.question_id),
    )[:WEAKEST_ANSWERS]
    weak = [
        [
            r.question_id,
            _number(r.judge.faithfulness if r.judge else None),
            _number(r.judge.citation_precision if r.judge else None),
            _first_problem(r),
        ]
        for r in weakest
    ]
    judge_cost = values.get("judge_cost_usd") or 0.0
    failures = int(values.get("judge_failures") or 0)
    max_cost = _number(values.get("max_cost_usd"), 4)
    answer_cost = sum(r.cost_usd for r in rows)
    return [
        "## Answer metrics (chapter 18.4 and 18.6)",
        "",
        *_table(header, table),
        "",
        "Faithfulness and citation precision score supported 1, partly",
        "supported 0.5, and not supported 0, averaged per answer and then",
        "over the answers; an unverified finding scores 0, and each citation",
        "the validator removed counts as unsupported. Latency and cost come",
        "from the audit record of each request and cover the questions with",
        "a model request.",
        "",
        f"Spend: answers {answer_cost:.4f} USD, judge {judge_cost:.4f} USD; "
        f"maximum answer cost {max_cost} USD; judge failures {failures}.",
        "",
        "### Per question (answers)",
        "",
        *_table(
            [
                "Question",
                "Type",
                "Outcome",
                "Requests",
                "Faithfulness",
                "Citation precision",
                "Coverage",
                "Numeric",
                "Checks",
                "Latency s",
                "Cost USD",
                "Output tokens",
                "Words",
            ],
            per,
        ),
        "",
        "### Weakest answers",
        "",
        *_table(
            ["Question", "Faithfulness", "Citation precision", "First issue"],
            weak,
        ),
    ]


def _sections(values: Mapping[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in values.items()) or "none"


def _per_question(
    run: runner.EvalRun, questions: Mapping[str, golden.GoldenQuestion]
) -> list[str]:
    main = run.variants[0].name
    rows = []
    for r in run.results:
        if r.variant not in {main, ""}:
            continue
        values = r.metrics
        rows.append(
            [
                r.question_id,
                r.type,
                r.outcome,
                r.label_level or "n/a",
                str(r.chunks),
                str(r.relevant),
                _number(values.get("recall_at_25")),
                _number(values.get("mrr")),
                _number(values.get("ndcg_at_10")),
                _number(values.get("coverage_recall")),
                _number(r.retrieval_ms, 0),
            ]
        )
    weakest = sorted(
        run.scored(main),
        key=lambda r: (r.metrics.get("recall_at_25") or 0.0, r.question_id),
    )[:WEAKEST_SHOWN]
    weak_rows = [
        [
            r.question_id,
            _number(r.metrics.get("recall_at_25")),
            ", ".join(
                s.filing_id + " " + "/".join(s.sections)
                for s in questions[r.question_id].expected
            ),
            _sections(r.sections),
            r.detail or "",
        ]
        for r in weakest
    ]
    header = ["Question", "Type", "Outcome", "Labels", "Chunks", "Relevant"]
    header += ["R@25", "MRR", "nDCG@10", "Coverage", "Retrieval ms"]
    return [
        f"## Per question ({main})",
        "",
        *_table(header, rows),
        "",
        "## Weakest questions",
        "",
        *_table(
            [
                "Question",
                "R@25",
                "Expected sources",
                "Context sections",
                "Note",
            ],
            weak_rows,
        ),
    ]


def render(
    run: runner.EvalRun, questions: Sequence[golden.GoldenQuestion]
) -> str:
    """Render the report as Markdown.

    Args:
        run: The run.
        questions: The golden questions of the run.

    Returns:
        The report text.
    """
    info = run.info
    by_id = {q.id: q for q in questions}
    stale = ", ".join(run.stale_labels) or "none"
    subset = info.subset or "all"
    lines = [
        "# Eval report",
        "",
        "Written by `keel eval` (chapter 18). Regenerate it; do not edit it.",
        "",
        *_table(
            ["Field", "Value"],
            [
                ["Run ID", info.run_id],
                ["Started (UTC)", info.started_at],
                [
                    "Golden set",
                    f"{info.golden_version}, subset {subset}",
                ],
                ["Questions", str(len(questions))],
                ["Index", f"{info.index_version}, build {info.build_id}"],
                ["Index chunks_sha256", info.chunks_sha256],
                ["Labels from another index", stale],
                ["Prompt version", info.prompt_version],
                [
                    "Answer model",
                    info.model
                    if run.answers
                    else f"{info.model} (not called by this run)",
                ],
                ["Judge model", info.judge_model or "none"],
                ["Model requests", _requests(run)],
                ["Variants", ", ".join(v.name for v in run.variants)],
                ["Wall time", f"{run.seconds:.0f} s"],
            ],
        ),
        "",
        *_gates(run),
        "",
        *_per_type(run),
        "",
        "Metric notes: the ranking is the context of each variant ordered by",
        "its final score (reranked chunks first). Recall at k divides the",
        "relevant chunks in the top k by min(k, R), so a section label larger",
        "than k can still reach 1. Relevant means grade 2 of a chunk label, or",
        "any chunk of an expected (filing, section) pair of a section label.",
        "nDCG at 10 uses the grades as gains; coverage recall applies to",
        "questions with 2 or more expected companies.",
        "",
        *_ablation(run),
        "",
        *_refusals(run),
        "",
        *_per_question(run, by_id),
        "",
        *_answers(run),
        "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _requests(run: runner.EvalRun) -> str:
    answers = sum(r.model_requests for r in run.answers)
    judged = sum(
        1
        for r in run.answers
        if r.judge is not None
        and (r.judge.usage.output_tokens or r.judge.error)
    )
    return f"{answers} answer, {judged} judge"


def _answer_json(result: answering.AnswerResult) -> dict[str, Any]:
    data = {
        f.name: getattr(result, f.name)
        for f in dataclasses.fields(result)
        if f.name not in {"judge", "flags"}
    }
    data["flags"] = dict(result.flags)
    judged = result.judge
    if judged is not None:
        data["judge"] = {
            "faithfulness": judged.faithfulness,
            "citation_precision": judged.citation_precision,
            "drift": judged.drift,
            "missing": list(judged.missing),
            "cost_usd": judged.cost_usd,
            "usage": dataclasses.asdict(judged.usage),
            "error": judged.error,
            "claims": [v.model_dump() for v in judged.claims.values()],
            "citations": [v.model_dump() for v in judged.citations.values()],
        }
    return data


def write(
    run: runner.EvalRun,
    questions: Sequence[golden.GoldenQuestion],
    path: pathlib.Path,
) -> pathlib.Path:
    """Write the Markdown report and the JSON results beside it.

    Args:
        run: The run.
        questions: The golden questions of the run.
        path: The Markdown file, such as `eval/report.md`.

    Returns:
        The JSON file, such as `eval/report.json`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(run, questions), encoding="utf-8")
    data = {
        "info": dataclasses.asdict(run.info),
        "variants": [dataclasses.asdict(v) for v in run.variants],
        "seconds": round(run.seconds, 1),
        "stale_labels": list(run.stale_labels),
        "gates": [
            {
                "name": r.gate.name,
                "threshold": r.gate.threshold,
                "value": r.value,
                "status": r.status,
            }
            for r in run.gates()
        ],
        "summary": {v.name: run.summary(v.name) for v in run.variants},
        "results": [dataclasses.asdict(r) for r in run.results],
        "answer_values": run.answer_values(),
        "answers": [_answer_json(r) for r in run.answers],
    }
    json_path = path.with_suffix(".json")
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return json_path
