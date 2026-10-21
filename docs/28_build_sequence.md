## 28. Build sequence

Chapter 20 keeps the 4-hour timebox for the core, which is what the brief asks for. This chapter is the order of work for everything else, with no time estimates. Each stage names the chapters to read and the evidence that ends the stage. Stages 1 to 11 build the full core of chapters 7 to 18. Stages 12 to 16 build chapters 25 and 26. Stages 17 to 22 build chapter 27. Work through the stages in order, as fast as the evidence permits, with 1 PR per stage. In attended mode, stop after each PR for a review. In unattended mode (chapter 29.11), merge each PR when CI is green and continue with the next stage. The engineer reviews the merged PRs afterwards.

| Stage | Work | Chapters | Done when |
| --- | --- | --- | --- |
| 0 | Repository foundation: the starter files of chapter 29, the GitHub repository with branch protection, environments, the corpus release, and the fine-grained token for release-please. Also the pre-commit hooks, the front-end placeholder (1 page that renders the name Keel). The placeholder passes lint, types, unit tests, build, and the smoke e2e. Then the vendored `pylintrc`, the first PR | 29 | The CI workflow is green on the empty package and the front-end placeholder, `main` is protected, and the first PR merged with a rebase |
| 1 | Repo skeleton, config, `keel inventory` with the zip safety checks | 15, 17, 23 | The counts match the corpus facts, and the build report records assumption A-15 |
| 2 | The parser with all 11 checks, the table rebuild, and the parser tests from real snippets | 7 | All 246 files parse, GE is quarantined, 18 tests pass |
| 3 | The section detector and the chunker with the SimHash | 8, 9 | 95% of 10-Ks have the 3 core sections, and the chunk count is in the 35,000 to 40,000 range |
| 4 | The index build with the manifest and the embeddings | 9 | `keel index` completes, and `vectors.npy` matches the chunk count |
| 5 | Question understanding with the fuzzy match and the group lists | 10 | The 3 example questions resolve as planned |
| 6 | The retriever with the reranker, the quotas, the collapse, and the budget | 11 | Each example question gives the planned context under 32,000 tokens |
| 7 | The provider adapter, prompt 1.0.0, the schema, the stream, the citation validator, the answer cache, the audit log, the mock provider with the request counter | 12, 16, 17 | `keel ask` answers example question 1 live with valid citations, and `test_single_request` passes |
| 8 | Prompt iterations from the 3 answers, recorded in the prompt log | 13 | The NVDA answer carries fiscal labels, and the pharma answer names the 1-10-K limit |
| 9 | The API and the front-end with all 11 states and the Motion animations of 14.8 | 14 | A streamed answer shows in the browser with citation chips. The pipeline steps light up in order. Reduced motion turns the animations off. The Playwright specs of 14.9 pass in CI |
| 10 | The eval harness with the 28 golden questions, the section-level labels, and the lexical versus dense versus hybrid ablation | 18 | `eval/report.md` exists with the gates |
| 11 | The reliability set and the timebox security controls | 15, 16 | The offline drill passes with the network off |
| 12 | W-01, W-02, and W-04: the trace drawer, the eval page, the adversarial preset | 25 | The drawer springs up and shows `model requests: 1` on a live answer |
| 13 | The ticker map, the company facts fetch with the cache, the concept map, the facts block, the fact citations, 3 tests | 26.1 | The NVIDIA revenue question answers with exact reported values and units |
| 14 | `keel add TICKER` end to end, 3 tests | 26.2 | 2 companies outside the corpus answer questions |
| 15 | W-03 and W-05: the performance memo, the pushback drills, the code walk notes, the pre-fetch of the 54 company facts files, and `keel warm-cache` | 25, 16 | Everything the demo touches is on disk |
| 16 | The cold-read rehearsal, the full demo against a timer, the failure drills, the recording | 21, 25 | The rehearsal fits 25 minutes with 5 minutes to spare |
| 17 | Users and tokens, the audit record per user, the history page, shareable links | 27 | 2 users see their own history, and a link opens a stored answer |
| 18 | Comp sets, question templates, feedback | 27 | A question that names a comp set resolves it, and a thumbs vote lands in the feedback table |
| 19 | Memo export, Markdown then DOCX | 27 | An exported memo opens in Word with numbered sources and SEC links |
| 20 | The watch list, `keel refresh`, the timer, the banner | 26.3, 27 | A new filing for a watched ticker appears after the next refresh |
| 21 | Deploy with the container and the infrastructure of chapter 29, the backup and the restore, the data use page | 27, 29 | A colleague uses Keel from a phone over HTTPS |
| 22 | The start guide, the metrics script, a second rehearsal with the product features | 27 | The pilot plan of chapter 27.6 is ready for 5 users |

Cut order when scope must shrink: first `keel add` and the watch list (stages 14 and 20), which leaves the facts block as the on-demand story. Second, the DOCX export (keep Markdown). Third, the reranker. Fourth, the dense index. Never cut the trace drawer, the performance memo, or the rehearsal.

NOTE: Chapters 25 to 28 came after the conformance note in chapter 24. The same searches for modal verbs, dashes, semicolons, and -ing forms ran on these chapters, and the new technical names appear in table 27.7. Chapters 14.8, 14.9, and 29.9 to 29.11 came later under the same rules. Their technical names are Motion, Tailwind CSS, Vite, gts, Vitest, Playwright, Railway, and Claude Code.
