# CLAUDE.md

## What this repo is

Keel answers business questions about SEC 10-K and 10-Q filings. Each question makes exactly one LLM request. The filing text grounds each answer, and the service validates each citation. The full specification is in `docs/01_*.md` through `docs/29_*.md`. The order of work is chapter 28 (`docs/28_build_sequence.md`): stages 0 to 22. The stage cards in `docs/STAGES.yaml` index each stage into the chapters, the files, the tests, and the evidence. Chapter 29 (`docs/29_engineering_standards.md`) sets the code, CI/CD, infrastructure, and Git standards. Principal engineers grade all four. `docs/GOTCHAS.md` lists the known traps. Read it when a stage card names it.

## No time estimates

Do not estimate how long a stage takes. Do not pace the work by a duration in the docs. The minute blocks in chapter 20 describe the scope of the 4-hour timebox of the assessment. They are not build estimates. Minutes in chapters 21, 25, and 26 are demo timings. Weeks in chapter 27 are the client pilot calendar. None of these limit the build. Work each stage as fast as its done-when evidence permits. Never pad, defer, or split work because of a duration written anywhere.

## How to work

- Start every stage with `/stage NN`. The command reads the stage card, the chapters it names, and `docs/BUILD_REPORT.md`. The stage starts from the repository state. Never start a stage from memory of an earlier one.
- Work on a branch named `<type>/stage-NN-short-name`. The card names it. Create the branch before the first edit. The pre-commit hook blocks commits on `main`.
- Inside a stage, make 2 to 5 logical commits in the order a reviewer reads them: code, tests, docs, config. The card has the commit plan. Every commit must pass `uv run pre-commit run --all-files` and `make test` on its own. Commit messages follow Conventional Commits with the scopes in `commitlint.config.cjs`. Keep the `Co-Authored-By` trailer that Claude Code adds. Push the branch after every commit.
- After a stage, do these steps in order. Run `make test`. Produce the done-when evidence with the commands on the card. Append the stage entry to `docs/BUILD_REPORT.md`. Run `/review`. Open the PR with `scripts/pr.sh open "<title>" <body file>`. The body comes from `.github/PULL_REQUEST_TEMPLATE.md` with the evidence. `gh pr` does not work in a cloud session, so `scripts/pr.sh` uses the REST API everywhere.
- Review mode, unattended (the default, chapter 29.11): the cloud environment sets `KEEL_UNATTENDED=1`, which turns on the Stop hook. After the PR opens, run `scripts/pr.sh wait <number>` and then `scripts/pr.sh merge <number>`. Then start the next stage. Never stop for a person.
- Review mode, attended: the prompt says "stop after each PR". Stop after the PR opens, and wait for the review.
- In both modes, never push to `main` and never force push.
- Failure policy (unattended): make 3 attempts at the done-when evidence. After the third failure, record the failure and the error in the build report. If the card says `cuttable: true` or names a `cut_within_stage`, apply that cut and continue. Otherwise write `Status: blocked at stage N: <reason>` on `main` through a docs-only PR (branch `docs/build-status`) and stop.
- Do not implement roadmap items from chapter 22 unless chapter 28 names them.
- Ask before you do any of these:
    - Change a decision in `docs/04_*.md` (D-01 to D-36).
    - Add a dependency that is not in `pyproject.toml` or `web/package.json`.
    - Call an external API other than the Anthropic API and the SEC endpoints in chapter 26.
    - Delete anything under `corpus/`.
- In unattended mode, take the most conservative option instead of a question. Record it in the build report under "Decisions taken without review". Then continue.
- When the specification and the data disagree, the data wins. Record the discrepancy in `docs/BUILD_REPORT.md` and in the decisions log. Then continue.
- Use the `corpus-analyst` subagent for any look at a corpus file. Use the `reviewer` subagent through `/review` before every PR.
- Read the installed SDK and the provider documentation before any provider code. Never guess a parameter name.

## Non-negotiables

- Exactly one model request per question (D-01, D-04). The mock provider counts requests. `test_single_request` must pass at all times.
- No LLM call at index time, in retrieval, in reranking, or after the answer (D-02, D-28).
- Deterministic filing and chunk IDs (D-23). The fiscal period comes from the cover page, never from the file name (D-21). Quarantine on a metadata conflict (D-20). The GE file must be in quarantine.
- The validator checks every citation against the context after the call. A finding with no valid citation gets the mark `unverified`. The page never hides it.
- Secrets come only from environment variables. Never log, print, or commit them. `.env` is in `.gitignore`.
- Acceptance criteria AC-01 to AC-11 in `docs/03_*.md` define done for the demo core. Each edge case in `docs/19_*.md` needs its named test.
- No em dashes anywhere: not in docs, code comments, UI strings, or commit messages. Use a comma, a colon, or a new sentence.

## Code standards (Google style guides, chapter 29)

Python:

- 80 columns, 4-space indent, PEP 8 names, `ruff format` output.
- A Google docstring with `Args:`, `Returns:`, and `Raises:` on every public function and class.
- Import modules, not names: `import pathlib`, then `pathlib.Path`. The exceptions are `typing`, `collections.abc`, `typing_extensions`, `dataclasses`, and `__future__`.
- No relative imports. No mutable defaults. No bare `except`. No `assert` for validation.
- Logging with `%` placeholders. `main()` behind the `__name__` guard.
- Exceptions subclass `KeelError` and end in `Error`. The condition names of chapter 6.5 map to classes with that suffix: `IndexMissing` becomes `IndexMissingError`.
- pydantic models at module boundaries, frozen dataclasses inside, full annotations.
- `mypy --strict` clean and `pylint --rcfile=pylintrc` clean.

TypeScript (the Google TypeScript Style Guide, enforced by `gts`):

- 2-space indent, single quotes.
- Named exports only. No default exports in `src/`.
- No `any`. Use `unknown` and narrow.
- Interfaces for object types. `import type` for types. `readonly` where a value does not change. `T[]` for arrays.
- camelCase for values. PascalCase for types and components.
- One component per file, named after the component. JSDoc on every exported symbol. No `namespace`.
- `npm run lint --prefix web`, `npm run typecheck --prefix web`, and `npm run test --prefix web` clean.
- Motion presets live only in `web/src/motion/presets.ts`. Components never define inline transitions.
- Model text and filing text render as JSX text nodes. The only sanitized HTML is the answer markdown after DOMPurify.

Shell, Markdown, YAML, Terraform:

- Shell: `#!/bin/bash`, `set -euo pipefail`, a `main` function, 2-space indent, quoted variables, `shellcheck` clean.
- Markdown and YAML: `markdownlint-cli2` and `yamllint --strict` clean.
- Terraform: `terraform fmt` and `tflint` clean.

Tests:

- `tests/unit` holds snippets and pure functions. `tests/integration` holds the mini corpus and the API with the mock provider. `tests/eval` needs the full index or the live provider, and PRs exclude it.
- Coverage on `keel/` is 85% or more.
- Tests never touch the network. The pinned models come from the local Hugging Face cache. `keel doctor --download-models` fills it, and CI caches it. pytest runs with `HF_HUB_OFFLINE=1`.
- Front-end: Vitest with React Testing Library for the components and the state reducer. Playwright in `web/e2e/` for the specs of chapter 14.9, against `keel serve` with the mock provider (`KEEL_LLM__PROVIDER=mock`, fault header `X-Keel-Mock`).
- Before every commit, `uv run pre-commit run --all-files` must pass. It runs the same checks as CI.
- The `PostToolUse` hook in `.claude/settings.json` formats and lints every file you edit. Fix what it reports before you move on.

## Stack and conventions

- Python 3.12, `uv` for dependencies with a committed `uv.lock`, the `hatchling` build backend, the package `keel/` at the repo root.
- FastAPI and uvicorn, pydantic and pydantic-settings, SQLite with FTS5, NumPy, the `anthropic` SDK, PyYAML, rapidfuzz, httpx. python-docx under the extra `export` (chapter 27 only).
- sentence-transformers with `BAAI/bge-small-en-v1.5`, pinned to a revision hash. `cross-encoder/ms-marco-MiniLM-L-6-v2`, pinned.
- Front-end (chapters 14.8 and 14.9): React 19 with TypeScript in strict mode, Vite, Tailwind CSS 4, Motion for React, `marked` and `DOMPurify`. `npm run build --prefix web` writes `web/dist`. FastAPI serves it at `/` with a fallback to `index.html`. The 11 UI states are a union type in `web/src/state.ts` with one reducer. The SSE client uses `fetch` and a `ReadableStream` parser, because the bearer token rules out `EventSource`. The Dockerfile builds the front-end in a Node stage.
- Repo layout: `docs/17_*.md`, chapter 17.6, plus the foundation files in chapter 29.3. Do not add a top-level directory outside that tree without a question.
- Config: `config/keel.yaml`. A top-level key overrides as `KEEL_<KEY>` (for example `KEEL_OFFLINE=1`). A nested key overrides as `KEEL_<SECTION>__<KEY>` (for example `KEEL_INDEX__DIR`). Prices live in `config/prices.yaml` with their check date.
- Pilot host: AWS (D-39): 1 EC2 `t3.large` from `infra/terraform/`, Caddy for HTTPS, S3 for backups. Railway (`railway.toml`, chapter 29.9) was the default; it stays in the repository as the alternative.

## Commands

```text
uv sync --all-extras
uv run keel doctor             # environment checks: FTS5, models, keys, ports; --download-models fills the model cache
uv run keel inventory          # counts, manifest check, discrepancies
uv run keel parse --all --summary
uv run keel chunk --all --summary
uv run keel index              # full build; --incremental skips unchanged files
uv run keel understand "question"
uv run keel retrieve --question 1 --summary
uv run keel ask "question"     # one answer in the terminal; --json for the record
uv run keel serve              # API and front-end on port 8000; --bootstrap on Railway
uv run keel eval               # golden set, writes eval/report.md
uv run keel warm-cache         # answer cache for the demo questions
uv run keel add TICKER         # chapter 26
uv run keel refresh            # chapter 26; --dry-run lists new filings
uv run keel export REQUEST_ID  # chapter 27; --format markdown|docx
uv run keel bootstrap          # chapter 29.9: download the corpus, build the index when absent
make test                      # ruff, mypy, pylint, pytest with coverage
uv run pre-commit run --all-files
npm run dev --prefix web       # Vite dev server on 5173, proxies /api to 8000
npm run check --prefix web     # gts lint, tsc, vitest, vite build
npm run test:e2e --prefix web  # Playwright; KEEL_E2E_BASE_URL=http://127.0.0.1:8000 against keel serve
```

## Placeholders to resolve before stage 1

Resolve these in `config/keel.yaml` and `.env` before stage 1. Every `TODO` in those files is one of them. If a value is not available: in attended mode, stop and ask. In unattended mode, record the gap in the build report and continue with the stages that do not need it.

- `corpus/edgar_corpus.zip` is present. Or `KEEL_CORPUS__URL` points at it. Or `GH_TOKEN` can download the release asset `corpus-v1`.
- `ANTHROPIC_API_KEY` and `KEEL_API_TOKEN` are in `.env` or in the session environment.
- `llm.model`, `llm.fallback_model`, `llm.judge_model`: the dated snapshot identifiers for Claude Sonnet 5.5 and Claude Haiku 5.5. Resolve them from the provider's models list. Record them in `config/keel.yaml` and in `docs/04_*.md`.
- `embedding.revision` and `reranker.revision`: the commit hashes of the two Hugging Face models, pinned.
- `edgar.user_agent`: a name and an email address. The SEC requires it.
- `demo.add_companies`: the 2 tickers that `keel add` ingests for the demo (chapter 26.6).
- Check assumption A-15 during `keel inventory`: is the NVDA 10-K filed in February 2026 in the zip? Record the answer in `docs/BUILD_REPORT.md`. The NVIDIA worked example in chapter 11 branches on it.
- Confirm the prices in `config/prices.yaml` against the provider price page. Record the date.

## Build report

Keep `docs/BUILD_REPORT.md` current. For each stage, record what you built, the test count, and the measured numbers (file counts, chunk count, build time, recall, latency, cost). Record every deviation from the specification with its reason. The `Status:` line at the top is the state of the build: `Status: next stage N`, `Status: blocked at stage N: <reason>`, or `Status: complete <date>`. Update it with every stage entry. In unattended mode the Stop hook reads it and keeps the session at work until it says complete or blocked. The panel reads this file during the demo code walk.
