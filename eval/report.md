# Eval report

Written by `keel eval` (chapter 18). Regenerate it; do not edit it.

| Field | Value |
| --- | --- |
| Run ID | eval-20261022T064805Z |
| Started (UTC) | 2026-10-22T06:48:05+00:00 |
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
| Wall time | 1362 s |

## Regression gates

| Gate | Threshold | Value | Status | Source |
| --- | --- | --- | --- | --- |
| Recall at 25 | >= 0.85 | 0.74 | fail | retrieval, main variant |
| MRR | >= 0.60 | 0.96 | pass | retrieval, main variant |
| Faithfulness | >= 0.90 | 0.87 | fail | judge, claims of the direct answer and the findings |
| Citation precision | >= 0.90 | 0.99 | pass | judge, plus the validator drift count |
| Coverage completeness on comparison and sector questions | >= 1.00 | 1.00 | pass | coverage statement and gaps (code) |
| Numeric accuracy | >= 0.90 | 1.00 | pass | answer values within 0.5% of the gold (code) |
| Schema validity | >= 1.00 | 1.00 | pass | answer schema (code) |
| Refusal correctness | >= 1.00 | 1.00 | pass | answer step: out-of-scope response and 0 model requests |
| Latency p95 | <= 40.00 s | 34.07 s | pass | audit records, total latency |
| Mean cost per question | <= 0.25 USD | 0.09 USD | pass | audit records, answer cost |

Verdict: blocked: a gate failed. A pending gate does not block on its own.

## Retrieval metrics (hybrid)

| Type | Questions | R@10 | R@25 | R@48 | MRR | nDCG@10 | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all | 23 | 0.77 | 0.74 | 0.64 | 0.96 | 0.83 | 0.94 |
| single_company | 5 | 0.57 | 0.54 | 0.50 | 1.00 | 0.70 | n/a |
| comparison | 5 | 0.96 | 0.93 | 0.78 | 1.00 | 0.97 | 0.95 |
| trend | 4 | 0.72 | 0.59 | 0.46 | 1.00 | 0.82 | n/a |
| numeric | 4 | 0.88 | 1.00 | 0.91 | 0.79 | 0.76 | n/a |
| sector | 3 | 0.60 | 0.64 | 0.57 | 1.00 | 0.81 | 0.93 |
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
| hybrid | 0.74 | 0.83 | 0.96 | 0.64 | 6184 | 8305 |
| lexical | 0.69 | 0.80 | 0.94 | 0.57 | 5781 | 13580 |
| dense | 0.67 | 0.81 | 0.96 | 0.56 | 6472 | 9708 |
| hybrid, no reranker | 0.68 | 0.77 | 0.93 | 0.64 | 114 | 1475 |
| lexical, no reranker | 0.69 | 0.78 | 0.85 | 0.59 | 76 | 423 |
| dense, no reranker | 0.67 | 0.77 | 0.91 | 0.56 | 50 | 1129 |

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
| G-01 | single_company | scored | chunk | 45 | 31 | 1.00 | 1.00 | 1.00 | n/a | 6802 |
| G-02 | single_company | scored | section | 48 | 26 | 0.08 | 1.00 | 0.36 | n/a | 5206 |
| G-03 | single_company | scored | chunk | 48 | 6 | 0.17 | 1.00 | 0.71 | n/a | 4918 |
| G-04 | single_company | scored | section | 48 | 109 | 0.44 | 1.00 | 0.87 | n/a | 4964 |
| G-05 | single_company | scored | chunk | 48 | 3 | 1.00 | 1.00 | 0.58 | n/a | 7740 |
| G-06 | comparison | scored | chunk | 48 | 42 | 0.68 | 1.00 | 1.00 | 1.00 | 7367 |
| G-07 | comparison | scored | section | 42 | 81 | 1.00 | 1.00 | 1.00 | 1.00 | 8367 |
| G-08 | comparison | scored | section | 48 | 67 | 0.96 | 1.00 | 1.00 | 1.00 | 8590 |
| G-09 | comparison | scored | chunk | 47 | 11 | 1.00 | 1.00 | 0.83 | 1.00 | 6149 |
| G-10 | comparison | scored | section | 43 | 294 | 1.00 | 1.00 | 1.00 | 0.75 | 6981 |
| G-11 | trend | scored | chunk | 48 | 87 | 0.56 | 1.00 | 0.89 | n/a | 7419 |
| G-12 | trend | scored | section | 46 | 247 | 1.00 | 1.00 | 1.00 | n/a | 7227 |
| G-13 | trend | scored | section | 48 | 566 | 0.44 | 1.00 | 0.47 | n/a | 5375 |
| G-14 | trend | scored | section | 46 | 101 | 0.36 | 1.00 | 0.92 | n/a | 6942 |
| G-15 | numeric | scored | chunk | 48 | 4 | 1.00 | 0.14 | 0.27 | n/a | 5379 |
| G-16 | numeric | scored | chunk | 48 | 2 | 1.00 | 1.00 | 0.76 | n/a | 5220 |
| G-17 | numeric | scored | section | 48 | 180 | 1.00 | 1.00 | 1.00 | n/a | 5389 |
| G-18 | numeric | scored | section | 48 | 1335 | 1.00 | 1.00 | 1.00 | n/a | 5422 |
| G-19 | sector | scored | chunk | 40 | 44 | 0.56 | 1.00 | 0.75 | 0.80 | 6587 |
| G-20 | sector | scored | section | 48 | 294 | 0.92 | 1.00 | 1.00 | 1.00 | 6184 |
| G-21 | sector | scored | chunk | 41 | 20 | 0.45 | 1.00 | 0.67 | 1.00 | 6896 |
| G-22 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-23 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-24 | out_of_corpus | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-25 | ambiguous_entity | refused | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| G-26 | ambiguous_entity | scored | section | 48 | 36 | 1.00 | 1.00 | 1.00 | n/a | 5257 |
| G-27 | adversarial | scored | section | 41 | 43 | 0.48 | 1.00 | 0.94 | n/a | 5417 |
| G-28 | adversarial | answer_only | n/a | 0 | 0 | n/a | n/a | n/a | n/a | 0 |

## Weakest questions

| Question | R@25 | Expected sources | Context sections | Note |
| --- | --- | --- | --- | --- |
| G-02 | 0.08 | MSFT_10K_2025-06-30 business | mdna 27, financial_statements 14, business 7 |  |
| G-03 | 0.17 | TSLA_10K_2025-12-31 legal_proceedings, TSLA_10Q_2025-09-30 legal_proceedings | unknown 22, risk_factors 12, legal_proceedings 11, business 3 |  |
| G-14 | 0.36 | UNH_10K_2022-12-31 risk_factors, UNH_10K_2023-12-31 risk_factors, UNH_10K_2024-12-31 risk_factors | mdna 30, risk_factors 12, unknown 4 |  |
| G-04 | 0.44 | DIS_10K_2024-09-28 mdna | mdna 25, financial_statements 23 |  |
| G-13 | 0.44 | PFE_10Q_2024-03-31 mdna, PFE_10Q_2024-06-30 mdna, PFE_10Q_2024-09-29 mdna, PFE_10K_2024-12-31 mdna, PFE_10Q_2025-03-30 mdna, PFE_10Q_2025-06-29 mdna, PFE_10Q_2025-09-28 mdna | financial_statements 26, mdna 22 |  |
| G-21 | 0.45 | AAPL_10K_2025-09-27 risk_factors, MSFT_10K_2025-06-30 risk_factors, GOOG_10K_2025-12-31 risk_factors, AMZN_10K_2025-12-31 risk_factors, META_10K_2025-12-31 risk_factors, NVDA_10K_2025-01-26 risk_factors | risk_factors 41 |  |

## Answer metrics (chapter 18.4 and 18.6)

| Type | Questions | Questions with a call | Faithfulness | Citation precision | Coverage | Numeric | Schema | Latency p50 s | Latency p95 s | Mean cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | 28 | 24 | 0.87 | 0.99 | 1.00 | 1.00 | 1.00 | 23.1 | 34.1 | 0.0935 |
| single_company | 5 | 5 | 0.90 | 0.99 | n/a | n/a | 1.00 | 21.0 | 21.4 | 0.0868 |
| comparison | 5 | 5 | 0.89 | 1.00 | 1.00 | n/a | 1.00 | 30.6 | 33.5 | 0.1061 |
| trend | 4 | 4 | 0.76 | 0.99 | n/a | n/a | 1.00 | 26.4 | 28.7 | 0.1015 |
| numeric | 4 | 4 | 0.93 | 0.97 | n/a | 1.00 | 1.00 | 15.6 | 17.1 | 0.0723 |
| sector | 3 | 3 | 0.95 | 1.00 | 1.00 | n/a | 1.00 | 34.1 | 47.7 | 0.1134 |
| ambiguous_entity | 2 | 1 | 0.73 | 1.00 | n/a | n/a | 1.00 | 22.8 | 22.8 | 0.0872 |
| adversarial | 2 | 2 | 0.84 | 1.00 | n/a | n/a | 1.00 | 17.3 | 18.7 | 0.0786 |
| out_of_corpus | 3 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

Faithfulness and citation precision score supported 1, partly
supported 0.5, and not supported 0, averaged per answer and then
over the answers; an unverified finding scores 0, and each citation
the validator removed counts as unsupported. Latency and cost come
from the audit record of each request and cover the questions with
a model request.

Spend: answers 2.2444 USD, judge 2.0055 USD; maximum answer cost 0.1190 USD; judge failures 0.

### Per question (answers)

| Question | Type | Outcome | Requests | Faithfulness | Citation precision | Coverage | Numeric | Checks | Latency s | Cost USD | Output tokens | Words |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | single_company | answered | 1 | 0.65 | 0.95 | n/a | n/a | n/a | 21.4 | 0.0928 | 2165 | 162 |
| G-02 | single_company | answered | 1 | 1.00 | 1.00 | n/a | n/a | n/a | 19.0 | 0.0926 | 2112 | 123 |
| G-03 | single_company | answered | 1 | 1.00 | 1.00 | n/a | n/a | n/a | 21.1 | 0.0907 | 2922 | 141 |
| G-04 | single_company | answered | 1 | 0.91 | 1.00 | n/a | n/a | n/a | 21.0 | 0.0718 | 2783 | 149 |
| G-05 | single_company | answered | 1 | 0.94 | 1.00 | n/a | n/a | n/a | 19.4 | 0.0858 | 1773 | 156 |
| G-06 | comparison | answered | 1 | 0.83 | 1.00 | 1.00 | n/a | n/a | 33.1 | 0.1125 | 4550 | 146 |
| G-07 | comparison | answered | 1 | 0.88 | 1.00 | 1.00 | n/a | n/a | 29.6 | 0.0994 | 3366 | 130 |
| G-08 | comparison | answered | 1 | 0.89 | 1.00 | 1.00 | n/a | n/a | 33.6 | 0.1043 | 4367 | 120 |
| G-09 | comparison | answered | 1 | 0.92 | 1.00 | 1.00 | n/a | n/a | 24.3 | 0.1072 | 2875 | 153 |
| G-10 | comparison | answered | 1 | 0.91 | 1.00 | 1.00 | n/a | n/a | 30.6 | 0.1071 | 3937 | 143 |
| G-11 | trend | answered | 1 | 0.78 | 1.00 | n/a | n/a | n/a | 28.8 | 0.1078 | 3346 | 157 |
| G-12 | trend | answered | 1 | 0.68 | 0.95 | n/a | n/a | n/a | 28.0 | 0.1011 | 3307 | 168 |
| G-13 | trend | answered | 1 | 0.81 | 1.00 | n/a | n/a | n/a | 24.8 | 0.1004 | 2982 | 142 |
| G-14 | trend | answered | 1 | 0.78 | 1.00 | n/a | n/a | n/a | 23.5 | 0.0969 | 2741 | 183 |
| G-15 | numeric | answered | 1 | 1.00 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 12.2 | 0.0620 | 1102 | 57 |
| G-16 | numeric | answered | 1 | 0.88 | 0.88 | n/a | 1.00 | 6 of 6 gold values | 17.2 | 0.0769 | 1982 | 91 |
| G-17 | numeric | answered | 1 | 0.83 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 16.3 | 0.0771 | 1304 | 57 |
| G-18 | numeric | answered | 1 | 1.00 | 1.00 | n/a | 1.00 | 1 of 1 gold values | 14.9 | 0.0732 | 1339 | 103 |
| G-19 | sector | answered | 1 | 0.95 | 1.00 | 1.00 | n/a | n/a | 34.1 | 0.1141 | 4767 | 124 |
| G-20 | sector | answered | 1 | 0.97 | 1.00 | 1.00 | n/a | n/a | 28.8 | 0.1072 | 3950 | 163 |
| G-21 | sector | answered | 1 | 0.92 | 1.00 | 1.00 | n/a | n/a | 49.2 | 0.1190 | 5353 | 101 |
| G-22 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-23 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-24 | out_of_corpus | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-25 | ambiguous_entity | out_of_scope | 0 | n/a | n/a | n/a | n/a | refusal ok | 0.0 | 0.0000 | 0 | 0 |
| G-26 | ambiguous_entity | answered | 1 | 0.73 | 1.00 | n/a | n/a | n/a | 22.8 | 0.0872 | 2831 | 135 |
| G-27 | adversarial | answered | 1 | 0.75 | 1.00 | n/a | n/a | adversarial ok | 18.9 | 0.0830 | 1807 | 116 |
| G-28 | adversarial | answered | 1 | 0.93 | 1.00 | n/a | n/a | adversarial ok | 15.6 | 0.0741 | 1461 | 134 |

### Weakest answers

| Question | Faithfulness | Citation precision | First issue |
| --- | --- | --- | --- |
| G-01 | 0.65 | 0.95 | C1 partly_supported: The chunks show the fiscal 2025 period ending September 27, 2025 and the 'Macroeconomic and Industry Risks', 'Financial Risks' and 'General Risks' headings, but no 'business' or 'legal and regulatory' risk heading appears in them. |
| G-12 | 0.68 | 0.95 | C1 partly_supported: The paired FY2024 and FY2025 10-K inventory passages are nearly identical apart from an addition, but the cited chunks do not show that Amazon's overall risk factor structure was stable with only additions. |
| G-26 | 0.73 | 1.00 | C1 partly_supported: The chunks show competitive and reputational, information security, supply chain and third-party, and legal/regulatory/global headings, but no 'investment and infrastructure' or 'financial' category heading appears. |
