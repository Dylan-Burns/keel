## 29. Engineering standards

The panel grades the code, the CI and CD pipeline, the infrastructure, and the Git history, with principal engineers as reviewers. This chapter sets the standard for each, names the tool that enforces it, and lists the files that ship in stage 0 of chapter 28. The Google style guides are the base for every language in the repo. This chapter supersedes the CI workflow of chapter 17.10 and adds files to the layout of chapter 17.6.

### 29.1 Style guides and the tools that enforce them

| Language | Guide | Tools | Where the check runs |
| --- | --- | --- | --- |
| Python | Google Python Style Guide: 80 columns, 4-space indent, Google docstrings, PEP 8 names, module imports, Black or Pyink format | `ruff` for lint and format with the Google docstring convention, `mypy --strict`, `pylint` with the vendored Google `pylintrc` | Pre-commit, CI job `python lint, format, types` |
| TypeScript | Google TypeScript Style Guide: 2-space indent, single quotes, and named exports only. No any (use unknown), interfaces for object types, and import type for types. Names: camelCase and PascalCase. Also JSDoc on exported symbols, `const` and `let`, braces on every block | gts (the Google TypeScript Style package: ESLint flat config and Prettier settings) with the React hooks and jsx-a11y plugins, and tsc in strict mode | Pre-push, CI job `web lint, types, tests, build` |
| HTML and CSS | Google HTML/CSS Style Guide | Prettier, review | Same |
| Shell | Google Shell Style Guide: `#!/bin/bash`, `set -euo pipefail`, a `main` function, 2-space indent, quoted variables | `shellcheck` | Pre-commit, CI job `markdown, yaml, shell, dashes` |
| Markdown | Google Markdown Style Guide: ATX headings, 80 columns, 1 list marker | `markdownlint-cli2` | Same |
| YAML |  | `yamllint --strict` | Same |
| Terraform | HashiCorp style | `terraform fmt`, `terraform validate`, `tflint`, `checkov` | CI workflow `infra` |
| Commit messages | Conventional Commits | `conventional-pre-commit`, `commitlint` | Commit-msg hook, CI job `conventional commits` |
| All text | No em dash or en dash | A `pygrep` hook and a `grep` step | Pre-commit, CI |

### 29.2 Python rules that a reviewer checks

The tools enforce the mechanical rules. The reviewer checks these rules, which no tool checks.

- Import modules, not names: `import pathlib` and then `pathlib.Path(...)`, never `from pathlib import Path`. Exemptions: `typing`, `collections.abc`, `typing_extensions`, `dataclasses`, and `__future__`. No relative imports.
- Each public function and class has a Google docstring with `Args:`, `Returns:`, and `Raises:` sections. The summary line ends with a period.
- No mutable default argument. No bare `except`. No `assert` for validation. A log call uses `%` placeholders, not an f-string.
- Executable logic lives in `main()` behind the `__name__` guard.
- A pydantic model crosses every module boundary, and a frozen dataclass holds internal state. Every public function has full annotations.
- Every exception subclasses `KeelError` (the condition names of chapter 6.5 map to classes with the Error suffix, for example IndexMissing to IndexMissingError) and ends in `Error`.
- Library code has no `print`. Every log record carries the request ID.

### 29.3 Repository foundation files

| File | Purpose |
| --- | --- |
| `pyproject.toml` | Project metadata, pinned dependency groups, and the `ruff`, `mypy`, `pytest`, and `coverage` configuration with the 85% gate |
| `uv.lock`, `.python-version` | Reproducible installs |
| `.pre-commit-config.yaml` | The hooks that mirror CI: format, lint, secrets, YAML, Markdown, shell, dashes, commit messages, and `mypy` and the unit tests on push |
| `.editorconfig`, `.markdownlint.yaml`, `.yamllint.yaml` | Editor and lint settings |
| `commitlint.config.cjs` | The allowed commit types and scopes |
| `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `CHANGELOG.md` | The workflow, the disclosure policy, the MIT license, and the changelog that release-please maintains |
| `.github/workflows/ci.yml` | Lint, types, tests with coverage, audit, web lint, text checks, commit lint, secret scan, container build |
| `.github/workflows/eval.yml` | The nightly gated eval on the mini corpus with the live provider |
| `.github/workflows/codeql.yml` | Static analysis for Python and TypeScript |
| `.github/workflows/release-please.yml`, `.github/workflows/release.yml` | The release PR, the version tag, the image build with SBOM, scan, and provenance |
| `.github/workflows/deploy.yml` | The manual, approved deploy to the pilot host |
| `.github/workflows/infra.yml` | Terraform format, validate, lint, and policy checks |
| `.github/dependabot.yml` | Weekly dependency updates for Python, npm, actions, Docker, and Terraform |
| `.github/PULL_REQUEST_TEMPLATE.md`, `.github/CODEOWNERS`, `.github/ISSUE_TEMPLATE/` | The PR checklist, the required reviewer, and the issue forms |
| `Dockerfile`, `.dockerignore`, `docker-compose.yml` | The multi-stage image that runs as a non-root user, and the hardened compose file |
| `infra/` | The Caddyfile, the systemd timers, the backup script, the Terraform for the pilot host |
| `web/package.json`, `web/eslint.config.js`, `web/tsconfig.json` | The front-end package, lint, and type settings, next to vite.config.ts, playwright.config.ts, and .prettierrc.cjs |
| `scripts/setup_github.sh`, `scripts/fetch_pylintrc.sh` | The repository setup with branch protection, and the vendored `pylintrc` |

The Railway files are `railway.toml` and `.github/workflows/deploy.yml`. The Claude Code files are `.claude/settings.json`, `.claude/skills/`, and `.claude/agents/`, with the stage cards in `docs/STAGES.yaml` and the known traps in `docs/GOTCHAS.md` (chapter 29.10).

### 29.4 Git workflow

1. Keep `main` protected: no direct push, no force push, a linear history, every CI job green, every conversation resolved. `scripts/setup_github.sh` applies these rules.
2. Open 1 branch per stage with the name `<type>/stage-NN-short-name`, for example `feat/stage-07-single-call`. A fix after review stays on the same branch.
3. Write 2 to 5 commits per stage in the order a reviewer reads them. The order is the code, the tests, the docs, the config. Each commit builds and passes the tests on its own, so `git bisect` works.
4. Use Conventional Commits with the scopes in `commitlint.config.cjs`: `feat(parser): cover page period and fiscal math`.
5. Open 1 PR per stage from the template, with the done-when evidence in the body. Merge with rebase, never with squash, so the logical commits survive. In unattended mode, the agent runs the reviewer subagent, then scripts/pr.sh wait and scripts/pr.sh merge (REST calls through gh api, because the GitHub proxy of a cloud session rejects gh pr) instead of \`gh pr merge --rebase --auto\`. GitHub merges the PR when every check is green.
6. Let release-please open the release PR and set the tag. Never tag by hand.
7. With a second maintainer, raise the required approvals to 1 and require a CODEOWNERS review.

### 29.5 The CI and CD pipeline

| Workflow | Trigger | Jobs | Gate |
| --- | --- | --- | --- |
| `ci` | Every PR and every push to `main` | 9 jobs. Python: lint with format and types, tests with coverage, and the dependency audit. Web: lint with types, unit tests, and build, then the Playwright end-to-end tests against the mock provider. Text: the Markdown, YAML, shell, and dash checks, and the commit lint. Then the secret scan and the container build with a smoke test | All jobs are required checks on `main` |
| `eval` | Nightly, push to `main`, manual | The mini index, then `keel eval --gate` with the live provider through the `eval` environment | The chapter 18 gates fail the job |
| `codeql` | PR, push, weekly | Static analysis for Python and TypeScript | Findings show in the Security tab |
| `release-please` | Push to `main` | The release PR with the changelog and the version bump | A merge creates the tag |
| `release` | A version tag | Image build and push to GHCR, SPDX SBOM, Trivy scan, build provenance attestation, release assets | A high or critical vulnerability fails the release |
| `deploy` | Manual with a version input | A Railway deploy from the tagged commit through the Railway CLI, then a smoke test over HTTPS. The workflow \`deploy-aws.yml\` is the SSH alternative for the AWS host | The `production` environment requires a reviewer |
| `infra` | A change under `infra/` | Terraform format, validate, `tflint`, `checkov` | Format and validate fail the job, and `checkov` reports |

### 29.6 Container and infrastructure

- The image builds in 3 stages. A Node stage runs the Vite build of the front-end. A Python builder runs `uv sync --frozen`. A slim runtime copies web/dist from the Node stage and runs as the `keel` user. It has a health check, no shell for the user, and the model cache on a mounted volume.
- The compose file runs the app read-only, with all capabilities dropped. It sets `no-new-privileges`, a 4 GB memory limit, and the API bound to the loopback interface. Caddy terminates TLS with Let's Encrypt, sets the security headers, and passes SSE through without a buffer.
- Two systemd timers run `keel refresh` at 02:00 and the backup at 02:30. The backup script takes a consistent SQLite snapshot and writes a checksummed archive to S3. The restore procedure is in `infra/README.md`, and the engineer tests it once before the pilot.
- Terraform creates 1 EC2 instance (Ubuntu 24.04, encrypted root volume, IMDSv2 required). It creates an Elastic IP and a security group that limits SSH to the admin CIDR. It creates an IAM instance profile that can only write the backup prefix. It creates an S3 bucket with versions, encryption, a public access block, and a 90-day lifecycle. It creates an optional Route 53 record.
- Railway is the default pilot host (chapter 29.9). The AWS host is the alternative. Without a purchased domain, the AWS host uses a free `sslip.io` name so Caddy can get a certificate. Vercel cannot host the API, because its functions have no persistent disk and a bundle limit far below PyTorch. The laptop demo needs no host at all.

### 29.7 Why Python and not Go

The model call takes more than 95% of the latency of a question. Retrieval takes milliseconds, and the reranker takes 1 to 3 seconds of PyTorch on a CPU. A faster runtime cannot change the first number. Go cannot run the embedding model or the reranker without cgo bindings to ONNX Runtime or a Python sidecar. The brief defaults to Python with FastAPI. The role is AI work, and the eval tools are Python-native. The code must read well in a 1-hour walk. At pilot scale, FastAPI handles the concurrency, and the provider API and the reranker CPU are the bottlenecks in any language. Decision D-05 records Go as the alternative. Go earns a place later for a high-volume ingestion worker, which chapter 22 can add.

### 29.8 Stage 0 procedure

1. Copy the starter files into a new directory, and run `git init`.
2. Set the GitHub handle in `.github/CODEOWNERS`, and fill the `TODO` values in `config/keel.yaml` and `.env`.
3. Run `uv sync --all-extras`, `npm install --prefix web` (this creates web/package-lock.json, which the first commit includes), npx --prefix web playwright install chromium, and `scripts/fetch_pylintrc.sh`. Commit the vendored `pylintrc`.
4. Run `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push`.
5. Make the first commit: `chore(stage-00): repository foundation`.
6. Run `scripts/setup_github.sh <owner> keel private` to create the repository, protect `main`, and create the `eval` and `production` environments. Add the secrets with `gh secret set`.
7. Open the first PR from a branch `chore/stage-00-foundation`, confirm that every CI job runs, and merge with a rebase. The `ci` jobs must pass on an empty `keel` package with 1 placeholder test, which stage 1 replaces.

### 29.9 Railway deployment, the default pilot host

Railway builds the `Dockerfile`, attaches 1 persistent volume, and gives an HTTPS subdomain with 1 click. The pilot needs no DNS access, no certificate, and no SSH key. The AWS path in `infra/terraform/` stays in the repo as the alternative that the panel can read.

1. Create a Railway project from the GitHub repository. Turn off the automatic deploy on push, so releases stay explicit through `deploy.yml`.
2. Add a volume with the mount path `/data`, and set the service memory limit to 4 GB or more.
3. Set the service variables. These are the secrets from `.env`, `KEEL_CORPUS__DIR=/data/corpus/edgar`, `KEEL_INDEX__DIR=/data/index`, `KEEL_LOGS__DIR=/data/logs`, `KEEL_EDGAR__CACHE_DIR=/data/cache/edgar`, `HF_HOME=/data/cache/hf`, and `KEEL_CORPUS__URL`. The last one holds the download URL of the corpus zip.
4. Put the corpus zip at the download URL. The URL is a Railway bucket with a signed URL, or a release asset of the repository. The host of the URL goes into the outbound allow list of control S-11.
5. Generate the domain in the Railway settings, and record the URL as `KEEL_HOSTNAME` in the GitHub variables.
6. On the first start, `keel bootstrap` (the Railway start command runs the same routine through the --bootstrap flag of keel serve) starts the HTTP server first. Then a background task downloads the zip when `/data/corpus` is empty. The task extracts it with the zip safety checks. It builds the index when `/data/index/current` is absent. During the build, /api/health answers 200 at once and /api/ready reports index\_loaded false. The Railway health check passes. The page shows the index-not-built state of chapter 14.6 until the build ends. Later starts find the index and skip the build.
7. The in-app scheduler runs `refresh` at 02:00 and the backup at 02:30. The backup writes the checksummed archive of `infra/backup.sh` to an S3-compatible bucket (a Railway bucket) with the credentials from the service variables. The scheduler is a config flag, off by default, on for the Railway service.
8. `deploy.yml` checks out the tagged commit and runs `railway up` with a project token from the `production` environment. Then it runs the smoke test over HTTPS.

NOTE: A Railway cron service cannot share the volume of the app service. The in-app scheduler is the reason the refresh and the backup run inside the app on Railway. On the AWS host, the systemd timers do the same work from outside the app.

### 29.10 Claude Code configuration for the build

The engineer builds Keel with Claude Code. These files make the agent faster and more accurate, and they ship in stage 0.

| File | Purpose |
| --- | --- |
| `CLAUDE.md` | The rules of the repo, the standards, the stage workflow, and the placeholders. Kept short, because the chapters hold the detail. |
| `docs/STAGES.yaml` | 1 card per stage. A card names the branch, the chapters to read, and the files to create. It names the test names, the done-when evidence, and the commit plan. The agent reads the card, then only the sections the card names, instead of the whole plan. |
| `docs/GOTCHAS.md` | The known traps: the PyTorch CPU wheel index, the FTS5 build of SQLite, and the revision pin of the Hugging Face models. Also the bge query prefix, SSE through uvicorn, the forced tool call of the Anthropic SDK, and the SEC request rules. |
| `.claude/settings.json` | Permission rules that allow the build commands without a prompt and deny force pushes, recursive deletes, and reads of `.env`. Three hooks. A PreToolUse guard blocks force pushes, pushes to main, skipped commit hooks, and deletes outside the generated directories. A PostToolUse hook formats and lints every edited file. A Stop hook keeps an unattended session at work until the build report says complete or blocked. |
| `.claude/skills/stage/SKILL.md` | The `/stage NN` command, which expands the stage card into the session prompt with the branch, the chapters, the done-when evidence, and the PR step. |
| `.claude/skills/review/SKILL.md` | The `/review` command, which runs the PR checklist against the diff before the PR opens. |
| `.claude/agents/reviewer.md` | A read-only reviewer subagent for the Google style rules that no tool checks, and for the chapter 19 test names. |
| `.claude/agents/corpus-analyst.md` | A read-only subagent that inspects corpus files and reports counts and snippets, so the main context stays small. |

Rules for the agent that these files encode:

- Start each stage with the \`/stage NN\` command. The command re-reads CLAUDE.md, the stage card, and the build report. The stage starts from the repository state and not from memory, in a new session or in a long one.
- Use the corpus-analyst subagent for any look at a corpus file, and the reviewer subagent before every PR.
- Read the installed SDK and the provider documentation before any provider code, and never guess a parameter name.
- Run `uv run pre-commit run --all-files` before every commit, and `make test` before every PR.

### 29.11 Unattended build

The build runs without the engineer at the keyboard and without the laptop. The repository holds the state, so any session can continue from the point where the last one stopped.

1. Where the build runs: a Claude Code cloud session (claude.ai/code) with the repository connected. The session runs in Anthropic's cloud, continues with the laptop closed, and the engineer follows it from the phone. The cloud environment needs network access set to Custom with the default list plus `huggingface.co`, `hf.co`, `download.pytorch.org`, `www.sec.gov`, and `data.sec.gov` (or Full). It needs these environment variables: `ANTHROPIC_API_KEY`, `KEEL_API_TOKEN`, `KEEL_EDGAR__USER_AGENT`, `KEEL_UNATTENDED=1` (turns on the Stop hook), `GH_TOKEN` (a fine-grained token for the repository with read and write on contents, pull requests, actions, and workflows), `BASH_DEFAULT_TIMEOUT_MS=600000`, and `BASH_MAX_TIMEOUT_MS=3600000` (the index build runs longer than the 2-minute default).
2. The corpus: a release asset `corpus-v1` of the private repository. `keel bootstrap` downloads it with `gh release download` when `GH_TOKEN` has a value, or from `KEEL_CORPUS__URL`.
3. The command: `/build-all` (file `.claude/skills/build-all/SKILL.md`). It runs stages 0 to 22 in order through `/stage NN`. After each stage it runs the pre-commit hooks, `make test`, and the reviewer subagent. Then it runs `scripts/pr.sh open`, `scripts/pr.sh wait`, and `scripts/pr.sh merge`, then `git pull` on `main`. Then the next stage starts. It never stops for a person. The PR steps go through the GitHub REST API. The GitHub proxy of a cloud session rejects GraphQL, and with it `gh pr` and `gh issue`.
4. State: `docs/BUILD_REPORT.md` has 1 entry per finished stage, and its `Status:` line names the next stage. A session that starts with `/build-all` reads the report first and continues from the first stage without an entry. A stage branch that already exists on `origin` continues. The session does not recreate it. An open PR for it goes straight to the wait and merge steps.
5. Failure policy: a stage gets 3 attempts at its done-when evidence. After the third failure, the agent records the failure and the error in the build report. If the stage card says `cuttable: true`, the agent applies the chapter 28 cut and continues. Otherwise it writes `Status: blocked at stage N: <reason>` through a docs-only PR to `main` (branch `docs/build-status`), so the watchdog and the engineer see it, and stops.
6. The 2 human gates: the Railway project with its token (the engineer creates them once, before the build. Without the token, stage 21 records the deploy as open and the build continues) and the approval of the production deploy in GitHub (the engineer approves from the phone).
7. The watchdog: a routine at claude.ai/code/routines on the same repository and environment. Its cron runs every 3 hours, set through `/schedule update`. Its prompt is in START\_HERE.md. Each run is a fresh cloud session. It reads the build report on `main`. It exits when the status is complete or blocked. It also exits when any branch has a commit newer than 3 hours (a build session is active). Otherwise it runs `/build-all`. The 3-hour window covers the longest step, the full index build. The watchdog restarts a build that a usage limit or a reclaimed VM stopped. Routines draw on the same subscription usage as sessions, so a usage limit pauses both until the window resets.

NOTE: The review that the attended mode puts between stages moves to the end in unattended mode. The engineer reads the merged PRs in order, with the build report beside them, before the rehearsal of stage 16.
