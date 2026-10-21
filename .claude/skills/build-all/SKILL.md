---
description: Run every remaining build stage without a stop (unattended mode, chapter 29.11)
---

Run the Keel build from the first unfinished stage to stage 22 without a stop for a person.

1. Read `CLAUDE.md` and `docs/BUILD_REPORT.md`. The `Status:` line names the next stage, and the first stage with no entry in the report confirms it. If the status is `complete` or `blocked`, say so and stop.
2. Check the environment once. Run `gh auth status` or `echo $GH_TOKEN`. Run `uv run keel doctor` if the package exists. Make sure that `corpus/edgar_corpus.zip` exists, or download it with `gh release download corpus-v1 --pattern edgar_corpus.zip --dir corpus` or from `KEEL_CORPUS__URL`. Record a missing value in the build report under "Gaps". Continue with the stages that do not need it.
3. For each remaining stage N in order: run the steps of `/stage N` in unattended mode. `/stage` resumes a branch that already exists on `origin` and an open PR for it. After the merge, start the next stage at once. Do not ask whether to continue.
4. Failure policy: 3 attempts per stage at its done-when evidence. After the third failure, record the failure and the error in the build report. If the card says `cuttable: true`, apply the chapter 28 cut and continue. Otherwise write the blocked status on `main`. Run `git checkout main && git pull --ff-only`. Create the branch `docs/build-status`. Set `Status: blocked at stage N: <reason>` in `docs/BUILD_REPORT.md`, with the failed attempts under the stage heading. Commit `docs(stage-NN): blocked status`. Run `scripts/pr.sh open`, `scripts/pr.sh wait`, and `scripts/pr.sh merge`. Then stop. The watchdog reads this status and does not restart.
5. Decisions that `CLAUDE.md` says to ask about: take the most conservative option. Record it under "Decisions taken without review" in the build report. Continue.
6. At the end of stage 21, find the open release-please PR: `gh api repos/{owner}/{repo}/pulls?state=open --jq '.[] | select(.user.login | test("release-please")) | .number'`. Run `scripts/pr.sh wait` and `scripts/pr.sh merge` on it. Wait for the `release` workflow run on the new tag (`gh run list --workflow release.yml`, a REST command). Then start the deploy: `gh workflow run deploy.yml -f version=<version>`. The production deploy waits for a human approval. Do not wait for it. Record the deploy as open in the build report.
7. When stage 22 merges, set `Status: complete <YYYY-MM-DD>` on a branch `docs/build-complete`, open the PR with `scripts/pr.sh open`, wait, merge, and stop.

Keep the context of each stage small. Read the card and the named chapters only. Use the `corpus-analyst` subagent for corpus files. Summarize long command output to the numbers that the evidence needs.
