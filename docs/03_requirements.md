## 3. Requirements

Keel must answer a business question about the corpus in 1 LLM request with validated citations. The answer must arrive in 40 seconds or less at the 95th percentile. The demo must pass the 11 acceptance criteria in table 3.4.

### 3.1 Functional requirements

| ID | Requirement | Verified by |
| --- | --- | --- |
| FR-01 | The system must accept a natural-language question of 3 to 1,000 characters through the API and through the front-end. | API tests |
| FR-02 | The system must resolve company names, tickers, aliases, and sector groups to tickers in the corpus without an LLM call. | Unit tests |
| FR-03 | The system must parse the time scope of a question with fiscal awareness and must apply the scope as a metadata filter. | Unit tests |
| FR-04 | The system must retrieve chunks with hybrid lexical and dense retrieval, with metadata filters, and with quotas per company and per period. | Integration tests |
| FR-05 | The system must send exactly 1 request to the model per question and must produce the answer from that request. | Provider adapter test with a call counter |
| FR-06 | The answer must be a JSON object with a direct answer, findings per company, and citations keyed to chunk IDs. The answer must also hold a coverage statement, gaps, a confidence level, and next questions. When more than 1 company is in scope, the answer must hold a comparison table. | Schema validation |
| FR-07 | Each citation must reference a chunk that was in the prompt. The server must remove invalid citations and must flag claims without a valid citation. | Unit tests |
| FR-08 | The system must stream the answer to the front-end as the model produces the answer. | Manual check and API tests |
| FR-09 | The answer must state which companies, forms, and periods the model used, and which requested companies are not in the corpus. | Eval run |
| FR-10 | The system must refuse or must give a partial answer when the context does not support the question, and must say why. | Eval run |
| FR-11 | The front-end must show the answer, the citations with filing name, section, and SEC URL, and the retrieved chunks with scores. The front-end must also show the coverage indicator and the latency and cost badge. | Manual check |
| FR-12 | The system must write 1 audit record per question. The record must hold the question, the chunk IDs, the prompt hash, the model version, the latency, and the cost. | API tests |
| FR-13 | The index build must be idempotent and incremental, and must write a manifest with checksums and versions. | Build tests |
| FR-14 | The parser must validate the metadata of each filing against the cover page and must quarantine conflicts. | Parser tests |
| FR-15 | The system must serve cached answers for the 3 example questions when the provider is unreachable. | Failure drill |
| FR-16 | The system must expose health and readiness endpoints. | API tests |

### 3.2 Non-functional requirements

| ID | Requirement | Target for the demo | Target for production |
| --- | --- | --- | --- |
| NFR-01 | Latency to the first streamed token | p50 of 6 seconds or less | p50 of 4 seconds or less |
| NFR-02 | Latency to the complete answer | p95 of 40 seconds or less | p95 of 30 seconds or less |
| NFR-03 | Cost per question | $0.25 or less | $0.15 or less on average |
| NFR-04 | Availability | 100% over the 30-minute demo, with the offline fallback | 99.5% per month |
| NFR-05 | Auditability | 1 audit record per answer with a reproducible prompt hash | The same, with 1 year of retention |
| NFR-06 | Reproducibility | The same question, index version, prompt version, and model version give the same chunk IDs. The answer text can differ at the token level, even at temperature 0. | The same |
| NFR-07 | Index build time | 30 minutes or less on an 8-core laptop | 10 minutes or less for an incremental build |
| NFR-08 | Concurrency | 2 simultaneous questions without an error | 20 simultaneous questions |
| NFR-09 | Security | Secrets in environment variables, a bearer token, and no model text rendered as HTML without sanitization | All controls in chapter 15 |
| NFR-10 | Portability | One-command setup with Docker Compose on macOS and Linux | The same, plus Kubernetes manifests |

### 3.3 Non-goals

- Keel does not keep multi-turn chat memory in this release.
- Keel does not fetch filings from EDGAR during the demo.
- Keel does not read structured XBRL financial data in this release.
- Keel does not give investment advice or recommendations.
- Keel does not use multi-step agents, an LLM-based question rewrite, or an LLM reranker.
- Keel does not fine-tune the model.
- Keel does not have user accounts or roles beyond 1 bearer token.
- Keel does not accept questions in languages other than English.
- Keel does not ingest PDF or HTML files. The corpus holds plain text files only.

### 3.4 Acceptance criteria for the demo

| ID | Criterion | Check |
| --- | --- | --- |
| AC-01 | `docker compose up` starts the service and the front-end on port 8000 within 2 minutes when the index exists. | Timed start |
| AC-02 | `keel index` builds the index from the extracted corpus with 245 indexed filings and 1 quarantined file, and writes the manifest. | Build report |
| AC-03 | Each of the 3 example questions returns a complete JSON answer with at least 1 valid citation per company in scope. | Eval run |
| AC-04 | The comparison question returns findings for AAPL, TSLA, and JPM, and the coverage statement names the forms and periods used for each company. | Eval run |
| AC-05 | The NVIDIA trend question labels each period as a fiscal year with the period end date. | Eval run |
| AC-06 | The pharmaceutical question lists PFE, JNJ, MRK, LLY, and ABBV in the coverage statement. It names the single-10-K limit for MRK, LLY, and ABBV in the gaps. | Eval run |
| AC-07 | A question about a company that is not in the corpus returns an out-of-scope answer with the list of covered companies, without a model call. | API test |
| AC-08 | With the provider blocked, the front-end shows the degraded mode with retrieved chunks, and the 3 example questions return cached answers. | Failure drill |
| AC-09 | `pytest` passes with at least 40 tests, and `ruff` and `mypy` pass. | CI run |
| AC-10 | The eval run on the golden set reports retrieval recall at 25 of at least 0.85 and citation precision of at least 0.90. | Eval report |
| AC-11 | The audit log holds 1 record per question with all fields in FR-12. | API test |
