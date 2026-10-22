## 5. Questions for the panel

Ask the first 5 questions before the session, and ask the other questions during the session when the related chapter comes up. Each question names the assumption that Keel uses until the panel answers.

| ID | Question | Why the answer matters | Assumption until answered |
| --- | --- | --- | --- |
| P-01 | Does a call to a local embedding model count as an LLM call under the single-call rule? | If yes, dense retrieval must go, and Keel runs with lexical retrieval only. | No (D-01). |
| P-02 | Does a local cross-encoder reranker count as an LLM call? | If yes, the reranker flag goes off, and precision drops on boilerplate sections. | No (A-13). |
| P-03 | Is index-time LLM summarization acceptable under the rule? | Keel does not use it now. A yes opens a phase 1 option for contextual chunk summaries. | Not used (D-02). |
| P-04 | Does a retry of a request that failed with no output count as a second call? | If yes, `max_retries` goes to 0, and a transient provider error shows as an error. | No (D-04). |
| P-05 | Is the scope strictly calendar 2023 to 2025, or is the full range of file dates (February 2022 to February 2026) in scope? | A strict scope removes 64 files and changes the fiscal coverage of several companies. | The full range (D-19). |
| P-06 | Will the panel type live questions, and in which style: single company, comparison, or numeric? | The question types drive the retrieval plans and the golden set weights. | All types, in English (A-01). |
| P-07 | Does the demo venue have internet access, and is a personal hotspot acceptable? | The provider call needs the network. The offline fallback covers a loss. | Yes (A-02). |
| P-08 | Is there a preferred model provider or a budget limit per question? | The adapter supports a second provider, and the budget sets the context size. | Anthropic, with a limit of $0.25 per question (NFR-03). |
| P-09 | Which companies and sectors matter most to the firm, and which tickers belong to the groups major pharmaceutical companies and major banks? | The group dictionary and the golden set match the firm's portfolio. | A-06 and A-07. |
| P-10 | How large is the deal team, and what does the firm pay today for terminal and research seats? | The value model uses these numbers directly. | A-11 and A-12. |
| P-11 | Are numeric answers from financial statements more important than narrative answers? | A yes moves structured XBRL data from phase 2 to phase 1 of the roadmap. | Narrative first, numeric second. |
| P-12 | Does the firm have private data rooms or portfolio documents that Keel must read later? | Access control moves earlier in the roadmap, and multi-tenant design gets tested sooner. | Phase 3 (chapter 22). |
| P-13 | Does the firm have gold answers or past memos that can seed the evaluation set? | Gold answers improve the faithfulness and numeric accuracy measures. | No. The consultant writes the golden set. |
| P-14 | Does the demo run on the consultant's laptop or on a cloud host that the firm controls? | A cloud host changes the secret controls and the network controls in chapter 15. | The consultant's laptop. |
| P-15 | Does the firm want prose, JSON, or both from the API? | Both exist in 1 call. The front-end renders prose from the JSON. | Both (D-13). |
