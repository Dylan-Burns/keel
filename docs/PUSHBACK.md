# Pushback drills

The drills of chapter 25.5 (W-05). The rule for every challenge: agree with
what is true, ask which standard the panel has in mind, then show the config
flag, the number, or the roadmap line. Never defend a choice the code does
not defend. Every number below is measured: the eval run on index 1.2.0
(`eval/report.md`, run eval-20261022T064805Z), the build entries of
`docs/BUILD_REPORT.md`, and `docs/PROMPT_LOG.md`.

## The chapter 25.5 challenges

| Challenge | Short answer | Show |
| --- | --- | --- |
| Recall of 0.85 sounds low. | It is low, and it misses its own gate: recall at 25 is 0.74 against a gate of 0.85. What is your threshold? Comparisons score 0.93; long trend sections and single-company section questions pull the mean down (single company 0.54, trend 0.59, sector 0.64). The ablation shows each part paying: hybrid 0.74, lexical 0.69, dense 0.67, hybrid without the reranker 0.68. Next: the reranker threshold and the section weights per question type. | `eval/report.md` per type and ablation tables; `/api/eval` |
| SQLite does not scale. | Correct. It holds 63,688 chunks in 1 file with no service at a venue, and `vectors.npy` is a 98 MB memory map. The store sits behind 1 interface (`keel/stores/`); chapter 17 gives the pgvector migration with a script. | `keel/stores/chunk_store.py`, chapter 17 |
| A character count divided by 4 is sloppy. | Agreed, and the code does not do it. `keel calibrate` sent 1 count call over 200 chunks: the bge count times 1.15 was 54% low, so the factor is 1.91, and the whole-request estimate is within 2% to 10% of the provider count. The facts block is estimated at its own measured 1.8 characters per token. | `docs/BUILD_REPORT.md` stage 8, `retrieval.calibration_factor` |
| The value numbers are estimates, not measurements. | Yes. Every number carries an assumption ID with a low, base, and high case; the low case does not pay back on hours alone. The pilot measures the real numbers from the audit log. | Table 2.4.1 and 2.4.2 |
| Why is this better than a filing pasted into a chat window? | Coverage of 245 filings, citations that the server validates against the context, a coverage statement that names what is absent, about $0.09 per question, and an audit line per answer. A paste gives none of these. | The trace drawer, `logs/audit.jsonl` |
| Is 1 call a toy constraint? | The brief requires it, and it forced every step before the call to be testable code. The trace drawer prints `model requests: 1`. Chapter 22 names the tasks that need agents and keeps them separate. | `test_single_request`, the drawer |
| What happens when the model is wrong? | The validator removes a citation outside the context and counts it as drift; a finding with no valid citation shows `unverified`; faithfulness is 0.87 against a gate of 0.90 (it fails, and the memo says why). Numeric answers: 9 of 9 of the gold values within 0.5%. | `docs/PERFORMANCE_MEMO.md`, the drift count |
| Can we use this tomorrow? | For narrative questions on public filings, as a pilot beside the current tools (chapter 27). Not for private data: chapter 15 lists the production controls the code does not hold yet. | `docs/PERFORMANCE_MEMO.md` decision rule |

## The build deviations

Each is recorded in `docs/BUILD_REPORT.md` and, where it touches a decision,
in `docs/04_assumptions_and_decisions_log.md`.

| Challenge | Short answer |
| --- | --- |
| The plan said a forced tool call. Why structured output? | Sonnet 5.5 rejects `tool_choice` `tool` and `any` with HTTP 400 (stage 7, checked before any generation). Stage 7 shipped a strict tool with `tool_choice: auto`; stage 8 measured structured output (`output_config.format`) against it on the 3 examples: both schema-valid, 14% fewer output tokens, 5.5% lower cost, `direct_answer` still streams first. Structured output is D-13's first preference and cannot end without an answer; `llm.output_mode: tool` stays selectable. |
| Why no temperature 0? | The 5.5 models reject `temperature`, and SDK 2.0 has no such parameter (D-12 note). Determinism comes from the pinned model, the byte-stable prompt, and the deterministic retrieval; thinking is at the lowest setting. The eval measures the answers, not the sampler. |
| Why plain model ids, not dated snapshots? | The models list has no dated id for the 5.5 models; `claude-sonnet-5-5` is the pinned snapshot (stage 0, note on D-11). The cache key and the audit line carry the id, so a change is visible. |
| Why 64,000 chunks, not 35,000 to 40,000? | The data won. The corpus has 68 MB of clean text, not 59, and each of about 20,000 tables is its own chunk with its caption (35% of the chunks). Merging prose across a table would break the character span of a chunk. Index 1.2.0 holds 63,688 chunks after the units lines rejoined their tables. |
| The reranker takes 5 seconds. | On this Intel CPU, 80 pairs of near 512-token chunks take about 5 s idle (D-10 reranks the top 80 per question, split over the sub-queries). It is the price of recall: without it R@25 drops from 0.74 to 0.68. `reranker.enabled: false` turns it off; a GPU or a smaller top-N is the production fix. The first token came after 8.1 s to 16.4 s in the live answers of stages 7, 12, and 13 (`docs/BUILD_REPORT.md`), above the 6 s SLO, mostly for this reason. |
| Who judges the answers? | A different model, Opus 5.5 (D-35), with structured output, 1 request per answer at about $0.08, after the answer and never in the request path. Since judge prompt 1.2.0 it reads each cited chunk exactly as the answer model read it, with the filing attributes, and a statement about Keel itself (no investment advice) leaves the score instead of counting as a filing claim. A fact citation is judged against its fact line. The human rubric of 18.5 is not scored yet; that is the honest gap. |
| You said 1 request. The code allows 6. | 1 per answer. Up to 3 requests to Sonnet and 3 to the Haiku fallback, only before any content arrives, with byte-identical prompts (D-04 per model, chapter 16.4). Never after content. The drawer then reads `model requests: 2 (1 failed before content)`, so the claim stays measured. `max_retries: 0` turns retries and the fallback off. In the eval run every answer made exactly 1 (24 requests for 24 answers). |
| The numbers in the facts come from a filing that is not in the corpus. | True for NVIDIA: the company facts file carries values from the fiscal 2026 10-K, filed after the corpus. The fact ID and the EDGAR filing link name the source; the answer and the gaps say so. This is the roadmap item built early, and the audit line records the source. |
| What if the panel counts the embedding model as an LLM call? | `reranker.enabled: false` turns the cross-encoder off. The dense index has no config flag yet (a gap against chapter 21.5): the retriever runs lexical only, with section weights and quotas, when the embedding model is absent (E-F-11), and the eval runs that variant. The ablation gives the price: lexical without the reranker R@25 0.69, 5 points under hybrid with the reranker, at 76 ms instead of 6.2 s. |
| The demo answers come from a cache. | Only with `KEEL_OFFLINE=1`, after a provider failure before content, or on a spent budget; the page asks with `use_cache: false`, so the live path is the default (chapter 16.12 step 3; the API default of chapter 14.2 stays `true` for other clients). The cache key holds the index, prompt, and model versions, and the trace drawer shows `from_cache`. `keel warm-cache` filled it through the same pipeline on index 1.2.0. |
