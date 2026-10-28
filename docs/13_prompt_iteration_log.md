## 13. Prompt iteration log

NOTE: This chapter is the plan. The measured history, versions 1.0.0 to 1.5.1 with each rule's before and after, is [`docs/PROMPT_LOG.md`](PROMPT_LOG.md); the shipped version is 1.5.1.

The prompt moves from a naive version 0.1.0 to version 1.0.0 in 8 planned iterations. Each row names the hypothesis, the change, the evidence that the eval harness collects, the expected result, and the decision rule. The first version is naive on purpose, so the log shows what each rule fixes. After each eval run, the engineer writes the measured values and the run ID into the Result column of `docs/PROMPT_LOG.md`.

| Version | Hypothesis | Change | Evaluation evidence | Result (expected, then measured) | Decision |
| --- | --- | --- | --- | --- | --- |
| 0.1.0 | A plain instruction with the chunks is enough. | System block: Answer the question with the context below. No schema, no citations. | Faithfulness and citation precision on the golden set. The 3 example questions by hand. | Expected: invented comparisons for JPM, no citations, mixed fiscal and calendar labels. Measured: run ID and values here. | Keep as the baseline. Move to 0.2.0. |
| 0.2.0 | Citations keyed to chunk IDs stop invented claims. | Add rule 2 (cite chunk IDs) and the `<chunk id>` wrapper. Add the `citations` list. | Citation precision and citation drift count. | Expected: citation precision above 0.7, with drift to IDs outside the context. | Keep. Add server validation in 0.3.0. |
| 0.3.0 | Untrusted data declaration and per-company structure stop cross-company contamination. | Add rule 4, the `company_findings` field, and the question analysis block with `resolved_tickers`. Add server citation validation. | Faithfulness per company on the comparison questions. The adversarial injection cases in the golden set. | Expected: no finding attributed to the wrong company, injection cases ignored, drift removed by the server. | Keep. |
| 0.4.0 | Explicit number rules stop unit and period errors. | Add rules 6 to 10, the `fiscal` and `period_end` attributes, and the table caption carry. | Numeric accuracy on the numeric golden questions. The `quote_mismatch` and `period_mismatch` flags. | Expected: numeric accuracy above 0.9, fiscal labels with period end dates in every numeric answer. | Keep. |
| 0.5.0 | Boilerplate domination comes from retrieval and from the prompt together. | Add rule 15 (no rank order) and rule 11 (delta-only). Retrieval side: the forward-looking weight 0.5 and the SimHash collapse. | Share of citations to forward-looking chunks. Human rubric score for specificity. | Expected: forward-looking citations under 10% of all citations, specificity score up by 1 point. | Keep both changes. Record the retrieval change in the index notes. |
| 0.6.0 | A required coverage statement makes gaps visible. | Add rules 12 and 13, the `coverage` and `gaps` fields, the context index, and the `filings_available` line. | Coverage completeness on the comparison and sector questions. | Expected: coverage completeness 1.0, and every single-10-K company named in the gaps for trend questions. | Keep. |
| 0.7.0 | Verbosity hides the answer and raises cost. | Add rules 17 and 18 (3 to 6 sentences, under 900 words) and the `maxItems` limit on next questions. Tighten the schema with `additionalProperties: false`. | Output tokens per answer and the human rubric score for clarity. | Expected: output tokens under 2,000 on average and no loss in faithfulness. | Keep. |
| 1.0.0 | The field order controls the stream and the refusal path controls empty contexts. | Put `direct_answer` first in the schema, add rules 16, 19, and 20, and add the `refusal` object. Pin the prompt version in the manifest compatibility field. | Time to first visible prose. The out-of-corpus and empty-context golden cases. | Expected: first prose within 6 seconds at p50, and a refusal object on every empty-context case. | Ship 1.0.0 for the demo. |

Rules for the log:

- A new version changes exactly 1 hypothesis, so the eval difference has 1 cause.
- Reject a version that lowers faithfulness or citation precision on the golden set, even when the answers read better.
- The eval run ID, the index version, and the model snapshot appear beside every measured value.
- The log never deletes a rejected version. The rejected version stays with its evidence.
