# Code walk

The cold-read rehearsal of chapter 25.6 (W-05). Walk the modules in
pipeline order against a 20-minute timer, aloud, with nothing open in
advance. Each stop names the file, the functions to open, the corpus fact
that the module answers, and the 2 questions the panel is most likely to
ask, with a short answer.

The 3-minute rule: no stop may take more than 3 minutes. The 3 largest
modules (`understanding.py` 1,822 lines, `retriever.py` 1,539 lines,
`sections.py` 1,174 lines) are each split into 2 stops of at most 3
minutes, so the walk splits the explanation instead of the code. If a stop
still runs over in rehearsal, split the module before the demo (chapter
25.6 step 5) and record the split in the build report.

The numbers below are the measured ones of `docs/BUILD_REPORT.md` (index
1.2.0: 246 files, 245 indexed, 1 quarantined, 63,688 chunks).

## Timing plan

| Stop | Module | Minutes |
| --- | --- | --- |
| 1 | `keel/extractor.py`, `keel/inventory.py` | 1 |
| 2 | `keel/parsers/form_10k_10q.py`, `keel/parsers/base.py`, `keel/parsers/corpus.py`, `keel/tables.py` | 2.5 |
| 3a, 3b | `keel/sections.py` | 2 + 1 |
| 4 | `keel/chunker.py` | 1.5 |
| 5 | `keel/indexer.py`, `keel/stores/` | 1.5 |
| 6a, 6b | `keel/understanding.py` | 1.5 + 1.5 |
| 7a, 7b | `keel/retriever.py`, `keel/context.py` | 2 + 1.5 |
| 8 | `keel/edgar.py` | 1 |
| 9 | `keel/prompt.py`, `prompts/` | 1 |
| 10 | `keel/providers/`, `keel/partial_json.py` | 1 |
| 11 | `keel/answer.py`, `keel/reliability.py` | 2 |
| 12 | `keel/citations.py` | 1 |
| 13 | `keel/cache.py`, `keel/audit.py`, `keel/warm_cache.py` | 1 |
| 14 | `keel/api/`, `web/src/` | 1 |
| 15 | `keel/evaluation/` | 1.5 |
| | Total | 20 |

## 1. Extract and inventory

- Files: `keel/extractor.py` (`extract_zip`, `check_entry`),
  `keel/inventory.py` (`build_inventory`, `parse_filename`,
  `full_quarterly_coverage`).
- Corpus fact: the zip holds 246 filings and `manifest.json`, flat; 54
  tickers, 89 10-Ks and 157 10-Qs. The manifest claims 15 companies with
  full quarterly coverage; the files show 12 (E-D-25).
- Q: Why a custom extractor? A: control S-10: every entry is checked for
  traversal, links, and size before a byte is written.
- Q: Is the NVIDIA 10-K of February 2026 in the corpus? A: no (A-15 is
  false); the latest NVDA 10-K is fiscal 2025, so example 2 anchors on the
  fiscal 2026 Q3 10-Q.

## 2. Parse

- Files: `keel/parsers/form_10k_10q.py` (`TenKTenQParser.parse`,
  `parse_header`, `cut_xbrl`, `remove_artifacts`, `repair_boundaries`,
  `read_cover`), `keel/parsers/base.py` (`filing_id`, `chunk_id`,
  `fiscal_period`, `names_match`), `keel/parsers/corpus.py`
  (`finish_corpus`, `year_end_months`), `keel/tables.py` (`find_tables`).
- Corpus fact: 2 header shapes (7 and 9 keys); the fiscal period comes from
  the cover page, never the file name (D-21): 0 filename fallbacks, 5
  split-cell cover reads. GE is quarantined: the cover names General
  Electric Capital Corporation, the header General Electric Company.
- Q: Why read the period from the cover? A: the file name is a label
  someone typed; the cover is the filing. The cover equals the header
  period in all 192 files that have one, and the check would catch a
  mismatch (D-20).
- Q: What is the XBRL cut? A: the hidden facts block before the cover page,
  up to 284,260 characters (BAC); the cover marker is the cut, measured on
  the corpus (the chapter's prose window started early in 205 files).

## 3a. Sections: candidates and order

- File: `keel/sections.py` (`detect`, `classify`, `decide`, `select`).
- Corpus fact: the NVDA fiscal 2025 10-K has 8 `Item 1A` candidates: 1
  heading, 1 table-of-contents row, 6 cross-references.
- Q: Why an order constraint instead of a heading regex? A: a regex finds
  all 8 candidates; the items of a 10-K appear in a fixed order, so a
  weighted longest increasing run keeps the 1 real heading and drops the
  contents row and the references.
- Q: What happens when a 10-Q has no `PART II` match? A: the Part fallback
  assigns items by position after the table of contents; Part II items
  with a short body ("no material changes") join the previous section.

## 3b. Sections: relocation and coverage

- Files: `keel/sections.py` (`carve`, `relocate_10k_content`,
  `relocate_risk_factors`, `coverage_report`).
- Corpus fact: 87 of 88 10-Ks have all 3 core sections (98.9%); the miss
  is IBM, whose MD&A sits in an exhibit. Many 10-Ks put the MD&A or the
  statements after Item 15 (XOM, JPM, BAC, MS).
- Q: Why not exclude everything after the exhibits heading? A: 73% of an
  XOM 10-K sits there; relocation takes the first MD&A heading and the
  auditor's report as section starts.

## 4. Chunk

- File: `keel/chunker.py` (`chunk_filing`, `pack`, `prefix_line`,
  `simhash`, `HFTokenCounter`).
- Corpus fact: 63,688 chunks, 22,163 table chunks; sentence packing to 400
  tokens with a 480 maximum and 50 tokens of overlap; each table is its own
  chunk with the caption repeated.
- Q: Why 64,000 chunks, not the 35,000 to 40,000 of chapter 9? A: the
  corpus has 68 MB of clean text and 20,000 tables; each table is its own
  chunk, and merging prose across a table would break the character span
  of a chunk. The data won.
- Q: Why count tokens with the bge tokenizer? A: the chunk must fit what
  the embedding model reads (510 tokens); the model tokens of the answer
  model are a calibrated factor (1.91, stage 8).

## 5. Index and stores

- Files: `keel/indexer.py` (`build_index`, `verify`, `next_version`,
  `current_build`), `keel/stores/chunk_store.py`, `keel/stores/sqlite_fts.py`
  (`search`, `match_expression`), `keel/stores/numpy_dense.py` (`top_k`,
  `embed_query`).
- Corpus fact: a full build takes 1 h 44 min on the Intel CPU (10.6 chunks
  per second, 98% embedding); an incremental build re-embeds only changed
  filings (1.2.0: 43 filings, 45 min) and gives the same bytes.
- Q: SQLite does not scale. A: correct; it holds 64,000 chunks with no
  service. The store is 1 file behind 1 interface; chapter 17 gives the
  pgvector migration.
- Q: How do you know the index is intact? A: the manifest holds the sha256
  of both files; `/api/ready` refuses to serve on a mismatch (16.7).

## 6a. Understanding: entities

- File: `keel/understanding.py` (`Understander.analyze`, `Resolver.resolve`,
  `check_input`).
- Corpus fact: 54 companies with aliases; `JPMorgan` resolves to JPM, `GE`
  resolves to a not-indexed company (the quarantine).
- Q: Why no LLM for entity resolution? A: D-02: no model call before the
  answer. 6 ordered rules (alias, explicit ticker, guarded ticker, fuzzy at
  0.88) resolve all 30 golden questions as labeled in 1 to 3 ms.
- Q: What stops `cost` from resolving to Costco? A: lower-case aliases that
  are English words never match; short tickers need upper case and a
  position guard.

## 6b. Understanding: time and type

- Files: `keel/understanding.py` (`parse_time_scope`, `company_window`,
  `classify`, `topics`, `out_of_scope_parts`).
- Corpus fact: 17 companies have a non-December fiscal year; NVIDIA's ends
  in late January, so "the last two years" is a window of 8 NVDA filings.
- Q: How do you handle fiscal years? A: a window per company on
  `period_end_date`, from the nominal month of the cover period.
- Q: What is out of scope? A: unknown companies, prices, advice, years
  after the corpus; the response costs 0 model requests (G-22 to G-25).

## 7a. Retrieval

- File: `keel/retriever.py` (`build_plan`, `Retriever.retrieve`, `fuse`,
  `weigh`, `collapse`, `cap_companies`, `rerank_share`).
- Corpus fact: example 1 has 3 sub-queries (1 per company), 513
  candidates, 64 collapsed as near-duplicates by SimHash.
- Q: Why hybrid? A: the ablation on index 1.2.0: hybrid R@25 0.74 against
  0.69 lexical and 0.67 dense, and 0.68 for hybrid without the reranker.
- Q: The reranker takes 5 s. A: yes, 80 pairs on the Intel CPU (retrieval
  p50 6.2 s against 0.1 s without it); it buys 6 points of recall.
  `reranker.enabled: false` turns it off.

## 7b. Context budget

- File: `keel/context.py` (`build_context`, `Budget`, `estimate_tokens`,
  `truncate_table`, `render_chunk`, `Calibration`).
- Corpus fact: 48 chunks and about 32,000 model tokens per context; the
  character estimate was 54% low until the calibration factor 1.91.
- Q: A character count divided by 4 is sloppy. A: agreed, so the estimate
  is the bge count times 1.91, measured with 1 count call over 200 chunks;
  it is within 2% to 10% of the provider count.
- Q: How are companies kept fair? A: a round-robin quota fill per company,
  unused quota moved by rank.

## 8. Company facts

- File: `keel/edgar.py` (`EdgarClient`, `check_url`, `facts_lines`,
  `collect_facts`).
- Corpus fact: NVIDIA's fiscal 2025 revenue is 130,497 USD millions in the
  company facts, from the fiscal 2026 10-K, which is not in the corpus.
- Q: Is this a second LLM call or an agent? A: no; a cached JSON read
  before the call, like the index (D-01). `keel warm-cache` pre-fetches the
  56 files, so the demo makes 0 SEC requests.
- Q: SEC fair access? A: the `User-Agent` with name and email, 0.2 s between
  requests, a disk cache, and an allow list of 2 hosts (S-11).

## 9. Prompt

- Files: `keel/prompt.py` (`PromptFiles.load`, `build_bundle`,
  `guard_untrusted` in `context.py`), `prompts/answer_*_v1.4.0.*`.
- Corpus fact: the cached prefix is 2,792 tokens; the context is wrapped as
  untrusted data.
- Q: How do you version prompts? A: 3 files per version with a sha256
  hash; `docs/PROMPT_LOG.md` holds each change with its measured evidence.
- Q: Why structured output, not a forced tool call? A: Sonnet 5.5 rejects a
  forced tool choice with HTTP 400; structured output is D-13's first
  preference and cannot end without an answer.

## 10. Providers

- Files: `keel/providers/anthropic.py` (`AnthropicProvider.request`,
  `classify`), `keel/providers/mock.py` (`MockProvider`, the faults),
  `keel/partial_json.py` (`AnswerStream.feed`).
- Q: How is "1 call" proven? A: the provider counts requests;
  `test_single_request` and the audit field `model_requests` show it.
- Q: Why no temperature? A: the 5.5 models reject the parameter (D-12
  note); thinking is set to the lowest setting.

## 11. The pipeline and reliability

- Files: `keel/answer.py` (`Answerer.ask`, `_pipeline`, `_call`,
  `_attempts`, `_finish`), `keel/reliability.py` (`CircuitBreaker`,
  `BudgetGuard`, `halve_context`, `check_index`).
- Q: Can a question make more than 1 request? A: only before any content:
  up to 3 to Sonnet and 3 to the Haiku fallback (6 at most), and the trace
  drawer says `model requests: 2 (1 failed before content)`. Never after
  content (D-04).
- Q: What if both models are down? A: degraded mode: the retrieved chunks
  with SEC links and a Retry button; offline mode serves the answer cache.

## 12. Citations

- File: `keel/citations.py` (`validate`, `resolve_fact`, `quote_mismatch`,
  `period_mismatches`).
- Q: How do you stop hallucination? A: it is made visible: every citation
  must name a chunk or fact ID in this context, quotes are checked against
  the chunk, and a finding with no valid citation is `unverified`.
- Q: What is drift? A: a cited ID outside the context; it is removed and
  counted in the audit record.

## 13. Cache, audit, warm cache

- Files: `keel/cache.py` (`cache_key`, `AnswerCache`), `keel/audit.py`,
  `keel/warm_cache.py` (`prefetch_facts`, `demo_questions`, `warm_answers`).
- Q: When is the cache used? A: only offline, after a provider failure
  before content, or on a spent budget; the key holds the index, prompt,
  and model versions, so a stale entry never hits.
- Q: What is in the audit line? A: the request, the retrieval trace, the
  tokens, the cost, the flags; never the prompt or a key (S-07).

## 14. API and front-end

- Files: `keel/api/routes.py`, `keel/api/sse.py`, `keel/api/auth.py`,
  `web/src/state.ts` (the 11 states, 1 reducer),
  `web/src/components/TraceDrawer.tsx`.
- Q: Why fetch and not EventSource? A: the bearer token needs a header.
- Q: How is model text rendered safely? A: JSX text nodes; only the answer
  markdown goes through DOMPurify with a fixed allow list.

## 15. Evaluation

- Files: `keel/evaluation/runner.py` (`evaluate`, `stale_labels`),
  `metrics.py`, `judge.py`, `gates.py`, `eval/golden.yaml`, `eval/labels/`.
- Q: How do you know retrieval is good? A: recall at 25 on graded chunk
  labels and section labels for 23 questions, with the ablation; see
  `docs/PERFORMANCE_MEMO.md` for the numbers and the decision rule.
- Q: Who judges the judge? A: a different model (Opus 5.5, D-35) with the
  filing line of each chunk; the human rubric of 18.5 is not yet scored.
