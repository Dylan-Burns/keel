## Stage

<!-- Stage number and name from docs/28_build_sequence.md, for example "Stage 7: single call and validation" -->

## What changed

<!-- 2 to 5 lines. What the reviewer sees in the diff, not a restatement of the spec. -->

## Done-when evidence

<!-- Paste the output that satisfies the stage's done-when column: command output, counts, a screenshot path. -->

## Checklist

- [ ] One stage only; no roadmap items from chapter 22 unless chapter 28 names them
- [ ] `make test` green locally; CI green
- [ ] New tests for new behavior; edge cases from chapter 19 have their named tests
- [ ] Google style: docstrings on public APIs, module imports, no mutable defaults
- [ ] No secrets, no em dashes, no commented-out code
- [ ] `docs/BUILD_REPORT.md` updated for this stage
- [ ] Deviations from the specification recorded in `docs/04_*.md` with a reason
- [ ] Commits follow Conventional Commits and each one builds on its own
