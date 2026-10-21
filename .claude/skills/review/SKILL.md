---
description: Review the current branch against the PR checklist before the PR opens
---

Review the current branch against `main` before the PR opens.

1. Run `git diff main...HEAD --stat` and `git log main..HEAD --oneline`. Confirm 2 to 5 commits, each with a Conventional Commits header and a scope from `commitlint.config.cjs`, in reviewer order (code, tests, docs, config).
2. Write the diff to a file: `git diff main...HEAD > .claude/review.diff`. Write the log to `.claude/review.log`. Ask the `reviewer` subagent to review those two files. It checks the diff against the checklist in `.github/PULL_REQUEST_TEMPLATE.md`. It checks the Google style rules in `CLAUDE.md` that no tool checks. These are module imports, docstring sections, exception names, and named exports. Also no mutable defaults, no validation with `assert`, and no `any`. It checks the chapter 19 test names for this stage. It checks the non-negotiables. These are one model request, no LLM call outside the answer, and validated citations. Also no secrets in code or logs, and no dashes. The subagent is read-only. It reads the files and reports.
3. Fix every finding with a commit on the same branch (`fix(<scope>): ...` or `refactor(<scope>): ...`). A finding that is wrong gets a one-line reason in the PR body, not silence.
4. Run `uv run pre-commit run --all-files` and `make test` once more. Delete `.claude/review.diff` and `.claude/review.log`. Report the result in one paragraph: findings fixed, findings declined with reasons, and the test count.
