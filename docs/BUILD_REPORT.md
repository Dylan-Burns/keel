# Build report

Status: next stage 1

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
- Attempts: 1.

## Gaps

Values that were not available when the build needed them, and what the build did instead.

| Gap | Effect | Resolution |
| --- | --- | --- |
| Local `docker build` at stage 0 | The Docker Desktop disk on the laptop is full (other projects), so the build failed at the last copy step after `uv sync --frozen` passed in the builder stage | The CI job `docker build` builds the image and runs the smoke test; the local evidence waits for free Docker disk |

## Decisions taken without review

Decisions that CLAUDE.md says to ask about, taken in unattended mode. One line each: the decision, the conservative option taken, the stage.

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
| Assumption A-15 (NVDA 10-K filed February 2026 in the zip) | |
