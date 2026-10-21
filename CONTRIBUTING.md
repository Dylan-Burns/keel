# Contributing

This repository is built to withstand review by principal engineers. The rules
below are enforced by tooling where tooling can, and by review where it
cannot. If a rule here and a tool disagree, fix the tool configuration in the
same PR.

## Git workflow

- Trunk-based. `main` is protected: no direct pushes, no force pushes, linear
  history, CI green, every conversation resolved before merge.
- One branch per stage of `docs/28_build_sequence.md`, named
  `<type>/stage-NN-short-name`, for example `feat/stage-07-single-call`.
  Fixes after review stay on the same branch. Branches live for one PR.
- One PR per stage, from the template. The PR body carries the done-when
  evidence; `docs/BUILD_REPORT.md` carries it permanently.
- Commits follow Conventional Commits with the scopes in
  `commitlint.config.cjs`: `feat(parser): cover page period and fiscal math`.
  Each commit builds and passes tests on its own, so `git bisect` works. A
  stage is usually 2 to 5 commits: the code, its tests, its docs, and any
  config, in the order a reviewer wants to read them.
- Merge with "rebase and merge" to keep the logical commits and a linear
  history. Never squash a multi-commit stage into one.
- Tags and releases come from release-please; never tag by hand.
- With a second maintainer, raise the required approvals to 1 in the branch
  protection and require a CODEOWNERS review.

## Code standards

Keel follows the Google style guides for every language in the repo. The
tooling enforces the mechanical rules; the reviewer enforces the rest.

| Language | Guide | Tooling |
| --- | --- | --- |
| Python | [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) | `ruff` (lint and format, 80 columns, Google docstrings), `mypy --strict`, `pylint` with Google's `pylintrc` |
| TypeScript | [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html) | `gts` (ESLint flat config and Prettier) plus the rules in `web/eslint.config.js`, `tsc --noEmit` strict, Vitest, Playwright |
| HTML and CSS | [Google HTML/CSS Style Guide](https://google.github.io/styleguide/htmlcssguide.html) | Prettier, review |
| Shell | [Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html) | `shellcheck`; `set -euo pipefail`, a `main` function, 2-space indent |
| Markdown | [Google Markdown Style Guide](https://google.github.io/styleguide/docguide/style.html) | `markdownlint-cli2` |
| YAML | | `yamllint --strict` |
| Terraform | | `terraform fmt`, `terraform validate`, `tflint`, `checkov` |

Python rules that reviewers check because no tool does:

- Import modules, not names: `import pathlib` then `pathlib.Path(...)`, never
  `from pathlib import Path`. Exemptions: `typing`, `collections.abc`,
  `typing_extensions`, `dataclasses`, and `__future__`. No relative imports.
- Google docstrings with `Args:`, `Returns:`, `Raises:` on every public
  function and class; the summary line ends with a period.
- No mutable default arguments. No bare `except`. No `assert` for
  validation. Logging calls use `%` placeholders, not f-strings.
- Executable logic lives in `main()` behind `if __name__ == "__main__":`.
- Public types are pydantic models at module boundaries and frozen
  dataclasses inside; every public function is fully annotated.
- Exceptions subclass `KeelError` and end in `Error`.
- No print in library code; `logging` with the request ID in every record.
- No em dashes or en dashes anywhere, including comments and commit messages.

## Tests

- `tests/unit` for pure functions and parser rules on real 2 KB snippets.
- `tests/integration` for the mini corpus, the API with the mock provider,
  the stream, and the reliability paths. Tests never touch the network.
- `tests/eval` for anything that needs the full index or the live provider;
  marked `eval` and excluded from the PR run.
- Coverage on `keel/` stays at or above 85%. A PR that lowers it explains why.
- Every edge case in `docs/19_edge_case_register.md` has the test named in
  its row; a new edge case adds a row and a test together.

## Definition of done for a stage

1. The done-when evidence from `docs/28_build_sequence.md` is in the PR body.
2. `make test` passes locally; CI is green.
3. `docs/BUILD_REPORT.md` has the stage entry with measured numbers.
4. Any deviation from the specification is recorded in
   `docs/04_assumptions_and_decisions_log.md` with a reason.
5. No secret, no dash, no commented-out code, no TODO without a link.

## Local setup

```text
uv sync --all-extras
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
npm install --prefix web
npx --prefix web playwright install chromium
scripts/fetch_pylintrc.sh
make test
```
