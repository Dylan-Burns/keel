# Start here

The plan is split into `docs/01_*.md` to `docs/29_*.md`. The stage cards in
`docs/STAGES.yaml` index it. The repository foundation (CI, container,
Railway and AWS infrastructure, standards, Claude Code configuration) is in
place; stage 0 turns it on.

Two ways to run the build:

- Unattended (recommended, chapter 29.11): one Claude Code cloud session
  runs stages 0 to 22 without a stop, merges each PR when CI is green, and
  a scheduled task restarts it if it dies. The laptop can be closed.
- Attended: Claude Code on the laptop, one stage per prompt, a review
  between stages.

## 1. Create the repository (once, on the laptop)

1. `git init keel && cp -r keel-starter/. keel/ && cd keel`
2. Put the corpus at `corpus/edgar_corpus.zip`. Do not extract it by hand.
3. Copy `.env.example` to `.env` and fill in the two secrets. Fill the
   `TODO` values in `config/keel.yaml`. If you do not know a value, leave the
   `TODO`; the build records the gap and continues.
4. Install the tools once (`npm install` creates `web/package-lock.json`,
   which the first commit includes):
   `uv sync --all-extras && npm install --prefix web && npx --prefix web playwright install chromium && scripts/fetch_pylintrc.sh && uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push`
5. First commit: `git add -A && git commit -m "chore(stage-00): repository foundation"`
   (the hooks run; fix what they report before the commit lands).
6. Create the GitHub repository, the branch protection, the environments,
   and the corpus release: `scripts/setup_github.sh Dylan-Burns keel private`
7. Create one fine-grained GitHub token for this repository with read and
   write on contents, pull requests, actions, and workflows. It serves two
   purposes: the cloud session uses it as `GH_TOKEN`, and release-please
   uses it as `RELEASE_PLEASE_TOKEN` so the release PR can pass CI and the
   tag can start the release build:
   `gh secret set RELEASE_PLEASE_TOKEN` and `gh secret set ANTHROPIC_API_KEY --env eval`.
   For the pilot deploy, later: `gh secret set RAILWAY_TOKEN --env production`
   and `gh variable set KEEL_HOSTNAME --body <domain>`.

## 2. Unattended build in a cloud session

1. Open claude.ai/code, connect the `Dylan-Burns/keel` repository, and
   create a cloud environment for it. In the environment dialog:
   - Network access: `Custom`, with "Also include default list of common
     package managers" checked, and these domains: `huggingface.co`,
     `hf.co`, `download.pytorch.org`, `www.sec.gov`, `data.sec.gov`.
     (`Full` also works.) `api.anthropic.com` and GitHub need no entry.
   - Environment variables: `ANTHROPIC_API_KEY`, `KEEL_API_TOKEN`,
     `KEEL_EDGAR__USER_AGENT` (name and email), `KEEL_UNATTENDED=1` (turns
     on the Stop hook that keeps the session at work until the build report
     says complete or blocked), `GH_TOKEN` (the token from step 7 above; it
     lets the session open and merge PRs through the REST API and download
     the corpus release), `BASH_DEFAULT_TIMEOUT_MS=600000`, and
     `BASH_MAX_TIMEOUT_MS=3600000` (the index build runs longer than the
     2-minute command default).
   - Setup script (optional, cached): `uv sync --all-extras && npm ci --prefix web && npx --prefix web playwright install --with-deps chromium`.
2. Start a session in that environment with this prompt:

   ```text
   /build-all
   ```

   The command runs stages 0 to 22 in order, opens 1 PR per stage, merges
   each PR when CI is green, and writes `docs/BUILD_REPORT.md` as it goes.
   Close the laptop. Follow the PRs from the phone.

3. The watchdog. Create a routine at claude.ai/code/routines on the same
   repository and environment: schedule preset "hourly", then run
   `/schedule update` from the CLI to set the cron to every 3 hours
   (`0 */3 * * *`). Its prompt:

   ```text
   Read docs/BUILD_REPORT.md on main. If the Status line says complete or blocked, stop and say why.
   Run `git fetch --all` and `git for-each-ref --sort=-committerdate --format='%(committerdate:iso8601) %(refname:short)' refs/remotes/origin | head -n 1`.
   If the newest commit on any branch is less than 3 hours old, a build session is active: stop.
   Otherwise run /build-all. It continues from the first stage without an entry in the build report, resumes a stage branch that exists on origin, and uses the branch names from docs/STAGES.yaml, never a claude/ branch.
   ```

   A routine run is a fresh cloud session. Usage limits pause routines and
   sessions alike until the window resets; the next run picks the build up.

4. Two human gates remain: create the Railway project with a volume at
   `/data` and add `RAILWAY_TOKEN` (infra/README.md) before stage 21, and
   approve the production deploy in GitHub when the workflow asks. Without
   the token, stage 21 records the deploy as pending and the build goes on.
5. When the status line says complete: read the merged PRs in order with
   the build report beside them, then run the rehearsal of stage 16.

## 3. Attended build on the laptop

Open Claude Code in the repository and paste, one stage at a time:

```text
/stage 0
Stop after each PR and wait for my review.
```

Review the PR, merge with rebase, then `/stage 1`, and so on. The stage
cards carry the branch, the chapters, the tests, the evidence, and the
commit plan, so the prompt needs nothing else. If a review turns up a
problem, say what is wrong and ask for a fix commit on the same branch.

## Re-export after a doc edit

Export the Claude doc as Markdown, save it as `plan.md` in the repository
root, run `python scripts/split_plan.py plan.md docs/`, then delete
`plan.md`. The stage cards and `docs/GOTCHAS.md` are not part of the export
and survive the split.
