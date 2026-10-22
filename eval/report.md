# Eval report

Written by `keel eval` (chapter 18). Regenerate it; do not edit it.

| Field | Value |
| --- | --- |
| Run ID | eval-20261022T031218Z |
| Started (UTC) | 2026-10-22T03:12:18+00:00 |
| Golden set | 1.0.0, subset all |
| Questions | 28 |
| Index | 1.0.1, build 20261021T231603728106Z |
| Index chunks_sha256 | 722b9b5693e4284330cbe36342c8d8679357be7f4cd899cf67c02c65bdb266be |
| Labels from another index | none |
| Prompt version | 1.3.0 |
| Answer model | claude-sonnet-5-5 |
| Judge model | claude-opus-5-5 |
| Model requests | 47 answer, 24 judge |
| Variants | hybrid, lexical, dense, hybrid, no reranker, lexical, no reranker, dense, no reranker |
| Wall time | 1572 s |

## Regression gates

| Gate | Threshold | Value | Status | Source |
| --- | --- | --- | --- | --- |
| Recall at 25 | >= 0.85 | 0.75 | fail | retrieval, main variant |
| MRR | >= 0.60 | 0.97 | pass | retrieval, main variant |
| Faithfulness | >= 0.90 | 0.86 | fail | judge, claims of the direct answer and the findings |
| Citation precision | >= 0.90 | 0.99 | pass | judge, plus the validator drift count |
| Coverage completeness on comparison and sector questions | >= 1.00 | 1.00 | pass | coverage statement and gaps (code) |
| Numeric accuracy | >= 0.90 | 1.00 | pass | answer values within 0.5% of the gold (code) |
| Schema validity | >= 1.00 | 1.00 | pass | answer schema (code) |
| Refusal correctness | >= 1.00 | 1.00 | pass | answer step: out-of-scope response and 0 model requests |
| Latency p95 | <= 40.00 s | 38.95 s | pass | audit records, total latency |
| Mean cost per question | <= 0.25 USD | 0.09 USD | pass | audit records, answer cost |

Verdict: blocked: a gate failed. A pending gate does not block on its own.

## Retrieval metrics (hybrid)

| Type | Questions | R@10 | R@25 | R@48 | MRR | nDCG@10 | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all | 23 | 0.78 | 0.75 | 0.65 | 0.97 | 0.83 | 0.94 |
| single_company | 5 | 0.61 | 0.56 | 0.52 | 1.00 | 0.73 | n/a |
| comparison | 5 | 0.96 | 0.93 | 0.78 | 1.00 | 0.97 | 0.95 |
| trend | 4 | 0.72 | 0.57 | 0.46 | 1.00 | 0.82 | n/a |
| numeric | 4 | 0.88 | 1.00 | 0.91 | 0.80 | 0.76 | n/a |
| sector | 3 | 0.63 | 0.68 | 0.57 | 1.00 | 0.83 | 0.93 |
| ambiguous_entity | 1 | 1.00 | 1.00 | 0.81 | 1.00 | 1.00 | n/a |
| adversarial | 1 | 0.90 | 0.48 | 0.37 | 1.00 | 0.94 | n/a |

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
| hybrid | 0.75 | 0.83 | 0.97 | 0.65 | 8961 | 16201 |
| lexical | 0.68 | 0.81 | 0.94 | 0.54 | 8458 | 11123 |
| dense | 0.68 | 0.82 | 0.97 | 0.55 | 8450 | 13216 |
| hybrid, no reranker | 0.65 | 0.77 | 0.95 | 0.62 | 198 | 2126 |
| lexical, no reranker | 0.69 | 0.77 | 0.85 | 0.57 | 114 | 680 |
| dense, no reranker | 0.65 | 0.76 | 0.88 | 0.57 | 89 | 1551 |

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
| G-01 | single_company | scored | chunk | 45 | 31 | 1.00 | 1.00 | 1.00 | n/a | 21563 |
| G-02 | single_company | scored | section | 48 | 26 | 0.08 | 1.00 | 0.36 | n/a | 14919 |
| G-03 | single_company | scored | chunk | 48 | 6 | 0.17 | 1.00 | 0.71 | n/a | 8696 |
| G-04 | single_company | scored | section | 48 | 109 | 0.56 | 1.00 | 1.00 | n/a | 5792 |
| G-05 | single_company | scored | chunk | 48 | 3 | 1.00 | 1.00 | 0.58 | n/a | 9116 |
| G-06 | comparison | scored | chunk | 48 | 42 | 0.68 | 1.00 | 1.00 | 1.00 | 12234 |
| G-07 | comparison | scored | section | 42 | 81 | 1.00 | 1.00 | 1.00 | 1.00 | 8961 |
| G-08 | comparison | scored | section | 48 | 67 | 0.96 | 1.00 | 1.00 | 1.00 | 5201 |
| G-09 | comparison | scored | chunk | 47 | 11 | 1.00 | 1.00 | 0.83 | 1.00 | 8994 |
| G-10 | comparison | scored | section | 43 | 294 | 1.00 | 1.00 | 1.00 | 0.75 | 12249 |
| G-11 | trend | scored | chunk | 48 | 87 | 0.48 | 1.00 | 0.88 | n/a | 11245 |
| G-12 | trend | scored | section | 46 | 247 | 1.00 | 1.00 | 1.00 | n/a | 8863 |
| G-13 | trend | scored | section | 48 | 566 | 0.44 | 1.00 | 0.47 | n/a | 8292 |
| G-14 | trend | scored | section | 46 | 101 | 0.36 | 1.00 | 0.92 | n/a | 16344 |
| G-15 | numeric | scored | chunk | 48 | 4 | 1.00 | 0.20 | 0.28 | n/a | 9031 |
| G-16 | numeric | scored | chunk | 48 | 2 | 1.00 | 1.00 | 0.76 | n/a | 5986 |
| G-17 | numeric | scored | section | 48 | 180 | 1.00 | 1.00 | 1.00 | n/a | 12670 |
| G-18 | numeric | scored | section | 48 | 1337 | 1.00 | 1.00 | 1.00 | n/a | 5338 |
| G-19 | sector | scored | chunk | 38 | 44 | 0.68 | 1.00 | 0.81 | 0.80 | 9344 |
| G-20 | sector | scored | section | 48 | 294 | 0.92 | 1.00 | 1.00 | 1.00 | 8870 |
| G-21 | sector | scored | chunk | 41 | 20 | 0.45 | 1.00 | 0.67 | 1.00 | 5781 |
| G-22 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-23 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-24 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-25 | ambiguous_entity | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-26 | ambiguous_entity | scored | section | 48 | 36 | 1.00 | 1.00 | 1.00 | n/a | 4868 |
| G-27 | adversarial | scored | section | 41 | 43 | 0.48 | 1.00 | 0.94 | n/a | 4851 |
| G-28 | adversarial | answer_only | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |

## Weakest questions

| Question | R@25 | Expected sources | Context sections | Note |
| --- | --- | --- | --- | --- |
| G-02 | 0.08 | MSFT_10K_2025-06-30 business | mdna 27, financial_statements 14, business 7 |  |
| G-03 | 0.17 | TSLA_10K_2025-12-31 legal_proceedings, TSLA_10Q_2025-09-30 legal_proceedings | unknown 22, risk_factors 12, legal_proceedings 11, business 3 |  |
| G-14 | 0.36 | UNH_10K_2022-12-31 risk_factors, UNH_10K_2023-12-31 risk_factors, UNH_10K_2024-12-31 risk_factors | mdna 30, risk_factors 12, unknown 4 |  |
| G-13 | 0.44 | PFE_10Q_2024-03-31 mdna, PFE_10Q_2024-06-30 mdna, PFE_10Q_2024-09-29 mdna, PFE_10K_2024-12-31 mdna, PFE_10Q_2025-03-30 mdna, PFE_10Q_2025-06-29 mdna, PFE_10Q_2025-09-28 mdna | financial_statements 25, mdna 23 |  |
| G-21 | 0.45 | AAPL_10K_2025-09-27 risk_factors, MSFT_10K_2025-06-30 risk_factors, GOOG_10K_2025-12-31 risk_factors, AMZN_10K_2025-12-31 risk_factors, META_10K_2025-12-31 risk_factors, NVDA_10K_2025-01-26 risk_factors | risk_factors 41 |  |
| G-11 | 0.48 | NVDA_10K_2024-01-28 mdna/financial_statements, NVDA_10Q_2024-04-28 mdna/financial_statements, NVDA_10Q_2024-07-28 mdna/financial_statements, NVDA_10Q_2024-10-27 mdna/financial_statements, NVDA_10K_2025-01-26 mdna/financial_statements, NVDA_10Q_2025-04-27 mdna/financial_statements, NVDA_10Q_2025-07-27 mdna/financial_statements, NVDA_10Q_2025-10-26 mdna/financial_statements | mdna 40, financial_statements 8 |  |

## Answer metrics (chapter 18.4 and 18.6)

| Type | Questions | Model calls | Faithfulness | Citation precision | Coverage | Numeric | Schema | Latency p50 s | Latency p95 s | Mean cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | 28 | 24 | 0.86 | 0.99 | 1.00 | 1.00 | 1.00 | 27.8 | 38.9 | 0.0905 |
| single_company | 5 | 5 | 0.87 | 0.98 | n/a | n/a | 1.00 | 25.9 | 34.0 | 0.0857 |
| comparison | 5 | 5 | 0.87 | 1.00 | 1.00 | n/a | 1.00 | 33.2 | 39.2 | 0.1028 |
| trend | 4 | 4 | 0.79 | 0.97 | n/a | n/a | 1.00 | 31.7 | 34.2 | 0.0962 |
| numeric | 4 | 4 | 0.86 | 1.00 | n/a | 1.00 | 1.00 | 19.4 | 21.7 | 0.0658 |
| sector | 3 | 3 | 0.95 | 1.00 | 1.00 | n/a | 1.00 | 37.9 | 39.0 | 0.1129 |
| ambiguous_entity | 2 | 1 | 0.83 | 1.00 | n/a | n/a | 1.00 | 24.3 | 24.3 | 0.0866 |
| adversarial | 2 | 2 | 0.85 | 1.00 | n/a | n/a | 1.00 | 17.7 | 19.0 | 0.0788 |
| out_of_corpus | 3 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

Faithfulness and citation precision score supported 1, partly
supported 0.5, and not supported 0, averaged per answer and then
over the answers; an unverified finding scores 0, and each citation
the validator removed counts as unsupported. Latency and cost come
from the audit record of each request and cover the questions with
a model request.

Spend: answers 2.1731 USD, judge 1.9600 USD; maximum answer cost 0.1184 USD.

### Per question (answers)

| Question | Type | Outcome | Requests | Faithfulness | Citation precision | Coverage | Numeric | Checks | Latency s | Cost USD | Output tokens | Words |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | single_company | answered | 1 | 0.61 | 1.00 | n/a | n/a | n/a | 35.4 | 0.0929 | 2203 | 140 |
| G-02 | single_company | answered | 2 | 1.00 | 1.00 | n/a | n/a | n/a | 28.5 | 0.0909 | 1942 | 124 |
| G-03 | single_company | answered | 2 | 0.91 | 1.00 | n/a | n/a | n/a | 24.8 | 0.0851 | 2364 | 161 |
| G-04 | single_company | answered | 2 | 0.89 | 1.00 | n/a | n/a | n/a | 23.1 | 0.0691 | 2520 | 131 |
| G-05 | single_company | answered | 2 | 0.94 | 0.92 | n/a | n/a | n/a | 25.9 | 0.0903 | 2231 | 164 |
| G-06 | comparison | answered | 2 | 0.77 | 1.00 | 1.00 | n/a | n/a | 40.2 | 0.1126 | 4563 | 146 |
| G-07 | comparison | answered | 2 | 0.73 | 1.00 | 1.00 | n/a | n/a | 33.2 | 0.1021 | 3637 | 129 |
| G-08 | comparison | answered | 2 | 0.93 | 1.00 | 1.00 | n/a | n/a | 31.5 | 0.1039 | 4330 | 153 |
| G-09 | comparison | answered | 2 | 1.00 | 1.00 | 1.00 | n/a | n/a | 27.1 | 0.0917 | 2632 | 145 |
| G-10 | comparison | answered | 2 | 0.92 | 1.00 | 1.00 | n/a | n/a | 35.4 | 0.1034 | 3570 | 156 |
| G-11 | trend | answered | 2 | 0.86 | 1.00 | n/a | n/a | n/a | 34.3 | 0.1008 | 3732 | 175 |
| G-12 | trend | answered | 2 | 0.72 | 0.88 | n/a | n/a | n/a | 29.7 | 0.0973 | 2928 | 212 |
| G-13 | trend | answered | 2 | 0.69 | 1.00 | n/a | n/a | n/a | 26.3 | 0.0924 | 2824 | 140 |
| G-14 | trend | answered | 2 | 0.88 | 1.00 | n/a | n/a | n/a | 33.7 | 0.0942 | 2477 | 182 |
| G-15 | numeric | answered | 2 | 0.79 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 19.7 | 0.0546 | 1238 | 73 |
| G-16 | numeric | answered | 2 | 0.71 | 1.00 | n/a | 1.00 | 6 of 6 gold values | 19.2 | 0.0697 | 1863 | 88 |
| G-17 | numeric | answered | 2 | 0.93 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 22.0 | 0.0700 | 1193 | 61 |
| G-18 | numeric | answered | 2 | 1.00 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 16.2 | 0.0690 | 1313 | 99 |
| G-19 | sector | answered | 2 | 1.00 | 1.00 | 1.00 | n/a | n/a | 39.1 | 0.1139 | 4813 | 135 |
| G-20 | sector | answered | 2 | 0.94 | 1.00 | 1.00 | n/a | n/a | 33.5 | 0.1064 | 3878 | 177 |
| G-21 | sector | answered | 2 | 0.92 | 1.00 | 1.00 | n/a | n/a | 37.9 | 0.1184 | 5288 | 115 |
| G-22 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-23 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-24 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-25 | ambiguous_entity | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-26 | ambiguous_entity | answered | 2 | 0.83 | 1.00 | n/a | n/a | n/a | 24.3 | 0.0866 | 2770 | 132 |
| G-27 | adversarial | answered | 2 | 0.89 | 1.00 | n/a | n/a | adversarial ok | 19.2 | 0.0841 | 1920 | 122 |
| G-28 | adversarial | answered | 2 | 0.81 | 1.00 | n/a | n/a | adversarial failed | 16.1 | 0.0735 | 1398 | 121 |

### Weakest answers

| Question | Faithfulness | Citation precision | First issue |
| --- | --- | --- | --- |
| G-01 | 0.61 | 1.00 | C1 partly_supported: The chunk identifies the FY2025 10-K and shows only the 'Macroeconomic and Industry Risks' heading; it does not show the business, legal and regulatory compliance, financial or general risk categories. |
| G-13 | 0.69 | 1.00 | C1 partly_supported: The chunk states all four 2024 quarterly revenue figures, but not the quarter-end dates (March 31, June 30, September 29, December 31) that the claim attaches. |
| G-16 | 0.71 | 1.00 | C4 partly_supported: The table shows Greater China as the only decline (-8%) and Europe at +7%, but the fiscal 2023 end date of September 30, 2023 is not stated in the cited chunk. |

## Stage 10 notes on this run (added by hand, not by keel eval)

The sections below this heading were written after the run from the JSON
files of 3 runs; everything above it is the output of
`keel eval --set eval/golden.yaml --answers` (run eval-20261022T031218Z).

Before and after the stage 10 retrieval fixes (hybrid, the same index):
first report eval-20261022T013234Z (stages 0 to 6), the same harness after
the rebase on stages 7 and 8 (eval-20261022T022831Z), and this run with the
fixes (the retrieval values equal those of eval-20261022T024459Z, which ran
the fixes without answers).

| Run | R@10 | R@25 | R@48 | MRR | nDCG@10 |
| --- | --- | --- | --- | --- | --- |
| first report | 0.63 | 0.63 | 0.56 | 0.88 | 0.72 |
| after stage 8 | 0.64 | 0.62 | 0.55 | 0.88 | 0.73 |
| after the fixes | 0.78 | 0.75 | 0.65 | 0.97 | 0.83 |

| Question | Type | R@25 first | R@25 stage 8 | R@25 fixes | MRR first | MRR stage 8 | MRR fixes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | single_company | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-02 | single_company | 0.00 | 0.00 | 0.08 | 0.00 | 0.00 | 1.00 |
| G-03 | single_company | 0.17 | 0.17 | 0.17 | 1.00 | 1.00 | 1.00 |
| G-04 | single_company | 0.32 | 0.32 | 0.56 | 1.00 | 1.00 | 1.00 |
| G-05 | single_company | 0.67 | 0.67 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-06 | comparison | 0.72 | 0.60 | 0.68 | 1.00 | 1.00 | 1.00 |
| G-07 | comparison | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-08 | comparison | 0.96 | 0.96 | 0.96 | 1.00 | 1.00 | 1.00 |
| G-09 | comparison | 0.45 | 0.45 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-10 | comparison | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-11 | trend | 0.48 | 0.48 | 0.48 | 1.00 | 1.00 | 1.00 |
| G-12 | trend | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-13 | trend | 0.44 | 0.44 | 0.44 | 1.00 | 1.00 | 1.00 |
| G-14 | trend | 0.48 | 0.36 | 0.36 | 1.00 | 1.00 | 1.00 |
| G-15 | numeric | 0.75 | 0.75 | 1.00 | 0.10 | 0.10 | 0.20 |
| G-16 | numeric | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-17 | numeric | 0.72 | 0.72 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-18 | numeric | 0.36 | 0.36 | 1.00 | 0.06 | 0.06 | 1.00 |
| G-19 | sector | 0.52 | 0.48 | 0.68 | 1.00 | 1.00 | 1.00 |
| G-20 | sector | 0.92 | 0.92 | 0.92 | 1.00 | 1.00 | 1.00 |
| G-21 | sector | 0.30 | 0.35 | 0.45 | 1.00 | 1.00 | 1.00 |
| G-26 | ambiguous_entity | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| G-27 | adversarial | 0.24 | 0.24 | 0.48 | 1.00 | 1.00 | 1.00 |

The sections fix (Item 1A of the PFE 10-Ks) changes the index content and
takes effect only after `keel index`; this run used the published index, so
G-19 does not show it yet.

2 artifacts of this run, fixed in the harness after it (not re-run, to keep
1 live run): the harness opened a new event loop per question, so the
pooled connection of the async client failed with a connection error
before any response on 23 of the 24 answers and the D-04 retry answered (the Requests column shows 2;
the provider logged 24 answer and 24 judge responses, all HTTP 200; the
latency holds a 2 s backoff); and the G-28 check counted the citations
list, where the answer named the planted chunk as an instruction it did not
follow. Re-scored on the saved answer, G-28 passes; a 2-question live check
after the fix (G-27, G-28) made 1 request each and passed both checks.
