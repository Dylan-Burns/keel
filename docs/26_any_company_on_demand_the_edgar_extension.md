## 26. Any company on demand: the EDGAR extension

The brief scopes the exercise to the corpus in the zip file, and the required path runs on that corpus alone. This chapter builds phase 1 of the roadmap early. It adds exact reported numbers from the XBRL company facts API, `keel add TICKER` for any filer, and a watch list with a nightly refresh. The fetches run before the answer call, like the index build, so decision D-01 holds. The demo shows results from the night before, never a first live fetch.

### 26.1 Exact numbers from the company facts API

The endpoint `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` returns every value that a company has reported, in 1 JSON file per company. Each value carries the unit, the fiscal year and period, the form, the filing date, and the accession number. The fetch needs no HTML parse, and the numbers are the ones that the company filed.

1. Add `keel/edgar.py`. Load `https://www.sec.gov/files/company_tickers.json` once and cache it, to map tickers to CIKs.
2. Fetch the company facts with the required `User-Agent` header (name and email address). Send no more than 10 requests per second, with a 0.2-second pause between requests. Cache every response under `cache/edgar/`. The 54 corpus companies cost 54 requests the night before and 0 on demo day.
3. Add `config/facts.yaml` with 8 concepts: revenue, net income, diluted EPS, operating income, total assets, cash, shares outstanding, and long-term debt. Each entry lists the XBRL concept names in priority order, because companies tag revenue under different concepts (`Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`).
4. When the question type includes `numeric`, add a `<facts>` block to the context, with 1 line per fact. A line holds a fact ID, the value, the unit, and the fiscal label. It also holds the period end date, the form, and the filing date. Keep the latest filing per period, limit the block to the time window and to 40 lines.
5. Add 1 rule to the system block: for a number, prefer the `<facts>` block. Cite the fact ID. Use the chunks for the narrative around the number.
6. Extend the citation validator to fact IDs. The front-end shows a fact citation with a link to the filing index on EDGAR.
7. Score golden question G-15 as an exact match against the facts value. Change the memo decision rule from hold to ship for the 8 mapped concepts.
8. Show `facts: N lines from 1 cached file` in the trace drawer.

```
facts:NVDA:Revenues:FY2025 | <value> | USD millions | FY2025 | period end <date> | 10-K filed <date> | accession <number>
```

The demo moment: ask for NVIDIA revenue in fiscal 2025 and fiscal 2024 and the change in outlook. The answer gives the 2 reported values with units and period end dates from the facts block. It gives the outlook from the MD&A chunks. All of this comes from 1 call.

### 26.2 `keel add TICKER`

1. Resolve the ticker to a CIK from the cached ticker map. An unknown ticker stops with a message and the SEC lookup URL.
2. Fetch `https://data.sec.gov/submissions/CIK##########.json`. Pick the latest 10-K and the latest 10-Q from `filings.recent` by form and filing date. Take the accession number, the primary document name, and the report date.
3. Download the primary document from `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}` with the `User-Agent` header, and cache the file. A 10-K is 1 to 15 MB of inline XBRL HTML.
4. Convert the HTML to the corpus text format: drop `script` and `style` elements. Drop the hidden iXBRL header (`display:none` containers). Render each table row as pipe-separated cells on 1 line. Collapse whitespace. Write a `.txt` file with the 7-line header and the 60-equals separator.
5. Run the parser of chapter 7 unchanged. It includes the registrant check and the fiscal math. Then run the incremental build of chapter 9 for the new files only.
6. Record `source: edgar` for each new filing in the manifest and in the `filings` table. The coverage chips and the audit record show the source.

### 26.3 Watch list and nightly refresh

1. Keep the watch list in the `watch_list` table (ticker, user, added date).
2. `keel refresh` checks the submissions API for each watched ticker, compares the accession numbers with the `filings` table. It runs `keel add` for each new 10-K or 10-Q.
3. Run `keel refresh` at 02:00 local time. Use a systemd timer, a cron line, or the in-app scheduler of chapter 29.9. Write `refresh.log`.
4. The front-end banner reads the log and lists the filings added since the user's last visit.

### 26.4 Risks and controls

| Risk | Control |
| --- | --- |
| A first live fetch fails on stage | Run `keel add` for 2 companies the night before. Demo the command output, the manifest diff, and a question about a new company. Keep a live fetch optional with the hotspot up. |
| SEC fair-access rules | The `User-Agent` header with name and email on every request, the 0.2-second pause, and a disk cache, so a repeat run makes 0 requests. |
| Embedding time | About 600 chunks per 10-K, about 2 minutes on a CPU, never during the demo. |
| HTML variance across filers | The converter targets the 2 filers that the demo adds. The registrant check and the section order constraint catch a bad conversion, and a failed file goes to quarantine with the reason. |
| Concept mismatch in the facts | The priority lists per concept. A company with no match yields no fact line, and the answer uses the chunks and states the gap. |
| Scope creep in the eyes of the panel | Say it first: the required exercise runs on the provided corpus alone. This is the first roadmap item, built early, and the audit record shows the source of every filing. |

### 26.5 Tests

| Test | Expected result |
| --- | --- |
| `test_ticker_to_cik` | A saved slice of the ticker map resolves NVDA to its CIK |
| `test_submissions_pick` | A saved submissions JSON yields the latest 10-K and 10-Q |
| `test_html_to_text` | A saved 60 KB sample of 1 real 10-K converts to the corpus format with the header, the separator, and pipe rows |
| `test_facts_block` | A saved company facts JSON yields the revenue lines for the window with units and fiscal labels |
| `test_facts_citation` | A fact ID in the answer passes the validator, and the validator drops an unknown fact ID |
| `test_no_network` | Every EDGAR test runs with the network blocked |

### 26.6 Demo placement

- Minute 38 to 46 (value and future state): show live EDGAR instead of a description. Open the `keel add` log from the night before. Show the 2 new companies in the coverage chips. Ask 1 question about one of them. Then run the NVIDIA numeric question and open the drawer on the facts lines.
- Pick 2 added companies that fit the fictitious firm. A good pick is a mid-cap in a sector the panel is likely to care about (panel question P-09), not another mega-cap.
- The memo and the README state that numeric answers depend on the 8 mapped concepts. They name the concepts, so the limit is as visible as the capability.
