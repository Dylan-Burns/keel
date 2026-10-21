---
description: Run one build stage from docs/STAGES.yaml, from the repository state
argument-hint: <stage number 0 to 22>
---

Run stage $ARGUMENTS of the Keel build.

1. Read `CLAUDE.md`. Read the card with `id: $ARGUMENTS` in `docs/STAGES.yaml`. Read `docs/BUILD_REPORT.md`. If the report already has an entry for stage $ARGUMENTS, say so and go to step 11.
2. Read only the docs the card's `read` field names, in full. Do not read other chapters unless a card entry points there. For any look at a corpus file, use the `corpus-analyst` subagent and work from its report.
3. `git fetch origin`. If the card's branch exists on `origin`, check it out and continue from its state. An earlier session built part of this stage. Read its log and its diff against `main` before you add work. If `scripts/pr.sh number` prints a PR number for it, go to step 10. Otherwise `git checkout main && git pull --ff-only`. Then create the branch the card names.
4. Build what the card's `build` field lists, per the chapters. Follow the code standards in `CLAUDE.md`. Every test name in the card's `tests` field must exist and pass. Add the tests the chapters name for this stage, even when the card omits them.
5. Make the commits in the card's `commits` plan, in that order. Before each commit: `uv run pre-commit run --all-files` and `make test` pass. One failed check means fix, then commit; never `--no-verify`. Push the branch after every commit (`git push origin HEAD`), so a reclaimed session loses nothing.
6. Produce the done-when evidence: run each command in the card's `evidence` field and keep the output. Compare the numbers with the chapter and state every discrepancy.
7. Append the stage entry to `docs/BUILD_REPORT.md` (what was built, test count, measured numbers, deviations with reasons, attempts), set the status line at the top to `Status: next stage <N+1>`, and commit it as `docs(stage-NN): build report`.
8. Run `/review`. Fix what it reports with a commit on the same branch.
9. Write the PR body from `.github/PULL_REQUEST_TEMPLATE.md` to a file. Put the evidence output under the done-when heading. Then open the PR: `scripts/pr.sh open "<type>(stage-NN): <title>" <body file>`. The script uses the GitHub REST API. `gh pr` does not work in a cloud session.
10. Review mode. Unattended (the default): run `scripts/pr.sh wait <number>`. It waits for every check. Then run `scripts/pr.sh merge <number>`. It makes a rebase merge and leaves `main` checked out and current. If a check fails, read the log with `gh run view <run id> --log-failed` (a REST command). Fix it on the same branch, push, and wait again. After 3 failed attempts, apply the failure policy in `CLAUDE.md`. Attended (the prompt said "stop after each PR"): stop after the PR opens.
11. Report in 2 lines: "stage $ARGUMENTS merged" (or "stage $ARGUMENTS open as PR #N" in attended mode) and the next stage number. Under `/build-all`, continue with the next stage at once; alone, stop here.

Never push to `main`. Never force push. Never merge a PR that has a red check. Never skip a test to make a check green.
