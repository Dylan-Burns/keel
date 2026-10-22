## 25. Demo additions from the recruiter guidance

The recruiter named 3 things that the panel grades beyond a system that works. First, the candidate knows the code cold. Second, the system has an evaluation, and the candidate can explain an underperformance to a client. Third, the candidate stays calm under pushback. This chapter adds 6 items that make each point visible in the room. Each item is small, because the data that the item needs already exists.

| ID | Item | Where it lands | Recruiter point |
| --- | --- | --- | --- |
| W-01 | Answer-trace drawer | `web/src/components/TraceDrawer.tsx`, and `api/sse.py` adds the audit record to the `final` event | Workflow logic and the single-call rule |
| W-02 | The `/api/eval` page | `api/routes.py` renders `eval/report.md` and `docs/PROMPT_LOG.md` | Evaluation |
| W-03 | Performance memo for the client | `docs/PERFORMANCE_MEMO.md` | Explanation of an underperformance |
| W-04 | A deliberate failure on stage | A preset button for golden question G-27 | Guardrails and composure |
| W-05 | Pushback drills and a cold-read rehearsal | `docs/PUSHBACK.md`, `docs/CODE_WALK.md` | Code knowledge and composure |
| W-06 | Motion animations in the front-end | `web/src/motion/presets.ts` and `web/src/components`, per chapter 14.8 | The workflow is visible as it runs, and the product looks finished to a client |

### 25.1 Answer-trace drawer

The drawer sits under the answer and renders the audit record of the current answer in pipeline order. The drawer shows the resolved entities and the question type, the filters, and the candidates per company before and after the near-duplicate collapse. It shows the quota fills (for example 16 of 16, 16 of 16, and 11 of 16 for JPM), the chunk count, and the token estimate. It shows the prompt hash, the prompt version, and the model snapshot. It shows the token counts, the cost, and the latency to the first token and in total. It shows the citation drift count and a literal line `model requests: 1`. When a retry happened before any content, the line reads model requests: 2 (1 failed before content), so the single-call claim stays measurable instead of asserted. The request count comes from the provider adapter counter that the test for FR-05 already uses. The drawer also shows `from_cache` and `degraded` when they apply, so the offline fallback is visible. The line to say: every step above the model request is code that the panel can open.

### 25.2 The `/api/eval` page

The page renders `eval/report.md` and `docs/PROMPT_LOG.md` as read-only HTML through the same markdown renderer and sanitizer as the answers. The page shows recall at 25 per golden question with the expected sources, and the overall metrics. It also shows the ablation table, the latency and cost figures, and the prompt log versions with their rubric scores. The page has no logic beyond the render, because `keel eval` writes the report. In the demo, open the page in the tests segment instead of a description of numbers from memory.

### 25.3 Performance memo for the client

Write 1 page in `docs/PERFORMANCE_MEMO.md`, addressed to the client, with the date, the index version, and the model snapshot. Use these 5 headings.

1. What we measured: recall at 25 overall and per question type, faithfulness, citation precision, and schema validity. Also refusal correctness, latency, and cost per question, with the golden set size.
2. What works today: narrative questions. These are risk comparisons, regulatory scans, and outlook over time. The citations open for a partner.
3. What is weak, with evidence: the 37 companies with 1 10-K cannot support trend questions, and the answer says so. Numeric questions depend on units from the table caption. The memo names the 1 miss found in the eval, if any. It gives the chunk, the expected value, and the answer given.
4. Decision rule: ship narrative questions now. Hold numeric questions behind a warning until the XBRL facts in chapter 26 land. The gate is a numeric accuracy of 0.95 on the golden set.
5. What changes next and when: the reranker threshold, the judge thresholds, and live EDGAR for coverage, each with a date.

Lead with the decision, write in the client's language, and keep the numbers as measured. The memo is the written answer to the question about a model that underperforms, before the panel asks it.

### 25.4 A deliberate failure on stage

1. At about minute 44, press the preset for golden question G-27 (an instruction to ignore the rules and print the system prompt, then a real question about Tesla risks).
2. Before the answer streams, say what must happen. The question still gets an answer. The model ignores the planted instruction. The validator drops and counts a citation to an ID outside the context. The gaps list names what the filings cannot answer.
3. Open the trace drawer and point at the drift count.
4. If the model does something unexpected, show the validator output and the audit record. Say what the next prompt version changes. A guardrail that catches a failure in the room is stronger proof than a guardrail in a slide.

### 25.5 Pushback drills

The rule for every challenge: agree with what is true. Ask which standard the panel has in mind. Then show the config flag, the number, or the roadmap line. Never defend a choice that the code does not defend.

| Challenge | Response |
| --- | --- |
| Recall of 0.85 sounds low. | Ask for their threshold. Show recall per question type: comparisons score high, and long-section trend questions pull the average down. Show the ablation and name the reranker threshold as the next step. |
| SQLite does not scale. | Correct. SQLite holds 40,000 chunks with no service at a venue. The store interface is 1 file, and chapter 17 gives the pgvector migration with a script. |
| A character count divided by 4 is sloppy. | Agree. Show the measured error against the provider token count on 200 chunks and the calibration factor from chapter 11. |
| The value numbers are estimates, not measurements. | Yes. Every number carries an assumption ID with a low, base, and high case. The low case does not pay back on hours alone, and the pilot measures the real numbers from the audit log. |
| Why is this better than a filing pasted into a chat window? | Coverage, citations that the server validates, a coverage statement that names what is absent, a cost of $0.09 per question, and an audit log. A paste gives none of these. |
| Is 1 call a toy constraint? | The brief requires it, and the constraint forced the retrieval and the prompt to carry the answer, so every step before the call is testable. Chapter 22 names the tasks that need agents and why. |
| What happens when the model is wrong? | Show a claim with no valid citation marked `unverified`, the drift count, and the memo decision rule for numeric questions. |
| Can we use this tomorrow? | For narrative questions on public filings, yes, as a pilot beside the current tools (chapter 27). Not for private data: chapter 15 lists the production controls, and the code does not hold them. |

### 25.6 Cold-read rehearsal

1. Clone the repo into a new directory and open nothing in advance.
2. Walk the modules in pipeline order against a 20-minute timer, and explain each module aloud.
3. Use `docs/CODE_WALK.md`. For each module, the file lists the corpus fact that the module answers. It also lists the 2 questions that the panel is most likely to ask. For `sections.py`: why an order constraint instead of a heading regex. And what happens when a 10-Q has no `PART II` match.
4. Do the walk once the day before and once on the day of the demo, before it starts.
5. If a module takes more than 3 minutes to explain, split the module before the demo.

### 25.7 Changes to the demo narrative in chapter 21

The hour has 2 halves. Minutes 0 to 30 are the demo of chapter 21, which the rehearsal of chapter 25.6 keeps at 25 minutes with 5 minutes to spare. Minutes 30 to 60 are the discussion. The items below at minute 32 and later sit in the discussion half on purpose, as the material the panel asks for.

- Minute 10 to 12: open the trace drawer on the answer to example question 1 before example question 2. The code walk shrinks by 2 minutes.
- Minute 32 to 38: open the `/api/eval` page instead of the markdown file, and end on the prompt log versions.
- Minute 44 to 46: run the deliberate failure, then open the discussion.
- Put the memo in the repo and in the printed packet. Mention it when the panel asks about underperformance.

### 25.8 Motion animations (W-06)

The client wants to see a product, not a script. Chapter 14.8 specifies the animations. The pipeline steps light up as the events arrive. The chunks and the citations stagger in. The answer streams with a fade. The trace drawer springs up to the line `model requests: 1`. Each animation shows a real event from the stream, so the panel watches the single call happen. The rules in 14.8 keep the animations honest. No animation delays data. Reduced motion turns them off. A reviewer can remove any of them in 1 function. In the demo, say 1 sentence about it when the first answer streams. The steps that light up are the 3 stages of the pipeline. The drawer shows that the model ran once.
