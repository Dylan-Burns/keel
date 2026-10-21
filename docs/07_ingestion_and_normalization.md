## 7. Ingestion and normalization

The parser turns each raw file into a `ParsedFiling` with validated metadata, clean text, and reconstructed tables. A file that fails a check goes to the quarantine list with a reason. Every rule below responds to a measured property of the corpus. The parser is deterministic, and a repeat run on the same file gives the same output.

### 7.1 Parser stages

1. Read the bytes and decode as UTF-8 in strict mode. Remove a byte order mark. Normalize the end-of-line characters to `\n`.
2. Parse the 7-line header and find the separator line.
3. Apply Unicode NFKC normalization. Replace non-breaking spaces with spaces, curly quotes with straight quotes, and remove zero-width characters.
4. Remove the XBRL block between the separator and the first real prose.
5. Remove page-number artifacts and Table-of-Contents artifacts.
6. Repair fused sentences and fused headings.
7. Reconstruct the pipe tables with carried column labels and units.
8. Read the cover page: the form phrase, the period end date, and the registrant name.
9. Validate the metadata against the file name, the header, and the manifest. Quarantine a file with a conflict.
10. Hand the clean text and the tables to the section detector (chapter 8).

NOTE: Stage 3 runs before stage 4 because the XBRL block holds no spaces, and the NFKC rule does not change that property. Stage 6 runs after stage 4 because the repair rules must not touch the XBRL block.

### 7.2 Header parse

The header holds 7 lines with the keys Company, Ticker, Filing Type, Filing Date, CIK, Source, and URL, then a line of 60 equals signs. The parser reads the keys with 1 regular expression per line and accepts extra spaces around the colon.

```
HEADER_LINE = r"^(Company|Ticker|Filing Type|Filing Date|CIK|Source|URL)\s*:\s*(.*)$"
SEPARATOR   = r"^={60}$"
FORM_MAP    = {"10-K (Annual Report)": "10-K", "10-Q (Quarterly Report)": "10-Q"}
```

If a key is absent, or if the Filing Type value is not in `FORM_MAP`, the parser reports `HeaderError` and quarantines the file. The parser validates the URL host as `www.sec.gov` with the `https` scheme. A URL with another host goes into the metadata with the flag `url_untrusted` and never renders as a link.

### 7.3 Separator detection

The separator is the first line that matches `SEPARATOR` within the first 20 lines. If no line matches, the parser reports `SeparatorMissing` and quarantines the file. The body starts after the separator.

### 7.4 XBRL block removal

In 241 of 246 files, a block of inline XBRL facts follows the separator. The block holds strings such as `iso4217:USD`, `xbrli:shares`, `us-gaap:`, member names, and dates with no spaces. The block length runs from 18,772 characters (NVDA fiscal 2025 10-K) to 284,260 characters (BAC 10-K filed 2025-02-25). The parser uses 2 detectors and 1 signature check.

```
COVER_MARKER = r"UNITED\s+STATES\s*SECURITIES\s+AND\s+EXCHANGE\s+COMMISSION"   # case-insensitive
PROSE_WINDOW = 300 characters with at least 25 spaces and at least 3 lowercase words of 4 or more letters
XBRL_SIGNS   = ("us-gaap:", "xbrli:", "iso4217", "dei:")
MAX_BLOCK    = 400000 characters
```

1. Find the first `COVER_MARKER` match after the separator. This match is the primary cut point.
2. Scan from the separator for the first position where a `PROSE_WINDOW` starts. This position is the secondary cut point.
3. Set the cut point to the earlier of the 2 points.
4. If the removed block holds no `XBRL_SIGNS` string and has more than 200 characters, keep the block. Log a warning. This rule protects the 5 files without an XBRL block.
5. If the cut point is more than `MAX_BLOCK` characters after the separator, log a warning and still cut.
6. If no cut point exists, keep the body and log `no_xbrl_block`.
7. Record `xbrl_block_chars` in the metadata. The build report shows the minimum, the median, and the maximum.

CAUTION: If the build report shows a maximum `xbrl_block_chars` above 300,000, inspect that file before you publish the index. If the report shows a block below 1,000 characters for a file with a known block, inspect that file too.

### 7.5 Whitespace and sentence boundary repair

Whole sections sit on 1 line, and the median longest line is 51,424 characters. The parser repairs boundaries with 5 rules. The rules run in this order.

```
R1 fused period   : (?<=[a-z0-9\)\]"'%])\.(?=[A-Z][a-z])          -> ". "
R2 U.S. boundary  : (?<=\bU\.S\.)(?=[A-Z][a-z])                      -> " "
R3 fused heading  : (?<=[a-z]{4})(?=[A-Z][a-z]{2})  inside 1 token    -> "\n"  (protected names excluded)
R4 item label     : (?<!\n)(?=Item\s*\d{1,2}[A-C]?\.)                 -> "\n"
R5 whitespace     : 2 or more spaces -> 1 space; 3 or more newlines -> 2 newlines
```

Rule R1 protects the abbreviations in `config/abbreviations.txt` (Inc., Corp., Co., No., Ltd., Mr., Dr., vs., Jr., Sr., St.). Rule R3 protects the names in `config/protected_names.txt` (JPMorgan, McDonald, PepsiCo, BlackRock, iPhone, iPad, eBay, YouTube, LinkedIn, PayPal, ExxonMobil, ConocoPhillips, GitHub, and others). Rule R3 splits `BusinessesNVIDIA` into `Businesses` and `NVIDIA`. The second token starts with a capital letter, and the first token has 4 or more letters. A wrong split only changes lexical tokens, and the dense model tolerates it. The parser test in table 7.13 measures the rules on real snippets.

### 7.6 Removal of page-number and Table-of-Contents artifacts

Page numbers fuse with the phrase Table of Contents and with the next sentence, as in `36Table of ContentsIn July 2023`. The NVDA fiscal 2025 10-K holds 82 such occurrences. The parser applies these rules before the sentence repair.

```
A1 fused page break : \b\d{1,3}\s*Table of Contents\s*   -> "\n"
A2 bare page number : ^\s*\d{1,4}\s*$                    -> ""
A3 statement page   : ^\s*F-\d{1,3}\s*$                   -> ""
```

Rule A1 matches the exact case `Table of Contents` and does not match the real heading `TABLE OF CONTENTS`, which the section detector uses in chapter 8. The parser counts the removals per file and writes the count into the build report.

### 7.7 Non-breaking space and quote normalization

243 files hold non-breaking spaces and 245 files hold curly quotes. The parser maps U+00A0 and U+202F to a space, and U+2018 and U+2019 to an apostrophe. The parser maps U+201C and U+201D to a straight double quote, and removes U+200B and U+FEFF. NFKC normalization also maps ligatures and full-width characters. This stage runs before every regular expression, so the item label regex sees `Item 1A.` and not `Item\u00a01A.`.

### 7.8 Table row reconstruction

Tables are flat pipe-delimited rows, and the title, the column labels, and the units often sit apart from the numbers. The parser rebuilds each table with this procedure.

1. Mark a line with 2 or more pipe characters as a table row.
2. Group consecutive table rows into 1 table. Permit 1 blank line inside a group.
3. Mark the first 1 or 2 rows as label rows. The condition: at least 50% of the non-empty cells are not numeric.
4. Search the 3 lines before the table and the label rows for a units phrase with the regular expression `\((?:in|dollars in|amounts in)\s+(thousands|millions|billions)[^)]*\)`.
5. Set the title to the nearest non-empty line within 3 lines before the table. Reject a table row, a line longer than 120 characters, or a line that ends with a period.
6. Render the table for the chunker as 1 caption line and 1 line per data row. The caption holds `TABLE:`, the title, the units, and the column labels.
7. Split a table with more than 40 data rows into parts of 40 rows. Repeat the caption on each part.

```
TABLE: <title> | units: in millions, except per share data | columns: <label 1> | <label 2> | <label 3>
<cell> | <cell> | <cell>
```

The parser does not convert numbers. The text keeps the numbers as written, and the prompt rules in chapter 12 tell the model to carry the units from the caption.

### 7.9 Cover page: period end date and fiscal year

The cover page phrase runs into the next token, as in `For the fiscal year ended January 26, 2025OR` and `For the quarterly period ended December 31, 2022or`. The parser reads the phrase with this regular expression, which stops at the 4-digit year.

```
PERIOD_END = r"(?i)(fiscal\s+year|quarterly\s+period)\s+ended\s*:?\s*([A-Z][a-z]+\.?\s+\d{1,2},?\s*\d{4})"
REGISTRANT = r"([A-Z][A-Za-z0-9&.,' -]{2,80}?)\s*\(?\s*Exact name of registrant"
```

The fiscal year and the fiscal period come from the period end date and the company's fiscal-year-end month.

1. Read the first `PERIOD_END` match after the cover marker. The first group gives the form phrase and the second group gives the date.
2. Compute the nominal month of the date. If the day is 4 or less, the nominal month is the previous month. This rule covers 52-week and 53-week calendars, such as a Disney year that ends on October 2.
3. For a 10-K, set the fiscal year to the year of the period end date. NVDA January 26, 2025 gives fiscal 2025, and AAPL September 28, 2024 gives fiscal 2024.
4. For each ticker, set the fiscal-year-end month to the nominal month of the 10-K period end date. Use the 10-K of that ticker in the corpus. If the ticker has no 10-K, read `config/fiscal_year_ends.yaml`.
5. For a 10-Q, compute `offset = (fiscal_year_end_month - nominal_quarter_month) mod 12`. An offset of 9 is Q1, 6 is Q2, and 3 is Q3. Another value gives the period `unknown` and a warning.
6. For a 10-Q, set the fiscal year to the year of the nominal quarter month plus the offset in months. AAPL December 2022 with a September year end gives offset 9, Q1, and fiscal 2023. NVDA October 2024 with a January year end gives offset 3, Q3, and fiscal 2025.
7. Store `period_end_date`, `fiscal_year`, `fiscal_period` (FY, Q1, Q2, Q3), and `fiscal_year_end_month`.

### 7.10 Metadata validation and the quarantine list

The parser runs 11 checks and records the result of each check in the metadata. A quarantine stops the file from the index. A warning goes into the build report.

| Check | Rule | Severity |
| --- | --- | --- |
| CK-01 | The header holds all 7 keys. | Quarantine |
| CK-02 | The separator exists. | Quarantine |
| CK-03 | The ticker in the file name equals the header ticker. | Quarantine |
| CK-04 | The form in the file name, the header form, and the cover page phrase agree. | Quarantine |
| CK-05 | The filing date in the file name equals the header filing date. | Warning |
| CK-06 | The registrant name on the cover page matches the header company name after normalization. | Quarantine |
| CK-07 | The cover page gives a period end date. | Fallback to the period code with the flag `period_source=filename`, then a warning. A file with no period code goes to quarantine. |
| CK-08 | The period code in the file name, when present, equals the calendar quarter of the period end date. | Warning |
| CK-09 | The filing date is 0 to 120 days after the period end date. | Warning |
| CK-10 | The file is in the manifest file list. | Warning with the flag `unmanifested` |
| CK-11 | The filing ID is unique. | Keep the file with the latest filing date, then a warning |

Name normalization for CK-06 has 3 steps: convert to upper case, remove punctuation, and drop the stop tokens. The stop tokens are THE, INC, INCORPORATED, CORP, CORPORATION, CO, COMPANY, LTD, LIMITED, PLC, LLC, and AND. The check passes when the 2 token sets are equal. The GE file fails this check: the header gives the set GENERAL ELECTRIC and the cover page gives GENERAL ELECTRIC CAPITAL. The extra token CAPITAL is a conflict, and the file goes to the quarantine list with the reason `registrant_mismatch`. The source URL `gecc10k2014.htm` and the filing date 2015-02-27 appear in the quarantine record as evidence.

A human can lift a quarantine with an entry in `config/overrides.yaml` that states the correct ticker, company, form, and period end date. The build report lists every quarantined file with its reason. The front-end coverage page lists the quarantined files so that a user knows why GE has no data.

### 7.11 Deterministic document and chunk IDs

The filing ID and the chunk ID come from validated metadata, not from file names or random values.

```
filing_id = f"{ticker}_{form_code}_{period_end_date:%Y-%m-%d}"      # AAPL_10Q_2022-12-31
chunk_id  = f"{filing_id}__{section}__{sequence:04d}"                # AAPL_10Q_2022-12-31__risk_factors__0007
chunk_hash = sha256(normalized_chunk_text)[:16]
corpus_sha256 = sha256 of the sorted list of (file name, file sha256)
```

The sequence number restarts at 0 for each section. The chunk hash changes when the text changes, and the chunk ID stays stable within 1 index version. The audit log records the index version with every chunk ID, so an old audit record still resolves to the right text.

### 7.12 Idempotent re-runs

1. Compute the sha256 of each file in the corpus directory.
2. Compare each file hash, the parser version, and the chunker version with the `filings` table of the current index.
3. Skip a file whose 3 values are unchanged.
4. Parse, chunk, and embed a file that is new or changed, and replace its rows and vectors.
5. Delete the rows and vectors of a file that is no longer in the directory.
6. Rebuild the FTS5 index and recompute the manifest checksums.
7. Write the new index into a temporary directory, then rename the directory to `index/current` in 1 atomic operation.

A failed build never touches `index/current`. A second run of the same build on the same corpus produces the same chunk IDs, the same chunk hashes, and the same manifest checksums.

### 7.13 Parser tests from real snippets

The tests read small excerpts copied from the real files into `tests/fixtures/snippets/`. Each excerpt is 2 KB or smaller.

| Test | Snippet source | Expected result |
| --- | --- | --- |
| `test_header_parse` | The 7-line header of the NVDA fiscal 2025 10-K | All 7 keys, form `10-K`, URL host `www.sec.gov` |
| `test_separator_missing` | A header with the separator line removed | `SeparatorMissing` and a quarantine record |
| `test_xbrl_cut_at_cover` | The first 20,000 characters of the NVDA fiscal 2025 10-K | The cut point is at the cover marker, and `xbrl_block_chars` is 18,772 |
| `test_xbrl_long_block` | The first 300,000 characters of the BAC 10-K filed 2025-02-25 | `xbrl_block_chars` is 284,260 and the cover marker follows the cut |
| `test_no_xbrl_block` | The body start of a file without an XBRL block | No removal and the log `no_xbrl_block` |
| `test_cover_fused_or` | `For the fiscal year ended January 26, 2025OR` | Period end date 2025-01-26, form phrase `fiscal year` |
| `test_cover_fused_transition` | `For the quarterly period ended December 31, 2022or TRANSITION REPORT` | Period end date 2022-12-31, form phrase `quarterly period` |
| `test_fiscal_q1_apple` | AAPL 10-Q with period end 2022-12-31 | Fiscal 2023, Q1 |
| `test_fiscal_q3_nvda` | NVDA 10-Q with period end in October 2024 | Fiscal 2025, Q3 |
| `test_nominal_month` | A period end date of October 2 | Nominal month September |
| `test_heading_split` | `OverviewOur Company and Our BusinessesNVIDIA pioneered` | 3 segments: `Overview`, `Our Company and Our Businesses`, `NVIDIA pioneered` |
| `test_protected_name` | `JPMorgan Chase` and `McDonald's` | No split |
| `test_page_artifact` | `36Table of ContentsIn July 2023` | `In July 2023` on a new line and 1 removal counted |
| `test_fused_items` | `Item 3. Defaults Upon Senior SecuritiesNone.Item 4. Mine Safety DisclosuresNot applicable.` | 2 item labels on separate lines with bodies `None.` and `Not applicable.` |
| `test_nbsp_item_label` | `Item 1A.\u00a0\u00a0\u00a0Risk Factors` | The label matches after normalization |
| `test_table_units` | A pipe table with a units line 2 lines above | Caption holds `units: in millions` and the column labels |
| `test_registrant_mismatch` | The GE header and the GE cover page | Quarantine with reason `registrant_mismatch` |
| `test_idempotent_ids` | 2 parses of the same file | Identical chunk IDs and chunk hashes |
