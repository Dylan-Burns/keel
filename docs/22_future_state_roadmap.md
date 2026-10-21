## 22. Future state roadmap

The roadmap has 3 phases over about 18 months. Phase 1 makes Keel a daily tool on public data. Phase 2 adds numeric and event data, and phase 3 adds the firm's private data with access control. Each capability keeps the single-call pattern or moves to a multi-step agent, and the table says which.

### 22.1 Phases

| Phase | Months | Capability | What the capability unlocks for the firm | Pattern |
| --- | --- | --- | --- | --- |
| 1 | 0 to 3 | Live EDGAR ingestion with the incremental build, for every company the firm tracks | Coverage grows from 54 companies to the firm's full comparable set, with filings within 1 day of release | Index time, no model call |
| 1 | 0 to 3 | Feedback capture on every answer (thumbs, a note, a corrected citation) | The eval set grows from the firm's own questions, and the prompt log gets real evidence | Single call, plus a stored record |
| 1 | 0 to 3 | Evaluation in CI on the full index, nightly, with the gates | A model snapshot change or a parser change never reaches analysts without a measured check | Eval time only |
| 1 | 0 to 3 | Cost controls: a daily budget, per-user limits, and a cost page from the audit log | Finance sees the cost per team and per question | No model call |
| 1 | 0 to 3 | OpenID Connect and the Principal filters | Named users, so the audit log supports a review of who asked what | No model call |
| 1 | 0 to 3 | Index-time summaries per section, if the panel permits them (P-03) | Better recall on long MD&A sections | Index-time model call, still 1 answer call |
| 2 | 3 to 9 | Structured XBRL financials from the companyfacts data, joined to the chunks by filing ID | Numeric questions use the reported values with their units, and growth rates come from code, not from the model | Code before the call, 1 answer call |
| 2 | 3 to 9 | Earnings call transcripts and selected news, with speaker metadata | Outlook questions get management statements beside the filing text | 1 answer call per corpus set |
| 2 | 3 to 9 | Alerts on new filings for a watch list, with a diff of the risk factors against the previous filing | Portfolio and target reviews start from the change, not from the whole filing | A scheduled multi-step agent that runs the diff and 1 call per alert |
| 2 | 3 to 9 | Portfolio dashboards with saved questions that re-run on each new filing | A partner sees the same 10 questions answered for every portfolio company each quarter | 1 call per saved question, scheduled |
| 3 | 9 to 18 | Private data rooms: PDF ingestion, per-tenant indexes, and the isolation test | Due diligence on private targets with the same citation discipline, inside the firm's controls | 1 answer call, with the Principal filters |
| 3 | 9 to 18 | Multi-step research agents for long memos: plan, retrieve per section, draft, and check citations | A draft memo for the investment committee in 1 hour instead of 1 day, with every claim cited | Multi-step agent, several calls, with the single-call answer path as 1 tool |
| 3 | 9 to 18 | Cross-source reconciliation: filings against transcripts against data room documents | Contradictions between what a company filed and what management said surface automatically | Multi-step agent |

### 22.2 What stays in the single-call pattern

- Every question-and-answer use case: comparables, risk benchmark, regulatory scans, numeric lookups, and saved dashboard questions.
- Every index-time addition: live EDGAR, XBRL joins, transcripts, and data room documents.
- The reason: 1 call keeps the latency under 40 seconds, the cost under $0.25, and the audit record simple. Retrieval and code carry the complexity.

### 22.3 What moves to multi-step agents

- Long memo drafts that need a plan, several retrievals, and a citation check per section.
- Alerts that need a diff between 2 filings before the answer.
- Reconciliation across sources that needs a search per claim.
- The reason: these tasks need intermediate results that a human reviews. The extra calls produce a visible work product, not only a longer answer.

### 22.4 Gates between phases

| Gate | Measure |
| --- | --- |
| Phase 1 to phase 2 | 60% of the deal team uses Keel weekly for 1 quarter, and the measured hours saved reach the base case of table 2.4.1 |
| Phase 2 to phase 3 | Numeric accuracy of 0.95 or more on the XBRL-backed questions, and a security review of the production controls in chapter 15 |

NOTE: A CI-hosted build chain (the Claude Code GitHub Action, 1 stage per job, with a fresh context per stage) is a roadmap item for the case where a second engineer runs stages without a Claude subscription. The unattended build of chapter 29.11 runs in a cloud session and needs no such chain.
