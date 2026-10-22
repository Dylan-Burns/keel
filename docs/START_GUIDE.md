# Keel start guide for the pilot

The 1-page guide for the 5 pilot users of chapter 27.6 (2 associates, 2 analysts, 1 partner). Keel answers questions about the SEC 10-K and 10-Q filings of the indexed companies. Each answer comes from 1 model request, and the server checks every citation against the filing text before it shows it. A finding that no citation supports carries the mark `unverified`; the page never hides it.

## 1. Get your token

The pilot engineer creates 1 token per person and hands it over in person or through the firm's password manager, never by email or chat:

```bash
uv run keel users add alice --role analyst   # analyst, partner, or admin
```

The command prints the token once. Keel stores only its sha256 hash in the users file, so a lost token cannot be recovered: ask for a new one, and the engineer runs `keel users remove alice` and `keel users add alice` again. A removed user loses access on the next request, with no restart.

## 2. Sign in

Open the pilot address the engineer sends you (the HTTPS subdomain of the Railway deploy; `http://localhost:8000` on the engineer's laptop). Paste the token into **Access token** at the top right and click **Save**. The token stays in this browser tab only (session storage) and is gone when you close the tab. **Token rejected** means a typo or a removed user.

## 3. Ask

- Type a question that names companies (names or tickers) and, if it matters, a period: `What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?`
- Or pick a **template** under the question box (public comparables, risk benchmark, portfolio review, regulatory scan, memo paragraph), fill the companies and the period, and click **Fill**. Fill only prefills the box; nothing is sent until you ask.
- Read the answer top down: the direct answer, the findings per company with citation chips (each opens the quote, the filing, the section, the fiscal period, and the SEC link), the comparison table, the coverage statement, and the gaps list. The gaps list is always there: it says what the filings in the index do not cover.
- Every number carries its fiscal label and period end date. NVIDIA's fiscal year ends in January, so "fiscal 2025" ended on January 26, 2025.
- A company outside the index gets the gray out-of-scope card with no model call. Ask the engineer to add it (section 6).

## 4. History and share links

- **History** in the footer lists your own questions, newest first, with **Open answer**, **Copy link**, and **Re-run**. Re-run prefills the question box; it never sends on its own.
- **Copy link** gives `/a/<request ID>`. Anyone with a pilot token can open it read-only, and the page does not show who asked. A link works while Keel still stores the answer: for 10 minutes, then as long as the answer cache holds it (a comp set question or a degraded answer is not cached, so its link ends after 10 minutes; Re-run asks it again).

## 5. Comp sets

**Comp sets** in the footer saves a named list of tickers, shared by the firm. Any user creates a set; only its owner and the admins change or delete it. A question names a set with `my <name> comps`, `our <name> comp set`, `the <name> peers`, or `<name> comparables`: `How do the risk factors of my software comps compare?` A ticker outside the index shows in the gaps as "(comp set, not in the corpus)" until the engineer adds it.

## 6. Feedback, memos, new companies

- **Thumbs up or down** under each finished answer, with an optional note (at most 2,000 characters). A thumbs-down flags the answer; the engineer reviews every flagged answer each week (`keel feedback --flagged`) and turns the good ones into golden questions. Your later vote on the same answer replaces the earlier one.
- **Memo export**: the web page has no memo button yet. Send the answer link to the engineer, who runs `keel export <request ID> --format docx` (or `markdown`) and returns a memo with numbered footnotes and SEC links. A script can call `GET /api/export/<request ID>?format=docx` with the bearer token. **Export JSON** and **Copy as markdown** in the footer save the raw answer.
- **New companies and new filings**: the engineer runs `keel add TICKER` for a company outside the index (its latest 10-K and 10-Q from EDGAR), and the watch list (`keel watch add TICKER`) holds the portfolio companies that `keel refresh` checks for new filings: each night once the deploy's scheduler runs it (stage 21), by hand until then.

## 7. What data goes where

| Data | Where it goes | Who sees it |
| --- | --- | --- |
| Your question and the retrieved filing excerpts (public SEC text) | 1 request to the model provider (Anthropic, Claude Messages API) per question. Under the provider's commercial terms, API data is not used to train models; the engineer checks the current terms before the pilot | The provider, for that request |
| Your question, your user name, the chunk IDs, the model, the tokens, the cost, the latency | 1 line in the audit log (`<logs.dir>/audit.jsonl` on the pilot volume, owner-only file, rotated daily). It never holds the prompt text or a token | You (history), the admins, the engineer |
| A memo export: its time, request ID, format, and user name (`cli` for `keel export`) | 1 line in the export log (`<logs.dir>/exports.jsonl`, owner-only file). It never holds the question, the answer, or a token | The engineer (pilot metrics) |
| The answer | The answer cache on the pilot volume | Any pilot token holder with the link |
| Votes and notes, comp sets | The pilot store (`<logs.dir>/pilot.sqlite`) | The engineer and the admins (`keel feedback`); comp sets are shared by the firm |
| Your token | Only its sha256 hash, in the users file | Nobody can read the token back |

At question time Keel calls only the model provider and the SEC (`www.sec.gov`, `data.sec.gov`, for the company facts of a numeric question and for `keel add`). The nightly backup of the deploy (stage 21) copies the index and the current audit log to the firm's bucket; the pilot store, the export log, and the rotated audit files are not in it yet, so the engineer copies them by hand. Do not paste private deal data into a question: the pilot covers public filings only (chapter 27.4). Chapter 27.2 sets a 1-year retention for the audit log; the deletion is a manual step of the engineer during the pilot.

## 8. Whom to contact

The pilot engineer (the role that deploys Keel and answers pilot questions, about 1 day a week for the 4 weeks, chapter 27.5) for tokens, new companies, the watch list, memo exports, a wrong answer, or a service that does not answer. Report a wrong answer with its link and a thumbs-down note. The pilot sponsor at the firm (the partner who owns the pilot decision at week 4) for the scope of the pilot and access for a new user.

## 9. How the pilot is measured

The engineer runs `uv run python scripts/pilot_metrics.py --since <pilot start date> --exclude-user <engineer> --exclude-user legacy` each week (`legacy` is the shared service token and every `keel ask` or `keel eval` run from the terminal, such as the weekly golden set). It reads the audit log, the feedback table, the corpus manifest, the refresh log, and the export log, and prints per week: active users, questions, cost, cost per question, thumbs-up rate, memos exported, companies added, and filings refreshed. A memo the engineer writes with `keel export` for you counts under the user `cli`. The success metrics of chapter 27.6: 3 of 5 users active each week from week 2, 30 or more questions a week from week 3, a thumbs-up rate of 70% or more, and 3 or more memos exported. At week 4 the pilot continues to phase 2 of chapter 22 when 3 of the 4 hold. Hours saved come from you, not from the logs.
