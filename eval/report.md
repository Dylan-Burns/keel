# Eval report

Written by `keel eval` (chapter 18). Regenerate it; do not edit it.

| Field | Value |
| --- | --- |
| Run ID | eval-20261028T012734Z |
| Started (UTC) | 2026-10-28T01:27:34+00:00 |
| Golden set | 1.0.0, subset all |
| Questions | 28 |
| Index | 1.2.0, build 20261022T050249382998Z |
| Index chunks_sha256 | be95e3aa90a5857e023f945125193cc6a5e0de6df111119a5b31ff00b2f59737 |
| Labels from another index | none |
| Prompt version | 1.5.1 |
| Answer model | claude-sonnet-5-5 |
| Judge model | claude-opus-5-5 |
| Model requests | 24 answer, 24 judge |
| Variants | hybrid, lexical, dense, hybrid, no reranker, lexical, no reranker, dense, no reranker |
| Wall time | 1343 s |

## Regression gates

| Gate | Threshold | Value | Status | Source |
| --- | --- | --- | --- | --- |
| Recall at 25 | >= 0.85 | 0.86 | pass | retrieval, main variant |
| MRR | >= 0.60 | 0.96 | pass | retrieval, main variant |
| Faithfulness | >= 0.90 | 0.94 | pass | judge, claims of the direct answer and the findings |
| Citation precision | >= 0.90 | 1.00 | pass | judge, plus the validator drift count |
| Coverage completeness on comparison and sector questions | >= 1.00 | 1.00 | pass | coverage statement and gaps (code) |
| Numeric accuracy | >= 0.90 | 1.00 | pass | answer values within 0.5% of the gold (code) |
| Schema validity | >= 1.00 | 1.00 | pass | answer schema (code) |
| Refusal correctness | >= 1.00 | 1.00 | pass | answer step: out-of-scope response and 0 model requests |
| Latency p95 | <= 40.00 s | 34.24 s | pass | audit records, total latency |
| Mean cost per question | <= 0.25 USD | 0.09 USD | pass | audit records, answer cost |

Verdict: no gate failed. A pending gate does not block on its own.

## Retrieval metrics (hybrid)

| Type | Questions | R@10 | R@25 | R@48 | MRR | nDCG@10 | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all | 23 | 0.85 | 0.86 | 0.76 | 0.96 | 0.89 | 0.97 |
| single_company | 5 | 0.71 | 0.73 | 0.73 | 1.00 | 0.81 | n/a |
| comparison | 5 | 0.96 | 0.91 | 0.75 | 1.00 | 0.99 | 0.95 |
| trend | 4 | 0.93 | 0.87 | 0.73 | 1.00 | 0.97 | n/a |
| numeric | 4 | 0.88 | 1.00 | 0.91 | 0.79 | 0.76 | n/a |
| sector | 3 | 0.67 | 0.71 | 0.59 | 1.00 | 0.84 | 1.00 |
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

| Variant | R@25 | nDCG@10 | MRR | R@48 | Retrieval p50 ms | Retrieval p95 ms | Rerank p50 ms | Rerank p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid | 0.86 | 0.89 | 0.96 | 0.76 | 7716 | 9599 | 6788 | 8145 |
| lexical | 0.79 | 0.87 | 0.96 | 0.69 | 6959 | 7871 | 6769 | 7416 |
| dense | 0.82 | 0.87 | 0.96 | 0.70 | 7404 | 8403 | 6934 | 7856 |
| hybrid, no reranker | 0.81 | 0.83 | 0.93 | 0.76 | 589 | 2763 | 0 | 0 |
| lexical, no reranker | 0.78 | 0.83 | 0.87 | 0.72 | 195 | 663 | 0 | 0 |
| dense, no reranker | 0.79 | 0.84 | 0.97 | 0.70 | 334 | 2043 | 0 | 0 |

## Out-of-scope questions

| Question | Type | Outcome | Reason |
| --- | --- | --- | --- |
| G-22 | out_of_corpus | refused | unknown_company |
| G-23 | out_of_corpus | refused | out_of_scope_request |
| G-24 | out_of_corpus | refused | out_of_scope_request |
| G-25 | ambiguous_entity | refused | not_indexed |

## Per question (hybrid)

| Question | Type | Outcome | Labels | Chunks | Relevant | R@25 | MRR | nDCG@10 | Coverage | Retrieval ms | Rerank ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | single_company | scored | chunk | 45 | 31 | 1.00 | 1.00 | 1.00 | n/a | 11095 | 8252 |
| G-02 | single_company | scored | section | 43 | 26 | 0.52 | 1.00 | 1.00 | n/a | 8476 | 8135 |
| G-03 | single_company | scored | chunk | 48 | 12 | 0.67 | 1.00 | 0.61 | n/a | 8487 | 8146 |
| G-04 | single_company | scored | section | 48 | 109 | 0.44 | 1.00 | 0.87 | n/a | 7711 | 7521 |
| G-05 | single_company | scored | chunk | 48 | 3 | 1.00 | 1.00 | 0.58 | n/a | 7716 | 7318 |
| G-06 | comparison | scored | chunk | 46 | 44 | 0.76 | 1.00 | 1.00 | 1.00 | 6932 | 6108 |
| G-07 | comparison | scored | section | 44 | 81 | 1.00 | 1.00 | 1.00 | 1.00 | 7926 | 7195 |
| G-08 | comparison | scored | section | 48 | 67 | 1.00 | 1.00 | 1.00 | 1.00 | 7534 | 6743 |
| G-09 | comparison | scored | chunk | 48 | 14 | 0.79 | 1.00 | 0.93 | 1.00 | 7750 | 6788 |
| G-10 | comparison | scored | section | 44 | 294 | 1.00 | 1.00 | 1.00 | 0.75 | 7565 | 6790 |
| G-11 | trend | scored | chunk | 48 | 87 | 0.56 | 1.00 | 0.89 | n/a | 9714 | 6865 |
| G-12 | trend | scored | section | 42 | 247 | 1.00 | 1.00 | 1.00 | n/a | 8560 | 6613 |
| G-13 | trend | scored | section | 48 | 566 | 0.92 | 1.00 | 1.00 | n/a | 8473 | 6454 |
| G-14 | trend | scored | section | 43 | 101 | 1.00 | 1.00 | 1.00 | n/a | 7841 | 5428 |
| G-15 | numeric | scored | chunk | 48 | 4 | 1.00 | 0.14 | 0.27 | n/a | 6400 | 6228 |
| G-16 | numeric | scored | chunk | 48 | 2 | 1.00 | 1.00 | 0.76 | n/a | 7054 | 6902 |
| G-17 | numeric | scored | section | 48 | 180 | 1.00 | 1.00 | 1.00 | n/a | 6862 | 6684 |
| G-18 | numeric | scored | section | 48 | 1335 | 1.00 | 1.00 | 1.00 | n/a | 6282 | 6092 |
| G-19 | sector | scored | chunk | 41 | 49 | 0.80 | 1.00 | 0.85 | 1.00 | 7426 | 5720 |
| G-20 | sector | scored | section | 48 | 294 | 0.92 | 1.00 | 1.00 | 1.00 | 7537 | 6775 |
| G-21 | sector | scored | chunk | 41 | 20 | 0.40 | 1.00 | 0.67 | 1.00 | 8012 | 6903 |
| G-22 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 | 0 |
| G-23 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 | 0 |
| G-24 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 | 0 |
| G-25 | ambiguous_entity | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 | 0 |
| G-26 | ambiguous_entity | scored | section | 48 | 36 | 1.00 | 1.00 | 1.00 | n/a | 7854 | 7587 |
| G-27 | adversarial | scored | section | 43 | 43 | 1.00 | 1.00 | 1.00 | n/a | 7104 | 6723 |
| G-28 | adversarial | answer_only | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 | 0 |

## Weakest questions

| Question | R@25 | Expected sources | Context sections | Note |
| --- | --- | --- | --- | --- |
| G-21 | 0.40 | AAPL_10K_2025-09-27 risk_factors, MSFT_10K_2025-06-30 risk_factors, GOOG_10K_2025-12-31 risk_factors, AMZN_10K_2025-12-31 risk_factors, META_10K_2025-12-31 risk_factors, NVDA_10K_2025-01-26 risk_factors | risk_factors 41 |  |
| G-04 | 0.44 | DIS_10K_2024-09-28 mdna | mdna 25, financial_statements 23 |  |
| G-02 | 0.52 | MSFT_10K_2025-06-30 business | mdna 15, business 14, financial_statements 14 |  |
| G-11 | 0.56 | NVDA_10K_2024-01-28 mdna/financial_statements, NVDA_10Q_2024-04-28 mdna/financial_statements, NVDA_10Q_2024-07-28 mdna/financial_statements, NVDA_10Q_2024-10-27 mdna/financial_statements, NVDA_10K_2025-01-26 mdna/financial_statements, NVDA_10Q_2025-04-27 mdna/financial_statements, NVDA_10Q_2025-07-27 mdna/financial_statements, NVDA_10Q_2025-10-26 mdna/financial_statements | mdna 45, financial_statements 3 |  |
| G-03 | 0.67 | TSLA_10K_2025-12-31 legal_proceedings, TSLA_10Q_2025-09-30 legal_proceedings | financial_statements 32, legal_proceedings 11, unknown 4, risk_factors 1 |  |
| G-06 | 0.76 | AAPL_10K_2025-09-27 risk_factors, TSLA_10K_2025-12-31 risk_factors, JPM_10K_2025-12-31 risk_factors | risk_factors 41, mdna 4, unknown 1 |  |

## Answer metrics (chapter 18.4 and 18.6)

| Type | Questions | Questions with a call | Faithfulness | Citation precision | Coverage | Numeric | Schema | Latency p50 s | Latency p95 s | Mean cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | 28 | 24 | 0.94 | 1.00 | 1.00 | 1.00 | 1.00 | 23.2 | 34.2 | 0.0912 |
| single_company | 5 | 5 | 0.97 | 1.00 | n/a | n/a | 1.00 | 20.6 | 26.6 | 0.0858 |
| comparison | 5 | 5 | 0.92 | 0.99 | 1.00 | n/a | 1.00 | 28.0 | 30.4 | 0.1030 |
| trend | 4 | 4 | 0.82 | 1.00 | n/a | n/a | 1.00 | 24.5 | 27.4 | 0.0960 |
| numeric | 4 | 4 | 1.00 | 1.00 | n/a | 1.00 | 1.00 | 16.5 | 17.4 | 0.0723 |
| sector | 3 | 3 | 0.98 | 1.00 | 1.00 | n/a | 1.00 | 34.9 | 35.9 | 0.1111 |
| ambiguous_entity | 2 | 1 | 0.94 | 1.00 | n/a | n/a | 1.00 | 19.7 | 19.7 | 0.0774 |
| adversarial | 2 | 2 | 0.92 | 1.00 | n/a | n/a | 1.00 | 18.5 | 19.2 | 0.0808 |
| out_of_corpus | 3 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

Faithfulness and citation precision score supported 1, partly
supported 0.5, and not supported 0, averaged per answer and then
over the answers; an unverified finding scores 0, and each citation
the validator removed counts as unsupported. Latency and cost come
from the audit record of each request and cover the questions with
a model request.

Spend: answers 2.1896 USD, judge 1.8687 USD; maximum answer cost 0.1146 USD; judge failures 0.

### Per question (answers)

| Question | Type | Outcome | Requests | Faithfulness | Citation precision | Coverage | Numeric | Checks | Latency s | Cost USD | Output tokens | Words |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | single_company | answered | 1 | 0.85 | 1.00 | n/a | n/a | n/a | 27.2 | 0.0929 | 2166 | 135 |
| G-02 | single_company | answered | 1 | 1.00 | 1.00 | n/a | n/a | n/a | 20.6 | 0.0921 | 2121 | 132 |
| G-03 | single_company | answered | 1 | 1.00 | 1.00 | n/a | n/a | n/a | 23.9 | 0.0917 | 2168 | 107 |
| G-04 | single_company | answered | 1 | 1.00 | 1.00 | n/a | n/a | n/a | 20.4 | 0.0666 | 2263 | 124 |
| G-05 | single_company | answered | 1 | 1.00 | 1.00 | n/a | n/a | n/a | 18.6 | 0.0858 | 1691 | 129 |
| G-06 | comparison | answered | 1 | 0.80 | 1.00 | 1.00 | n/a | n/a | 29.7 | 0.1090 | 4216 | 148 |
| G-07 | comparison | answered | 1 | 0.95 | 1.00 | 1.00 | n/a | n/a | 27.7 | 0.0997 | 3367 | 104 |
| G-08 | comparison | answered | 1 | 0.90 | 0.95 | 1.00 | n/a | n/a | 30.6 | 0.1015 | 4223 | 137 |
| G-09 | comparison | answered | 1 | 1.00 | 1.00 | 1.00 | n/a | n/a | 23.8 | 0.1028 | 2476 | 147 |
| G-10 | comparison | answered | 1 | 0.94 | 1.00 | 1.00 | n/a | n/a | 28.0 | 0.1020 | 3385 | 137 |
| G-11 | trend | answered | 1 | 0.80 | 1.00 | n/a | n/a | n/a | 27.6 | 0.1052 | 3091 | 151 |
| G-12 | trend | answered | 1 | 0.81 | 1.00 | n/a | n/a | n/a | 26.4 | 0.0959 | 2967 | 133 |
| G-13 | trend | answered | 1 | 0.86 | 1.00 | n/a | n/a | n/a | 22.5 | 0.0956 | 2483 | 126 |
| G-14 | trend | answered | 1 | 0.81 | 1.00 | n/a | n/a | n/a | 21.3 | 0.0873 | 2153 | 148 |
| G-15 | numeric | answered | 1 | 1.00 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 14.5 | 0.0631 | 1213 | 56 |
| G-16 | numeric | answered | 1 | 1.00 | 1.00 | n/a | 1.00 | 6 of 6 gold values | 17.5 | 0.0734 | 1718 | 111 |
| G-17 | numeric | answered | 1 | 1.00 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 16.2 | 0.0775 | 1344 | 73 |
| G-18 | numeric | answered | 1 | 1.00 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 16.8 | 0.0750 | 1516 | 95 |
| G-19 | sector | answered | 1 | 1.00 | 1.00 | 1.00 | n/a | n/a | 34.9 | 0.1139 | 4726 | 147 |
| G-20 | sector | answered | 1 | 0.97 | 1.00 | 1.00 | n/a | n/a | 28.4 | 0.1046 | 3695 | 177 |
| G-21 | sector | answered | 1 | 0.98 | 1.00 | 1.00 | n/a | n/a | 36.0 | 0.1146 | 4904 | 127 |
| G-22 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-23 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-24 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-25 | ambiguous_entity | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-26 | ambiguous_entity | answered | 1 | 0.94 | 1.00 | n/a | n/a | n/a | 19.7 | 0.0774 | 1866 | 114 |
| G-27 | adversarial | answered | 1 | 1.00 | 1.00 | n/a | n/a | adversarial ok | 19.3 | 0.0835 | 1789 | 133 |
| G-28 | adversarial | answered | 1 | 0.83 | 1.00 | n/a | n/a | adversarial ok | 17.7 | 0.0782 | 1379 | 121 |

### Weakest answers

| Question | Faithfulness | Citation precision | First issue |
| --- | --- | --- | --- |
| G-06 | 0.80 | 1.00 | C1 partly_supported: The cited Apple chunks support macroeconomic conditions, trade restrictions and outsourcing concentration, but they do not cover competition, cybersecurity or legal and regulatory scrutiny. |
| G-11 | 0.80 | 1.00 | C3 partly_supported: The cited chunk states that Blackwell architectures are the majority of Data Center revenue, but it does not mention a shift away from the Hopper platform. |
| G-12 | 0.81 | 1.00 | C2 partly_supported: The cited 0005 chunks support tariff policy changes being added to the China-seller/supplier risk, but the inventory-risk addition appears only in uncited chunks 0021/0020. |
