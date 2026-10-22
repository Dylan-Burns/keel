# Eval report

Written by `keel eval` (chapter 18). Regenerate it; do not edit it.

| Field | Value |
| --- | --- |
| Run ID | eval-20261022T111922Z |
| Started (UTC) | 2026-10-22T11:19:22+00:00 |
| Golden set | 1.0.0, subset all |
| Questions | 28 |
| Index | 1.2.0, build 20261022T050249382998Z |
| Index chunks_sha256 | be95e3aa90a5857e023f945125193cc6a5e0de6df111119a5b31ff00b2f59737 |
| Labels from another index | none |
| Prompt version | 1.4.0 |
| Answer model | claude-sonnet-5-5 |
| Judge model | claude-opus-5-5 |
| Model requests | 24 answer, 24 judge |
| Variants | hybrid, lexical, dense, hybrid, no reranker, lexical, no reranker, dense, no reranker |
| Wall time | 1300 s |

## Regression gates

| Gate | Threshold | Value | Status | Source |
| --- | --- | --- | --- | --- |
| Recall at 25 | >= 0.85 | 0.86 | pass | retrieval, main variant |
| MRR | >= 0.60 | 0.96 | pass | retrieval, main variant |
| Faithfulness | >= 0.90 | 0.86 | fail | judge, claims of the direct answer and the findings |
| Citation precision | >= 0.90 | 0.99 | pass | judge, plus the validator drift count |
| Coverage completeness on comparison and sector questions | >= 1.00 | 1.00 | pass | coverage statement and gaps (code) |
| Numeric accuracy | >= 0.90 | 1.00 | pass | answer values within 0.5% of the gold (code) |
| Schema validity | >= 1.00 | 1.00 | pass | answer schema (code) |
| Refusal correctness | >= 1.00 | 1.00 | pass | answer step: out-of-scope response and 0 model requests |
| Latency p95 | <= 40.00 s | 32.24 s | pass | audit records, total latency |
| Mean cost per question | <= 0.25 USD | 0.09 USD | pass | audit records, answer cost |

Verdict: blocked: a gate failed. A pending gate does not block on its own.

## Retrieval metrics (hybrid)

| Type | Questions | R@10 | R@25 | R@48 | MRR | nDCG@10 | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all | 23 | 0.85 | 0.86 | 0.76 | 0.96 | 0.89 | 0.97 |
| single_company | 5 | 0.71 | 0.73 | 0.72 | 1.00 | 0.81 | n/a |
| comparison | 5 | 0.96 | 0.92 | 0.76 | 1.00 | 0.99 | 0.95 |
| trend | 4 | 0.93 | 0.87 | 0.73 | 1.00 | 0.97 | n/a |
| numeric | 4 | 0.88 | 1.00 | 0.91 | 0.79 | 0.76 | n/a |
| sector | 3 | 0.63 | 0.71 | 0.59 | 1.00 | 0.83 | 1.00 |
| ambiguous_entity | 1 | 1.00 | 1.00 | 0.81 | 1.00 | 1.00 | n/a |
| adversarial | 1 | 1.00 | 1.00 | 0.86 | 1.00 | 1.00 | n/a |

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
| hybrid | 0.86 | 0.89 | 0.96 | 0.76 | 5927 | 7270 |
| lexical | 0.80 | 0.87 | 0.96 | 0.69 | 5453 | 6369 |
| dense | 0.82 | 0.87 | 0.96 | 0.70 | 5755 | 7206 |
| hybrid, no reranker | 0.81 | 0.83 | 0.93 | 0.76 | 223 | 1137 |
| lexical, no reranker | 0.78 | 0.83 | 0.87 | 0.72 | 120 | 316 |
| dense, no reranker | 0.79 | 0.84 | 0.97 | 0.70 | 122 | 911 |

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
| G-01 | single_company | scored | chunk | 45 | 31 | 1.00 | 1.00 | 1.00 | n/a | 7290 |
| G-02 | single_company | scored | section | 43 | 26 | 0.52 | 1.00 | 1.00 | n/a | 5927 |
| G-03 | single_company | scored | chunk | 46 | 12 | 0.67 | 1.00 | 0.61 | n/a | 4972 |
| G-04 | single_company | scored | section | 48 | 109 | 0.44 | 1.00 | 0.87 | n/a | 5773 |
| G-05 | single_company | scored | chunk | 48 | 3 | 1.00 | 1.00 | 0.58 | n/a | 7905 |
| G-06 | comparison | scored | chunk | 46 | 44 | 0.76 | 1.00 | 1.00 | 1.00 | 6960 |
| G-07 | comparison | scored | section | 44 | 81 | 1.00 | 1.00 | 1.00 | 1.00 | 6658 |
| G-08 | comparison | scored | section | 48 | 67 | 0.96 | 1.00 | 1.00 | 1.00 | 5469 |
| G-09 | comparison | scored | chunk | 48 | 14 | 0.86 | 1.00 | 0.93 | 1.00 | 5934 |
| G-10 | comparison | scored | section | 43 | 294 | 1.00 | 1.00 | 1.00 | 0.75 | 6331 |
| G-11 | trend | scored | chunk | 48 | 87 | 0.56 | 1.00 | 0.89 | n/a | 7088 |
| G-12 | trend | scored | section | 42 | 247 | 1.00 | 1.00 | 1.00 | n/a | 7027 |
| G-13 | trend | scored | section | 48 | 566 | 0.92 | 1.00 | 1.00 | n/a | 6808 |
| G-14 | trend | scored | section | 43 | 101 | 1.00 | 1.00 | 1.00 | n/a | 6589 |
| G-15 | numeric | scored | chunk | 48 | 4 | 1.00 | 0.14 | 0.27 | n/a | 5379 |
| G-16 | numeric | scored | chunk | 48 | 2 | 1.00 | 1.00 | 0.76 | n/a | 5155 |
| G-17 | numeric | scored | section | 48 | 180 | 1.00 | 1.00 | 1.00 | n/a | 5460 |
| G-18 | numeric | scored | section | 48 | 1335 | 1.00 | 1.00 | 1.00 | n/a | 5433 |
| G-19 | sector | scored | chunk | 40 | 49 | 0.76 | 1.00 | 0.81 | 1.00 | 6695 |
| G-20 | sector | scored | section | 48 | 294 | 0.92 | 1.00 | 1.00 | 1.00 | 5884 |
| G-21 | sector | scored | chunk | 41 | 20 | 0.45 | 1.00 | 0.67 | 1.00 | 5424 |
| G-22 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-23 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-24 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-25 | ambiguous_entity | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-26 | ambiguous_entity | scored | section | 48 | 36 | 1.00 | 1.00 | 1.00 | n/a | 5030 |
| G-27 | adversarial | scored | section | 42 | 43 | 1.00 | 1.00 | 1.00 | n/a | 5046 |
| G-28 | adversarial | answer_only | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |

## Weakest questions

| Question | R@25 | Expected sources | Context sections | Note |
| --- | --- | --- | --- | --- |
| G-04 | 0.44 | DIS_10K_2024-09-28 mdna | mdna 25, financial_statements 23 |  |
| G-21 | 0.45 | AAPL_10K_2025-09-27 risk_factors, MSFT_10K_2025-06-30 risk_factors, GOOG_10K_2025-12-31 risk_factors, AMZN_10K_2025-12-31 risk_factors, META_10K_2025-12-31 risk_factors, NVDA_10K_2025-01-26 risk_factors | risk_factors 41 |  |
| G-02 | 0.52 | MSFT_10K_2025-06-30 business | business 15, mdna 15, financial_statements 13 |  |
| G-11 | 0.56 | NVDA_10K_2024-01-28 mdna/financial_statements, NVDA_10Q_2024-04-28 mdna/financial_statements, NVDA_10Q_2024-07-28 mdna/financial_statements, NVDA_10Q_2024-10-27 mdna/financial_statements, NVDA_10K_2025-01-26 mdna/financial_statements, NVDA_10Q_2025-04-27 mdna/financial_statements, NVDA_10Q_2025-07-27 mdna/financial_statements, NVDA_10Q_2025-10-26 mdna/financial_statements | mdna 45, financial_statements 3 |  |
| G-03 | 0.67 | TSLA_10K_2025-12-31 legal_proceedings, TSLA_10Q_2025-09-30 legal_proceedings | financial_statements 32, legal_proceedings 11, unknown 2, risk_factors 1 |  |
| G-06 | 0.76 | AAPL_10K_2025-09-27 risk_factors, TSLA_10K_2025-12-31 risk_factors, JPM_10K_2025-12-31 risk_factors | risk_factors 41, mdna 4, unknown 1 |  |

## Answer metrics (chapter 18.4 and 18.6)

| Type | Questions | Questions with a call | Faithfulness | Citation precision | Coverage | Numeric | Schema | Latency p50 s | Latency p95 s | Mean cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | 28 | 24 | 0.86 | 0.99 | 1.00 | 1.00 | 1.00 | 23.0 | 32.2 | 0.0936 |
| single_company | 5 | 5 | 0.87 | 1.00 | n/a | n/a | 1.00 | 20.5 | 22.7 | 0.0873 |
| comparison | 5 | 5 | 0.88 | 0.99 | 1.00 | n/a | 1.00 | 28.9 | 32.2 | 0.1045 |
| trend | 4 | 4 | 0.72 | 0.94 | n/a | n/a | 1.00 | 25.1 | 26.9 | 0.1007 |
| numeric | 4 | 4 | 0.90 | 1.00 | n/a | 1.00 | 1.00 | 15.7 | 18.4 | 0.0742 |
| sector | 3 | 3 | 0.94 | 1.00 | 1.00 | n/a | 1.00 | 32.0 | 36.4 | 0.1122 |
| ambiguous_entity | 2 | 1 | 0.88 | 1.00 | n/a | n/a | 1.00 | 20.7 | 20.7 | 0.0839 |
| adversarial | 2 | 2 | 0.88 | 1.00 | n/a | n/a | 1.00 | 17.0 | 19.0 | 0.0836 |
| out_of_corpus | 3 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

Faithfulness and citation precision score supported 1, partly
supported 0.5, and not supported 0, averaged per answer and then
over the answers; an unverified finding scores 0, and each citation
the validator removed counts as unsupported. Latency and cost come
from the audit record of each request and cover the questions with
a model request.

Spend: answers 2.2460 USD, judge 2.0493 USD; maximum answer cost 0.1164 USD; judge failures 0.

### Per question (answers)

| Question | Type | Outcome | Requests | Faithfulness | Citation precision | Coverage | Numeric | Checks | Latency s | Cost USD | Output tokens | Words |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | single_company | answered | 1 | 0.83 | 1.00 | n/a | n/a | n/a | 22.9 | 0.0935 | 2231 | 132 |
| G-02 | single_company | answered | 1 | 1.00 | 1.00 | n/a | n/a | n/a | 18.4 | 0.0920 | 2139 | 140 |
| G-03 | single_company | answered | 1 | 0.81 | 1.00 | n/a | n/a | n/a | 20.5 | 0.0943 | 2464 | 139 |
| G-04 | single_company | answered | 1 | 0.90 | 1.00 | n/a | n/a | n/a | 21.6 | 0.0717 | 2776 | 140 |
| G-05 | single_company | answered | 1 | 0.81 | 1.00 | n/a | n/a | n/a | 18.8 | 0.0847 | 1583 | 162 |
| G-06 | comparison | answered | 1 | 0.75 | 1.00 | 1.00 | n/a | n/a | 32.3 | 0.1135 | 4659 | 141 |
| G-07 | comparison | answered | 1 | 1.00 | 1.00 | 1.00 | n/a | n/a | 25.8 | 0.0978 | 3183 | 133 |
| G-08 | comparison | answered | 1 | 0.84 | 0.97 | 1.00 | n/a | n/a | 28.9 | 0.1012 | 4211 | 153 |
| G-09 | comparison | answered | 1 | 0.83 | 1.00 | 1.00 | n/a | n/a | 23.0 | 0.1042 | 2612 | 128 |
| G-10 | comparison | answered | 1 | 0.97 | 1.00 | 1.00 | n/a | n/a | 31.9 | 0.1058 | 3805 | 141 |
| G-11 | trend | answered | 1 | 0.90 | 1.00 | n/a | n/a | n/a | 25.8 | 0.1085 | 3422 | 139 |
| G-12 | trend | answered | 1 | 0.50 | 0.83 | n/a | n/a | n/a | 27.1 | 0.0994 | 3315 | 133 |
| G-13 | trend | answered | 1 | 0.89 | 1.00 | n/a | n/a | n/a | 23.9 | 0.1000 | 2924 | 128 |
| G-14 | trend | answered | 1 | 0.61 | 0.94 | n/a | n/a | n/a | 24.3 | 0.0948 | 2914 | 170 |
| G-15 | numeric | answered | 1 | 1.00 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 12.5 | 0.0622 | 1118 | 60 |
| G-16 | numeric | answered | 1 | 0.81 | 1.00 | n/a | 1.00 | 6 of 6 gold values | 16.0 | 0.0748 | 1775 | 83 |
| G-17 | numeric | answered | 1 | 0.79 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 18.9 | 0.0867 | 2264 | 98 |
| G-18 | numeric | answered | 1 | 1.00 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 15.3 | 0.0730 | 1318 | 93 |
| G-19 | sector | answered | 1 | 0.95 | 1.00 | 1.00 | n/a | n/a | 36.9 | 0.1164 | 4991 | 172 |
| G-20 | sector | answered | 1 | 0.91 | 1.00 | 1.00 | n/a | n/a | 28.3 | 0.1059 | 3824 | 139 |
| G-21 | sector | answered | 1 | 0.96 | 1.00 | 1.00 | n/a | n/a | 32.0 | 0.1144 | 4890 | 147 |
| G-22 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-23 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-24 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-25 | ambiguous_entity | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-26 | ambiguous_entity | answered | 1 | 0.88 | 1.00 | n/a | n/a | n/a | 20.7 | 0.0839 | 2495 | 145 |
| G-27 | adversarial | answered | 1 | 0.91 | 1.00 | n/a | n/a | adversarial ok | 19.2 | 0.0878 | 2248 | 104 |
| G-28 | adversarial | answered | 1 | 0.86 | 1.00 | n/a | n/a | adversarial failed | 14.7 | 0.0793 | 1324 | 114 |

### Weakest answers

| Question | Faithfulness | Citation precision | First issue |
| --- | --- | --- | --- |
| G-12 | 0.50 | 0.83 | C2 partly_supported: The cited FY2025 chunks show tariff language in the inventory, inflation and China-supplier passages, but no cited chunk shows that the FY2024 10-K lacked it in those places. |
| G-14 | 0.61 | 0.94 | C1 partly_supported: The chunks show continuity in the goodwill and cybersecurity text, but they include no fiscal 2023 counterparts for the Change Healthcare and AI/ML passages, so the 'few additions' characterization cannot be fully confirmed. |
| G-06 | 0.75 | 1.00 | C1 partly_supported: Chunks 0000 and 0002 support macroeconomic conditions, trade restrictions and tariffs, and Asia-concentrated outsourcing, but not intense competition, cybersecurity or regulatory scrutiny. |
