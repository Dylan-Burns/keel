# CLAUDE.md

## What this repo is

Keel answers business questions about SEC 10-K and 10-Q filings. Each question makes exactly one LLM request. The filing text grounds each answer, and the service validates each citation. The design is in `docs/ARCHITECTURE.md`; decisions are in `docs/DECISIONS.md` (D-01 onward), security controls in `docs/SECURITY.md` (S-xx), and edge cases with their tests in `docs/EDGE_CASES.md` (E-xx).

## How to work

- Work on a branch named `<type>/short-name`. The pre-commit hook blocks commits on `main`. Never force push.
- Commit messages follow Conventional Commits with the scopes in `commitlint.config.cjs`. Each commit passes `uv run pre-commit run --all-files` and `make test` on its own.
- Before a PR, run `make test` and `npm run check --prefix web`, then `/review`. The PR body follows `.github/PULL_REQUEST_TEMPLATE.md`.
- Ask before you do any of these:
    - Change a decision in `docs/DECISIONS.md`.
    - Add a dependency that is not in `pyproject.toml` or `web/package.json`.
    - Call an external API other than the Anthropic API and the SEC EDGAR endpoints.
    - Delete anything under `corpus/`.
- When the docs and the data disagree, the data wins. Record the discrepancy in `docs/DECISIONS.md`.
- Use the `corpus-analyst` subagent for any look at a corpus file. Use the `reviewer` subagent through `/review` before every PR.
- Read the installed SDK and the provider documentation before any provider code. Never guess a parameter name.

## Non-negotiables

- Exactly one model request per question (D-01, D-04 in `docs/DECISIONS.md`). The mock provider counts requests. `test_single_request` must pass at all times.
- No LLM call at index time, in retrieval, in reranking, or after the answer (D-02, D-28).
- Deterministic filing and chunk IDs (D-23). The fiscal period comes from the cover page, never from the file name (D-21). Quarantine on a metadata conflict (D-20). The GE file must be in quarantine.
- The validator checks every citation against the context after the call. A finding with no valid citation gets the mark `unverified`. The page never hides it.
- Secrets come only from environment variables. Never log, print, or commit them. `.env` is in `.gitignore`.
- A visitor's Anthropic key (`X-Anthropic-Api-Key`, public mode) lives only in the request's provider. Never store or log it; uvicorn runs with `access_log=False`, and nothing logs request headers.
- Each edge case in `docs/EDGE_CASES.md` needs its named test.
- No em dashes anywhere: not in docs, code comments, UI strings, or commit messages. Use a comma, a colon, or a new sentence.

## Code standards (Google style guides)

Python:

- 80 columns, 4-space indent, PEP 8 names, `ruff format` output.
- A Google docstring with `Args:`, `Returns:`, and `Raises:` on every public function and class.
- Import modules, not names: `import pathlib`, then `pathlib.Path`. The exceptions are `typing`, `collections.abc`, `typing_extensions`, `dataclasses`, and `__future__`.
- No relative imports. No mutable defaults. No bare `except`. No `assert` for validation.
- Logging with `%` placeholders. `main()` behind the `__name__` guard.
- Exceptions subclass `KeelError` and end in `Error`, for example `IndexMissingError`.
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
- Front-end: Vitest with React Testing Library for the components and the state reducer. Playwright in `web/e2e/`, against `keel serve` with the mock provider (`KEEL_LLM__PROVIDER=mock`, fault header `X-Keel-Mock`).
- Before every commit, `uv run pre-commit run --all-files` must pass. It runs the same checks as CI.
- The `PostToolUse` hook in `.claude/settings.json` formats and lints every file you edit. Fix what it reports before you move on.

## Stack and conventions

- Python 3.12, `uv` for dependencies with a committed `uv.lock`, the `hatchling` build backend, the package `keel/` at the repo root.
- FastAPI and uvicorn, pydantic and pydantic-settings, SQLite with FTS5, NumPy, the `anthropic` SDK, PyYAML, rapidfuzz, httpx. python-docx under the extra `export`.
- sentence-transformers with `BAAI/bge-small-en-v1.5`, pinned to a revision hash. `cross-encoder/ms-marco-MiniLM-L-6-v2`, pinned.
- Front-end: React 19 with TypeScript in strict mode, Vite, Tailwind CSS 4, Motion for React, `marked` and `DOMPurify`. `npm run build --prefix web` writes `web/dist`. FastAPI serves it at `/` with a fallback to `index.html`. The 11 UI states are a union type in `web/src/state.ts` with one reducer. The SSE client uses `fetch` and a `ReadableStream` parser, because the bearer token rules out `EventSource`. The Dockerfile builds the front-end in a Node stage.
- Repo layout: see the table in `README.md`. Do not add a top-level directory without a question.
- Config: `config/keel.yaml`. A top-level key overrides as `KEEL_<KEY>` (for example `KEEL_OFFLINE=1`). A nested key overrides as `KEEL_<SECTION>__<KEY>` (for example `KEEL_INDEX__DIR`). Prices live in `config/prices.yaml` with their check date.
- Host: Railway (D-41): 1 service built from the `Dockerfile` with a volume at `/data`, served at `www.keeldd.com`; the apex forwards at Squarespace. The AWS path (D-39, D-40) stays in `infra/terraform/` as the alternative. See `infra/README.md`.

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
uv run keel serve              # API and front-end on port 8000; --bootstrap downloads and builds on first start
uv run keel eval               # golden set, writes eval/report.md
uv run keel warm-cache         # answer cache for the demo questions
uv run keel add TICKER         # ingest 1 company from EDGAR
uv run keel refresh            # new filings of the watch list; --dry-run lists them
uv run keel export REQUEST_ID  # --format markdown|docx
uv run keel bootstrap          # download the corpus, build the index when absent
make test                      # ruff, mypy, pylint, pytest with coverage
uv run pre-commit run --all-files
npm run dev --prefix web       # Vite dev server on 5173, proxies /api to 8000
npm run check --prefix web     # gts lint, tsc, vitest, vite build
npm run test:e2e --prefix web  # Playwright; KEEL_E2E_BASE_URL=http://127.0.0.1:8000 against keel serve
```
