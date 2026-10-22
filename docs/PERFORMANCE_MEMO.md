# Performance memo: Keel filing answers

To: the investment team. Date: 2026-10-22. Index 1.2.0 (245 filings of 53
companies, 63,688 passages). Answer model `claude-sonnet-5-5`, prompt
1.4.0. Evidence: eval run `eval-20261022T111922Z` (`eval/report.md`).

**Decision: use Keel now for narrative questions on public filings, as a
pilot beside your current tools. Use it for reported numbers only for the 8
mapped company facts, and keep a warning on every other number.**

## 1. What we measured

28 test questions with known sources: 23 scored for retrieval, 24 answered
by the model, 4 that must be refused (a stock price, a company outside the
corpus, a quarter after the corpus, a quarantined filing).

| Measure | Result | Target | Status |
| --- | --- | --- | --- |
| Right passages found (recall at 25), all questions | 0.86 (0.83 on the stage 10 labels) | 0.85 | met |
| Comparisons / numeric / trend / sector / single company | 0.92 / 1.00 / 0.87 / 0.71 / 0.73 | | |
| First right passage near the top (MRR) | 0.96 | 0.60 | met |
| Claims supported by the cited text (faithfulness) | 0.86 (0.93 on a 13-question live run with judge prompt 1.2.0; the full set is not rerun) | 0.90 | miss on the full set |
| Citations that support their claim | 0.99 | 0.90 | met |
| Reported numbers within 0.5% of the filing | 9 of 9 (1.00) | 0.90 gate, 0.95 to ship | met |
| Valid answer format / correct refusals | 1.00 / 4 of 4 | 1.00 | met |
| Model requests per answer | 1 (24 for 24) | 1 | met |
| Time to the full answer, median / 95th percentile | 23.0 s / 32.2 s | 40 s | met |
| Cost per answer, mean / highest | $0.094 / $0.116 | $0.25 | met |

## 2. What works today

Narrative questions: risk comparisons across companies (recall 0.92, and every comparison
answer states the coverage of each company), regulatory scans of a sector, and
how a company's outlook changed over time. Every claim cites a passage that
opens on the SEC filing, and the server removes any citation outside the
retrieved text (0 in the run, 0 unverified findings, 0 misquotes:
the validator flags in `eval/report.json`). Questions out of scope are
refused without a model call.

## 3. What is weak, with evidence

- **Trends need several annual reports.** 40 of the 53 companies have 1
  10-K, 36 of them nothing else (the `filings` table of index 1.2.0). A question about change over time for
  them cannot be answered, and the answer says so in its gaps (for example
  "MRK has only one 10-K ... so no change over time can be shown").
- **Trend and summary answers overreach.** Faithfulness is 0.72 on trend
  questions. The weakest answer (Amazon risk changes, 0.50) says what was
  added since the earlier 10-K but cites only the later filing, so the
  cited text cannot show the change. Summary sentences list more themes
  than their citations cover (Apple, Tesla, and JPMorgan risks, 0.75).
- **Some answers still miss part of the right section.** Microsoft's
  business segments (0.52), Disney's fiscal 2024 drivers (0.44), and
  NVIDIA's revenue trend (0.56) find the right filing but rank other
  passages of it first. Recall rose from 0.74 to 0.86 after the retrieval
  read the latest annual report first, gave quarterly risk sections only
  their changes, and treated a question about 2 fiscal years as a trend
  (`docs/BUILD_REPORT.md`, follow-up after stage 22). The gate passes
  with 28 grades added for passages the first test labels never judged;
  on the first labels alone recall is 0.83.
- **Numbers depend on units and on the source.** Numbers from filing
  tables depend on the units line of each table (index 1.2.0 fixed 564
  such lines). No numeric miss was found: 9 of 9 gold values matched,
  including NVIDIA's fiscal 2025 revenue of $130,497 million, which the
  stage 15 answer took from the company facts line. That line comes from NVIDIA's
  fiscal 2026 10-K, which is newer than the corpus; the answer cites the fact
  with its EDGAR link, and the cached answer to the NVIDIA trend question
  flags the filing date difference in its gaps.
- **9 test values is a small sample** for the 0.95 rule.

## 4. Decision rule

Ship narrative questions now. For numbers, ship the 8 mapped company facts
(revenue, net income, diluted EPS, operating income, total assets, cash,
shares outstanding, long-term debt), which the answer cites by fact ID:
numeric accuracy is 1.00 against the 0.95 that this rule asks (the eval
gate is 0.90). Hold every other number
behind a warning until a larger numeric test set holds 0.95.

## 5. What changes next and when

| Change | Measure that decides | Target date |
| --- | --- | --- |
| Done: judge prompt 1.2.0 reads each cited chunk as the answer model read it and leaves statements about Keel out of the score (13 questions: 0.85 to 0.93). Next: a full live eval, and a change claim cites the earlier and the later filing | Faithfulness 0.90 on the full set | 2026-11-05 |
| Judge thresholds and a summary-claim rule in the prompt; the human rubric of 2 raters | Faithfulness 0.90; judge agreement with the raters | 2026-11-12 |
| Live EDGAR for coverage (`keel add`, nightly refresh) and a larger numeric set | Companies with 2 or more 10-Ks; 50 gold values at 0.95 | 2026-11-26 |
