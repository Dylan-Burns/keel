# Keel

Grounded answers to business questions about SEC filings, from 1 LLM call.

## Submission deliverables

| Deliverable | Where |
| --- | --- |
| README with setup and run instructions | This file: [Live site](#live-site), [Local setup](#local-setup), and [Run locally](#run-locally) |
| Indexing code | [`keel/parsers/`](keel/parsers/), [`keel/sections.py`](keel/sections.py), [`keel/chunker.py`](keel/chunker.py), [`keel/indexer.py`](keel/indexer.py), [`keel/stores/`](keel/stores/) |
| Retrieval code | [`keel/understanding.py`](keel/understanding.py), [`keel/retriever.py`](keel/retriever.py), [`keel/context.py`](keel/context.py) |
| Log of prompt iterations | [`docs/PROMPT_LOG.md`](docs/PROMPT_LOG.md) |
| Final prompt template | [`prompts/answer_system_v1.5.1.md`](prompts/answer_system_v1.5.1.md), [`prompts/answer_user_v1.5.1.md`](prompts/answer_user_v1.5.1.md), [`prompts/answer_schema_v1.5.1.json`](prompts/answer_schema_v1.5.1.json) |
| Front-end | [`web/`](web/), deployed at the [live site](#live-site) and served locally by `keel serve` |
| Example request ready to execute | [`scripts/example_request.sh`](scripts/example_request.sh); see [Example request](#example-request) |
| Notes on how quality was evaluated | [Evaluation](#evaluation) below; method in [`docs/18_evaluation.md`](docs/18_evaluation.md), last run in [`eval/report.md`](eval/report.md) |
| Assumptions and decisions | [`docs/04_assumptions_and_decisions_log.md`](docs/04_assumptions_and_decisions_log.md) |
| Business value for a PE firm | [`docs/02_business_context_and_value_creation_for_a_pe_firm.md`](docs/02_business_context_and_value_creation_for_a_pe_firm.md) |
| Future state and capabilities | [`docs/22_future_state_roadmap.md`](docs/22_future_state_roadmap.md) |

Each question makes exactly 1 model request. Question understanding,
retrieval, reranking, and citation validation are code with no LLM in
them. The mock provider counts requests and `test_single_request` guards
the rule in CI.

## Live site

Keel runs at <https://d1otueg71oygkx.cloudfront.net> with the full
index of 54 companies. The access token comes separately with the
submission. Open the site, paste the token into **Access token**, and
ask a question or pick one of the 3 examples.

## Example request

The script sends the request the web page sends: a streamed
`POST /api/ask` with the answer cache off, so each run is a live answer
from 1 model request. It needs `curl` and `jq`, and `KEEL_API_TOKEN`
exported with the token from the submission.

```bash
export KEEL_API_TOKEN=...
scripts/example_request.sh --url https://d1otueg71oygkx.cloudfront.net
scripts/example_request.sh --url https://d1otueg71oygkx.cloudfront.net "How has NVIDIA's revenue and growth outlook changed over the last two years?"
scripts/example_request.sh --url https://d1otueg71oygkx.cloudfront.net --json   # the full record: answer, retrieval, audit
```

Without `--url` the script targets a local `keel serve` on port 8000.
The same request with curl:

```bash
curl -N -X POST https://d1otueg71oygkx.cloudfront.net/api/ask \
  -H "Authorization: Bearer $KEEL_API_TOKEN" \
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

`uv run keel doctor` checks FTS5, the models, the keys, and the port.

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
