## What changed

<!-- 2 to 5 lines: what the reviewer sees in the diff and why. -->

## Evidence

<!-- Test output, measured numbers, or a screenshot path. -->

## Checklist

- [ ] `make test` and `npm run check --prefix web` green locally; CI green
- [ ] New tests for new behavior; a new edge case has its named test in docs/EDGE_CASES.md
- [ ] Still exactly 1 model request per question (`test_single_request`)
- [ ] Google style: docstrings on public APIs, module imports, no mutable defaults
- [ ] No secrets, no em dashes, no commented-out code
- [ ] A changed decision is recorded in docs/DECISIONS.md with its reason
- [ ] Commits follow Conventional Commits and each one builds on its own
