## 2. Business context and value creation for a PE firm

Keel pays back its production hardening cost in about 4 months in the base case. The value grows with each data source that the firm adds. This chapter gives the use cases, the status quo, and the value model with labeled assumptions. It then gives the build-versus-buy comparison and the limits of what the demo proves.

### 2.1 The client and the problem

The client is a fictitious mid-market PE firm with a deal team of about 10 analysts and associates (assumption A-11). The team does due diligence on targets, compares public comparables, and reviews portfolio companies each quarter. Today an analyst finds facts in filings with keyword search in PDF files, with the EDGAR full-text search, and with terminal subscriptions. Each fact needs a manual copy of the page reference into the memo. The work is slow, the coverage across companies is uneven, and the audit trail is weak.

### 2.2 Use cases

| Use case | Example question | Keel output | Value for the firm |
| --- | --- | --- | --- |
| Public comparables for due diligence | How do the margins and the outlook of Target and Walmart compare? | A comparison table with 1 citation per cell | A comparable set in minutes, with sources that a partner can check |
| Risk factor benchmark | Which risk factors do the major banks share, and which are unique to 1 bank? | Findings per company and a shared-versus-unique table | A consistent taxonomy across companies instead of 4 separate reads |
| Portfolio company review | What changed in Tesla's risk factors between fiscal 2024 and fiscal 2025? | A trend answer with the 10-K and 10-Q chunks for each period | Quarterly reviews that start from the filing text, not from memory |
| Regulatory scan | What regulatory risks do the major pharmaceutical companies face? | A sector answer with a coverage statement per company | Early sight of regulatory exposure across a sector |
| Investment committee memo | Summarize NVIDIA's revenue drivers over the last two years with citations. | A direct answer with citations and next questions | Memo paragraphs that carry their own evidence |

### 2.3 The status quo that Keel replaces

| Method today | Time per 3-company task | Cost | Weakness |
| --- | --- | --- | --- |
| Keyword search in PDF files and the EDGAR full-text search | 3 to 6 hours (assumption V-04) | Analyst time | No synthesis, no fiscal alignment, and manual citations |
| Terminal subscriptions | 1 to 3 hours for structured data | Assumed $25,000 per seat per year (assumption A-12) | Weak for narrative comparisons such as risk factors, and no custom prompts |
| A chat assistant without retrieval | Minutes | Low | Invented facts, no citations, and firm questions leave the firm |

Keel does not replace the terminal for market data and structured financials in this release. Keel replaces the narrative research step, which is the slowest step in the status quo.

### 2.4 Value model

Every number in this model is an assumption or a formula over assumptions. Table 2.4.1 lists the assumptions. Table 2.4.2 gives the results. Table 2.4.3 gives the cost per question.

Table 2.4.1: Assumptions

| ID | Assumption | Low | Base | High | Basis |
| --- | --- | --- | --- | --- | --- |
| V-01 | Analysts and associates who do primary-source research | 8 | 10 | 15 | Assumed size of a mid-market deal team |
| V-02 | Share of the team that uses Keel after 3 months | 40% | 60% | 80% | Assumed adoption |
| V-03 | Research tasks per analyst per month | 3 | 6 | 10 | Assumed. 1 task = 1 multi-company question set |
| V-04 | Hours per task with the status quo | 3 | 4 | 6 | Assumed manual search and reads |
| V-05 | Hours per task with Keel, with verification of citations | 1.5 | 1.0 | 0.75 | Assumed |
| V-06 | Loaded cost per analyst hour, USD | 120 | 150 | 175 | Assumed salary plus overhead |
| V-07 | Questions per task | 8 | 8 | 8 | Assumed. Includes next questions |
| V-08 | Model cost per question, USD | 0.09 | 0.09 | 0.09 | Table 2.4.3, base prices |
| V-09 | Host cost per month, USD | 300 | 300 | 300 | Assumed. 1 small virtual machine and storage |
| V-10 | Maintenance, engineer FTE | 0.2 | 0.1 | 0.1 | Assumed $20,000 per FTE month |
| V-11 | One-time production hardening, USD | 48,000 | 48,000 | 48,000 | Assumed 6 engineer weeks at $8,000 per week |

Table 2.4.2: Results

| Result | Low | Base | High | Formula |
| --- | --- | --- | --- | --- |
| Hours saved per month | 14.4 | 108 | 630 | V-01 x V-02 x V-03 x (V-04 minus V-05) |
| Labor value per year, USD | 20,736 | 194,400 | 1,323,000 | Hours saved x V-06 x 12 |
| Questions per month | 77 | 288 | 960 | V-01 x V-02 x V-03 x V-07 |
| Model cost per month, USD | 7 | 26 | 86 | Questions x V-08 |
| Run cost per year, USD | 51,684 | 27,912 | 28,632 | (V-09 + V-10 cost + model cost) x 12 |
| Net value per year, USD | minus 30,948 | 166,488 | 1,294,368 | Labor value minus run cost |
| Payback of V-11 | None on hours alone | About 3.5 months | Less than 1 month | V-11 divided by monthly net value |

CAUTION: In the low case, the saved hours do not cover a 0.2 FTE maintenance cost. The low case pays back only if maintenance stays at 0.05 FTE or if the firm counts the cycle-time value below. For this reason, chapter 22 ties each roadmap phase to a use case with measured adoption.

Table 2.4.3: Cost per question, base case

| Item | Tokens | Price per 1M tokens, USD | Cost, USD |
| --- | --- | --- | --- |
| System prompt, read from the prompt cache | 1,800 | 0.20 | 0.0004 |
| Question analysis and context, not cached | 33,000 | 2.00 | 0.0660 |
| Output | 2,000 | 10.00 | 0.0200 |
| Total | 38,000 |  | 0.0866 |

Assumption A-10: The prices are for Claude Sonnet 5.5 as published on third-party price pages on 2026-10-20. The pages give $2 per 1M input tokens and $10 per 1M output tokens. The cache-read price is $0.20 per 1M tokens, with 1 report of a cut to $0.10. The same pages list the fallback model, Claude Haiku 5.5, at $0.10 per 1M input tokens and $0.50 per 1M output tokens. These prices apply to prompts up to 100,000 tokens. A question that uses the fallback model costs about $0.005. A large question with 64,000 context tokens and 4,000 output tokens costs about $0.17. Confirm all prices on the provider price page before the demo.

Value that the model does not count:

- Cycle time: an answer arrives in about 1 minute. A partner can then ask a next question in the same session.
- Breadth: a team can ask about 20 companies for the same effort as 3 companies today.
- Consistency: 1 section taxonomy applies to every company, so comparisons are like for like.
- Audit trail: the service logs each answer with the question, the chunk IDs, the prompt hash, and the model version.
- Knowledge retention: questions and answers become assets of the firm, not of 1 analyst.

### 2.5 Build versus buy

| Criterion | Vendor research platform | Keel |
| --- | --- | --- |
| Public filing coverage | Thousands of companies, live | 54 companies now, live EDGAR in phase 1 of the roadmap |
| Private data rooms | Varies by vendor, often an add-on | Phase 3 of the roadmap, with access control in the design from day 1 |
| Custom prompts and taxonomy | Limited | Full control, with a prompt log and versions |
| Citation granularity | Document or page | Chunk and section, validated by the server |
| Audit log ownership | Held by the vendor | Held by the firm |
| Cost | Assumed $10,000 to $25,000 per seat per year (assumption A-12) | Compute plus maintenance, with no per-seat fee |
| Time to value | Weeks of setup | The demo now, production in about 3 months |
| Provider lock-in | High | Low, through the provider adapter |
| Security review | Vendor reports | The firm's own controls, listed in chapter 15 |

NOTE: Examples of the vendor category are financial research platforms with document search. This plan makes no claim about the current features or prices of any named vendor. Assumption A-12 is the price basis for the comparison.

Recommendation: buy data feeds, and build the thin answer layer where private data and custom workflows matter. Run Keel beside the current tools for 1 quarter. Measure adoption and hours saved with the audit log before the firm commits to phase 2.

### 2.6 What the demo proves and what the demo does not prove

The demo proves these points:

- A grounded, cited answer from 1 call works on real 10-K and 10-Q text with real parse problems.
- Deterministic question understanding resolves company names, groups, and time scopes without an LLM.
- The coverage statement and the gaps list make the limits of the corpus visible in every answer.
- The system degrades in a controlled way when the provider or the network fails.

The demo does not prove these points:

- Scale beyond 54 companies and 1 user at a time.
- Numeric precision across restated figures and across fiscal calendars at production volume.
- Security hardening for private data, which chapter 15 lists as post-timebox work.
- Adoption by the deal team, which only a pilot with the audit log can measure.
- Legal review of the data license for commercial use beyond public EDGAR data.
