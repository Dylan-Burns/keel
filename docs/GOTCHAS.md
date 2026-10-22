# Known traps

Read this before stages 0, 4, 6, 7, 9, 12, 13, 14, 20, and 21 (the stage cards name it). Each entry names the trap, the
symptom, and the rule. When an entry says "read the installed package", open
the package source under `.venv/` and read the signature; never guess a
parameter name from memory.

## Dependencies and the environment

- PyTorch pulls CUDA wheels of several gigabytes by default. Pin the CPU
  wheel index in `pyproject.toml` (`[[tool.uv.index]]` with
  `https://download.pytorch.org/whl/cpu` and `explicit = true`, then
  `[tool.uv.sources] torch = { index = "pytorch-cpu" }`). Check the image
  size after the Docker build; the CPU image stays under 2 GB.
- `uv run` is the only way to run project commands. A bare `python` or
  `pytest` uses the wrong interpreter.
- SQLite needs the FTS5 extension. `keel doctor` checks
  `PRAGMA compile_options` for `ENABLE_FTS5`. The uv-managed Python and the
  `python:3.12-slim` image both have it; a system Python may not.
- Pin both Hugging Face models to a commit hash with the `revision`
  parameter of `SentenceTransformer` and `CrossEncoder`, and record the hash
  in `config/keel.yaml`. Without the pin, a model update changes every
  vector and breaks the index checksum.
- At serve time set `HF_HUB_OFFLINE=1` so no request leaves for the Hub. At
  index time, the model download needs `huggingface.co` and its download
  hosts in the network allow list of the environment.
- The reranker and the embedder load in a few seconds each. Load them once
  at startup, never per request. `keel doctor` reports the load time.
- `tests/` never touch the network. Recorded responses live under
  `tests/fixtures/`; the mock provider replaces the Anthropic client.

## Embeddings and retrieval

- `BAAI/bge-small-en-v1.5` expects the query prefix
  `Represent this sentence for searching relevant passages:` (with one
  trailing space) for short
  queries against passages; the passages get no prefix. Normalize the
  vectors (`normalize_embeddings=True`) so the dot product is the cosine.
- Keep `vectors.npy` as float32 and in chunk-ID order; `test_vector_rows`
  checks that the row count equals the chunk count.
- FTS5 query syntax treats `-`, `.`, and quotes as operators. Escape every
  token (wrap each term in double quotes, and double any inner quote) before
  it reaches `MATCH`. Company names such as `Johnson & Johnson` and tickers
  such as `BRK.B` break an unescaped query.
- The token estimate for the budget is local (chapter 11 calibration factor);
  never call the provider's count endpoint per question.

## The single call (stage 7)

- One `messages` request per question. The mock provider counts requests;
  `test_single_request` must pass before any PR merges.
- Read the installed `anthropic` package for the tool-use and the streaming
  interfaces before any provider code. D-13 fixes the output mechanism: a
  forced tool call whose input schema is the answer schema
  (`prompts/answer_schema_v1.0.0.json`), which every SDK version supports.
  The server-side validator still runs on the result. Do not switch to a
  structured-output mode or a schema in the system block; both change the
  prompt bytes and the cache behavior that chapter 12 specifies.
  Stage 8 note: the 5.5 models reject the forced tool call, so prompt 1.3.0
  ships with `llm.output_mode: json_schema` (`output_config.format`), the
  first preference of D-13; its cached prefix stays byte-stable (2,673
  tokens). The prompt version and the mode must match.
- Prompt caching needs the `cache_control` marker on the system block, and
  the block must stay identical between requests: same prompt version, same
  tool definitions, same order. A single changed byte misses the cache.
- Retries are allowed before the first content token only (D-04). After the
  first `answer_delta`, a failure ends the answer with the `error` event.
- The model identifiers are dated snapshots from the provider's models list,
  never aliases. `test_model_pinned` reads them from `config/keel.yaml`.
- Keep `temperature: 0`. Determinism is still not guaranteed; the eval judge
  compares content, not bytes.

## SSE and the front-end (stages 0, 9, 12)

- A `StreamingResponse` with `media_type="text/event-stream"` needs the
  headers `Cache-Control: no-cache` and `X-Accel-Buffering: no`, and a
  keep-alive comment line (`: ping`) every 15 seconds so proxies do not
  close an idle stream. Caddy needs `flush_interval -1`; Railway's proxy
  streams without a setting.
- Flush after every event. Buffer nothing between the provider stream and
  the client.
- `EventSource` cannot send the bearer token header. The client reads the
  stream with `fetch` and a `ReadableStream` parser that splits on blank
  lines and handles a chunk boundary inside an event.
- FastAPI serves `web/dist` at `/`: mount the hashed assets as static files
  and return `index.html` for any non-API path, so the client routes
  (`/a/{request_id}`, `/history`) work on a reload. Keep `/api/*` routes
  registered before the fallback.
- The answer markdown is the only HTML on the page: `marked` then
  `DOMPurify` with the allow list of chapter 15, rendered once through
  `dangerouslySetInnerHTML` in one component (`AnswerMarkdown`). Every
  other string (chunk text, quotes, titles) renders as a JSX text node.
- Tailwind CSS 4 runs through `@tailwindcss/vite`; the entry is
  `@import 'tailwindcss';` in `web/src/styles.css`. There is no
  `tailwind.config.js`; theme tokens live in the `@theme` block.
- Motion for React: import from `motion/react`. `useReducedMotion()`
  returns `null` before hydration; treat only `true` as reduced. jsdom has
  no `matchMedia`; the Vitest setup file defines a stub.
- All variants and transitions live in `web/src/motion/presets.ts`, one
  named export per moment of table 14.8, each with a `reduced` twin. A
  component with an inline `transition` fails review.
- `gts` provides the ESLint flat config and the Prettier settings; the
  extra rules in `web/eslint.config.js` encode the Google TypeScript Style
  Guide points that gts leaves to review. `npm run fix --prefix web`
  applies the fixes. Never add `eslint-disable` to pass a rule; fix the
  code or raise the rule in the PR body.
- Named exports only under `web/src/`; the Vite and Playwright config files
  are exempt (their tools need a default export).
- Playwright: `KEEL_E2E_BASE_URL` points the specs at `keel serve`; without
  it the config serves `web/dist` with `vite preview`. The mock provider
  reads the `X-Keel-Mock` header only when `llm.provider` is `mock`.
  Install the browser once with `npx --prefix web playwright install
  chromium`. In CI the `web e2e` job installs it with `--with-deps`.
- The CI job names in `ci.yml` are the required checks in
  `scripts/setup_github.sh`: `web lint, types, tests, build` and
  `web e2e`. Rename both or neither.

## EDGAR (stages 13, 14, 20)

- Every request needs the header `User-Agent: <name> <email>` from
  `edgar.user_agent`, at most 10 requests per second (the plan uses a
  0.2-second pause). A missing header returns HTTP 403.
- Hosts: `data.sec.gov` (company facts, submissions) and `www.sec.gov`
  (ticker map, filing documents). Both are in the outbound allow list of
  control S-11; nothing else is, and no other host is added without a
  decision in `docs/04_*.md`.
- CIKs are 10 digits with leading zeros in the URL
  (`CIK0001045810.json`).
- Cache every response on disk under `edgar.cache_dir` with the fetch date;
  tests read the cache, never the network.

## Git and CI

- The `no-commit-to-branch` hook blocks commits on `main`. Create the stage
  branch before the first edit.
- Commit scopes must be in `commitlint.config.cjs`; an unknown scope fails
  the commit-msg hook and the CI job `conventional commits`.
- The names of the required status checks in `scripts/setup_github.sh` must
  equal the `name:` of each job in `ci.yml`. A renamed job blocks every
  merge until the protection rule is updated.
- In a Claude Code cloud session the GitHub proxy rejects GraphQL, so
  `gh pr ...` and `gh issue ...` return 403 even with a `GH_TOKEN`. Every PR
  step goes through `scripts/pr.sh` (REST calls with `gh api`): `open`,
  `number`, `status`, `wait`, `merge`. `gh run`, `gh workflow`, `gh api`,
  and `gh release download` are REST and work.
- `scripts/pr.sh merge` is a rebase merge through the REST API; GitHub
  refuses it while a required check is red or the branch is behind `main`
  (`strict` status checks), so rebase on `main` and push again in that case.
- The Bash tool waits 2 minutes for a command by default. The full index
  build and the first `uv sync` run longer: the cloud environment sets
  `BASH_DEFAULT_TIMEOUT_MS=600000` and `BASH_MAX_TIMEOUT_MS=3600000`, and
  a command over 10 minutes runs with `nohup ... &` and a log file that the
  agent polls.
- release-please opens a release PR after every merge to `main`, with the
  commit scope `main` (allowed in `commitlint.config.cjs`). It needs the
  secret `RELEASE_PLEASE_TOKEN` (a fine-grained token), because a PR or a
  tag made with the default `GITHUB_TOKEN` starts no workflow and the
  release PR could never pass the required checks. In attended mode the
  engineer merges it; in unattended mode the agent merges it only at the
  end of stage 21, to create the tag that `deploy.yml` needs.
- Dependabot PRs are not part of the build. Leave them for the engineer.

## Railway (stage 21)

- One volume, mounted at `/data`. Every writable path points under it
  through `KEEL_*__DIR` variables and `HF_HOME`. Nothing else in the
  container is writable.
- A Railway cron service cannot share the app's volume; the in-app
  scheduler does the nightly work.
- `railway up --service keel --ci` from the tagged checkout; the project
  token in `RAILWAY_TOKEN` scopes the command to the project and the
  environment.
- `keel serve --bootstrap` starts the HTTP server first and runs the
  bootstrap (download, extract, index build) in a background task, so
  `/api/health` answers within seconds and the Railway health check passes;
  `/api/ready` reports `index_loaded: false` until the build ends. A
  bootstrap that blocks the server start fails the deploy, because the
  index build takes far longer than any health check timeout.

## Writing

- No em dashes or en dashes anywhere, including commit messages and UI
  strings. The pre-commit hook `no-dashes` and the CI job
  `markdown, yaml, shell, dashes` fail on one.
- Google docstrings on every public function and class; `ruff` enforces the
  convention with `pydocstyle` rules.
