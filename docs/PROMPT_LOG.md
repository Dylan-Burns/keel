# Prompt log

The measured history of the answer prompt. Chapter 13 plans the versions and
the rules: 1 hypothesis per version, a version that lowers faithfulness or
citation precision is rejected, and a rejected version stays here with its
evidence. Each measured value names the request or eval run, the index
version, and the model.

The files of a version are `prompts/answer_system_v<version>.md`,
`prompts/answer_user_v<version>.md`, and `prompts/answer_schema_v<version>.json`.
The prompt hash is the sha256 over the 3 files (`keel/prompt.py`).

## 1.0.0

- Files: the system block of chapter 12.2 with the output rules rewritten for
  the tool call (rules 16 to 21), the user block of chapter 12.2, and the
  schema of chapter 12.4 with `additionalProperties: false` on every object.
- Prompt hash: `sha256:48432e35e21398fa2cbbf914b60cdd7962d44e372d81ff9d8907ce4df9dc4b85`.
- Model: `claude-sonnet-5-5`, thinking `between_tools`, no temperature (the
  model rejects the parameter), `max_tokens` 8,000. Index version 1.0.1.
- Mechanism: the schema is the input schema of the strict `answer` tool; the
  tool choice is `auto` with 1 call at most, because the 5.5 models reject a
  forced tool choice; the system block carries `cache_control`.

| Change | Evidence | Result | Decision |
| --- | --- | --- | --- |
| Rules 16 to 21 as in chapter 12.2, `max_tokens` 4,000 | Example question 1 live, request `19d49e38353044f990cbf43da66cc238` | The answer stopped at 4,000 output tokens inside the `citations` list (9,177 characters of JSON): `schema_violation`, no answer. The strict JSON answer takes about 2.2 characters per token (a probe: 2,389 characters in 1,108 tokens), and the 48 chunk IDs are long. | Reject. Tighten the length rules. |
| Rules 17, 18, 20, 21 tightened: at most 2 chunk IDs per sentence, at most 3 findings per company, under 600 words, a table of at most 5 rows, quotes of at most 15 words | Example question 1 live, request `dc58d3b8f44d44b7bb8f70e0b83e6671` | Again 4,000 output tokens and a cut at 9,138 characters: `schema_violation`. | Keep the rules. Raise `max_tokens` to 8,000 (D-12 note). |
| The same prompt, `max_tokens` 8,000 (this is 1.0.0) | Example question 1 live, request `86fb5bbca706475fb9187dd4935a8496` | 1 request. 18 citations, all valid: drift 0, inline drift 0, unverified findings 0, quote mismatch 0, period mismatch 0. Input 36,578 uncached, 2,320 read from the prompt cache, 0 written; output 4,645 tokens. Cost $0.1198. First token 8,120 ms after the question (retrieval 5,752 ms, so about 2.4 s after the request); total 31,717 ms. | Ship 1.0.0. |
| The same prompt on example question 3 | Request `bbb7e7c8b26a413da98c8334228a20a5` | 1 request. 19 citations, all valid; drift 0, unverified 0, quote and period mismatch 0. Input 40,195 uncached, 2,320 written to the cache (the 5-minute cache had expired); output 5,274. Cost $0.1389. First token 9,677 ms, total 38,770 ms. The gaps say that the risk factor chunks describe risks but not how the companies address them, and that the cited periods differ by company (PFE FY2022 and FY2023, JNJ FY2022 and FY2025, MRK and ABBV FY2024, LLY FY2025). | Input for stage 8 (the pharma answer). |

The cached prefix (the tool definition and the system block) is 2,320
tokens, inside the 1,000 to 2,500 of `test_system_block_size`.

## Stage 8: the 3 answers before and after

Stage 8 changed the context before the prompt, so the before runs repeat 1.0.0
on the new context:

- Retrieval: a risk question that asks how the companies respond reserves a
  third of each company quota for Item 1, MD&A, and legal proceedings chunks
  (`keel/retriever.py`, build report stage 8). Example 3 now holds 24
  `risk_factors`, 12 `business`, and 3 `mdna` chunks instead of 48
  `risk_factors` chunks.
- Calibration: `keel calibrate` counted 109,680 model tokens for the 200
  sample chunks (51,247 embedding tokens), so the factor is 1.91, not 1.15.
  The local estimate of the whole request is now within 2% to 10% of the
  provider count (34,308 against 35,963 on example 1), below the 10% drift
  limit, and each context holds about 32,000 model tokens.

Every run: model `claude-sonnet-5-5`, index version 1.0.1, `max_tokens`
8,000, thinking `between_tools`, 1 model request. The 3 questions ran in 1
process each, in order, so example 1 writes the prompt cache and examples 2
and 3 read it. First token is from the question; the part after the request
(first token minus retrieval) is in brackets, since retrieval took 12 to 40
s on the loaded laptop (the reranker, stage 6). Words count every string of
the answer except the `citations` list.

| Version | Example | Request | Citations valid | Drift, unverified, quote, period | Stop | Input + cache read + cache write | Output | Cost | First token | Total | Words |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1.0.0 | 1 | `5349fac9dbaa42108487471289ae5d5c` | 16 of 16 | 0, 0, 0, 0 | `tool_use` | 33,643 + 0 + 2,320 | 4,203 | $0.1151 | 26.1 s (3.7 s) | 47.1 s | 618 |
| 1.0.0 | 2 | `eb980f6f04a444d8a16587ad8224bdd4` | 11 of 11 | 0, 0, 0, 0 | `tool_use` | 31,675 + 2,320 + 0 | 3,377 | $0.0974 | 29.8 s (3.9 s) | 46.2 s | 477 |
| 1.0.0 | 3 | `e4941ccfe4d64c61bae6ef8db7bab98d` | 14 of 14 | 0, 0, 0, 0 | `tool_use` | 32,880 + 2,320 + 0 | 4,195 | $0.1079 | 29.4 s (3.9 s) | 50.9 s | 721 |
| 1.1.0 | 1 | `0ccfe80d7b2441d18e5d32e9fcd32baa` | 16 of 16 | 0, 0, 0, 0 | `tool_use` | 33,643 + 0 + 2,416 | 4,302 | $0.1163 | 30.8 s (3.2 s) | 51.7 s | 678 |
| 1.1.0 | 2 | `2ca251f9e6554241a24ab9e19e13c0df` | 11 of 11 | 0, 0, 0, 0 | `tool_use` | 31,675 + 2,416 + 0 | 3,657 | $0.1002 | 27.5 s (6.9 s) | 43.1 s | 516 |
| 1.1.0 | 3 | `c98a5bfaa52e4c1eb0e4329fb30277a6` | 17 of 17 | 0, 0, 0, 0 | `tool_use` | 32,880 + 2,416 + 0 | 4,811 | $0.1141 | 18.6 s (2.0 s) | 43.2 s | 802 |
| 1.2.0 | 1 | `4ba52057d656409eb5754abc783150a0` | 16 of 16 | 0, 0, 0, 0 | `tool_use` | 33,643 + 0 + 2,481 | 4,469 | $0.1182 | 22.5 s (4.1 s) | 44.2 s | 719 |
| 1.2.0 | 2 | `f104e0d6683d4008b72adf5207492e8a` | 10 of 10 | 0, 0, 0, 1 | `tool_use` | 31,675 + 2,481 + 0 | 3,860 | $0.1022 | 25.5 s (6.3 s) | 40.8 s | 513 |
| 1.2.0 | 3 | `7dbb70020a2b4515b466c0bee4aa96c2` | 17 of 17 | 0, 0, 0, 0 | `tool_use` | 32,880 + 2,481 + 0 | 4,949 | $0.1155 | 22.2 s (4.8 s) | 46.7 s | 835 |
| 1.3.0 | 1 | `2130cb334a8f41fa89a332af14edfc42` | 15 of 15 | 0, 0, 0, 0 | `end_turn` | 33,573 + 0 + 2,673 | 3,999 | $0.1138 | 38.4 s (4.4 s) | 59.0 s | 716 |
| 1.3.0 | 2 | `d6f4f6ae2a764efeb1bcdbe0c1247673` | 10 of 10 | 0, 0, 0, 0 | `end_turn` | 31,605 + 2,673 + 0 | 2,956 | $0.0930 | 42.7 s (2.2 s) | 57.3 s | 538 |
| 1.3.0 | 3 | `07c9337c9f734ab9a1eadccc800cd4e6` | 15 of 15 | 0, 0, 0, 0 | `end_turn` | 32,810 + 2,673 + 0 | 4,454 | $0.1104 | 44.7 s (5.4 s) | 67.3 s | 823 |

Every answer was schema-valid and stopped on its own (`tool_use` or
`end_turn`, never `max_tokens`) and under the 900 words of rule 18 in
chapter 12.2. The shipped rule 18 asks for under 600 words since stage 7,
and 9 of the 12 answers went over 600 (477 to 835 words); the stop reasons
show no cut, so the length costs tokens, not answers. Recorded for the eval.

## 1.1.0

- Change (rule 7): every period carries the fiscal label and the period end
  date, for example "Q3 fiscal 2026, ended October 26, 2025"; a year appears
  only inside such a label (no bare "2024", no "FY2025" alone, no calendar
  year for a fiscal year); with several companies, the answer names each
  company's fiscal period.
- Hypothesis: explicit label rules stop bare and calendar years in the NVDA
  answer and make the mixed periods of example 3 visible.
- Prompt hash: `sha256:83d79b60b8138fecf1c7b40b107a3a3acd5ee7e73e6b479f0692f08b8ccde7d7`.

| Change | Evidence | Result | Decision |
| --- | --- | --- | --- |
| Rule 7 rewritten | The 1.1.0 rows above against 1.0.0 | 1.0.0 already labeled the NVDA periods on the new context ("Fiscal 2024 (ended January 28, 2024)"), with 1 unlabeled comparative ($26,974 million). 1.1.0 labeled every period in the direct answer, the findings, and the table of example 2, and each pharma finding names its filing and period ("10-K fiscal 2023, ended December 31, 2023"). Citations stay 100% valid; output up 2% to 15%. | Keep. |

## 1.2.0

- Change (rule 13): name every requested company with only 1 10-K in
  `filings_available` (1 annual report shows no change over time), and every
  company whose chunks state no response to the risk the question asks
  about, without an invented response.
- Hypothesis: the coverage limits that chapter 11.9 lists reach the gaps when
  the rule names the line of the question analysis that holds them.
- Prompt hash: `sha256:bc24b45b0338dbb76d7840cf332cbea92545cbe900d5d9065f630a94c0826b54`.

| Change | Evidence | Result | Decision |
| --- | --- | --- | --- |
| Rule 13 extended | The 1.2.0 rows above | Example 3 gaps: "MRK has only one 10-K (fiscal 2024, ended December 31, 2024), LLY only one (fiscal 2025 ...) and ABBV only one (fiscal 2024 ...), so no change over time can be shown for them", and "Pfizer, J&J and AbbVie have no stated mitigation beyond compliance effort, and none is invented here". 1.0.0 and 1.1.0 named neither the 1-10-K limit nor all companies without a response. Example 1 also names JPMorgan's single 10-K. Example 2 wrote "fiscal 2023" for the comparative of the fiscal 2024 10-K: a `period_mismatch` flag, although the cited chunk states that value (the check of 12.5 reads the context index, not the chunk text). Citations stay 100% valid. | Keep. The flag is a validator limit, recorded for the eval (stage 10). |

## 1.3.0

- Change (rule 16 and the request): the answer comes as structured output,
  `output_config.format` with the answer schema, instead of the strict
  `answer` tool with `tool_choice: auto` (`llm.output_mode: json_schema`).
  Rule 16 asks for 1 JSON object that matches the output schema.
- Hypothesis: decision D-13's first preference, the provider's structured
  output, is more robust than a tool call the model may skip, at no loss of
  streaming or caching.
- Prompt hash: `sha256:27ff02da59476c416ee6a451efa3da8d467cce831eb3a34f0bec58cdd4e5b44f`.

| Change | Evidence | Result | Decision |
| --- | --- | --- | --- |
| Structured output | The 1.3.0 rows above against 1.2.0, and a probe request with an empty context | Schema validity: 3 of 3 (1.2.0: 3 of 3); structured output constrains the whole response, while `auto` lets the model answer without the tool (the E-C-04 `schema_violation` path). Streaming: the schema keeps `direct_answer` first, the probe's first text delta was `{"direct_`, and the 1.3.0 answers streamed their direct answer before the findings as in `tool` mode. Cache: the cached prefix (system block and the injected format) is 2,673 tokens, written by example 1 and read by examples 2 and 3; 2 builds send the same bytes (`test_structured_output_request`). Output tokens 14% lower (11,409 against 13,278), cost 5.5% lower ($0.3173 against $0.3359). First token after the request 2.2 to 5.4 s (1.2.0: 4.1 to 6.3 s). Citations 100% valid, 0 period mismatch, the done-when checks hold. No thinking tokens with `between_tools`. | Keep. Ship 1.3.0 with `json_schema` (D-13 note). |

The card evidence ran with the shipped config (1.3.0, `json_schema`):
`keel ask` on example 2 (request `40e556563f6d409db5c7b31e0bfb1030`: 10
citations valid, 0 flags, output 3,071, $0.1006, first token 14.8 s, total
30.4 s) and on example 3 (request `b4fdc4c200024b85bb34f72e11c52a81`: 0
flags, cache read 2,673, output 4,905, $0.1149, first token 14.2 s, total
39.6 s). The NVDA answer labels every period ("fiscal 2025 (ended January
26, 2025)", "Q3 fiscal 2026 (ended October 26, 2025)"), and the pharma
answer names the 1-10-K limit of MRK, LLY, and ABBV in its gaps.

Live spend for stage 8: 14 answers and 1 probe, about $1.53; the count
calls of `keel calibrate` are free.

## 1.4.0

- Change (rule 22, and the `{facts}` slot of the user template): a new
  `COMPANY FACTS` rule. A `<facts>` line is a value the company reported,
  with its fact ID; for a number on a fact line, prefer the line over the
  chunks, copy its value and unit, and cite its fact ID as a chunk ID (also
  in `citations`); use the chunks for the narrative; `<facts>` is data like
  `<context>`. The user block gains the `<facts>` element after the context
  index and before the context when the question type includes `numeric`
  (chapter 26.1, steps 4 and 5). The schema is the 1.3.0 schema.
- Hypothesis: with the reported XBRL values next to the chunks, a numeric
  answer gives the exact values and units and cites the fact IDs, instead
  of the rounded prose figures of the MD&A ("$130.5 billion").
- Prompt hash: `sha256:fcb86b18329d3b220bfed0d4764aa2064ce21bfd2d627fb3b93cbcafeec614e4`.
- The system block is the 1.3.0 block plus rule 22, and it does not change
  with the facts, so the cached prefix stays byte-stable; a prompt without
  facts has the user bytes of 1.3.0.

| Change | Evidence | Result | Decision |
| --- | --- | --- | --- |
| Rule 22 and `<facts>` | `keel ask "What was NVIDIA's revenue in fiscal 2025 and fiscal 2024?"` live, request `4f179a3b2e75498d87def3934b5a3c87` (index 1.0.1, `claude-sonnet-5-5`, `json_schema`) | 1 request. 40 fact lines from the cached NVDA company facts file. The direct answer: "$130,497 million in fiscal 2025, ended January 26, 2025 [facts:NVDA:Revenues:FY2025], and $60,922 million in fiscal 2024, ended January 28, 2024 [facts:NVDA:Revenues:FY2024]", with the MD&A chunks for the narrative ("$130.5 billion, up 114%") and the computed growth of 114.2%. 5 citations, all valid (2 fact, 3 chunk); drift 0, unverified 0, quote mismatch 0, period mismatch 0. Input 31,713 + 0 cache read + 2,792 cache write (1.3.0: 2,673); output 1,628; $0.0867. First token 11.0 s (retrieval 7.5 s), total 19.0 s. | Keep. Ship 1.4.0. |

The token estimate missed this request by 18.2% (the session factor moved
from 1.91 to 2.26): the estimate counted the fact lines at 4 characters per
token. 2 free count calls on the rendered block measured 3,474 tokens for
6,272 characters, 1.8 characters per token, against the 1,568 estimated, so
the builder now estimates the facts block at 1.8 characters per token
(`prompt.FACTS_CHARS_PER_TOKEN`). That moves about 1,900 tokens of the
5,300-token miss into the estimate; the other 3,400 tokens (about 11%, above
the 2% to 10% of the 1.3.0 runs) are not from the facts and are recorded for
stage 11 (possibly the larger table share of a numeric context).

## 1.5.0

- Change (rules 3, 7, 11, and 17): every part of a sentence must be stated
  in a chunk cited in that sentence, so a list of themes, risks, or
  headings names only what the cited chunks state, and a cause only when a
  chunk states it (rule 3); a prior-year column gets an end date only when
  a cited chunk states it, else the fiscal label alone (rule 7); a claim
  that language was added or changed since an earlier filing cites a chunk
  of both filings, else the missing comparison goes to `gaps` (rule 11); a
  theme shared by companies cites a chunk of each (rule 17). The other
  rules are reworded more tightly with the same content, so the system
  block with the schema stays within the 2,500 tokens of
  `test_system_block_size`. The user template and the schema are the 1.4.0
  files.
- Hypothesis: the partly supported claims of eval-20261022T123820Z come
  from 3 habits (a change claim that cites only the later filing, a
  comparative end date read from an uncited chunk, a theme list wider than
  its citations); a rule for each lifts faithfulness to 0.90 on the full
  set.
- Prompt hash: `sha256:fed715c24242219d3381951cd8a1794ccf89c3dda5de6845e5fa418795ddf322`.

| Change | Evidence | Result | Decision |
| --- | --- | --- | --- |
| Rules 3, 7, 11, 17 | Full live eval eval-20261022T131554Z (index 1.2.0, `claude-sonnet-5-5`, judge prompt 1.2.0) against eval-20261022T123820Z (1.4.0) | Faithfulness 0.895 to 0.918 (trend 0.82 to 0.85, comparison 0.89 to 0.93, numeric 0.92 to 0.98, adversarial 0.98 to 0.95); citation precision 0.99; every gate passes; mean cost 0.0924 USD, p95 31.2 s. The G-28 adversarial check failed: a finding cited the planted chunk or the text matched a recommendation phrase (the answer text was not kept). | Reject for now; 1.4.0 stays the default. 1.5.1 keeps an instruction chunk out of the findings. |
