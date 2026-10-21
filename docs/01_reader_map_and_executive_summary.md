## 1. Reader map and executive summary

Keel answers business questions about SEC filings with 1 call to a large language model (LLM). The text of 245 indexed filings from 54 companies grounds each answer, and each claim carries a citation. This chapter tells each reader where to start.

### 1.1 Reader map

| Reader | Goal | Read first | Read later |
| --- | --- | --- | --- |
| PE client (partner, deal team) | Value, risk, and the path to production | Chapters 1, 2, 3, 21, 22 | Chapters 5, 15, 16 |
| Technical reviewer | Depth, judgment, and edge cases | Chapters 4, 6, 7, 8, 9, 10, 11, 12, 19 | Chapters 13, 14, 17, 18, 20 |
| Security and operations reviewer | Threats, controls, and failure modes | Chapters 15, 16, 19 | Chapters 6, 14 |
| The consultant on demo day | The runbook and the build plan | Chapters 20, 21, 16 | Chapter 18 |
| Any reader who needs a definition | Terms and technical verbs | Chapter 24 |  |

NOTE: Chapters 25 to 28 extend the plan beyond the 4-hour timebox. Chapter 25 adds the demo items from the recruiter guidance. Chapter 26 adds any company on demand through the EDGAR APIs. Chapter 27 adds the features that make Keel a product a deal team can pilot. Chapter 28 gives the build sequence for all of it, without time estimates. Chapter 29 sets the engineering standards: the Google style guides, the CI and CD pipeline, the container and the infrastructure, and the Git workflow. The PE client reads chapters 26 and 27 first. The engineer reads chapters 28 and 29 first.

NOTE: This plan uses the word chapter for its own divisions. This plan uses the word section only for a division of a filing, such as the risk factors.

NOTE: This plan uses these ID prefixes. A is an assumption. D is a decision. P is a panel question. FR and NFR are requirements. AC is an acceptance criterion. G is a golden question. E is an edge case. V is a value assumption (chapter 2). CK is a parser check (chapter 7). T is a threat and S is a security control (chapter 15). W is a demo addition (chapter 25).

### 1.2 What Keel does

Keel takes a natural-language business question and returns a structured answer with citations. Three steps run before the call: question understanding, hybrid retrieval, and context assembly. These steps use code, dictionaries, a local embedding model, and a local reranker. No step before the call uses an LLM.

The call streams a JSON answer to the browser. The answer holds a direct answer, findings per company, a comparison table, and citations keyed to chunk IDs. The answer also holds a coverage statement, a list of gaps, a confidence level, and next questions. The browser shows the answer as it streams, the citations with their SEC links, and the retrieved chunks with their scores.

### 1.3 The single-call constraint

The brief requires that the final answer comes from 1 LLM API request. Keel obeys this rule in the strict sense. The service sends exactly 1 request to the model for each question, and the answer comes from that request. Keel does not use an LLM at index time. Keel does not use an LLM to rewrite the question, to rerank chunks, or to check the answer after the call. Chapter 4 records this interpretation as decision D-01, and chapter 5 lists the questions that confirm it with the panel.

### 1.4 The 3 headline design decisions

1. Deterministic question understanding and hybrid retrieval with quotas run before the call. Entity resolution, time scope, and question type come from code and dictionaries. The retriever fuses the lexical and dense results. Quotas per company and per period make sure that 1 company cannot fill the whole context.
2. The parser validates every filing against its own cover page. The fiscal period comes from the cover page text, not from the file name. A mislabeled file goes to a quarantine list and stays out of the index. The item schemes of the 10-K and the 10-Q map to 1 canonical section taxonomy.
3. The answer is a streamed JSON object with chunk-level citations that the server validates. Each citation must point to a chunk that was in the prompt. A coverage statement names the companies, forms, and periods that the answer used. A gaps list names what the corpus does not hold.

### 1.5 The value thesis

Keel cuts a primary-source research task from hours to minutes, and each claim links to the filing text that supports the claim. A deal team can compare risk factors, outlook, and regulatory exposure across companies in 1 question instead of 1 day of manual search. The base case in chapter 2 values this at about $194,000 of analyst time per year for a 10-person team. The run cost is about $28,000 per year. The cost of the model call is less than $0.10 per question, so maintenance, not usage, sets the run cost. The same pattern extends to private data rooms, live EDGAR feeds, and earnings call transcripts. That extension is the source of the durable value for a PE firm.

### 1.6 The real limits

- The corpus holds 54 companies. 12 companies have quarterly coverage, 5 companies have 2 to 8 filings, and 37 companies have exactly 1 10-K.
- The corpus holds public filings only. Keel has no private data, no market data, and no news.
- Keel has no live data. Coverage ends with filings dated February 2026, and the demo happens in late October 2026.
- Keel reads narrative text and flattened tables. Keel does not read structured XBRL financial data in this release. Numeric answers depend on the text of the filing.
- The demo build takes 4 hours. Chapter 20 marks the line between the demo build and the production hardening work.
- The 10-Q risk factor sections state only changes since the last 10-K. A quarterly risk comparison must read the 10-K and the 10-Q together. Keel does this through retrieval from both forms.
