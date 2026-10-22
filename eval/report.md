# Eval report

Written by `keel eval` (chapter 18). Regenerate it; do not edit it.

| Field | Value |
| --- | --- |
| Run ID | eval-20261022T013234Z |
| Started (UTC) | 2026-10-22T01:32:34+00:00 |
| Golden set | 1.0.0, subset all |
| Questions | 28 |
| Index | 1.0.1, build 20261021T231603728106Z |
| Index chunks_sha256 | 722b9b5693e4284330cbe36342c8d8679357be7f4cd899cf67c02c65bdb266be |
| Labels from another index | none |
| Prompt version | 1.0.0 (answer metrics pending stage 7) |
| Answer model | claude-sonnet-5-5 (not called by this run) |
| Model requests | 0 |
| Variants | hybrid, lexical, dense, hybrid, no reranker, lexical, no reranker, dense, no reranker |
| Wall time | 831 s |

## Regression gates

| Gate | Threshold | Value | Status | Source |
| --- | --- | --- | --- | --- |
| Recall at 25 | >= 0.85 | 0.63 | fail | retrieval, main variant |
| MRR | >= 0.60 | 0.88 | pass | retrieval, main variant |
| Faithfulness | >= 0.90 | n/a | pending stage 7 | judge, pending stage 7 |
| Citation precision | >= 0.90 | n/a | pending stage 7 | judge and drift count, pending stage 7 |
| Coverage completeness on comparison and sector questions | >= 1.00 | n/a | pending stage 7 | coverage statement, pending stage 7 |
| Numeric accuracy | >= 0.90 | n/a | pending stage 7 | answer values, pending stage 7 |
| Schema validity | >= 1.00 | n/a | pending stage 7 | answer schema, pending stage 7 |
| Refusal correctness | >= 1.00 | 1.00 | pass | understanding step (no retrieval, no call); request count at stage 7 |
| Latency p95 | <= 40.00 s | n/a | pending stage 7 | answer meta, pending stage 7 |
| Mean cost per question | <= 0.25 USD | n/a | pending stage 7 | answer meta, pending stage 7 |

Verdict: blocked: a gate failed. A pending gate does not block on its own.

## Retrieval metrics (hybrid)

| Type | Questions | R@10 | R@25 | R@48 | MRR | nDCG@10 | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all | 23 | 0.63 | 0.63 | 0.56 | 0.88 | 0.72 | 0.94 |
| single_company | 5 | 0.49 | 0.43 | 0.47 | 0.80 | 0.60 | n/a |
| comparison | 5 | 0.88 | 0.83 | 0.69 | 1.00 | 0.96 | 0.95 |
| trend | 4 | 0.72 | 0.60 | 0.48 | 1.00 | 0.82 | n/a |
| numeric | 4 | 0.36 | 0.71 | 0.67 | 0.54 | 0.39 | n/a |
| sector | 3 | 0.63 | 0.58 | 0.49 | 1.00 | 0.82 | 0.93 |
| ambiguous_entity | 1 | 1.00 | 1.00 | 0.81 | 1.00 | 1.00 | n/a |
| adversarial | 1 | 0.40 | 0.24 | 0.30 | 1.00 | 0.54 | n/a |

Metric notes: the ranking is the context of each variant ordered by
its final score (reranked chunks first). Recall at k divides the
relevant chunks in the top k by min(k, R), so a section label larger
than k can still reach 1. Relevant means grade 2 of a chunk label, or
any chunk of an expected (filing, section) pair of a section label.
nDCG at 10 uses the grades as gains; coverage recall applies to
questions with 2 or more expected companies.

## Ablation: retrieval mode and reranker (chapter 18.7)

| Variant | R@25 | nDCG@10 | MRR | R@48 | Retrieval p50 ms | Retrieval p95 ms |
| --- | --- | --- | --- | --- | --- | --- |
| hybrid | 0.63 | 0.72 | 0.88 | 0.56 | 9338 | 21646 |
| lexical | 0.61 | 0.73 | 0.87 | 0.53 | 9374 | 17544 |
| dense | 0.65 | 0.75 | 0.88 | 0.54 | 8356 | 21117 |
| hybrid, no reranker | 0.56 | 0.71 | 0.89 | 0.55 | 375 | 1915 |
| lexical, no reranker | 0.59 | 0.66 | 0.73 | 0.55 | 158 | 557 |
| dense, no reranker | 0.58 | 0.70 | 0.81 | 0.53 | 175 | 1435 |

## Out-of-scope questions

| Question | Type | Outcome | Reason |
| --- | --- | --- | --- |
| G-22 | out_of_corpus | refused | unknown_company |
| G-23 | out_of_corpus | refused | out_of_scope_request |
| G-24 | out_of_corpus | refused | out_of_scope_request |
| G-25 | ambiguous_entity | refused | not_indexed |

## Per question (hybrid)

| Question | Type | Outcome | Labels | Chunks | Relevant | R@25 | MRR | nDCG@10 | Coverage | Retrieval ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | single_company | scored | chunk | 48 | 31 | 1.00 | 1.00 | 1.00 | n/a | 21885 |
| G-02 | single_company | scored | section | 48 | 26 | 0.00 | 0.00 | 0.00 | n/a | 16600 |
| G-03 | single_company | scored | chunk | 48 | 6 | 0.17 | 1.00 | 0.71 | n/a | 17380 |
| G-04 | single_company | scored | section | 48 | 109 | 0.32 | 1.00 | 0.71 | n/a | 16586 |
| G-05 | single_company | scored | chunk | 48 | 3 | 0.67 | 1.00 | 0.58 | n/a | 26398 |
| G-06 | comparison | scored | chunk | 48 | 42 | 0.72 | 1.00 | 1.00 | 1.00 | 13226 |
| G-07 | comparison | scored | section | 48 | 81 | 1.00 | 1.00 | 1.00 | 1.00 | 13773 |
| G-08 | comparison | scored | section | 48 | 67 | 0.96 | 1.00 | 1.00 | 1.00 | 14152 |
| G-09 | comparison | scored | chunk | 48 | 11 | 0.45 | 1.00 | 0.78 | 1.00 | 16878 |
| G-10 | comparison | scored | section | 48 | 294 | 1.00 | 1.00 | 1.00 | 0.75 | 19496 |
| G-11 | trend | scored | chunk | 48 | 87 | 0.48 | 1.00 | 0.88 | n/a | 13757 |
| G-12 | trend | scored | section | 48 | 247 | 1.00 | 1.00 | 1.00 | n/a | 9338 |
| G-13 | trend | scored | section | 48 | 566 | 0.44 | 1.00 | 0.47 | n/a | 5758 |
| G-14 | trend | scored | section | 48 | 101 | 0.48 | 1.00 | 0.93 | n/a | 7968 |
| G-15 | numeric | scored | chunk | 48 | 4 | 0.75 | 0.10 | 0.17 | n/a | 5558 |
| G-16 | numeric | scored | chunk | 48 | 2 | 1.00 | 1.00 | 0.62 | n/a | 6813 |
| G-17 | numeric | scored | section | 48 | 180 | 0.72 | 1.00 | 0.78 | n/a | 5658 |
| G-18 | numeric | scored | section | 48 | 1337 | 0.36 | 0.06 | 0.00 | n/a | 5817 |
| G-19 | sector | scored | chunk | 48 | 44 | 0.52 | 1.00 | 0.77 | 0.80 | 6144 |
| G-20 | sector | scored | section | 48 | 294 | 0.92 | 1.00 | 1.00 | 1.00 | 6331 |
| G-21 | sector | scored | chunk | 48 | 20 | 0.30 | 1.00 | 0.70 | 1.00 | 6492 |
| G-22 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-23 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-24 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-25 | ambiguous_entity | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-26 | ambiguous_entity | scored | section | 48 | 36 | 1.00 | 1.00 | 1.00 | n/a | 6292 |
| G-27 | adversarial | scored | section | 48 | 43 | 0.24 | 1.00 | 0.54 | n/a | 6274 |
| G-28 | adversarial | answer_only | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |

## Weakest questions

| Question | R@25 | Expected sources | Context sections | Note |
| --- | --- | --- | --- | --- |
| G-02 | 0.00 | MSFT_10K_2025-06-30 business | mdna 28, financial_statements 20 |  |
| G-03 | 0.17 | TSLA_10K_2025-12-31 legal_proceedings, TSLA_10Q_2025-09-30 legal_proceedings | unknown 19, risk_factors 12, legal_proceedings 11, business 6 |  |
| G-27 | 0.24 | TSLA_10K_2025-12-31 risk_factors | risk_factors 48 |  |
| G-21 | 0.30 | AAPL_10K_2025-09-27 risk_factors, MSFT_10K_2025-06-30 risk_factors, GOOG_10K_2025-12-31 risk_factors, AMZN_10K_2025-12-31 risk_factors, META_10K_2025-12-31 risk_factors, NVDA_10K_2025-01-26 risk_factors | risk_factors 48 |  |
| G-04 | 0.32 | DIS_10K_2024-09-28 mdna | mdna 33, financial_statements 15 |  |
| G-18 | 0.36 | JPM_10K_2025-12-31 mdna/financial_statements | financial_statements 25, mdna 23 |  |
