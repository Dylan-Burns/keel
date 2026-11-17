# Decisions and assumptions

This log records the 41 design decisions (D-01 to D-41) and the 15
assumptions (A-01 to A-15) behind Keel. Each decision names the
alternatives, the reason for the choice, the cost to reverse it, and the
condition that would reopen it. Code comments, tests, and the other docs
cite these IDs, so an ID never changes and a retired entry keeps its row.

Where the implementation departed from the original decision, the
decision row states what was decided and the [notes from
implementation](#notes-from-implementation) state what the code does and
why. When the specification and the data disagreed, the data won.

Related documents: [ARCHITECTURE.md](ARCHITECTURE.md) for how the pieces
fit, [SECURITY.md](SECURITY.md) for the S-xx controls, and
[EDGE_CASES.md](EDGE_CASES.md) for the E-xx cases.

## Decisions

| ID | Decision | Alternatives considered | Rationale | Reversibility | Revisit when |
| --- | --- | --- | --- | --- | --- |
| D-01 | The answer call is the only LLM generation. Question embedding, lexical search, metadata filters, a local cross-encoder reranker, and code-based citation validation do not count as the answer call. | Count every model call, even embeddings. Permit a second LLM call for verification. | The answer must come from 1 LLM call; the pipeline around it is open. An embedding model and a cross-encoder do not generate text. | High. A config flag turns the reranker off, and lexical-only retrieval works without embeddings. | An embedding call must count as an LLM call. Then Keel runs with lexical retrieval only. |
| D-02 | Keel does not use an LLM at index time. | LLM summaries per section at index time. LLM-written chunk titles. | Not needed, adds cost, and blurs the one-request rule. | High. A later index version can add summaries. | Index-time summaries become acceptable. |
| D-03 | Every step before the answer call is disclosed: in the architecture doc, in the audit record, and in the trace drawer of the front-end. | Describe only the single call. | Full disclosure removes any doubt about what counts as the one request. | Not applicable. | None. |
| D-04 | A failed request that returns no answer does not count as the answer call. The adapter retries up to 2 times on transport errors, rate limits, and 5xx errors, and never after the stream has started to deliver content. | No retries. Retry after partial output. | The answer still comes from 1 completed request. A partial answer followed by a retry is 2 answers, so the design closes that path. | High. Set `max_retries` to 0. | Any second request counts as a violation. Then set `max_retries` to 0 and show the error. See the note on the fallback budget. |
| D-05 | Python 3.12 with FastAPI and uvicorn. | Flask, Django, Node with Express, Go with chi or Gin. | Native async streams, pydantic schemas, and type hints. The model call takes more than 95% of the latency per question, so a faster runtime gains little. The embedding model and the reranker run in PyTorch, which Go cannot run without cgo bindings or a sidecar service. Go can serve a high-volume ingestion worker later. | Low. The whole service. | The deployment target requires another language. |
| D-06 | The lexical index is SQLite FTS5 with BM25. | In-memory rank\_bm25, Elasticsearch, Postgres full-text search. | No new service, persistent on disk, and metadata joins in SQL. | Medium. The retriever interface hides the store. | An Elasticsearch cluster already exists. |
| D-07 | The embedding model is BAAI/bge-small-en-v1.5 (384 dimensions, 512-token input), pinned to a revision hash. | bge-base, nomic-embed-text-v1.5, all-MiniLM-L6-v2, a hosted embedding API. | Fast on a CPU with good English retrieval quality. A hosted API adds a dependency and a cost. | Medium. A rebuild of the dense index. | A GPU is available. Then use bge-base or bge-large. |
| D-08 | The dense index is a flat NumPy matrix of float32 unit vectors with cosine similarity over masked candidates. Metadata lives in SQLite. | FAISS, Chroma, LanceDB, Qdrant, pgvector now. | About 64,000 vectors. A brute-force scan over the filtered rows takes milliseconds and needs no service. | High. The store interface and the pgvector migration path. | A Postgres standard applies. Then migrate to pgvector. |
| D-09 | Fusion is reciprocal rank fusion with k = 60 and equal weights. | Weighted score sum with min-max normalization. Lexical only. Dense only. | Robust to different score scales with 1 parameter. The ablation in the eval measures the gain. | High. Config. | None. |
| D-10 | The reranker is cross-encoder/ms-marco-MiniLM-L-6-v2 over at most 80 fused candidates per question, on by default. | bge-reranker-base. No reranker. An LLM reranker. | Better precision on boilerplate-heavy sections. An LLM reranker breaks D-01. | High. Config flag. | A reranker is not permitted. Then turn the flag off. |
| D-11 | The answer model is Claude Sonnet 5.5, pinned. The fallback model is Claude Haiku 5.5, also pinned. | Opus 5.5 for quality. Haiku 5.5 only for cost. Another provider. | Long-context synthesis quality at about $0.09 per question. | High. Adapter and config. | Another provider is preferred. Then write a second adapter. |
| D-12 | Temperature 0 and an output limit of 4,000 tokens. | The default temperature. | Stable output and fewer invented details. | High. Config. | None. See the note: the 5.5 models reject `temperature`, and the limit is 8,000. |
| D-13 | The answer comes as structured JSON through a JSON schema. The adapter requests the provider's structured output. If the pinned model lacks that feature, the adapter uses a tool call with the same schema. | Free text with a JSON block at the end. A two-part output with prose and JSON. | The server validates the schema, and a two-part output duplicates content and doubles the output cost. | High. Adapter. | None. |
| D-14 | The service streams the answer with server-sent events (SSE). | WebSocket. A poll loop. | One direction, simple, and works through proxies and CloudFront. | High. | None. |
| D-15 | Prompt caching applies to the static system block. | No prompt caching. | A cache hit cuts the cost of the static prefix by about 90%. The gain grows with the question rate. | High. | None. |
| D-16 | A chunk targets 400 tokens, with a maximum of 480 tokens and an overlap of 50 tokens. | 256 tokens. 800 tokens. Sentence-level chunks. | Fits the 512-token input of the embedding model and keeps 1 risk factor per chunk in most cases. | Medium. A rebuild. | None. |
| D-17 | A chunk never crosses a canonical section boundary, and a table row never separates from its carried column labels and units. | Fixed-size chunks across sections. | Section filters and citations stay exact, and numbers keep their units. | Medium. A rebuild. | None. |
| D-18 | The context budget is 32,000 tokens and 48 chunks per question. | 100,000 tokens. | Cost, and a smaller context keeps the model on the most relevant chunks. | High. Config. | Cost stops mattering. Then raise the budget to 64,000 tokens. |
| D-19 | Keel indexes all 245 valid filings, including 37 files dated 2022 and 27 files dated 2026. | Drop files dated outside 2023 to 2025. | Fiscal 2023 10-Qs of AAPL and others have 2022 file dates, and the 2026 10-Ks carry fiscal 2025. The coverage statement shows the real dates. | High. A date filter in config. | The scope must be strictly calendar 2023 to 2025. Then set `corpus.date_filter`. |
| D-20 | Keel quarantines `GE_10K_2015-02-27_full.txt` and does not index it. | Relabel the file as GE Capital. Index the file as GE. | The body is the fiscal 2014 10-K of a different registrant (General Electric Capital). Relabeled data misleads a user who asks about GE. | High. An override file. | The file should be kept as GE Capital. Then add an entry to `config/overrides.yaml`. |
| D-21 | The fiscal year and the fiscal period come from the cover page date and the company's fiscal-year-end month, not from the file name. | Trust the file name period code. | The period code in the file name is the calendar quarter, not the fiscal quarter. | Low. Core parser rule. | None. |
| D-22 | The canonical section taxonomy has 8 sections plus `unknown`: business, risk\_factors, legal\_proceedings, mdna, market\_risk, financial\_statements, controls, other. | Keep the raw item labels. | Both forms map to 1 set of filters and 1 set of prompt rules. | Medium. | Finer sections are needed. Then add subsections. |
| D-23 | IDs are deterministic. The filing ID is ticker, form, and period end date. The chunk ID is filing ID, section, and sequence. The index stores a chunk hash. | Random UUIDs. | Repeat builds give the same IDs, so audit records, cached answers, and tests stay valid. | Low. | None. |
| D-24 | The front-end is a React application in TypeScript with Motion and Tailwind CSS, built by Vite into static files that FastAPI serves. | Vanilla JavaScript with no build step. Streamlit. | A typed component model, a product-grade UI, and a Vite build that CI runs in seconds. The built files ship inside the image, so the page loads no CDN. | Medium. | A different front-end standard applies. |
| D-25 | Docker Compose gives one-command setup, and `make demo` gives the native run. | A bare `pip install`. | Anyone can start the system on any machine. | High. | None. |
| D-26 | Authentication is a bearer token from an environment variable. Authorization hooks pass a Principal object with tenant and ticker filters into retrieval. | No authentication. OAuth now. | The service needs a lock from day 1, and private data later needs row filters from day 1. | High. | OpenID Connect replaces tokens. See the notes for named users and the public mode. |
| D-27 | The audit log is a JSON lines file on disk. | A SQLite table. An external log service. | Simple, append-only, and easy to export. | High. | None. |
| D-28 | No LLM-as-judge at question time. The judge runs only in the eval harness. | A judge after each answer. | A judge call is a second LLM call. | Not applicable. | None. |
| D-29 | The answer cache key is the hash of the normalized question, the index version, the prompt version, and the model. The cache is pre-warmed for the example questions and the golden set. | No cache. | An offline fallback and a cost saver for repeat questions. | High. | None. |
| D-30 | Near-duplicate chunks collapse at question time with a 64-bit SimHash computed at index time. | Index-time removal of duplicates. MinHash. | Boilerplate repeats across quarters. A question-time collapse keeps every filing available for period filters. | High. | None. |
| D-31 | When 2 chunks cover the same fiscal period, the chunk from the latest filing wins. | The original filing wins. | The latest filing carries restated figures. The prompt tells the model to name restatements. | High. | As-first-reported figures are preferred. |
| D-32 | Sector groups are hand-written in a YAML dictionary. | SIC codes from EDGAR. An LLM. | SIC codes are not in the corpus, and an LLM call breaks D-01. | High. | None. The admin company browser uses SIC codes from EDGAR for a different purpose. |
| D-33 | A relative time scope such as "last two years" uses the latest period end date in the corpus for each company as its anchor, not the wall clock. | Anchor to today's date. | The original corpus ends in February 2026. A wall-clock anchor months later cuts off the newest data for no gain. | High. | None. |
| D-34 | Tests use pytest, ruff, and mypy in strict mode on the package, with GitHub Actions. | unittest. No type checks. | The standard Python toolchain with strict types. | High. | None. |
| D-35 | The eval judge uses a pinned model that differs from the answer model where possible. | The same model as judge. | A different judge reduces shared blind spots. | High. | None. |
| D-36 | Diagrams are Mermaid blocks in the docs. | A diagram tool. | Mermaid renders in GitHub and needs no tool. | High. | None. |
| D-37 | On Intel macOS only, `pyproject.toml` pins torch 2.2.2, numpy 1.x, transformers 4.47, and sentence-transformers 3.4 through environment markers. Linux (CI, the image, the host) keeps torch 2.4 or later on the CPU index and numpy 2. Code uses only the APIs that both sentence-transformers lines share. | Build every Python step in a Linux container on the laptop. Drop the dense model on the laptop. | PyTorch publishes no Intel macOS wheel after 2.2.2, and the development laptop is an Intel Mac. One `uv.lock` covers both platforms. | High. Remove the markers on Apple silicon or Linux. | None. |
| D-38 | The outbound allow list of control S-11 for `keel bootstrap` holds the host of `corpus.url`, the host of `index.url`, and the GitHub release asset hosts (`github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com`), next to the 2 SEC hosts. Downloads are https only, port 443, with no credentials in the URL; every resolved address must be public; redirects are followed by hand (at most 5) and each target is checked again. Logs and errors name only the host, because a signed URL carries a secret in its query. With `GH_TOKEN` set and `gh` installed, `gh release download corpus-v1` runs first. | Download from any host. Add the host of a hosting bucket by name. | The host of a configured URL goes on the list; a GitHub release URL answers with a redirect to the asset hosts. No other host is added. | High. | A new download source is configured. |
| D-39 | The service runs on AWS: 1 EC2 `t3.large` (2 vCPU, 8 GB) in `us-east-2` from `infra/terraform/`, with Caddy for HTTPS on `<elastic-ip>.sslip.io`, an S3 bucket for the backups, and a dedicated `keel` IAM profile. Railway stays in the repository as the alternative. | Railway. AWS `t3.medium` (4 GB). Fly.io, Render, or a plain VPS. | Railway had a security incident that invalidated every API and project token, then a platform outage that disabled builds for Hobby workspaces on the day of the deploy. The AWS path was already written and checked in CI. 8 GB lets the host build the index itself (about 6.6 GB) instead of only restoring the `index-v1` archive, for about 60 USD a month, and the S3 bucket gives the nightly backup a home. | High. `railway.toml` and `deploy.yml` stay in the repository; `terraform destroy` removes the AWS host. | None. |
| D-40 | The public address is `https://keeldd.com` (and `www.keeldd.com`): a Route 53 hosted zone from `infra/terraform/dns.tf`, an ACM certificate in `us-east-1`, and aliases on the CloudFront distribution of D-39. The origin stays Caddy under the `sslip.io` name. The domain sends no mail (null MX, SPF `-all`, DMARC `p=reject`). | Keep the free `*.cloudfront.net` name. Keep the registrar's DNS and add a CNAME there (no CNAME at the apex, and the records would sit outside Terraform). Point the domain straight at the host and let Caddy hold the certificate (no CloudFront). | A name people can read and type. Route 53 keeps every record in Terraform, so the nightly plan catches drift, and its alias records serve the apex. ACM renews the certificate on its own. | High. An empty `domain_name` removes the zone, the certificate, and the aliases; the `*.cloudfront.net` name keeps working throughout. | None. |
| D-41 | The service runs on Railway, replacing the AWS host of D-39 and the CloudFront address of D-40. 1 service builds the `Dockerfile`, mounts 1 volume at `/data`, starts as root only to hand `/data` to the `keel` user (`RAILWAY_RUN_UID=0`, then `setpriv`), runs `keel serve --bootstrap` as that non-root user in public mode (the service settings live in `infra/README.md`, because Railway retires `railway.toml` on 2026-12-01), and restores the `index-v1` archive on the first start instead of building the index. `https://www.keeldd.com` is a Railway custom domain with a Railway certificate; Squarespace keeps the DNS and forwards the apex `keeldd.com` to `www` with a 301. | Rebuild the AWS stack from `infra/terraform/`. Fly.io or Render. A static page with no API. | The AWS host was torn down on 2026-10-30 to stop its monthly bill, which left `www` pointing at a deleted CloudFront distribution. Railway needs no Terraform, no Caddy, and no certificate work, and the prebuilt index keeps the memory below the 6.6 GB of a full build. | High. `infra/terraform/` and `deploy-aws.yml` stay in the repository; pointing the `www` CNAME back at a CloudFront distribution restores D-39 and D-40. | Railway cost or reliability falls short, or the nightly refresh and backup need systemd timers again. |

## Notes from implementation

These notes record where the code departs from the decision as first
written, with the measured reason.

- **D-39 and D-40, superseded by D-41.** The AWS host and the CloudFront
  address were torn down on 2026-10-30, and the site moved to Railway on
  2026-11-17. `railway.toml` and `deploy.yml` are no longer in the
  repository; `infra/terraform/`, the Caddyfile, the systemd units, and
  `deploy-aws.yml` remain as the AWS alternative.

- **D-04, fallback budget.** The fallback model has its own budget of 3
  requests, so a question can make up to 6 requests before any content
  (3 per model) and never one after content. `max_retries: 0` also turns
  the fallback off, so the reversal still means 1 request. A breaker
  failure is 1 failed request, not 1 failed question.
- **D-10, model id and rerank budget.** The Hugging Face Hub renamed the
  model to `cross-encoder/ms-marco-MiniLM-L6-v2` (the old id redirects);
  the config pins the new id at commit `233902d`. The 80 pairs are per
  question, split evenly over the sub-queries (26 each for 3 companies,
  10 each for 8 trend cells); pairs a sub-query cannot use move to the
  sub-queries with candidates left. Logits pass through a sigmoid so the
  retrieval weights multiply a positive score. Filing chunks run near the
  512-token limit, so 80 pairs took 5 to 6 seconds on the development
  laptop and 11.5 seconds on the t3.large host. `reranker.max_length`
  384, `reranker.threads` 0 (1 per vCPU), and `reranker.batch_size` 8 cut
  the host rerank to 6.8 seconds with recall at 25 down 0.001.
  `reranker.top_n` is capped at 80.
- **D-11, model ids.** The models list has no dated identifier for the 5.5
  models, so the pins are the plain ids `claude-sonnet-5-5` and
  `claude-haiku-5-5`.
- **D-12, temperature and output limit.** The 5.5 models reject
  `temperature` (`Extra inputs are not permitted`), so `llm.temperature`
  is null and the request sends none. The lowest thinking setting stands
  in: `between_tools` for Sonnet 5.5 and `disabled` for Haiku 5.5. The
  strict JSON answer runs at about 2.2 characters per token, and a
  3-company comparison hit 4,000 output tokens, so `max_output_tokens` is
  8,000. The longest answer in the full eval used 5,161 tokens.
- **D-13, output mode.** Sonnet 5.5 and Opus 5.5 reject a forced
  `tool_choice` with HTTP 400, so the first implementation used
  `tool_choice: auto` with a strict `answer` tool. Prompt 1.3.0 moved to
  the provider's structured output (`llm.output_mode: json_schema`, the
  schema in `output_config.format`). On the example questions both modes
  were schema-valid; structured output used 14% fewer output tokens, kept
  `direct_answer` streaming first, cannot end without the answer, and
  keeps a byte-stable cached prefix of 2,673 tokens. Strict mode rejects
  `maxItems`, so the schema drops it and the validator keeps the first 4
  next questions. The prompt version and `llm.output_mode` must match, or
  the service refuses to start.
- **D-26, named users and the public mode.** Named users live in
  `config/users.yaml` (gitignored): name, role (analyst, partner, admin),
  and the sha256 of a 256-bit token, managed with `keel users add` and
  `remove`. `KEEL_API_TOKEN` stays the admin user `legacy`. The Principal
  carries the user, and the audit record carries `user_name`. A shared
  link reads `GET /api/shared/{request_id}` for any token holder, while
  `GET /api/results` stays with the asker. With `auth.public` on, a
  request without a bearer token is a visitor who may send their own
  Anthropic key (see [SECURITY.md](SECURITY.md), S-18 to S-20).
- **D-29, when the cache is read.** The live path stays the default. The
  cache is read in offline mode, after a provider failure before content,
  when the caller asks (`keel ask --cached`), and for a visitor without a
  key. Mock, fallback, degraded, and out-of-scope answers are never
  written. A question that names a saved comp set neither reads nor
  writes the cache, because the key holds the question and not the
  tickers of the set, which a user can edit.
- **D-35, judge model.** The judge is `claude-opus-5-5`
  (`llm.judge_model`), 1 structured-output request per answer at effort
  `medium` (Opus 5.5 cannot turn thinking off), about 0.08 USD per answer.
  It reads each claim with the text of its cited chunks and their wrapper
  line.

## Assumptions

| ID | Assumption | Basis | Check and result |
| --- | --- | --- | --- |
| A-01 | Users type questions in English about companies in the corpus or near it. | The example questions. | Non-English questions get HTTP 400 (E-Q-12); unknown companies get an out-of-scope answer (E-Q-02). |
| A-02 | The service has network access to the provider. The offline mode covers a loss of access. | A hosted service. | `KEEL_OFFLINE=1` serves the answer cache and the degraded mode (E-F-09). |
| A-03 | The build machine has 8 CPU cores, 16 GB of RAM, and no GPU. The model downloads are about 150 MB. | The development laptop. | `keel doctor`. Result: the Intel i9 laptop (torch 2.2.2, 8 threads) embeds 10.6 chunks per second with bge-small at batch 32, not 30, so the full build of 64,727 chunks took 1 h 44 min (6,213 s), not about 27 minutes. An incremental build with no changed file takes 100 s. |
| A-04 | Retired. It concerned the build process, not the system. | Not applicable. | Not applicable. |
| A-05 | SEC EDGAR filings are public domain. The manifest `license` key confirms the terms. | The source is EDGAR. | Result: the key reads `Public domain (SEC filings are US government documents)`. |
| A-06 | The major pharmaceutical companies in the corpus are PFE, JNJ, MRK, LLY, and ABBV. | TMO sells instruments, and UNH is an insurer. | Edit `config/groups.yaml` to change the group. |
| A-07 | The major banks in the corpus are JPM, BAC, GS, and MS. | AXP, V, MA, and BLK are financial but not banks. BRK is a conglomerate. | Edit `config/groups.yaml` to change the group. |
| A-08 | The service runs months after the latest filing in the corpus, so the wall-clock date is not a useful anchor for relative time scopes. | The corpus ends in February 2026; the service went live in late 2026. | D-33 anchors on corpus dates; `keel doctor` warns on a wrong clock (E-F-12). |
| A-09 | The published facts about the corpus are correct. | Measured from the zip. | `keel inventory`. See [corpus facts as measured](#a-09-corpus-facts-as-measured). |
| A-10 | Model prices are as published on 2026-10-20. | `config/prices.yaml` with its check date. | Confirm on the provider price page when prices change. |
| A-11 | A typical user team has about 10 analysts and associates. | A mid-market investment team. | Sizes the rate limits and the daily budget; both are config. |
| A-12 | Terminal and vendor seats cost $10,000 to $25,000 per seat per year. | Assumed list prices. | Context for the cost per answer; not used by the code. |
| A-13 | A local cross-encoder reranker is not an LLM call under the one-request rule. | D-01: it scores pairs and generates no text. | The reranker can be turned off by config if the rule is read more strictly. |
| A-14 | 12 companies have full quarterly coverage. The manifest claim of 15 is a known discrepancy. | The file list. | Result: confirmed. 12 tickers have 3 10-Qs filed in each of 2023, 2024, and 2025 (AAPL, AMZN, DIS, GOOG, JNJ, KO, MSFT, NVDA, PFE, TSLA, UNH, XOM); 5 more have partial 10-Q coverage (BAC 3, JPM 3, META 6, MCD 1, PEP 1). |
| A-15 | The NVDA 10-K filed in February 2026 is in the corpus. | 27 files carry a 2026 date, and NVDA has 14 to 17 filings. | Result: false, the data wins. The latest NVDA 10-K is `NVDA_10K_2025-02-26_full.txt` (fiscal 2025), and the latest NVDA filing is the 10-Q filed 2025-11-19. "Last two years" for NVDA anchors on the fiscal 2026 Q3 10-Q (period end 2025-10-26), so the window runs from 2023-11-05 to 2025-10-26 and holds 8 filings: the fiscal 2024 10-K, the 3 10-Qs and the 10-K of fiscal 2025, and the Q1 to Q3 10-Qs of fiscal 2026. |

### A-09: corpus facts as measured

- **Inventory.** 246 files, 54 tickers, 89 10-Ks, 157 10-Qs, filing dates
  2022-02-09 to 2026-02-19 plus the GE file of 2015-02-27. 192 files
  carry 9 header keys (`Report Period` and `Quarter` after `Filing Date`),
  and 54 carry the 7 keys the parser first expected.
- **Parser.** An XBRL block sits in 245 files (only GE has none, not 5).
  The smallest block is 7,486 characters (an XOM 10-Q). A rule that cut
  at the earlier of 2 detectors cut inside the block in 205 files, so the
  cover marker is the cut. Rule R3 splits before a capital followed by 2
  letters of any case (`BusinessesNVIDIA`). A rule A4 removes fused page
  footers (AAPL, PFE). The registrant check (CK-06) reads 3 cover
  layouts with a case-blind label, matches names joined without spaces
  or with a leading `THE`, and never quarantines on a name read without
  the label. Table rows join a currency cell to the next cell, count a
  bare year as a header label, and need a second label row without
  numbers. V (September year end) is in `config/fiscal_year_ends.yaml`.
  The cover period also reads `year ended` and `quarter ended`.
- **Sections.** The first detector found the 3 core sections in about 82%
  of the 10-Ks. With labels fused mid-line, bodies past cross-references,
  more short-body items, and sections relocated from a later financial
  section, 87 of 88 indexed 10-Ks (IBM is the miss) and all 157 10-Qs
  have their core sections.
- **Chunks.** 64,727 chunks at first build, not the estimated 35,000 to
  40,000: the clean text is 68.4 MB, not 59 MB, and each of the 20,418
  tables is its own chunk, with the short prose between tables as its own
  chunks. Index 1.2.0, after a table units fix, holds 63,688 chunks.
- **Index layout.** `index/current` is a relative symlink to
  `index/<build_id>`, swapped with 1 atomic rename. An incremental build
  parses and chunks every file (the fiscal-year-end month and CK-11 are
  corpus-wide) and reuses only the embedding shards of unchanged filings.
  The previous build is kept for a rollback.
- **Retrieval weights.** With the first weights, the context of the
  3-company risk comparison held only `risk_factors` chunks (48 of 48).
  Later retrieval changes (a latest-10-K sub-query, superseded standing
  sections of earlier filings left out, 10-Q risk cells reading only
  their risk section, 2 named fiscal years read as a trend) raised recall
  at 25 from 0.63 at the first eval to 0.86.
- **Golden set gaps.** The latest XOM 10-K has no `market_risk` chunk,
  none of the 4 bank 10-Ks has a `market_risk` section, and the latest
  TSLA 10-Q has no `legal_proceedings` section. The golden set keeps its
  expected sources and names the gap.
