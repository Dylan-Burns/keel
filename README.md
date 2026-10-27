# Keel

Grounded answers to business questions about SEC filings, from 1 LLM call.
Live at <https://d1otueg71oygkx.cloudfront.net>; the access token was
sent by email.

## Submission deliverables

| Deliverable | Where |
| --- | --- |
| README with setup and run instructions | This file: the live site above, [Local setup](#local-setup), and [Run locally](#run-locally) |
| Indexing code | [`keel/parsers/`](keel/parsers/), [`keel/sections.py`](keel/sections.py), [`keel/chunker.py`](keel/chunker.py), [`keel/indexer.py`](keel/indexer.py), [`keel/stores/`](keel/stores/) |
| Retrieval code | [`keel/understanding.py`](keel/understanding.py), [`keel/retriever.py`](keel/retriever.py), [`keel/context.py`](keel/context.py) |
| Log of prompt iterations | [`docs/PROMPT_LOG.md`](docs/PROMPT_LOG.md) |
| Final prompt template | [`prompts/answer_system_v1.5.1.md`](prompts/answer_system_v1.5.1.md), [`prompts/answer_user_v1.5.1.md`](prompts/answer_user_v1.5.1.md), [`prompts/answer_schema_v1.5.1.json`](prompts/answer_schema_v1.5.1.json) |
| Front-end | [`web/`](web/), deployed at the live site above and served locally by `keel serve` |
| Example request ready to execute | [`scripts/example_request.sh`](scripts/example_request.sh); see [Example request](#example-request) |
| Notes on how quality was evaluated | [Evaluation](#evaluation) below; method in [`docs/18_evaluation.md`](docs/18_evaluation.md), last run in [`eval/report.md`](eval/report.md) |
| Assumptions and decisions | [`docs/04_assumptions_and_decisions_log.md`](docs/04_assumptions_and_decisions_log.md) |
| Business value for a PE firm | [`docs/02_business_context_and_value_creation_for_a_pe_firm.md`](docs/02_business_context_and_value_creation_for_a_pe_firm.md) |
| Future state and capabilities | [`docs/22_future_state_roadmap.md`](docs/22_future_state_roadmap.md) |

Each question makes exactly 1 model request. Question understanding,
retrieval, reranking, and citation validation are code with no LLM in
them. The mock provider counts requests and `test_single_request` guards
the rule in CI.

## Example request

One command, with the access token from the email in place of the
placeholder. It needs `curl` and `jq`.

```bash
KEEL_API_TOKEN=<access token from the email> scripts/example_request.sh
```

The script sends the request the web page sends to the live site: a
streamed `POST /api/ask` with the answer cache off, so the run is a live
answer from 1 model request. It prints the stream events, then the direct
answer, the findings per company, the gaps, and the audit line with the
model request count. The token is the same one the page takes as its
access token. A question in quotes after the script replaces the default
one, `--json` prints the full record, and `--local` sends the request to
a local `keel serve` instead.

The same request with curl:

```bash
curl -N -X POST https://d1otueg71oygkx.cloudfront.net/api/ask \
  -H "Authorization: Bearer <access token from the email>" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"question": "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?", "options": {"use_cache": false}}'
```

## Local setup

Requirements: Python 3.12, `uv`, Node 22, and the corpus zip at
`corpus/edgar_corpus.zip`.

```bash
cp .env.example .env        # set ANTHROPIC_API_KEY and KEEL_API_TOKEN
uv sync --all-extras
uv run keel doctor --download-models   # the 2 pinned Hugging Face models
```

`KEEL_API_TOKEN` is any string you choose; the local server accepts it
as the bearer token, and you paste the same value into the page. It is
not the token of the live site. `uv run keel doctor` checks FTS5, the
models, the keys, and the port.

## Run locally

```bash
make demo                   # builds the front-end and, on the first run, the index
```

Open `http://localhost:8000` and paste the value of `KEEL_API_TOKEN` into
**Access token**. The first index build took 1 h 44 min on an Intel
laptop; a faster CPU takes about 27 minutes.

Alternative: `docker compose up`.

The steps behind `make demo`, each runnable on its own:

```bash
uv run keel index           # parse, chunk, embed, and write the index
uv run keel serve           # the API and the front-end on port 8000
uv run keel ask "question"  # one answer in the terminal; --json for the record
```

## Evaluation

`uv run keel eval` runs the 28 questions of `eval/golden.yaml` against
the index and writes `eval/report.md`: recall at 10, 25, and 48, MRR,
nDCG, the retrieval ablations, and the gates. `--answers` adds the live
answers and an LLM judge (`claude-opus-5-5`) for faithfulness, citation
precision, and numeric accuracy.

The last full run, index 1.2.0 and prompt 1.5.1:

| Gate | Threshold | Value | Status |
| --- | --- | --- | --- |
| Recall at 25 | >= 0.85 | 0.86 | pass |
| MRR | >= 0.60 | 0.96 | pass |
| Faithfulness | >= 0.90 | 0.926 | pass |
| Citation precision | >= 0.90 | 1.00 | pass |
| Numeric accuracy | >= 0.90 | 1.00 | pass |
| Schema validity | 1.00 | 1.00 | pass |
| Refusal correctness | 1.00 | 1.00 | pass |
| Latency p95 | <= 40 s | 35.9 s | pass |
| Mean cost per question | <= 0.25 USD | 0.093 USD | pass |

Each prompt version in [`docs/PROMPT_LOG.md`](docs/PROMPT_LOG.md) records
1 hypothesis and the measured before and after on the 3 example questions.

## Pages and features

The question page is `/`. The footer links the other pages; the 3 admin
pages show only to an admin token.

| Page | What it does |
| --- | --- |
| Question (`/`) | Ask a question or pick one of the 3 examples or a template. The answer streams in: the direct answer, findings per company with citation chips, the comparison table, the coverage statement, and the gaps list. The right panel shows the retrieved passages with their scores, and the trace drawer shows the audit record with `model requests: 1`, tokens, cost, and latency |
| Filing reader | Opens from a citation chip: the cited section of the filing from Keel's own index, with previous and next, the fiscal period, and the SEC link. No model call |
| History (`/history`) | Your own questions, newest first, with Open answer, Copy link, and Re-run |
| Shared answer (`/a/<request ID>`) | A read-only answer that any token holder can open from a copied link |
| Comp sets (`/compsets`) | Named ticker lists shared by the firm. A question names one with `my <name> comps` |
| Financials (`/financials`) | The income statement, balance sheet, and cash flow of an indexed company from its XBRL, annual or quarterly, as a line-item table and bar charts with a link to each source filing |
| Companies (`/companies`) | The indexed companies, the watch list, and for an admin: Add company from EDGAR, Fetch facts, Dry run, and Run refresh |
| Eval report (`/eval`) | The regression gates as metric bars, the numbers of the last `keel eval` run, the report, and the prompt log with each version's rule changes |
| Debug (`/debug`) | How Keel reads a question (companies, type, time scope) and which chunks it would send, with scores. 0 model requests |
| Data use (`/help`) | What Keel sends where, what it logs, and who sees it |
| Jobs (`/jobs`, admin) | Every admin job with its status, progress, log tail, and result |
| Users (`/users`, admin) | Add a user (the token shows once) and remove one |
| System (`/system`, admin) | The doctor checks, the inventory, Rebuild index, Warm cache, Run eval, the backups with Back up now and Restore, and the budget |

Under each finished answer: thumbs up or down with a note, **Memo .md**
and **Memo .docx** (a memo with numbered footnotes and SEC links),
**Export JSON**, and **Copy as markdown**. The access token lives in the
tab's session storage and goes when the tab closes.
