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

from keel.evaluation import gates
from keel.evaluation import golden
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
_PENDING_SOURCE = {
    "faithfulness": "judge, pending stage 7",
    "citation_precision": "judge and drift count, pending stage 7",
    "coverage_completeness": "coverage statement, pending stage 7",
    "numeric_accuracy": "answer values, pending stage 7",
    "schema_validity": "answer schema, pending stage 7",
    "latency_p95_s": "answer meta, pending stage 7",
    "mean_cost_usd": "answer meta, pending stage 7",
}


def _number(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _source(result: gates.GateResult) -> str:
    key = result.gate.key
    if key in _PENDING_SOURCE:
        return _PENDING_SOURCE[key]
    if key == "refusal_correctness":
        return (
            "understanding step (no retrieval, no call); "
            "request count at stage 7"
        )
    return "retrieval, main variant"


def _status(result: gates.GateResult) -> str:
    if result.status == gates.PENDING:
        return "pending stage 7"
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
                _source(result),
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
                [
                    "Prompt version",
                    f"{info.prompt_version} (answer metrics pending stage 7)",
                ],
                ["Answer model", f"{info.model} (not called by this run)"],
                ["Model requests", "0"],
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
    ]
    return "\n".join(lines)


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
                "key": r.gate.key,
                "threshold": r.gate.threshold,
                "value": r.value,
                "status": r.status,
            }
            for r in run.gates()
        ],
        "summary": {v.name: run.summary(v.name) for v in run.variants},
        "results": [dataclasses.asdict(r) for r in run.results],
    }
    json_path = path.with_suffix(".json")
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return json_path
