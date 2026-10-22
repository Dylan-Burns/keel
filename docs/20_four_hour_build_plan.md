## 20. Four-hour build plan

The build reaches a complete demo with tests and a first eval run in 4 hours for 1 engineer with an AI coding assistant (A-04). The embedding build runs in the background from minute 75. The scope cut order at the end tells the engineer what to drop first when a slot overruns. Everything below the ship line is production hardening.

NOTE: The minute blocks in this chapter show the scope that fits the 4-hour timebox of the brief. They are not build estimates. The engineer works through the sequence in chapter 28 as fast as the done-when evidence permits, and never paces the work by these blocks.

### 20.1 Schedule

| Slot | Minutes | Work | Done when |
| --- | --- | --- | --- |
| 1 | 0 to 15 | Create the repo from the layout in chapter 17 with `pyproject.toml`, `uv.lock`, `Makefile`, `config/keel.yaml`, and `.env.example`. Write `keel inventory`, run it on the extracted corpus, and compare the counts with the corpus facts. | The inventory report shows 246 files, 54 tickers, 89 10-Ks, and 157 10-Qs. |
| 2 | 15 to 45 | Write the parser: the header, the separator, the normalization, and the XBRL cut. Add the artifact rules, the sentence rules, the cover page math, and the 11 checks. Write 8 parser tests from real snippets. | `keel parse` runs on all files, quarantines the GE file, and the 8 tests pass. |
| 3 | 45 to 70 | Write the section detector with the classification features, the order constraint, and the taxonomy map. Test on the NVDA fiscal 2025 10-K and 1 AAPL 10-Q. | 95% or more of 10-Ks have the 3 core sections in the build report. |
| 4 | 70 to 90 | Write the table rebuild and the chunker. Write the SQLite schema and the FTS5 build. Start the embedding build in the background. | `keel index --lexical-only` completes and the embedding process runs. |
| 5 | 90 to 115 | Write question understanding: the company, group, and synonym dictionaries, and the time scope parser. Add the type rules and the input checks. Write 12 unit tests. | The 3 example questions resolve to the expected tickers, scopes, and types. |
| 6 | 115 to 140 | Write the retriever: the lexical query, the dense query, the fusion, and the weights. Add the quotas, the SimHash collapse, and the context budget. Test with lexical results first, then with the dense index when the embeddings finish. | The 3 example questions give a context under 32,000 tokens with the expected company mix. |
| 7 | 140 to 165 | Write the provider adapter with the stream, the schema, prompt caching, the retries, and the mock. Write prompt 1.0.0 and the citation validator. Write `keel ask`. | `keel ask` answers example question 1 with valid citations from the live provider. |
| 8 | 165 to 190 | Write the FastAPI app: `/api/ask` with SSE, the read endpoints, the token check, the rate limit, and the audit log. Write the front-end page with the states empty, loading, streaming, complete, partial coverage, out of scope, and provider down. | The browser shows a streamed answer with citation chips and the right panel. |
| 9 | 190 to 215 | Write the eval harness with the golden set, the section-level labels, the retrieval metrics, and the judge. Run the retrieval metrics and the 3 example questions through the judge. Record the results in the prompt log. | `eval/report.md` exists with recall at 25 and citation precision. |
| 10 | 215 to 235 | Reliability: the breaker, the fallback model, the degraded mode, the index checksum check, and `keel warm-cache` for the 3 example questions. Write `docker-compose.yml`, the `Dockerfile`, and the CI workflow. | The offline drill passes with `KEEL_OFFLINE=1`, and `docker compose up` starts the service. |
| 11 | 235 to 250 | Write the README, the prompt log, the eval notes, and the runbook from the docs in this plan. Run `make test`. | `pytest`, `ruff`, and `mypy` pass with 40 or more tests. |
| 12 | 250 to 260 | Reserved. Fix what broke, run the pre-flight checklist, and record the demo video. | The pre-flight checklist in chapter 21 is complete. |

NOTE: Slot 12 shares its minutes with the overrun of any earlier slot. If no slot overruns, slot 12 starts at minute 250 and ends at minute 260.

### 20.2 Scope cut order

Cut from the top of this list first when a slot overruns.

1. The reranker. Keep the flag off and note the cut in the README.
2. The ablations. Keep the metrics from 1 configuration.
3. The Docker image. Keep `make demo`.
4. The chunk-level labels. Keep the section-level labels.
5. The rate limited and stale index states in the UI. Keep the server behavior.
6. The SimHash collapse. Keep the latest-filing weight.
7. The dense index. Keep lexical retrieval with the section weights and quotas, and state the cut in the demo.
8. The judge pass. Keep the retrieval metrics and the human check of the 3 example questions.

Never cut these items: the parser checks and the quarantine, the fiscal math, the single request with the mock counter, and the citation validation. Never cut the coverage statement, the streamed front-end, the audit log, or the answer cache for the 3 example questions.

### 20.3 The ship line

| Ships inside the timebox | Production hardening after the timebox |
| --- | --- |
| The parser with the 11 checks and the quarantine list | Playwright browser tests, OpenTelemetry traces, and the chunk size ablation |
| The section detector and the canonical taxonomy | Postgres with pgvector, the container hardening in S-09, and SSRF controls in S-11 |
| The hybrid retriever with quotas, collapse, and the context budget | OpenID Connect, the multi-tenant isolation test, and the legal review of the data license |
| 1 streamed request with a schema, citations, and the validator | Index-time summaries if the panel permits them (P-03), and structured XBRL financial data |
| The front-end with 7 of the 11 states | The 4 other states with full designs, and the feedback endpoint |
| The eval harness with the golden set and section-level labels | Chunk-level labels for 10 questions, 2 human raters, and the nightly eval schedule |
| The breaker, the fallback model, the degraded mode, and the answer cache | A daily alert for the provider budget, log retention, and a status page |
| The audit log and the index checksums | Audit log retention and export to the firm's log system |
