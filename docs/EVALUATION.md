# How quality was evaluated

The full results:

- [`eval/report.md`](../eval/report.md): the last full run, with every
  metric, the ablations, and the result of each question.
- The **Eval report** page of the live site
  (<https://d1otueg71oygkx.cloudfront.net/eval>, with the access token):
  the same report as metric bars, beside the prompt log.
- [`docs/18_evaluation.md`](18_evaluation.md): the method in full.
- [`docs/PROMPT_LOG.md`](PROMPT_LOG.md): how each result changed the prompt.

## The last run

Run `eval-20261028T012734Z`: prompt 1.5.1, index 1.2.0, answer model
`claude-sonnet-5-5`, judge model `claude-opus-5-5`. 28 questions, 24 of
them answered (1 model request each) and judged; the other 4 must be
refused with 0 model requests. All 10 gates pass. The run cost 4.06 USD
(2.19 answers, 1.87 judge) and took 22 minutes.

| Gate | Threshold | Value | Status |
| --- | --- | --- | --- |
| Recall at 25 | 0.85 or more | 0.86 | pass |
| MRR | 0.60 or more | 0.96 | pass |
| Faithfulness | 0.90 or more | 0.94 | pass |
| Citation precision | 0.90 or more | 1.00 | pass |
| Coverage completeness (comparison and sector) | 1.00 | 1.00 | pass |
| Numeric accuracy | 0.90 or more | 1.00 (9 of 9 gold values) | pass |
| Schema validity | 1.00 | 1.00 | pass |
| Refusal correctness | 1.00 | 1.00 (4 of 4) | pass |
| Latency p95 | 40 s or less | 34.2 s (p50 23.2 s) | pass |
| Mean cost per question | 0.25 USD or less | 0.091 USD | pass |

## The golden set

28 questions in [`eval/golden.yaml`](../eval/golden.yaml), written to cover
the ways an answer can go wrong, with the 3 example questions among them:

| Type | Questions | What it tests |
| --- | --- | --- |
| Single company | 5 | The right section of the right filing, including a non-December year end |
| Comparison | 5 | Fair coverage of 2 to 4 companies, aliases such as Google for GOOG |
| Trend | 4 | Change over several filings and fiscal periods |
| Numeric | 4 | Exact reported values with units and fiscal labels |
| Sector | 3 | 4 to 6 companies at once under a fixed context budget |
| Out of corpus | 3 | A company not in the library, a stock price, a period after the data |
| Ambiguous entity | 2 | The quarantined GE filing, Target as a common word |
| Adversarial | 2 | An instruction in the question, and a planted instruction in a filing |

## What is measured, and how

| Layer | Metric | How it is scored |
| --- | --- | --- |
| Retrieval | Recall at 10, 25, and 48; MRR; nDCG at 10; coverage of the expected companies | Against labeled chunks: 10 questions labeled chunk by chunk, the rest by the expected filing and section |
| Answers | Faithfulness: does the cited text support each claim? | An LLM judge, a different model from the answer model, reads each claim with the exact text it cites: supported 1, partly 0.5, not supported 0 |
| Answers | Citation precision: does each citation support its claim? | The same judge, plus every citation the server's validator removed |
| Code checks | Numeric accuracy, schema validity, refusals, coverage | Code, no model: numbers within 0.5% of the gold value, the answer matches the schema, out-of-scope questions get 0 model requests, every requested company appears in the coverage or the gaps |
| Operations | Latency and cost | The audit record of each request |

## What the results show

- **Numbers are exact.** All 9 gold values match within 0.5% (numeric
  faithfulness 1.00), because numeric questions read the companies'
  reported XBRL values rather than prose.
- **Citations hold.** Citation precision is 1.00 overall; the server's
  validator removed no citation and marked no finding unverified.
- **Refusals cost nothing.** The 4 questions that must be refused were,
  with 0 model requests each.
- **Trend questions are the weakest** (faithfulness 0.82, against 0.92 to
  1.00 for the other types). The judge marks a sentence partly supported
  when it summarizes slightly more than its cited passages state, such as
  a shift between product generations that only an uncited passage
  describes. Across all 24 answers the judge read 477 claims: 444
  supported, 32 partly supported, and 1 not supported.
- **Both search methods earn their place.** Recall at 25 is 0.86 for
  words and meaning together, against 0.79 for words alone and 0.82 for
  meaning alone. The reranker adds 5 points (0.81 without it) for about
  7 seconds per question on the laptop.

## How the results changed the prompt

Each prompt version was measured before it shipped, and a version that
lowered faithfulness or failed an adversarial check was rejected:

| Run | Prompt | Faithfulness | Outcome |
| --- | --- | --- | --- |
| First full run | 1.3.0 | 0.86 | Gate failed |
| With exact reported numbers | 1.4.0 | 0.895 | Gate failed by 0.005 |
| Every part of a sentence cited | 1.5.0 | 0.918 | Rejected: an adversarial check failed |
| No finding cites a planted instruction | 1.5.1 | 0.926 | Shipped |
| This run | 1.5.1 | 0.94 | All gates pass |

The same prompt scored 0.926 and 0.94 in 2 runs, so a difference of about
0.02 is within the judge's run-to-run noise.

## Limits

- 24 judged answers are a small sample; the gates on faithfulness and
  citation precision apply only from 5 judged answers up.
- The judge is a language model; its partly supported verdicts are the
  ones to read by hand, and the report lists the weakest answers with the
  judge's reason.
- One engineer wrote the labels and the gold values.

## Run it

```bash
uv run keel eval             # retrieval metrics and ablations, no model requests
uv run keel eval --answers   # plus 24 live answers and the judge, about 4 USD
uv run keel eval --gate      # exit non-zero when a gate fails
```
