## 19. Edge case register

The register holds 72 cases in 4 categories. Each case names how the system detects the case, what the system does, and the test that proves the behavior. The test names are the function names in `tests/`.

### 19.1 Data

| ID | Case | Detection | Action | Test |
| --- | --- | --- | --- | --- |
| E-D-01 | Mislabeled or inconsistent metadata (the GE file) | Check CK-06: the registrant token set on the cover page differs from the header name | Quarantine with reason `registrant_mismatch` and the evidence. The coverage page explains why GE has no data. | `test_registrant_mismatch` |
| E-D-02 | Files dated outside 2023 to 2025 (37 in 2022, 27 in 2026, 1 in 2015) | The filing date from the header | Index the file (D-19) and show the real date range in the coverage statement. A config date filter can exclude the file. | `test_date_filter_config` |
| E-D-03 | 2 file-name patterns, with and without a period code | The file name regex matches 1 of 2 patterns | Read the period from the cover page in both cases. Use the period code only for check CK-08. | `test_filename_patterns` |
| E-D-04 | Absent period code | The second pattern matches | No action, because the cover page is the source of the period | `test_filename_patterns` |
| E-D-05 | Calendar versus fiscal period codes | Check CK-08 compares the code with the calendar quarter of the period end date | The fiscal period comes from the fiscal math in chapter 7. A mismatch is a warning only. | `test_fiscal_q1_apple` |
| E-D-06 | Non-December fiscal year ends (NVDA, AAPL, MSFT, DIS, WMT, HD, TGT, CRM, COST, ORCL, NKE, ADBE, PG, DE, CSCO, SBUX) | The fiscal-year-end month per ticker from the 10-K | The fiscal label and the period end date go into every chunk and every citation. | `test_fiscal_q3_nvda`, `test_nominal_month` |
| E-D-07 | XBRL block of variable length, 18,772 to 284,260 characters | The cover marker and the prose window detectors | Cut at the earlier detector. Record the length and flag outliers. | `test_xbrl_cut_at_cover`, `test_xbrl_long_block` |
| E-D-08 | Files without an XBRL block (5 files) | The removed block holds no XBRL signature | Keep the body and log `no_xbrl_block` | `test_no_xbrl_block` |
| E-D-09 | Giant single lines up to 287,855 characters | The line length | The parser works on the whole text, not on lines. Rules R1 to R5 insert boundaries. | `test_giant_line_parse` |
| E-D-10 | Fused sentences and headings | Rules R1 to R3 match | Insert the boundary. Protect abbreviations and names. | `test_heading_split`, `test_protected_name` |
| E-D-11 | Page-number artifacts, 82 in the NVDA fiscal 2025 10-K | Rules A1 to A3 match | Remove the artifact and count the removal | `test_page_artifact` |
| E-D-12 | Pipe tables separated from their labels and units | The table group step and the units regex | Carry the title, the labels, and the units in a caption line on every table part | `test_table_units` |
| E-D-13 | Table-of-contents rows, cross-references, and real section starts | The classification features in chapter 8 | Select the real headings with the order constraint | `test_nvda_item_1a_once`, `test_toc_rows_rejected`, `test_cross_reference_rejected` |
| E-D-14 | 10-K and 10-Q item collisions | The form and the Part | Map through the canonical taxonomy keyed on form and Part | `test_10q_mdna`, `test_10k_properties_other` |
| E-D-15 | 10-Q risk-factor sections that state only changes | The form and the section | Set `delta_only = 1`, add the latest 10-K risk chunks to every risk question, and tell the model in rule 11 | `test_risk_10k_supplement` |
| E-D-16 | Non-breaking spaces and curly quotes in 243 and 245 files | The normalization stage | Map to spaces and straight quotes before every regex | `test_nbsp_item_label` |
| E-D-17 | Restated comparatives across filings | 2 candidates with the same fiscal period and different filing dates | Weight 1.05 for the later filing, and rule 8 tells the model to name the restatement | `test_latest_filing_weight` |
| E-D-18 | Near-duplicate boilerplate across quarters | SimHash distance of 3 or less | Keep the chunk from the later filing and show the collapse count | `test_simhash_collapse` |
| E-D-19 | Forward-looking statement and safe harbor text | The heading match in chapter 8 | Flag `forward_looking` and weight 0.5 | `test_forward_looking_flag`, `test_boilerplate_weight` |
| E-D-20 | Exhibit lists and signature pages | The exhibits item and the `SIGNATURES` heading | Mark `excluded` and never index | `test_exhibits_excluded` |
| E-D-21 | The 1.5 MB bank filings | The file size in the inventory | Parse with the same rules. The build report shows the parse time per file, and a file over 60 seconds gets a warning. | `test_large_file_parse_time` |
| E-D-22 | A corrupt or truncated file | A decode error, an absent header, an absent separator, or an absent cover page | Quarantine with the reason, and continue the build | `test_truncated_file_quarantine` |
| E-D-23 | A new file added later | A file hash that is not in the `filings` table | Incremental build of that file only, and a new minor index version | `test_incremental_add` |
| E-D-24 | A manifest that disagrees with the directory | The inventory set comparison | List the absent files and the unmanifested files in the build report, and index the files on disk | `test_manifest_mismatch` |
| E-D-25 | The manifest description claims 15 quarterly companies and the list shows 12 | The inventory counts per ticker | Record the discrepancy in the build report and in the README. No other action. | `test_inventory_counts` |
| E-D-26 | Duplicate content under 2 file names | 2 files with the same file hash or the same filing ID | Keep 1 file and warn (check CK-11) | `test_duplicate_filing_id` |
| E-D-27 | A byte order mark, Windows end-of-line characters, or invalid UTF-8 | The decode stage | Remove the mark and normalize line endings. Quarantine on an invalid byte sequence. | `test_bom_and_crlf`, `test_invalid_utf8` |
| E-D-28 | A header URL with a host other than `www.sec.gov` | The URL check in the header parse | Set `url_trusted = 0` and never render the link | `test_sec_url_only` |
| E-D-29 | An amended filing with the same period as an original filing | 2 filings with the same filing ID | Keep the filing with the later filing date and warn | `test_duplicate_filing_id` |

### 19.2 Query

| ID | Case | Detection | Action | Test |
| --- | --- | --- | --- | --- |
| E-Q-01 | A company named by brand, former name, or nickname (Facebook, Google, Coke, J&J) | The alias dictionary | Resolve to the ticker and show the resolved name | `test_alias_facebook`, `test_alias_coke` |
| E-Q-02 | A company not in the corpus | No alias match and a company mention or an external list match | Out-of-scope response with the covered companies, no model call | `test_unknown_company` |
| E-Q-03 | An ambiguous name (GE, Target, Chase, Meta, Apple) | The capitalization and position rules | Resolve only with the guard rules. For GE, explain the quarantine. | `test_ge_quarantined`, `test_common_word_guard` |
| E-Q-04 | A sector group | The group dictionary | Expand to the tickers and use the sector plan with quotas | `test_group_pharma`, `test_sector_cap` |
| E-Q-05 | A company with 1 10-K asked about a multi-year trend | The filings available for the ticker | Answer with the 1 filing and name the limit in the gaps and the coverage statement | `test_single_10k_trend_gap` |
| E-Q-06 | A comparison where 1 company dominates the retrieved set | The per-company candidate counts | Equal quotas per company, with unused quota moved by rank | `test_comparison_quotas` |
| E-Q-07 | Last two years across different fiscal calendars | The time scope parser | Anchor the window per company and label every period with the fiscal name and the period end date | `test_scope_last_two_years` |
| E-Q-08 | A numeric question with unit confusion | The numeric type | Table weight 1.3, the caption with units, and rules 6 to 10. The server checks quotes for numbers. | `test_quote_mismatch`, eval G-15 to G-18 |
| E-Q-09 | A question that mixes in-corpus and out-of-corpus facts (stock price, rumors, events after February 2026) | The out-of-scope patterns | Answer the in-corpus part and list the other part in the gaps | `test_mixed_scope` |
| E-Q-10 | An empty question | The length check | HTTP 400 | `test_question_limits` |
| E-Q-11 | A very long question | The length check | HTTP 413 with the limit | `test_question_limits` |
| E-Q-12 | A non-English question | The letter ratio or the language detector | HTTP 400 with a message in English | `test_non_english` |
| E-Q-13 | An off-topic question | No company, no group, no finance topic word | Out-of-scope response, no model call | `test_off_topic` |
| E-Q-14 | A typo in a ticker or name | The fuzzy match | Resolve with `fuzzy = true` and show did you mean | `test_fuzzy_typo` |
| E-Q-15 | A question that asks for investment advice | The advice patterns | The model gives the filing facts and declines the advice (rule 14) | eval G-28 |
| E-Q-16 | A question that asks the model to ignore its instructions | The injection patterns | Flag, log, and answer the real question. The system block holds rule 4. | `test_injection_flag`, eval G-27 |
| E-Q-17 | Several time scopes in 1 question | More than 1 scope match | Use the widest window and name both scopes in the question analysis | `test_multiple_scopes` |
| E-Q-18 | Last quarter for a company with a non-December year end | The relative quarter scope | Use the latest 10-Q by period end date and label the fiscal quarter | `test_last_quarter_label` |

### 19.3 Single call and context

| ID | Case | Detection | Action | Test |
| --- | --- | --- | --- | --- |
| E-C-01 | Context overflow | The token estimate before the request, and the provider error | Drop chunks by rank, halve the budget and retry once before any content, raise the calibration factor | `test_context_overflow_halves` |
| E-C-02 | Chunk order effects | The ablation in chapter 18 | Order by company, then period from the latest, then section weight, then score. Put the context index at the top. | `test_context_order` |
| E-C-03 | A citation to a truncated chunk | The `truncated` attribute | Keep the citation valid and show a truncated marker in the citation panel | `test_truncated_citation_marker` |
| E-C-04 | Malformed JSON from the model | The schema validation after the stream | Show the raw text as an unstructured answer with a warning, log `schema_violation`, no retry (D-04) | `test_malformed_json_path` |
| E-C-05 | An answer from model memory instead of the context | A claim with no citation, or a citation that the judge rejects | Mark the finding `unverified` in the UI. The eval faithfulness gate catches the pattern. | `test_unverified_finding`, eval faithfulness |
| E-C-06 | A model refusal | The `refusal` object | Show the reason and the retrieved chunks | `test_refusal_path` |
| E-C-07 | A stream disconnect mid-answer | The idle timeout or the connection error after content | Send an `error` event with the partial text kept on screen, no retry | `test_no_retry_after_content` |
| E-C-08 | A provider timeout or rate limit | HTTP 429, 529, or the connect timeout | Retry with backoff before content, then the fallback model, then the degraded mode | `test_retry_before_content`, `test_breaker_opens` |
| E-C-09 | A model version change | The snapshot in config and in the audit record | The pinned snapshot never changes without a config change. A change triggers a golden set run. | `test_model_pinned` |
| E-C-10 | A prompt cache miss | The `cached_input_tokens` value of 0 | No action. The cost difference is about $0.003 per question. | `test_cost_with_cache_miss` |
| E-C-11 | A cost spike | The session total and the daily budget | Stop model requests at the budget and serve the cache and the degraded mode | `test_budget_stop` |
| E-C-12 | Zero chunks after the filters | The empty context | The no-context response without a model request | `test_empty_context` |
| E-C-13 | Token estimate drift | The real input tokens from the provider differ from the estimate by more than 10% | Adjust the calibration factor for the session and log the drift | `test_calibration_adjust` |

### 19.4 Front-end and operations

| ID | Case | Detection | Action | Test |
| --- | --- | --- | --- | --- |
| E-F-01 | The index is not built | `/api/ready` reports `index_loaded: false` | The full-page card with the build command | `test_ready_without_index` |
| E-F-02 | A stale index after a corpus change | The corpus checksum mismatch | The amber banner with the rebuild command. The index still serves. | `test_stale_index_flag` |
| E-F-03 | 2 users at once | 2 concurrent requests | Async handlers, 1 SQLite connection per request in read-only mode, and a reranker lock. Both answers complete. | `test_two_concurrent_questions` |
| E-F-04 | A browser refresh mid-stream | The page loads with a request ID in session storage | The page fetches the stored result by request ID, which the idempotency store holds for 10 minutes | `test_result_by_request_id` |
| E-F-05 | A copy of a partial answer | The Copy button during the stream | The copied text carries a header line that says partial answer with the request ID | `test_copy_partial_header` |
| E-F-06 | Script injection through rendered citations | DOMPurify for the answer markdown, and JSX text nodes instead of `textContent` | No model or filing text reaches `innerHTML` without sanitization | `test_ui_escapes_model_text` |
| E-F-07 | Secrets absent at start | The config load | The service starts, `/api/ready` reports `provider_key: false`, and the front-end shows the degraded banner before any question | `test_missing_key_ready` |
| E-F-08 | A port conflict | The bind error at start | The `make demo` target picks the next free port from 8000 to 8010 and prints the URL | `test_port_fallback` |
| E-F-09 | A venue network without internet | The provider connect error, or `KEEL_OFFLINE=1` | The answer cache serves the example questions and the golden set, and other questions get the degraded mode | `test_offline_cache_hit` |
| E-F-10 | A laptop that sleeps during the demo | The pre-flight checklist | Run `caffeinate -dims` on macOS, or disable sleep in the power options, and keep the laptop on power | Pre-flight item in chapter 21 |
| E-F-11 | An embedding or reranker model download fails | The model load error | The build stops with the download command. At question time, lexical retrieval continues without the dense index and the UI shows `degraded_retrieval`. | `test_lexical_only_fallback` |
| E-F-12 | A wrong clock or time zone on the laptop | The `keel doctor` time check against the file dates | A warning only. The time scope uses corpus dates, not the clock (D-33). | `test_doctor_time_check` |
