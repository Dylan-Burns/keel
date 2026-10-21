# Build report

Status: next stage 0

One entry per stage of `docs/28_build_sequence.md`. Claude Code appends to this file after each stage. The panel reads it during the demo code walk.

The status line above is the state of the build. It takes one of three forms, and the Stop hook reads it in unattended mode:

- `Status: next stage N`
- `Status: blocked at stage N: <reason>`
- `Status: complete <YYYY-MM-DD>`

Entry format:

```text
## Stage N: <name>
- Built: <modules and files>
- Tests: <count passing> (<new tests>)
- Measured: <file counts, chunk count, build time, recall, latency, cost, as applicable>
- Deviations from the specification: <what, why, which decision or chapter it touches>
- Cut or deferred: <what, per the cut order>
- Attempts: <1 to 3, with the failure of each earlier attempt>
```

## Gaps

Values that were not available when the build needed them, and what the build did instead.

| Gap | Effect | Resolution |
| --- | --- | --- |

## Decisions taken without review

Decisions that CLAUDE.md says to ask about, taken in unattended mode. One line each: the decision, the conservative option taken, the stage.

## Placeholders resolved

| Placeholder | Value or status |
| --- | --- |
| corpus/edgar_corpus.zip present | |
| llm.model | |
| llm.fallback_model | |
| llm.judge_model | |
| embedding.revision | |
| reranker.revision | |
| edgar.user_agent | |
| demo.add_companies | |
| deploy.host | railway |
| prices checked_on | |
| Assumption A-15 (NVDA 10-K filed February 2026 in the zip) | |
