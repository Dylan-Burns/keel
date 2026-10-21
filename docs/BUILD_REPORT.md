# Build report

Status: next stage 3

One entry per stage of `docs/28_build_sequence.md`. Claude Code appends to this file after each stage. The panel reads it during the demo code walk.

The status line above is the state of the build. It takes one of three forms, and the Stop hook reads it in unattended mode:

- `Status: next stage N`
- `Status: blocked at stage N: <reason>`
- `Status: complete <YYYY-MM-DD>`

Entry format:

```text
## Stage N: <name>
- Built: <modules and files>
- Tests: <count passing> (<new tests>)
- Measured: <file counts, chunk count, build time, recall, latency, cost, as applicable>
- Deviations from the specification: <what, why, which decision or chapter it touches>
- Cut or deferred: <what, per the cut order>
- Attempts: <1 to 3, with the failure of each earlier attempt>
```

## Stage 0: Repository foundation

- Built: the starter files of chapter 29.3 as the root commit, `keel/__init__.py` with `__version__`, `keel/cli.py` with `keel --version`, the placeholder unit tests, the front-end placeholder (`web/index.html`, `web/src/main.tsx`, `App.tsx`, `styles.css`, `motion/presets.ts` with `pageLoad` and its reduced twin, `test-setup.ts`, `App.test.tsx`, `e2e/smoke.spec.ts`), `uv.lock`, `web/package-lock.json`, the vendored Google `pylintrc`.
- Tests: Python 3 passing (`test_version`, `test_version_command`, `test_no_arguments_prints_help`), coverage 100%. Vitest 2 passing. Playwright smoke 2 passing (desktop and phone).
- Measured: the corpus zip has 247 entries (246 filings and `manifest.json`), 81.8 MB uncompressed.
- Deviations from the specification:
    - The build laptop is an Intel Mac. PyTorch has no Intel macOS wheel after 2.2.2, so `pyproject.toml` pins torch 2.2.2, numpy 1.x, transformers 4.47, and sentence-transformers 3.4 on Intel macOS only (decision D-37). Linux keeps the CPU index and torch 2.4 or later.
    - The corpus arrived as an extracted folder. The build zipped it flat (the files and `manifest.json` at the root) into `corpus/edgar_corpus.zip`.
    - The GitHub repository was created by the engineer as public, not private.
    - Starter fixes so the starter passes its own checks: the `no-dashes` hook pattern (pygrep compiles a bytes regex, so `\u` escapes fail; it now uses UTF-8 byte escapes), SC2155 in `infra/backup.sh`, fence languages in the Markdown files, the react-hooks flat config, `sourceType: module` for the ESLint config file, no `projectService` next to the gts `project`, `composite: false` in `web/tsconfig.json`, a conditional `webServer` and a `127.0.0.1` preview host in the Playwright config, and `@types/node` as a dev dependency for `process.env` in that config.
    - ruff 0.17 formats Python blocks inside Markdown, so `docs/` joins the ruff exclude list to keep the plan chapters as written.
    - Security: the deploy workflows passed the version input straight into shell scripts. A validation step and `env` now carry it. The Bash guard also blocks pushes to `refs/heads/main`.
    - The 5.5 models have no dated snapshot id in the models list. The config pins the plain ids `claude-sonnet-5-5` and `claude-haiku-5-5` (note on D-11).
    - The Hub renamed the reranker to `cross-encoder/ms-marco-MiniLM-L6-v2`; the config pins the new id (note on D-10).
    - `config/prices.yaml` keys are now the model ids (`claude-sonnet-5-5`, `claude-haiku-5-5`, and `claude-opus-5-5` for the judge), with the Haiku long-prompt prices. The cost code of stage 7 reads these keys.
    - The card's commit plan puts `pylintrc` and `web/package-lock.json` in the third commit, so `make test` and `npm ci` cannot pass on the first two commits alone. The order follows the card.
    - The bootstrap push of the root commit to the empty `main` ran once outside the Bash guard, with the engineer's approval.
    - The root commit skipped only the `no-commit-to-branch` hook, because the foundation commit is the one commit chapter 29.8 places on `main`.
- Cut or deferred: none.
- Attempts: 1. The stage 0 PR ended with 6 commits, not 3, because a CodeQL review thread needed a test import fix (`import keel.cli` as a module).

## Stage 1: Repo skeleton, config, inventory

- Built: `keel/config.py` (pydantic-settings: `config/keel.yaml` first, then the environment and the dotenv file, `KEEL_` prefix, `__` for nested keys, the secrets as `SecretStr` from the environment only, the price table loader keyed by model id), `keel/errors.py` (`KeelError` and the error classes of chapter 6.5), `keel/extractor.py` (control S-10), `keel/inventory.py`, `keel/doctor.py`, the `inventory` and `doctor` commands in `keel/cli.py`, the 8 config dictionaries of chapter 17.6, `tests/fixtures/mini_corpus` (3 filing excerpts and a manifest), and `tests/fixtures/snippets` (both header shapes).
- Tests: Python 60 passing in PR runs (new: `test_inventory_counts`, `test_manifest_mismatch`, `test_date_filter_config`, `test_filename_patterns`, `test_doctor_time_check`, plus the extractor, config, doctor, and inventory unit tests), and 3 `eval` tests on the full extracted corpus passing locally. Coverage of `keel/` 99.1%.
- Measured (`keel inventory`): 246 files (81,818,446 bytes), 54 tickers, 89 10-Ks and 157 10-Qs, filing years 2015 1, 2022 37, 2023 50, 2024 52, 2025 79, 2026 27. Filing dates 2022-02-09 to 2026-02-19 (MS 10-K), plus the GE file of 2015-02-27. File names: 192 with a period code, 54 without. 17 tickers have a 10-Q; 12 have 3 10-Qs filed in each of 2023, 2024, and 2025. Largest file: the JPM 10-K filed 2026-02-13, 1,509,997 bytes. The manifest lists exactly the 246 files on disk, and its counts match. The zip extracts 247 entries (81,828,989 bytes) through the safe extractor.
- Measured (`keel doctor`): Python 3.12.13, SQLite 3.53.1 with FTS5, prices checked on 2026-10-21 for all 3 configured models, both secrets set, clock 244 days after the newest filing, 660 GB free, port 8000 free, both pinned models cached (`--download-models` loaded each in about 12 s on the laptop with sentence-transformers 3.4), index absent until stage 4.
- Corpus facts against the specification (the data wins):
    - A-15 is false: the NVDA 10-K filed in February 2026 is not in the zip. The latest NVDA 10-K is `NVDA_10K_2025-02-26_full.txt` (fiscal 2025); the latest NVDA filing is the 10-Q filed 2025-11-19. The chapter 10.4 and 11 branch without the fiscal 2026 10-K applies. Recorded in the assumptions log.
    - E-D-25 and A-14: the manifest description claims 15 companies with full quarterly coverage for 2023-2025; the files show 12 (AAPL, AMZN, DIS, GOOG, JNJ, KO, MSFT, NVDA, PFE, TSLA, UNH, XOM). BAC, JPM, META, MCD, and PEP have partial 10-Q coverage. `keel inventory` reports this as its only discrepancy.
    - A-05: the manifest `license` key reads `Public domain (SEC filings are US government documents)`.
    - Chapter 7.2 describes a 7-line header. 54 files have the 7 keys; 192 files (every file with a period code in its name) have 9 keys: `Report Period` and `Quarter` come between `Filing Date` and `CIK`. The stage 2 header parser must accept both shapes.
    - Note for stage 2: the JPM 10-K cover page puts `For the fiscal year ended` and `December 31, 2025` in separate table cells on 2 lines, so the `PERIOD_END` pattern of chapter 7.9 does not match it as written. The JPM excerpt in the mini corpus keeps that cover page.
- Deviations from the specification:
    - The card puts every test in the third commit. The unit tests of each module land in the commit of that module, so every commit passes `make test` with the 85% coverage gate on its own; the third commit holds the mini corpus, the snippets, the tests that read them, and the eval test.
    - `config/keel.yaml` gains `llm.prices` and a `dictionaries` section (companies, groups, synonyms, known external), so every dictionary path comes from config.
    - `keel/errors.py` is a module outside the chapter 17.6 tree; it holds the exception hierarchy every module shares.
    - Full quarterly coverage means 3 10-Qs filed in each calendar year 2023, 2024, and 2025. The manifest gives no definition; this one reproduces the 12 of A-14.
    - `keel doctor` checks the models through the Hugging Face cache layout (`models--<org>--<name>/snapshots/<revision>`) instead of importing `huggingface_hub`, which is only a transitive dependency. `--download-models` uses `SentenceTransformer(name, revision=...)` and `CrossEncoder(name, revision=...)`, the API that sentence-transformers 3.4 and 6 share (D-37). Linux CI with sentence-transformers 6 verifies the download step.
    - `keel doctor` exits 1 only on a failed check. A warning (no index, an absent key, a wrong clock, a busy port, an uncached model) exits 0.
    - The mini corpus excerpts (NVDA 10-K filed 2025-02-26, AAPL 10-Q filed 2023-02-03, JPM 10-K filed 2026-02-13, 13 KB to 28 KB each) keep the header, the separator, the first 1,500 characters of the XBRL block, the cover page and the table of contents verbatim, and a window of about 700 characters after each item heading in the body. The excerpts keep the bytes of the filings, including em dashes, en dashes, and non-breaking spaces.
- Review: the reviewer subagent found that a config validation error could carry an environment secret into the log (the messages now hold only the key path and the reason, with a test), that `test_inventory_counts` did not see the E-D-25 mismatch (it now does), that a failed model download on the newer hub client could escape as a traceback (the download boundary now catches every error), and smaller points on the extractor (a file as the target, duplicate entries), test isolation from the developer environment, the CI dash filter, and the README line for E-D-25. All fixed in 1 commit.
- Cut or deferred: none.
- Attempts: 1.

## Stage 2: Parser

- Built: `keel/parsers/base.py` (`ParsedFiling`, `FilingMetadata`, `CheckResult`, `QuarantineRecord`, `ParseContext`, the `FilingParser` protocol, decode and NFKC normalization, CK-06 name matching, the IDs of chapter 7.11, the fiscal math), `keel/parsers/form_10k_10q.py` (the stages of chapter 7.1 and the checks CK-01 to CK-10), `keel/parsers/corpus.py` (the per-ticker fiscal-year-end month, CK-11, the summary), `keel/parsers/__init__.py` (the registry by form), `keel/tables.py`, `keel parse` with `--all`, `--summary`, and `--json`, `config.read_word_list`, and 4 error classes (`FilingDecodeError`, `HeaderError`, `SeparatorMissingError`, `CoverPageNotFoundError`). 7 new snippets under `tests/fixtures/snippets` (606 to 1,514 bytes, copied from the corpus).
- Tests: Python 105 passing in PR runs (45 new: the 18 tests of table 7.13, the E-D tests on the card `test_giant_line_parse`, `test_large_file_parse_time`, `test_bom_and_crlf`, `test_invalid_utf8`, `test_truncated_file_quarantine`, `test_duplicate_filing_id`, plus `test_header_url_trust`, the check, table, and CLI tests), and 3 new `eval` tests on the full corpus passing locally (6 `eval` tests in all). Coverage of `keel/` 98.2%. Tests that need a long input (the 18,772 and 284,260 character blocks, the 287,855 character line, the 1.5 MB file) repeat a real snippet to the measured length, so every fixture stays at 2 KB or smaller; the eval test checks the 2 block lengths on the real files.
- Measured (`keel parse --all --summary`): 246 files, 245 parsed, 1 quarantined: `GE_10K_2015-02-27_full.txt`, `registrant_mismatch` (cover `General Electric Capital Corporation`, header `General Electric Company`, URL `gecc10k2014.htm`, filed 2015-02-27). Warnings: `registrant_not_found` 19 (17 DIS files and MS have no registrant name on the cover; the CMCSA cover puts it in a table), `cover_period_split_layout` 5 (the JPM 10-K and 3 JPM 10-Qs of 2025, the MCD 10-Q of 2023 Q1), `no_xbrl_block` 1 (GE). Checks: CK-01 to CK-05, CK-07, CK-09, CK-10 pass on 246; CK-06 pass 226, warning 19, quarantine 1; CK-08 pass 192, skipped 54 (no period code); CK-11 pass 245, skipped 1 (GE). `xbrl_block_chars`: min 7,486 (XOM 10-Q filed 2022-05-04), median 30,461, max 284,260 (BAC 10-K filed 2025-02-25); NVDA fiscal 2025 10-K 18,772. `period_source=filename`: 0. Artifact removals 8,693 (NVDA fiscal 2025 10-K: 81). Tables rebuilt 20,522. Parse time: total 25.0 s on the Intel laptop, median 0.083 s per file, slowest JPM 10-K 0.48 s, GS 10-K 0.40 s, BAC 10-K 0.35 s; no file near the 60-second limit (E-D-21). The cover period equals the header `Report Period` in all 192 files that have it, and the date in the source URL in all 240 URLs that carry one. Non-December fiscal year ends from the 10-Ks: AAPL 9, ADBE 11, COST 8, CRM 1, CSCO 7, DE 10, DIS 9, HD 1, MSFT 6, NKE 5, NVDA 1, ORCL 5, PG 6, SBUX 9, TGT 1, V 9, WMT 1.
- Cover page period detection (orchestrator question): the `PERIOD_END` pattern of chapter 7.9, as written and taken at its first match after the cover marker, finds no date in 2 files (IBM 10-K: `FOR THE YEAR ENDED DECEMBER 31, 20241-2360`; MCD 10-Q 2023 Q1: split cells) and a wrong date in 1 (MS 10-K: no `fiscal year` phrase on the cover, so the first match is `November 30, 2007` deep in the body); the 4 JPM split-cell covers match only by borrowing a later sentence. The parser tries each cover phrase (`fiscal year`, `quarterly period`, `year`, `quarter` ended) in order with the chapter pattern first and a split-cell pattern second (the date within 2 lines of the phrase). Result: 0 failures, 0 filename fallbacks, 5 split-cell reads.
- Deviations from the specification (the data wins; also in the decisions log under A-09 and D-21):
    - Chapter 7.4 cuts at the earlier of the cover marker and the prose window. On the corpus the prose window starts before the marker in 205 of 245 files: a window that ends past the marker counts the spaces of the cover text (15 to about 100 characters early, e.g. NVDA 18,757 instead of 18,772), and in DIS, MCD, MSFT, and XOM files the hidden facts at the top of the block hold text with spaces (4 MSFT and XOM bodies would have stayed whole). The cover marker is the cut; the prose window is the fallback for a body without the marker. With that rule the chapter numbers 18,772 and 284,260 reproduce exactly (the chapter counts from the end of the 60 equals signs).
    - Chapter 7.4 and E-D-08 say 5 files have no XBRL block (241 with one). The data shows 1: only GE. The other 245 bodies hold an XBRL sign before the cover marker. The smallest block is 7,486 characters (XOM 10-Q), not 18,772.
    - Chapter 7.9 step 3 gives a 10-K the calendar year of its period end. JNJ 10-Ks end on 2022-01-02 and 2023-01-01, which are fiscal 2021 and 2022. A 10-K takes the year of the nominal month instead (same answer for every other 10-K).
    - Chapter 7.10 CK-06: the registrant regex as written misses many cover layouts. The label match is case-blind (MS writes `Registrant`), cover text that runs into the name up to the commission file number is stripped (ABBV, CAT, HD, KO, LLY, NKE, PEP, PFE, TMO, V, XOM), a table cell may sit between name and label (BA, MA), the name may follow the label (BAC) or the file number (MSFT, MRK, PG). A name read without the label never quarantines (the DIS cover gives `Delaware` there); it gives `registrant_not_found`. The token comparison also accepts tokens equal when joined in order without a leading `THE` (`Coca-Cola` against `COCA COLA`, `THEPROCTER & GAMBLE`). The cover page is read from the text before the boundary repair, so rule R3 never splits a name (`UnitedHealth`, now also a protected name).
    - Rule R3 of chapter 7.5 reads `(?=[A-Z][a-z]{2})`, which does not split `BusinessesNVIDIA` as the chapter's own test expects; the parser uses `(?=[A-Z][A-Za-z]{2})`. Rules R1 to R4 skip table rows so that a cell never breaks across lines.
    - A new artifact rule A4 removes fused page footers such as `Apple Inc. | 2025 Form 10-K | 1` (838 in AAPL and PFE files), which made prose lines look like table rows. A line over 2,000 characters is not a table row.
    - Table rows: a currency cell joins the next cell (`$ 72,880`), a bare year counts as a label in a header row, and the second label row must hold no number (the 50% rule alone takes the first data row of a 2-column table as a label).
    - The NVDA fiscal 2025 10-K gives 81 artifact removals, the chapter says 82.
    - The Visa 10-K ends on September 30; V joins `config/fiscal_year_ends.yaml` (E-D-06 omits it).
    - Chapter 7.13 `test_idempotent_ids` compares chunk IDs and hashes; the chunker arrives at stage 3, so the test compares the filing ID, the metadata, the clean text, and the chunk IDs and hashes of the rendered table parts.
    - The card's commit plan has 3 parser commits in the order header, cover, tables. The parser stages call the table module and the corpus pass, so the commits are: tables, the parser with its checks, the CLI with the integration and eval tests, then a fix commit for the URL trust check (security review), then this report.
    - `test_sec_url_only` belongs to stage 9 (card). The parse-time URL check is `test_header_url_trust`: only `https://www.sec.gov/...` with no whitespace, control character, backslash, `@`, user, password, or port is trusted.
    - `keel/parsers/corpus.py` is a module outside the chapter 17.6 tree; it holds the rules that need every file (fiscal-year-end month, CK-11, the summary).
- Cut or deferred: none.
- Attempts: 1.

## Gaps

Values that were not available when the build needed them, and what the build did instead.

| Gap | Effect | Resolution |
| --- | --- | --- |
| Local `docker build` at stage 0 | The Docker Desktop disk on the laptop is full (other projects), so the build failed at the last copy step after `uv sync --frozen` passed in the builder stage | Resolved after stage 0: the image built locally at 1.5 GB, and `docker run --rm keel:local --version` prints `keel 0.1.0` |

## Decisions taken without review

Decisions that CLAUDE.md says to ask about, taken in unattended mode. One line each: the decision, the conservative option taken, the stage.

- The pre-commit ruff hook ran ruff 0.6.9 while `uv.lock` pins 0.17.1, and the 2 versions disagreed on stage 1 code (ANN101 against PLC0415). The hook moves to v0.17.1, the version CI already runs; no package dependency changes. Stage 1.
- The filing excerpts under `tests/fixtures/mini_corpus` and `tests/fixtures/snippets` keep the em dashes and en dashes of the real filings. The `no-dashes` hook, the CI dash check, and the whitespace hooks skip those 2 directories instead of altering the data. Stage 1.

## Placeholders resolved

| Placeholder | Value or status |
| --- | --- |
| corpus/edgar_corpus.zip present | yes, built from the extracted corpus folder on 2026-10-21 |
| llm.model | `claude-sonnet-5-5` (the models list has no dated id for the 5.5 models; the plain id is the pinned snapshot) |
| llm.fallback_model | `claude-haiku-5-5` |
| llm.judge_model | `claude-opus-5-5` (a different model from llm.model, D-35) |
| embedding.revision | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` (BAAI/bge-small-en-v1.5) |
| reranker.revision | `233902d25c440f23af6f7d6e94d2946bac0bee0a` (the Hub renamed the model to cross-encoder/ms-marco-MiniLM-L6-v2) |
| edgar.user_agent | Dylan Burns, with the engineer's email |
| demo.add_companies | ZTS, WDAY |
| deploy.host | railway |
| prices checked_on | 2026-10-21 against the provider price page. Correction: the Sonnet 5.5 cache read is 0.10, not 0.20 |
| Assumption A-15 (NVDA 10-K filed February 2026 in the zip) | absent (stage 1 `keel inventory`): the latest NVDA 10-K is `NVDA_10K_2025-02-26_full.txt` |
