## 11. Retrieval

The retriever runs 1 lexical query and 1 dense query per sub-query and fuses the lists with reciprocal rank fusion. The retriever reranks the top 80 candidates, collapses near-duplicate boilerplate, and applies quotas per company and per period. The context holds at most 32,000 tokens and 48 chunks. The 3 worked examples at the end of this chapter show the plan for each example question, with the real coverage limits of the corpus.

### 11.1 Hybrid scores and fusion

For each sub-query, the retriever reads the top 100 rows from the lexical index and the top 100 rows from the dense index. Both reads use the same metadata filter. The fused score of a chunk is the sum over the 2 lists of `1 / (60 + rank)`. The rank starts at 1, and a chunk absent from a list adds 0. The retriever then multiplies the fused score by the weights in the table below.

| Weight | Value | Condition |
| --- | --- | --- |
| Section weight | 0.6 to 1.5 from the `QuestionAnalysis` | The chunk section matches a weighted section |
| Unknown section | 0.7 | A section filter is active and the chunk section is `unknown` |
| Forward-looking boilerplate | 0.5 | `boilerplate_flag = forward_looking` |
| Table | 1.3 | The primary or secondary type is `numeric` and `is_table = 1` |
| Latest filing | 1.0 for the latest filing of the company, 0.9 for other filings in the window | Always |
| Delta-only risk section | 0.9 | `delta_only = 1` and the question is about risks |

The reranker (chapter 4, D-10) scores the top 80 weighted candidates against the sub-query text. The final score is the reranker score multiplied by the same weights, so boilerplate stays down after the rerank. The ablation in chapter 18 measures each part.

### 11.2 Metadata filters

The filter is 1 SQL `WHERE` clause over the `chunks` table. The lexical query joins `chunks_fts` with the clause, and the dense query reads the `vector_row` values of the matched rows and scores only those rows.

```sql
SELECT rowid, chunk_id, vector_row FROM chunks
WHERE ticker IN (?, ?, ?)
  AND (section IN ('risk_factors', 'mdna', 'business', 'legal_proceedings') OR section = 'unknown')
  AND period_end_date BETWEEN ? AND ?;
```

A question with no time scope has no date clause. A risk question always adds the latest 10-K `risk_factors` chunks of each company to the candidate set, even when the window covers only 10-Qs. The reason is that a 10-Q risk section states only the changes since the last 10-K.

### 11.3 Sub-queries and quotas

| Primary type | Sub-queries | Quota groups | Quota per group |
| --- | --- | --- | --- |
| `single_company` | 1 | 1 | 48 chunks |
| `comparison` with n companies | 1 per company, with the company name in the dense query text | 1 per company | 48 divided by n chunks, and 32,000 divided by n tokens |
| `trend` | 1 per period cell. A cell is 1 fiscal year and 1 form in the window, plus the latest 10-Q | 1 per cell | 48 divided by the cell count, with a minimum of 2 and with at least 4 chunks for each 10-K in the window |
| `sector` with m companies | 1 per company | 1 per company | The larger of 3 and 48 divided by m. When m is more than 12, keep the 12 companies with the highest summed scores. List the other companies in the gaps |
| `generic` | 1 | 1 per company, up to 12 | 4 chunks per company |

Unused quota moves to the groups that still have candidates, in rank order. A question with both `comparison` and `trend` uses company groups with period cells inside each group.

### 11.4 Deduplication of boilerplate

Risk factor text repeats across quarters with small changes. The retriever compares the 64-bit SimHash of every pair of candidates with the same ticker and the same section. A pair with a Hamming distance of 3 or less is a near-duplicate pair. The retriever keeps the chunk from the later filing date and drops the other chunk, unless the time scope covers only the earlier period. The front-end shows the count of collapsed chunks, so the user sees why 2 quarters give 1 citation.

### 11.5 Preference for the latest filing

The same figure for the same period appears in several filings, sometimes restated. For a numeric or trend question, when 2 candidates cover the same fiscal period, the candidate from the later filing gets a weight of 1.05. The context keeps both candidates when the budget permits. The prompt rule in chapter 12 tells the model to use the later value and to name the restatement.

### 11.6 Context budget algorithm

1. Set the budget to 32,000 tokens and 48 chunks. A request can lower these values within the limits of the config.
2. Estimate the model tokens of each chunk as `token_count` multiplied by the calibration factor. Add 60 tokens for the wrapper line. The default factor is 1.15. The calibration factor comes from 1 call at build time to the token count endpoint of the provider. The call covers a sample of 200 chunks. That call generates no text.
3. Sort the candidates of each quota group by final score.
4. Take the top candidate of each group in turn. Repeat until each group reaches its quota or has no candidates.
5. Skip a candidate that does not fit the budget that remains, and continue with the next candidate. Never cut a chunk.
6. If a long table row pushes a chunk over 480 tokens, cut the chunk. Cut at the last row boundary that fits. Set `truncated = true` on the wrapper line.
7. Move the unused quota to the groups with candidates, in rank order.
8. Order the context by company in the order of the question. Within a company, order by period from the latest to the earliest, then by section weight, then by score.
9. Write a context index at the top with 1 line per chunk. Each line holds the chunk ID, the ticker, the form, the fiscal label, the section, and the filing date.
10. Record the counts of chunks, tokens, collapsed near-duplicates, and dropped candidates for the front-end.
11. If the context holds 0 chunks, return the no-context response without a model request.

### 11.7 Worked example 1: Apple, Tesla, and JPMorgan risk factors

Question: What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?

| Step | Result |
| --- | --- |
| Resolved entities | AAPL (Apple), TSLA (Tesla), JPM (JPMorgan Chase) |
| Time scope | None. The latest 10-K of each company gets weight 1.0, and other filings get 0.9. |
| Question type | `comparison`. Section weights: `risk_factors` 1.5, `legal_proceedings` 1.1, `mdna` 1.0, `business` 0.8. |
| Filters | `ticker IN (AAPL, TSLA, JPM)`, the 4 sections above plus `unknown` at 0.7 |
| Retrieval plan | 3 sub-queries, each with lexical and dense queries for the phrase primary risk factors and the company name. 100 plus 100 candidates per sub-query, fused, then the top 80 reranked. |
| Quotas | 16 chunks and about 10,600 tokens per company |
| Deduplication | 10-Q risk sections for AAPL and TSLA collapse into the latest 10-K chunks where the text repeats. |
| Context budget | About 48 chunks and 28,000 to 31,000 tokens. Expected mix per company: 12 to 14 `risk_factors` chunks, 2 to 4 `mdna` or `legal_proceedings` chunks. |
| Expected answer shape | A direct answer of 3 to 5 sentences. Findings per company with 5 to 8 risk themes, each with 1 or more citations. A comparison table with 1 row per theme and 1 column per company. The themes are supply chain and China exposure, product demand, regulation and antitrust, litigation, interest rates and credit, cybersecurity, key personnel, and competition. A coverage statement with the filings used. Gaps and confidence. |
| Known gaps | JPM has 4 filings, so the JPM findings rest mostly on the 10-K filed 2026-02-13. The JPM coverage is thinner than the coverage for AAPL and TSLA. A 10-Q risk section is a delta. A filing does not rank its risks, so the answer reports the themes that the filing states and must not invent a rank order. The large JPM 10-K (1.5 MB) holds long risk sections, so the JPM quota fills with risk chunks and leaves little room for MD&A. |

### 11.8 Worked example 2: NVIDIA revenue and growth outlook

Question: How has NVIDIA's revenue and growth outlook changed over the last two years?

| Step | Result |
| --- | --- |
| Resolved entities | NVDA (NVIDIA) |
| Time scope | Last two years, anchored to the latest NVDA period end date (D-33). Case A: the 10-K filed in February 2026 is present (A-15). The anchor is the end of fiscal 2026, and the window covers fiscal 2025 and fiscal 2026. Case B: the 10-K is absent. The anchor is the latest 10-Q of fiscal 2026. The window covers fiscal 2024, fiscal 2025, and the quarters of fiscal 2026. |
| Question type | `trend` with `numeric` and `single_company`. Section weights: `mdna` 1.5, `financial_statements` 1.2, `business` 0.8, `risk_factors` 0.6. Table weight 1.3. |
| Filters | `ticker = NVDA`, `period_end_date` in the window, the weighted sections plus `unknown` |
| Retrieval plan | 1 sub-query per period cell. Case A: 2 10-K cells and 3 10-Q cells. Case B: 2 10-K cells and up to 6 10-Q cells. Lexical terms: revenue, revenues, growth, outlook, expect, data center. Dense query: NVIDIA revenue growth and outlook with the fiscal label of the cell. |
| Quotas | Case A: 9 chunks per cell with at least 4 for each 10-K. Case B: 6 chunks per cell. |
| Latest filing preference | Fiscal 2025 revenue appears in the fiscal 2025 10-K and as a comparative in the fiscal 2026 10-K. The fiscal 2026 chunk gets 1.05, and the prompt tells the model to name a restatement if the values differ. |
| Context budget | About 40 to 48 chunks. Expected mix: MD&A results tables with revenue by segment and by fiscal year, MD&A outlook paragraphs, and 10-Q quarterly revenue tables. |
| Expected answer shape | A direct answer with revenue per fiscal year, each labeled with the period end date, for example fiscal 2025, ended January 26, 2025. The answer gives the growth rate when both values are in the context, and the outlook statements per period. A trend table with 1 row per fiscal period. A coverage statement with the forms and periods used. Gaps and confidence. |
| Known gaps | The NVIDIA fiscal year ends in late January, so fiscal 2025 is not calendar 2025, and the answer must say so. The 10-K gives a qualitative outlook, not numeric guidance, so the answer must not invent a guidance figure. In case B the latest annual figure is fiscal 2025. Table units come from the caption (in millions), and the number rules in chapter 12 apply. |

### 11.9 Worked example 3: regulatory risks of the major pharmaceutical companies

Question: What regulatory risks do the major pharmaceutical companies face, and how are they addressing them?

| Step | Result |
| --- | --- |
| Resolved entities | Group `pharma`: PFE, JNJ, MRK, LLY, ABBV (A-06) |
| Time scope | None. The latest 10-K of each company gets weight 1.0. |
| Question type | `sector`. Section weights: `risk_factors` 1.5, `legal_proceedings` 1.2, `business` 1.0 (the government regulation subsection of Item 1), `mdna` 0.8. |
| Filters | `ticker IN (PFE, JNJ, MRK, LLY, ABBV)`, the 4 sections above plus `unknown` |
| Retrieval plan | 5 sub-queries. Lexical terms: regulation, regulatory, FDA, approval, prices, compliance, legislation, Medicare, litigation. Dense query: regulatory risks and the company response with the company name. |
| Quotas | 9 chunks per company, with 3 spare chunks moved to the companies with candidates. |
| Deduplication | PFE and JNJ 10-Q risk deltas collapse into the 10-K chunks where the text repeats. |
| Context budget | About 45 chunks and 28,000 tokens |
| Expected answer shape | A sector summary of 3 to 5 sentences. Findings per company that separate the risk from the response, with 1 or more citations for each. A comparison table with 1 row per theme and 1 column per company. The themes are drug price legislation, approval and clinical risk, product liability and litigation, data privacy, and international regulation. A coverage statement. Gaps and confidence. |
| Known gaps | MRK, LLY, and ABBV have exactly 1 10-K each, so the answer cannot show a trend for them and must say so. PFE and JNJ have quarterly coverage, but a 10-Q risk section is a delta. Response statements live mostly in Item 1 and in MD&A. A filing that gives no response statement must appear in the gaps, with no invented response. |

### 11.10 Tests

| Test | Expected result |
| --- | --- |
| `test_rrf_fusion` | A chunk at rank 1 in both lists scores 2 / 61 |
| `test_section_weights` | A `risk_factors` chunk outranks an equal `business` chunk for a risk question |
| `test_boilerplate_weight` | A forward-looking chunk scores half of an equal prose chunk |
| `test_comparison_quotas` | Each of 3 companies gets 16 chunks when candidates exist |
| `test_quota_redistribution` | A company with 5 candidates leaves 11 chunks for the other companies |
| `test_trend_cells` | Each 10-K in the window gets at least 4 chunks |
| `test_sector_cap` | A group of 53 companies keeps 12 companies and lists 41 in the gaps |
| `test_simhash_collapse` | 2 chunks with a Hamming distance of 2 collapse to the later filing |
| `test_latest_filing_weight` | The later comparative outranks the original for the same period |
| `test_budget_never_exceeded` | The context stays at or under 32,000 estimated tokens and 48 chunks |
| `test_context_order` | Companies appear in question order and periods from the latest to the earliest |
| `test_empty_context` | A filter with no rows returns the no-context response without a model request |
| `test_risk_10k_supplement` | A 10-Q-only window still includes the latest 10-K `risk_factors` chunks for a risk question |
