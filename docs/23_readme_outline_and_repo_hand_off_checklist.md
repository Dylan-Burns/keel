## 23. README outline and repo hand-off checklist

The README is the first file that the panel and the client read. The README gives the 3-command start, the single-call statement, and the map of the docs. The hand-off checklist lists what the repo must hold on delivery day.

### 23.1 README outline

```
# Keel

Grounded answers to business questions about SEC filings, from 1 LLM call.

## What Keel does (5 lines)
## The single-call constraint and how Keel obeys it (D-01, with the list of pre-call steps)
## Quick start
   1. cp .env.example .env and set ANTHROPIC_API_KEY and KEEL_API_TOKEN
   2. make demo            (builds the index on the first run, about 27 minutes on a CPU)
   3. open http://localhost:8000
   Alternative: docker compose up
## Example request (the curl command from chapter 14)
## The 3 example questions and what to look at in each answer
## Corpus facts and known limits (54 companies, 245 indexed filings, 1 quarantined, dates 2022-02 to 2026-02)
## Architecture (the Mermaid diagram and 1 paragraph)
## Configuration (config/keel.yaml keys and the KEEL_ environment overrides)
## Commands (keel inventory, parse, chunk, index, understand, retrieve, ask, eval, serve, warm-cache, doctor, add, refresh, export, bootstrap)
## Evaluation (how to run keel eval, the gates, and where the report lands)
## Prompt log (link to docs/PROMPT_LOG.md)
## Offline demo mode (KEEL_OFFLINE=1 and keel warm-cache)
## Security notes (the Timebox controls and the production list)
## Docs map (docs/01 to docs/29, one file per chapter of the plan)
## Decisions and assumptions (link to docs/04_assumptions_and_decisions_log.md)
## Questions for the panel (link to docs/05_questions_for_the_panel.md)
## License and data source (SEC EDGAR, the manifest license key, A-05)
```

### 23.2 Repo hand-off checklist

- [ ] `README.md` with the quick start verified on a clean machine.
- [ ] `docs/01_reader_map_and_executive_summary.md` to `docs/29_engineering_standards.md`, 1 file per chapter of this plan, with the file names that \`scripts/split\_plan.py\` writes.
- [ ] `docs/PROMPT_LOG.md` with the measured values and run IDs for each prompt version.
- [ ] `docs/EVALUATION.md` with the latest `eval/report.md` summary and the gate status.
- [ ] `docs/RUNBOOK.md` with the pre-flight checklist, the narrative, and the drills.
- [ ] `docs/adr/` with the first 6 records.
- [ ] `prompts/` with the final system block, the user block, the schema, and the judge prompt. Each file name holds a version.
- [ ] `config/` with every dictionary and the pinned model revisions.
- [ ] `eval/golden.yaml` with 28 questions, and `eval/labels/` with the labels and their index version.
- [ ] `tests/` with 40 or more tests, `tests/fixtures/snippets/` from real files, and `tests/fixtures/mini_corpus/` with 3 small filings.
- [ ] `.github/workflows/ci.yml` green on the main branch.
- [ ] `docker-compose.yml` and `Dockerfile` verified with `docker compose up`.
- [ ] `demo/answer_cache/` with 28 entries, `demo/static/` with 3 answers, and `demo/recording.mp4`.
- [ ] `index/current/manifest.json` with the checksums, and the build report with the quarantine list and the warnings.
- [ ] `logs/audit.jsonl` from the pre-flight run, with the request ID of each example question.
- [ ] `.env.example` with empty values, and no secret anywhere in the history (`gitleaks` clean).
- [ ] A tag `demo-2026-10` on the commit that the demo runs.
