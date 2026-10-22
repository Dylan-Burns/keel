# Eval report

Written by `keel eval` (chapter 18). A fixture for `test_eval_page_renders`.

| Field | Value |
| --- | --- |
| Run ID | eval-fixture |
| Golden set | 1.0.0, subset all |

## Regression gates

| Gate | Threshold | Value | Status | Source |
| --- | --- | --- | --- | --- |
| Recall at 25 | >= 0.85 | 0.63 | fail | retrieval, main variant |
| MRR | >= 0.60 | 0.88 | pass | retrieval, main variant |
| Faithfulness | >= 0.90 | n/a | pending | judge |
| Latency p95 | <= 40.00 s | 31.20 s | pass | answer meta |
| Mean cost per question | <= 0.25 USD | 0.31 USD | fail | answer meta |

Verdict: blocked: a gate failed.

## Notes

A <script>alert(1)</script> tag in the report stays text on the page.
