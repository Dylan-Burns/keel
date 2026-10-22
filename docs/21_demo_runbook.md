## 21. Demo runbook

The demo runs example question 1 first, because the comparison shows every part of the design in 1 answer. The corpus has full coverage for 2 of the 3 companies and a real gap for the third. The pre-flight checklist runs the night before and again 30 minutes before the session. Every failure has a drill with a script.

### 21.1 Pre-flight checklist

- [ ] Run `make test` and confirm that `pytest`, `ruff`, and `mypy` pass.
- [ ] Run `keel doctor`: Python version, model files present, index checksums valid, provider key present, clock sane, free disk above 2 GB.
- [ ] Run `curl /api/ready` and confirm `ready: true` with the expected index version.
- [ ] Run `keel warm-cache` and confirm 28 cache entries (the 28 golden questions, which include the 3 example questions G-06, G-11, and G-19, and the 4 no-call questions store their no-call response).
- [ ] Run the 3 example questions live and read every citation once.
- [ ] Leave `KEEL_OFFLINE` unset, block the provider host for 1 question, and confirm that the offline drill works.
- [ ] Open `demo/recording.mp4` and `demo/static/` and confirm that both play.
- [ ] Print the 3 answers.
- [ ] Run `caffeinate -dims` (macOS) or disable sleep, and connect the laptop to power.
- [ ] Close every other application, mute notifications, and set the browser zoom to 125%.
- [ ] Put the personal hotspot on standby and test it once.
- [ ] Write the request ID of the last live answer on a sticky note for the audit log demo.

### 21.2 The 30-minute narrative

| Minute | Segment | What to say and show |
| --- | --- | --- |
| 0 to 3 | The problem | An analyst spends 4 hours on a 3-company risk comparison from primary sources, with manual citations. The firm wants minutes, with evidence a partner can check. |
| 3 to 7 | The architecture | Show the component diagram. Name every step before the call: parse, sections, chunks, hybrid retrieval, rerank, budget. Say that none of them is an LLM call, and that the answer comes from 1 streamed request (D-01, D-03). |
| 7 to 13 | The live question | Type example question 1. Point at the resolved entities line and the retrieval panel with the 3 companies and the collapse count. Point at the direct answer as it streams. Open 2 citations and the SEC link. |
| 13 to 17 | How the context grounds the answer | Show the coverage statement with the filings used for AAPL, TSLA, and JPM. Show the gaps list with the JPM limit. Click a chunk and show the fiscal label and the period end date. Show the audit record for the request ID. |
| 17 to 20 | The second question | Type example question 2. Explain the NVIDIA fiscal year that ends in January, and show the fiscal labels in the answer. If a panel member wants a live question, take it here. |
| 20 to 24 | Value | Show table 2.4.2: the base case of $194,400 in analyst time against $27,912 in run cost. Show the cost per question under $0.10, and the low case that does not pay back on hours alone. Say what the demo proves and does not prove. |
| 24 to 27 | Future state | Show the roadmap in chapter 22: live EDGAR, XBRL financials, transcripts, private data rooms, alerts, and dashboards. Say which phases keep the single call. |
| 27 to 30 | Questions | Invite questions. Use the answers in 21.5. |

### 21.3 The first question and why

Run example question 1 (Apple, Tesla, JPMorgan risk factors) first. The question shows alias resolution (JPMorgan to JPM), per-company quotas, the boilerplate collapse, and the comparison table. The coverage statement shows a real gap, because JPM has 4 filings. The question has no fiscal trap, so the first answer is simple to read. Example question 2 comes second to show the fiscal math. Example question 3 comes third, or stays in reserve, because the single-10-K limit for 3 companies makes the gaps list long.

### 21.4 Failure drills

| Failure | Detection on stage | Script |
| --- | --- | --- |
| The provider returns an error or times out | The red banner and the degraded mode with chunks | Say: the model is unavailable, so Keel shows the sources it retrieved. This is the degraded mode from chapter 16. Click Retry once. If the retry fails, run the same question with `KEEL_OFFLINE=1`. Say that the cached answer came from the same pipeline on the same index. |
| The venue network has no internet | The browser offline banner, or the connect error | Switch to the hotspot. If the hotspot fails, set `KEEL_OFFLINE=1`, restart with `make demo`, and run the example questions from the cache. Say that the cache key holds the index, the prompt, and the model versions. |
| The service does not start | The terminal error | Check the port message. Run `make demo` again, which picks the next free port. If the index check fails, show the printed answers and open `demo/static/`. |
| The index is absent or corrupt | The full-page card | Say that the build takes 27 minutes, so the demo continues with the static export and the recording. Start `keel index` in the background anyway. |
| The laptop sleeps or restarts | A black screen | Wake the laptop, run `make demo`, and continue from the request ID on the sticky note with the stored result. |
| A live panel question is out of scope | The gray out-of-scope card | Say: this is the design, not a failure. The system refuses without a model call and shows the covered companies. Then ask for a question about a covered company. |
| A live panel question hits a thin company | The yellow partial-coverage banner | Point at the gaps list and the coverage statement. Say that the limit is in the corpus, and that the roadmap adds live EDGAR. |
| The model gives a weak answer | A finding marked unverified | Say that the server removed a citation that did not match the context. Show the drift count in the audit record. Explain that the eval gate measures this rate. |

### 21.5 Answers to the hard questions

| Question from the panel | Answer |
| --- | --- |
| How do you stop hallucination? | Keel does not stop it. Keel makes it visible and rare. The prompt permits claims only from the context, and every claim cites a chunk ID. The server removes citations that do not match the context, and the eval gates require faithfulness of 0.90 or more. A finding with no valid citation shows as unverified. |
| What does this cost at scale? | About $0.09 per question with Sonnet 5.5 at today's prices, and about $0.005 with the fallback model. At 288 questions per month, the model cost is $26. Maintenance, not usage, sets the run cost (table 2.4.2). |
| How is this secure? | The demo uses a bearer token, input limits, rate limits, sanitized output, pinned models, and an audit log. The system block declares the context as untrusted data, and the validator checks the citations. Private data needs the production controls in chapter 15. The chapter lists them, and the code does not hold them yet. |
| Why a single call? | The brief requires it, and the constraint forces discipline. The retrieval and the prompt must carry the answer, so every part before the call is testable code. The roadmap names the use cases that need multi-step agents and keeps them separate. |
| Why not fine-tune a model? | Fine-tuning does not add the filing text to the model, so citations still need retrieval. The filings change every quarter. A tuned model is a maintenance cost with no gain for grounded answers. Fine-tuning can help later for the output style, not for the facts. |
| Why not buy a vendor tool? | Buy data feeds, and build the thin answer layer where private data and custom workflows matter. The vendor holds the audit log and the prompts. Keel gives the firm both, with chunk-level citations and a provider adapter (table 2.5). |
| Why these numbers in the value model? | Every number is an assumption with an ID in table 2.4.1. The low case is negative on hours alone, and the pilot measures the real values with the audit log. |
| What breaks first in production? | Coverage. 54 companies is a demo corpus. Live EDGAR ingestion is phase 1 for that reason. The parser rules are the second risk, and the parser tests from real snippets are the control. |
| How do you know the retrieval is good? | Recall at 25 on labeled chunks, with a gate of 0.85, and the ablations in chapter 18 that compare lexical, dense, and hybrid retrieval. |
| What if the panel counts the embedding model as an LLM call? | The reranker flag and the dense index flag turn off in config, and Keel runs with lexical retrieval, section weights, and quotas. The eval report shows the cost in recall. |
