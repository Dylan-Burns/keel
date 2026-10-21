## 8. Section detection

The section detector finds the real start of each item and rejects the table-of-contents rows and the cross-references. The detector maps the 10-K scheme and the 10-Q scheme to 1 canonical taxonomy. The detector works on the clean text from chapter 7. A detection failure never stops the build. The failed span gets the section `unknown` and a warning.

### 8.1 The 3 kinds of item matches

An item label such as `Item 1A` appears several times in 1 filing. The NVDA fiscal 2025 10-K holds `Item 1A` 8 times. The 3 kinds are:

- A table-of-contents row: `Item 1A. | Risk Factors | 13`, with a page number in the last cell.
- A cross-reference inside prose: `Refer to Item 1A. Risk Factors` or `described in Part II, Item 7`.
- The real section start: `Item 1A. Risk Factors` on its own line, followed by the section text.

### 8.2 Candidate extraction

Rule R4 in chapter 7 puts each `Item` label at the start of a line. The detector extracts every candidate with 1 regular expression and records the features of each candidate.

```
PART_LABEL = r"(?m)^\s*PART\s+(I{1,3}|IV)\b"
ITEM_LABEL = r"(?m)^Item\s*(\d{1,2}[A-C]?)\s*[.:]?\s*\|?\s*([A-Za-z][^|\n]{2,90}?)\s*(?:\|\s*(\d{1,3}))?\s*$"
```

Group 1 is the item number, group 2 is the title text. Group 3 is a page number at the end, present when the row is a table row.

### 8.3 Classification features

| Feature | Rule | Effect |
| --- | --- | --- |
| `has_page_cell` | The line ends with a pipe and an integer of 300 or less. | Table-of-contents row |
| `in_toc_zone` | The candidate sits in the zone after the `TABLE OF CONTENTS` heading (or `INDEX`). The zone ends at the first candidate with 600 or more characters of prose before the next candidate. | Table-of-contents row |
| `in_cluster` | 5 or more candidates sit within 3,000 characters. | Table-of-contents row |
| `reference_cue` | The 60 characters before the label end with a reference cue. The cues are see, refer to, described in, discussed in, included in, set forth in, under, and in Part. A lowercase letter, a comma, or an open parenthesis before the label is also a cue. | Cross-reference |
| `trailing_cue` | The 40 characters after the title hold of this, above, below, or herein. | Cross-reference |
| `title_match` | The token set ratio between the title text and the expected title for the form and the item is 0.80 or more. | Real heading candidate |
| `body_ok` | The text up to the next candidate is 500 or more characters. Some items have short bodies by design: 1B, 3, 4, 6, 9, 9B, 9C, 16, and 10-Q Part II items 3, 4, and 5. These items accept 2 or more characters when `title_match` is 0.95 or more. | Real heading candidate |

A candidate with `has_page_cell`, `in_toc_zone`, or `in_cluster` is a table-of-contents row. A candidate with `reference_cue` or `trailing_cue` and without `body_ok` is a cross-reference. A candidate with `title_match` and `body_ok` is a real heading candidate with a score equal to the title match ratio. The fused short items from chapter 7, such as `Item 3. Defaults Upon Senior Securities` with the body `None.`, pass through the short-body rule.

### 8.4 Order constraint and selection

Real headings appear in the item order of the form, within each Part. The detector selects the final set with this procedure.

1. Group the real heading candidates by Part. For a 10-K, the Part comes from the nearest `PART_LABEL` match before the candidate. For a 10-Q, the first `PART II` match after Part I Item 4 starts Part II.
2. Within each Part, compute the longest sequence of candidates whose item numbers increase in the expected order. Use the sum of scores as the tie-break.
3. If 2 candidates for the same item survive, keep the candidate with the longer body.
4. Set the span of each section from its heading start to the next selected heading start.
5. Mark the span after the exhibits item as excluded. The exhibits item is 10-K Item 15 or 10-Q Part II Item 6. Mark also the span after the `SIGNATURES` heading as `excluded`. The chunker does not index excluded spans.
6. Tag a span whose heading matches Forward-Looking Statements, Cautionary Note, or Special Note with `boilerplate_flag=forward_looking`. The chunker indexes the span with the flag, and retrieval applies a weight of 0.5 to it (chapter 11).

### 8.5 Canonical section taxonomy

| Canonical section | 10-K items | 10-Q items |
| --- | --- | --- |
| `business` | Item 1 | None |
| `risk_factors` | Item 1A | Part II Item 1A |
| `legal_proceedings` | Item 3 | Part II Item 1 |
| `mdna` | Item 7 | Part I Item 2 |
| `market_risk` | Item 7A | Part I Item 3 |
| `financial_statements` | Item 8 | Part I Item 1 |
| `controls` | Item 9A | Part I Item 4 |
| `other` | Items 1B, 1C, 2, 4, 5, 6, 9, 9B, 9C, 10, 11, 12, 13, 14, 16 | Part II Items 2, 3, 4, 5 |
| `excluded` | Item 15 and the signature page | Part II Item 6 and the signature page |
| `unknown` | Any span without a selected heading | Any span without a selected heading |

The item numbers collide across forms: Item 2 is Properties in a 10-K and MD&A in a 10-Q Part I. The map above keys on the form and the Part, so the collision never reaches the index. The chunk metadata keeps the raw item label beside the canonical section for diagnostics.

NOTE: A 10-Q risk-factor section usually states only the changes since the last 10-K. The chunk metadata marks every 10-Q `risk_factors` chunk with `delta_only=true`. Retrieval for a risk question always adds the latest 10-K `risk_factors` chunks of the same company (chapter 11). The prompt tells the model that a 10-Q risk section is a delta.

### 8.6 When detection fails

| Failure | Detection | Action |
| --- | --- | --- |
| A 10-K lacks `risk_factors`, `mdna`, or `financial_statements`. | The coverage check after selection. | Warning `sections_incomplete` in the build report. The unassigned spans become `unknown` sections of at most 20,000 characters each. |
| A 10-Q lacks `mdna` or `financial_statements`. | The same check. | The same action. |
| The `risk_factors` body of a 10-K is shorter than 300 characters. | A length check. | Warning `risk_factors_short`. The span stays indexed. |
| No `PART II` match in a 10-Q. | The Part check. | The detector assigns the items after Item 4 to Part II by order, with confidence 0.5. |
| 2 real headings for 1 item have bodies within 10% of each other. | The tie check. | Keep both as the same section, with a warning. |

The detector stores a confidence value per section, equal to the title match ratio of the selected heading. A section filter at question time includes `unknown` chunks with a weight of 0.7, so a missed section still surfaces. The build report prints the share of 10-Ks with all 3 core sections. The target is 95% or more.

### 8.7 Tests

| Test | Input | Expected result |
| --- | --- | --- |
| `test_nvda_item_1a_once` | The NVDA fiscal 2025 10-K | Exactly 1 real `risk_factors` section with a body longer than 20,000 characters, and 7 rejected candidates |
| `test_toc_rows_rejected` | `Item 1A. \| Risk Factors \| 13` | Classified as a table-of-contents row |
| `test_cross_reference_rejected` | `Refer to Item 1A. Risk Factors` inside prose | Classified as a cross-reference |
| `test_10q_part_ii_risk` | An AAPL 10-Q | Part II Item 1A maps to `risk_factors` with `delta_only=true` |
| `test_10q_mdna` | The same 10-Q | Part I Item 2 maps to `mdna` |
| `test_10k_properties_other` | A 10-K | Item 2 maps to `other` |
| `test_short_items` | `Item 3. Defaults Upon Senior Securities` with body `None.` | Accepted as a real heading through the short-body rule |
| `test_exhibits_excluded` | A 10-K | The span after Item 15 is `excluded` |
| `test_forward_looking_flag` | A span with the heading Cautionary Note Regarding Forward-Looking Statements | `boilerplate_flag=forward_looking` |
| `test_unknown_fallback` | A text with no item labels | 1 or more `unknown` sections and the warning `sections_incomplete` |
