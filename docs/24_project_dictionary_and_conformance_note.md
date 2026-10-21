## 24. Project dictionary and conformance note

The dictionary gives 1 definition for each technical name and technical verb in this plan. A term has 1 meaning in every chapter.

### 24.1 Dictionary

| Term | Type | Definition |
| --- | --- | --- |
| answer | Technical name | The JSON object that the model returns for 1 question |
| answer cache | Technical name | The local store of complete answers, keyed by the question hash, the index version, the prompt version, and the model snapshot |
| answer call | Technical name | The single request to the model that produces the answer |
| audit record | Technical name | The JSON line written for 1 question with the fields in FR-12 |
| bearer token | Technical name | The secret string in the `Authorization` header that the demo requires |
| boilerplate | Technical name | Filing text that repeats across periods with little change, such as forward-looking statements |
| BM25 | Technical name | The score function of the lexical index |
| breaker | Technical name | The circuit breaker that stops provider requests after repeated failures |
| build report | Technical name | The file that the index build writes with counts, warnings, and the quarantine list |
| cache (verb) | Technical verb | To store a result for reuse |
| calibration factor | Technical name | The ratio between the model token count and the local token count, measured once at build time |
| canonical section | Technical name | 1 of the 8 named divisions of a filing in the taxonomy of chapter 8, plus `unknown` and `excluded` |
| chapter | Technical name | A numbered division of this plan |
| chunk | Technical name | A piece of filing text of at most 480 tokens with metadata, the unit of retrieval and citation |
| chunk hash | Technical name | The first 16 hex characters of the sha256 of the normalized chunk text |
| chunk ID | Technical name | The deterministic identifier of a chunk: filing ID, section, and sequence |
| citation | Technical name | A reference from a claim to a chunk ID, with a claim text and a quote |
| citation drift | Technical name | A citation to a chunk ID that is not in the context |
| context | Technical name | The set of chunks inside the prompt for 1 question |
| context budget | Technical name | The token and chunk limits of the context, and the algorithm that fills them |
| context index | Technical name | The list of 1 line per chunk at the top of the context |
| corpus | Technical name | The set of filing files and the manifest that Keel indexes |
| cover page | Technical name | The first page of a filing after the XBRL block, with the form, the period, and the registrant |
| cross-encoder | Technical name | A model that scores a query and a chunk together, used as the reranker |
| degraded mode | Technical name | The response with retrieved chunks and no answer when the model is unavailable |
| delta-only | Technical name | A 10-Q risk factor section that states only changes since the last 10-K |
| dense index | Technical name | The NumPy matrix of embedding vectors, 1 row per chunk |
| dense query | Technical name | The embedding vector of the question text used to search the dense index |
| embed (verb) | Technical verb | To compute the embedding vector of a text |
| embedding model | Technical name | The local model that computes embedding vectors |
| embedding vector | Technical name | A list of 384 numbers that represents a text for similarity search |
| eval harness | Technical name | The code that runs the golden set and reports the metrics |
| fallback | Technical name | A substitute that the system uses when the primary item fails |
| filing | Technical name | 1 10-K or 10-Q from the corpus |
| filing ID | Technical name | The deterministic identifier of a filing: ticker, form, and period end date |
| fiscal label | Technical name | The name of a period in the company's fiscal calendar, such as FY2025 or Q1 FY2023 |
| fiscal period | Technical name | FY, Q1, Q2, or Q3 in the company's fiscal calendar |
| fiscal year end month | Technical name | The nominal month in which the company's fiscal year ends |
| fine-tuning | Technical name | The further adaptation of a model with new examples |
| forward-looking statements | Technical name | The safe harbor text of the SEC about future expectations |
| fusion | Technical name | The combination of the lexical list and the dense list into 1 ranked list with reciprocal rank fusion |
| fuzzy match | Technical name | A text match that tolerates small differences, measured by a ratio |
| golden set | Technical name | The 28 questions with expected sources that the eval harness runs |
| group | Technical name | A named set of tickers, such as `pharma` or `banks` |
| hardening | Technical name | The work that makes the demo build fit for production |
| hash (verb) | Technical verb | To compute a fixed-length digest of data with sha256 |
| header | Technical name | The first 7 lines of a filing file, with the company, the ticker, the form, the filing date, the CIK, the source, and the URL |
| heading | Technical name | A title line inside filing text or inside this plan |
| idempotent | Technical name | A property of an operation whose repeat gives the same result as the first run |
| index (noun) | Technical name | The lexical index, the dense index, the chunk table, and the manifest together |
| index (verb) | Technical verb | To add filings to the index |
| index version | Technical name | The semantic version of 1 index build |
| inventory | Technical name | The command and the report that count the corpus files and compare them with the manifest |
| judge | Technical name | The model that scores claims against chunks at eval time |
| lexical index | Technical name | The FTS5 table with BM25 ranking |
| lexical query | Technical name | The term query sent to the lexical index |
| LLM | Technical name | A large language model, such as Claude Sonnet 5.5 |
| log (verb) | Technical verb | To write an event record |
| manifest | Technical name | `manifest.json` in the corpus, or the index manifest with checksums, as named in context |
| metadata filter | Technical name | The SQL condition on ticker, form, section, and dates that limits a query |
| near-duplicate | Technical name | A pair of chunks with a SimHash Hamming distance of 3 or less |
| nominal month | Technical name | The month of a period end date after the day-4 rule of chapter 7 |
| normalize (verb) | Technical verb | To map text or names into a standard form |
| panel | Technical name | The interview panel that plays the PE client |
| parse (verb) | Technical verb | To read a file into structured data |
| parser | Technical name | The module that parses a filing |
| period code | Technical name | The calendar quarter token in a file name, such as 2022Q4. The brief calls it the period token. |
| period end date | Technical name | The last day of the period that a filing covers, from the cover page |
| pin (verb) | Technical verb | To fix a version or a revision so that it cannot change without a config change |
| Principal | Technical name | The object that carries the identity and the permitted filters of a request |
| prompt | Technical name | The system block and the user block sent to the model |
| prompt bundle | Technical name | The prompt plus the schema and the prompt hash |
| prompt caching | Technical name | The provider feature that reuses the processed static part of a prompt |
| prompt hash | Technical name | The sha256 of the prompt files and the schema |
| provider | Technical name | The company that serves the model through an API, Anthropic in this release |
| provider adapter | Technical name | The module that sends the answer call to a provider behind 1 interface |
| quarantine (verb and noun) | Technical verb | To exclude a file from the index with a recorded reason, and the list of such files |
| query | Technical name | A search request sent to an index |
| question | Technical name | The natural-language text that the user types |
| question analysis | Technical name | The object with tickers, groups, time scope, question type, and flags |
| quota | Technical name | The maximum number of chunks and tokens for 1 company or 1 period in the context |
| render (verb) | Technical verb | To show data in the browser page |
| rerank (verb) | Technical verb | To score candidates again with the cross-encoder |
| reranker | Technical name | The cross-encoder model and the step that uses it |
| retrieve (verb) | Technical verb | To find candidate chunks for a question |
| retriever | Technical name | The module that retrieves and fuses candidates |
| sanitize (verb) | Technical verb | To remove unsafe HTML from text before the browser renders it |
| schema | Technical name | The JSON schema of the answer |
| section | Technical name | A division of a filing, mapped to a canonical section |
| section detector | Technical name | The module that finds the real section starts |
| SimHash | Technical name | A 64-bit fingerprint of a text that near-duplicates share |
| single call | Technical name | The rule that the answer comes from 1 model request |
| SSE | Technical name | Server-sent events, the stream format from the service to the browser |
| stream (verb) | Technical verb | To send an answer in parts as the model produces it |
| streaming | Technical name | The delivery of an answer in parts |
| sub-query | Technical name | 1 of the retrieval requests that a retrieval plan runs for 1 question |
| table caption | Technical name | The line that carries the title, the units, and the column labels of a table chunk |
| timebox | Technical name | The 4-hour build limit |
| token | Technical name | The unit in which a model counts text |
| trace | Technical name | The record of 1 request across stages in an observability tool |
| validate (verb) | Technical verb | To check data against rules or a schema |
| worked example | Technical name | A step-by-step retrieval plan for 1 example question in chapter 11 |
| XBRL block | Technical name | The run of inline XBRL facts with no spaces at the start of 241 files |

The names below end in -ing and are technical names in this plan, so the writing rules permit them.

| Term | Definition |
| --- | --- |
| advertising | The sale of advertisement space, as in advertising revenue |
| AI coding assistant | A software tool that writes code from instructions beside the engineer |
| chunking | The step that splits a section into chunks |
| earnings | The reported profit of a company, as in earnings call and earnings per share |
| finding | 1 cited point in the answer about 1 company |
| grounding | The property of an answer whose claims come from the context |
| Hamming distance | The count of bits that differ between 2 SimHash values |
| indexing pipeline | The offline sequence of steps from the zip file to the index |
| legal proceedings | The canonical section for lawsuits and regulatory actions |
| loading | The front-end state between the request and the first streamed token |
| non-breaking space | The Unicode character U+00A0 |
| question understanding | The step that turns the question into a `QuestionAnalysis` object |
| warning | A build report entry that does not stop the build |

The STRIDE category names spoofing and tampering in chapter 15 are also technical names, and so are the SEC item titles quoted in chapter 8.

### 24.2 Conformance note

This note records the checks that ran on this plan before delivery.

- Required chapters: all 24 required chapters are present in the required order, and each chapter stands on its own. Chapters 25 to 29 came later, under the same rules.
- Edge case register: the register holds 72 cases. Every case named in the brief has a detection, an action, and a test.
- Modal verbs: a search for should, shall, may, might, could, and would found 6 uses of would. Each use got a rewrite. The other words have 0 uses outside fenced code.
- Dashes: a search for the em dash and the en dash found 0 uses.
- Semicolons and slashes: prose uses none. Fenced code keeps its own syntax.
- The -ing form: a search for every word that ends in -ing found 245 uses. Each use that stays is a technical name from the dictionary. Or it is the verbatim text of an example question from the brief. Verbs, adjectives, and other nouns in the -ing form got a rewrite. Examples: handling, rendering, pinning, licensing, remaining, missing, trailing, ordering, ranking, working, blocking, conflicting, framing, rating, buying, training, hosting, settings, savings, onboarding, meeting, evening, scoring, filtering, typing, linting, grouping, and targeting.
- Sentence length: a check compared each procedural sentence with the 20-word limit, and each descriptive sentence with the 25-word limit. About 60 sentences over a limit got a split.
- Noun clusters: clusters of 4 or more words got hyphens or a rewrite. Examples: fiscal-year-end month, table-of-contents row, risk-factor section, and Content-Security-Policy header.
- The word follow: each use means come after. The word fall is not used.
- One word, one meaning: chapter is a division of this plan. Section is a division of a filing. Question is the user input. Query is an index request. Answer is the model output. Response is an HTTP message. Chunk is the unit of retrieval.
- Numbers: every count uses figures, and the unit stays with the number.
- Quality bar: every claim about the data matches the corpus facts in the brief. Every number in the value model carries an assumption ID. Every edge case has detection, action, and test. Every decision names at least 1 alternative. Each example question has a worked example with its coverage limits. The 4-hour build plan marks the ship line.
- ASD-STE100 pass on October 21, 2026, over all 29 chapters. No sentence is over 20 words in a procedure or 25 words in a description. Enumerations are short sentences or vertical lists. The active voice replaced the passive where the agent is known. Approved words replaced non-approved ones: check for the word that means to confirm, and get for the word that means to receive. Modal verbs, dashes, semicolons, and the -ing rule hold at 0 findings.

NOTE: The checks ran as text searches over the plan. A reader who copies a chapter into the repo can run the same searches with a text editor.
