## 27. Pilot-ready product features

A deal team uses a filings tool every week only if the tool fits the work the team already does. That work is comp sets, memos with sources, and a watch on portfolio companies. It also needs trust in what the tool says about its own limits. The core answers questions. The features in this chapter make the answers part of the work product. Each feature is small because it sits on data that the core already produces. The audit record becomes the history. The alias file becomes the comp sets. And `keel add` becomes the watch list refresh.

### 27.1 What a deal team needs, and what delivers it

| Job in the deal team | What the product does | Built on |
| --- | --- | --- |
| Build and reuse a comparable set for a target | Saved comp sets (name plus tickers) that a question can name, with `keel add` for any absent company | `config/companies.yaml`, chapter 26 |
| Put a cited paragraph into an investment committee memo | Export an answer as a memo: direct answer, findings, comparison table, numbered footnotes with filing name, section, period, and SEC link | The validated answer JSON |
| Review portfolio companies each quarter | A watch list with a nightly refresh and a banner that lists the filings added since the user's last visit | Chapter 26 |
| Find what a colleague asked last month | A history page per user with a re-run button, and a shareable link to any stored answer | The audit record and the answer cache |
| Trust the numbers | Exact reported values from the XBRL facts for the 8 mapped concepts, with the concept named in the citation | Chapter 26 |
| Know what the tool cannot do | The coverage chips, the gaps list, and the performance memo on the help page | Chapters 12 and 25 |
| Tell the firm what the tool costs and who uses it | Audit records per user, a monthly usage and cost view, and a pilot metrics script | The audit log |

### 27.2 The pilot feature set

| Feature | Files | Notes |
| --- | --- | --- |
| Users and tokens | `config/users.yaml`, `api/auth.py` | Name, role (analyst, partner, admin), token hash. Every audit record carries the user. OpenID Connect replaces this in a paid engagement. |
| History and shareable links | `api/routes.py` (`/api/history`, `/a/{request_id}`), `web/` | A stored answer renders from the audit record and the answer cache. A link opens read-only for any user with a token. |
| Comp sets | Table `comp_sets`, `keel/understanding.py`, `web/` | Create and edit in the UI. The phrase `my software comps` in a question expands to the tickers. A ticker outside the index starts `keel add` in the background with a status line. |
| Question templates | `web/` | 5 buttons that prefill a structured question: public comparables, risk benchmark, portfolio review, regulatory scan, and a memo paragraph. Each has placeholders for the companies and the period. |
| Feedback | Table `feedback`, `api/routes.py`, `web/` | A thumbs vote and a note per answer. The eval script reads flagged answers as candidate golden questions. |
| Memo export | `keel/export.py` | Markdown first, then DOCX through python-docx. Footnote numbers follow citation order, and every number carries its fiscal label and period end date. |
| Watch list and refresh | `keel/edgar.py`, `keel refresh`, a timer | Chapter 26.3. |
| Deploy and backup | `Dockerfile`, `Caddyfile`, `infra/backup.sh` | Railway by default (chapter 29.9): the image, 1 volume, an HTTPS subdomain, backups to an S3-compatible bucket from the in-app scheduler. The AWS alternative: 1 small host, HTTPS through Caddy, a nightly copy of `chunks.sqlite`, `vectors.npy`, `audit.jsonl`, and the feedback table to object storage. The engineer writes the restore procedure and tests it once. |
| Data use page | `web/src/components/HelpPage.tsx` | What goes to the model provider, that the provider does not use API data to train models under its commercial terms (check the current terms before the pilot). Also what the service logs, the 1-year retention, and who can see the history. |
| Start guide and metrics | `docs/PILOT.md`, `scripts/pilot_metrics.py` | A 1-page start guide. Weekly numbers from the audit log: active users, questions, cost, thumbs-up rate, companies added. |

### 27.3 Product rules that stay from the demo

- 1 model request per question stays. The rule keeps the cost at about $0.09 per question and the audit record complete. The agent tasks in chapter 22 get their own budget later.
- Every number carries its fiscal label and period end date, and every claim carries a citation that the server validated. The page marks an answer without a citation and does not hide it.
- The gaps list is always shown. A tool that says what it does not know is a tool that a partner keeps.

### 27.4 What the pilot does not include

Private data rooms, per-tenant isolation, OpenID Connect, transcripts, and news. Each is in chapter 22 with a size, and the firm needs none of them to learn whether a deal team adopts the tool.

### 27.5 Cost of the pilot

At about $0.09 per question, 5 users with 40 questions a week cost about $18 a week in model calls. The host costs about $40 a month. Embeddings run locally. The cost that repeats and matters is the engineer who answers questions during the pilot, about 1 day a week for 4 weeks.

### 27.6 The pilot plan

1. Week 0: deploy, load the firm's comp sets and watch list (the portfolio and 2 live deals), run `keel add` for every ticker outside the corpus. Run the golden set. Write the performance memo with the measured numbers.
2. Weeks 1 to 4: 5 users (2 associates, 2 analysts, 1 partner). The engineer reviews the flagged answers each week, adds golden questions from the feedback, and ships prompt and alias fixes.
3. Success metrics, from the audit log and not from interviews. Three of 5 users are active each week by week 2. Users ask 30 or more questions a week by week 3. The thumbs-up rate is 70% or more. Users export 3 or more memos. Users report hours saved against the base case of table 2.4.1.
4. Decision at week 4: continue to phase 2 of chapter 22 if 3 of the 4 metrics hold. Otherwise fix the top 3 reasons from the feedback table and run 2 more weeks.

### 27.7 New technical names

| Term | Definition |
| --- | --- |
| comp set | A named list of tickers that a user saves and that a question can name |
| watch list | The tickers that `keel refresh` checks for new filings each night |
| memo export | The Markdown or DOCX file that holds 1 answer with numbered footnotes |
| trace drawer | The front-end panel that renders the audit record of the current answer |
| facts block | The `<facts>` element in the context with 1 line per XBRL fact |
| pilot | The 4-week use of Keel by 5 users with measured adoption |
