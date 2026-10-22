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
