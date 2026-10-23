## 14. API and front-end

The API has 1 answer endpoint that streams server-sent events, 7 read endpoints, and 1 feedback stub. The front-end is a React application in TypeScript, built by Vite into static files that the service serves at `/`. Every UI state in table 14.6 has a visible design, so the panel never sees a blank screen.

### 14.1 Endpoints

| Method and path | Purpose | Auth | Response |
| --- | --- | --- | --- |
| `POST /api/ask` | Answer a question. Streams SSE when the `Accept` header is `text/event-stream`, else returns JSON. | Bearer token | SSE events or the response object in 14.2 |
| `GET /api/health` | Liveness: the process runs | None | `{"status": "ok", "version": "0.3.1"}` |
| `GET /api/ready` | Readiness: index loaded and verified, models loaded, provider key present | None | `{"ready": true, "index_version": "1.0.0", "checks": {...}}` |
| `GET /api/coverage` | Filings per ticker with forms and fiscal periods, and the quarantine list | Bearer token | JSON |
| `GET /api/chunks/{chunk_id}` | The full text and metadata of 1 chunk for the citation panel | Bearer token | JSON |
| `GET /api/chunks/{chunk_id}/context` | The cited chunk with up to 20 neighbours before and after it in the same filing item (`before`, `after`, default 4), the overlap shown once, for the filing reader; no model call | Bearer token | JSON |
| `GET /api/examples` | The 3 example questions and the golden set questions | Bearer token | JSON |
| `GET /api/index/status` | The manifest, the corpus checksum match, and the build warnings | Bearer token | JSON |
| `POST /api/feedback` | Record a thumbs vote and a note (phase 1 of the roadmap) | Bearer token | HTTP 501 in this release |
| `GET /` | The front-end build: index.html and the hashed assets from web/dist | None | HTML |
| `GET /api/results/{request_id}` | The stored answer for a request ID from the idempotency store (10 minutes) or the answer cache. E-F-04 and a page refresh mid-stream use it | Bearer token | The answer JSON of 14.2, or 404 |

### 14.2 Request and response schemas

```json
{
  "question": "string, 3 to 1000 characters",
  "options": {
    "stream": true,
    "max_context_tokens": 32000,
    "max_chunks": 48,
    "use_cache": true,
    "model": null
  }
}
```

```json
{
  "request_id": "01J...",
  "analysis": { "tickers": ["AAPL", "TSLA", "JPM"], "primary_type": "comparison", "time_scope": {"kind": "none"} },
  "retrieval": {
    "chunks": [ {"chunk_id": "...", "ticker": "AAPL", "form": "10-K", "fiscal_label": "FY2025", "section": "risk_factors", "score": 0.91, "filing_name": "Apple Inc. 10-K FY2025", "sec_url": "https://www.sec.gov/..."} ],
    "collapsed_near_duplicates": 7,
    "dropped_candidates": 102,
    "token_estimate": 29800
  },
  "answer": { "direct_answer": "...", "company_findings": [], "comparison_table": null, "citations": [], "coverage": {}, "gaps": [], "confidence": "high", "confidence_reason": "...", "next_questions": [], "refusal": null },
  "citations_resolved": [ {"chunk_id": "...", "filing_name": "...", "section_title": "Risk Factors", "fiscal_label": "FY2025", "sec_url": "https://www.sec.gov/...", "valid": true, "location": {"section_label": "Part I, Item 1A. Risk Factors", "heading": "Risk Factors", "item_label": "Item 1A", "passage": 3, "passages": 36, "is_table": false, "anchor": null, "filing_date": "2025-10-31", "accession": "0000320193-25-000079"}} ],
  "meta": {
    "model": "claude-sonnet-5-5-<snapshot>",
    "prompt_version": "1.0.0",
    "index_version": "1.0.0",
    "prompt_hash": "sha256:...",
    "latency_ms": {"understanding": 4, "retrieval": 820, "rerank": 1900, "first_token": 3100, "total": 18400},
    "usage": {"input_tokens": 31200, "cached_input_tokens": 1800, "output_tokens": 1650},
    "cost_usd": 0.082,
    "degraded": false,
    "from_cache": false,
    "flags": {"citation_drift": 0, "injection_suspect": false}
  }
}
```

NOTE: The values above show the shape only. The real values come from the request.

### 14.3 Server-sent events

| Event | Payload | When |
| --- | --- | --- |
| `meta` | `request_id`, `index_version`, `prompt_version`, `model` | Immediately. The request\_id echoes the Idempotency-Key header of the request, or a server UUID when the header is absent |
| `analysis` | The `QuestionAnalysis` summary | After question understanding |
| `retrieval` | The chunk list with scores and the collapse counts | After the context budget |
| `answer_delta` | New characters of `direct_answer` | During the stream |
| `findings` | 1 company object | When the object closes |
| `final` | The validated answer, the resolved citations, and `meta` | After validation |
| `error` | `code`, `message`, `retry_after` when known | On any failure |
| `done` | Empty | Last event |

### 14.4 Example request

```bash
export KEEL_API_TOKEN=change-me
curl -N -X POST http://localhost:8000/api/ask \
  -H "Authorization: Bearer $KEEL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"question": "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"}'

# Non-streamed JSON
curl -s -X POST http://localhost:8000/api/ask \
  -H "Authorization: Bearer $KEEL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "How has NVIDIA'"'"'s revenue and growth outlook changed over the last two years?", "options": {"stream": false}}' | jq .answer.direct_answer
```

The same request through the front-end:

1. Open `http://localhost:8000` in the browser.
2. Paste the token into the token field once. The page keeps the token in session storage only.
3. Click the example chip Apple, Tesla, JPMorgan risk factors, or type a question.
4. Press Enter or click Ask.
5. Read the direct answer as it streams, then open the findings and the comparison table.
6. Click a citation chip to open the chunk in the right panel, with the SEC link.
7. Click Copy for the markdown or Export for the JSON.

### 14.5 UI layout

| Region | Content |
| --- | --- |
| Top bar | The name Keel, the index version badge, a health dot (green, amber, red), and the latency and cost badge of the last answer |
| Question area | A text input with a character counter, 3 example chips, the Ask button, and the resolved entities line (for example AAPL, TSLA, JPM, with a did-you-mean note after a fuzzy match) |
| Answer area | The streamed direct answer, the findings per company as expandable groups, the comparison table, and the gaps list. The coverage indicator (a row of company chips with the forms and periods used, gray for an absent company), the confidence chip, and the next questions as chips |
| Right panel | The citation list with filing name, section title, fiscal label, the SEC link, and the quote. Below the citations, the retrieved chunks with scores, the section, and the collapsed near-duplicate count |
| Footer | Copy as markdown, Export JSON, the request ID, and the prompt version |

On a phone the layout is 1 column, and the right panel becomes a drawer. Every link to the SEC opens in a new tab with `rel="noopener noreferrer"`, and only `https://www.sec.gov` URLs render as links.

### 14.6 UI states

| State | Trigger | What the user sees |
| --- | --- | --- |
| Empty | The page loads | The question area with the example chips, the coverage summary (54 companies, 245 filings, 1 quarantined), and the index version |
| Loading | The user sends the question | A progress line with 3 steps: understanding, retrieval, model. The resolved entities appear after step 1. |
| Streaming | The first `answer_delta` arrives | The direct answer grows in place, with a cursor, and the retrieved chunks appear in the right panel |
| Complete | The `final` event arrives | The full answer, the citation chips become clickable, and the latency and cost badge updates |
| Partial coverage | `companies_missing` is not empty, or a finding is `unverified` | A yellow banner that names the absent companies or the unverified findings, above the answer |
| Out of scope | HTTP 200 with `refusal`, or the no-call response | A gray card with the reason, the list of covered companies, and the example chips |
| Rate limited | HTTP 429 | A card with the wait time from `retry_after` and a countdown. The Ask button stays off until the countdown ends. |
| Provider down | The `error` event with code `provider_unavailable`, or `degraded: true` | A red banner that says the model is unavailable, the retrieved chunks with their SEC links, and a Retry button |
| Index not built | `GET /api/ready` returns `ready: false` with `index_loaded: false` | A full-page card with the command `keel index` and the expected build time |
| Stale index | `/api/index/status` reports a corpus checksum mismatch | An amber banner that says the corpus changed after the build and names the rebuild command |
| Network offline | The browser cannot reach the service | A red banner from the browser `offline` event, and the last answer stays on screen |

### 14.7 Tests

| Test | Expected result |
| --- | --- |
| `test_ask_stream_events` | The SSE stream holds `meta`, `analysis`, `retrieval`, at least 1 `answer_delta`, `final`, and `done`, in that order, with the mock provider |
| `test_ask_json` | The non-streamed response validates against the response schema |
| `test_auth_required` | A request without the token gets HTTP 401 |
| `test_rate_limit` | The 11th request in 1 minute from 1 client gets HTTP 429 with `Retry-After` |
| `test_question_limits` | An empty question gets 400 and a 1,001-character question gets 413 |
| `test_ready_without_index` | With no index directory, `/api/ready` returns `ready: false` |
| `test_chunk_lookup` | A known chunk ID returns the text and the metadata, and an unknown ID returns 404 |
| `test_sec_url_only` | A chunk with `url_trusted = 0` returns `sec_url: null` |
| `test_ui_escapes_model_text` | A direct answer with `<script>` renders as text in the page (a Playwright end-to-end test in web/e2e, chapter 14.9) |
| `test_ui_reduced_motion` | With prefers-reduced-motion set to reduce, the complete state appears with no transition, and the page content is identical to the animated path (a Playwright end-to-end test in web/e2e, chapter 14.9) |

### 14.8 Motion: the animated front-end

The front-end uses Motion for React (the `motion` package, MIT license) for every animation and Tailwind CSS for every style. Motion gives spring physics, stagger, layout animation, and exit animation through `motion.div`, `AnimatePresence`, variants, and the `layout` prop. The animations make the single-call flow visible to the client as it happens. The 3 pipeline steps light up in order. The retrieved chunks arrive. The answer streams. The trace drawer shows the 1 model request. The animations never delay data.

| Moment | Animation | Rule |
| --- | --- | --- |
| Page load | The top bar and the question area fade in, and the 3 example chips stagger in 60 ms apart (`staggerChildren` on the parent variant) | Once per load |
| Question sent | The 3 progress steps (understanding, retrieval, model) light up in sequence as the `meta`, `analysis`, and `retrieval` events arrive, and the active step pulses | The pulse stops on the first `answer_delta` |
| Entities resolved | The entity chips spring in from the left | A spring with stiffness 300 and damping 25 |
| Retrieval | The retrieved chunks in the right panel stagger in from the bottom, 30 ms apart, and the score bars grow to their width | 48 chunks at most, so the stagger ends in under 1.5 s |
| Stream | Each `answer_delta` appends its text with a 120 ms opacity fade, and the cursor blinks | The text is in the DOM before the fade starts |
| Complete | The findings groups expand with a height animation. The citation chips pop in with a stagger. The comparison table rows stagger in. The latency and cost badge counts up from 0 to its value over 600 ms (`animate` on a motion value) | The badge counts to the measured value, never to an estimate |
| Trace drawer (W-01) | The drawer slides up with a spring inside `AnimatePresence`, and the line `model requests: 1` draws attention with 1 scale pulse | The pulse runs once per answer |
| Partial coverage, provider down, stale index | The banner slides down from the top bar | A banner never leaves the screen on its own |
| Deliberate failure (W-04) | The gray out-of-scope card fades in with the example chips | The same durations as the normal path |
| Eval page (W-02) | The metric bars grow to their values on first view, and a value below its gate turns red at the end of the animation | The number is visible before the bar moves |
| State change | The `layout` prop keeps the question area in place when the answer area changes height | On the answer container only |

Rules:

- Every animation is 300 ms or less, except the count up (600 ms) and the chunk stagger.
- `useReducedMotion()` turns every animation off, and the page shows the final state at once. The e2e test `test_ui_reduced_motion` checks it with the `reducedMotion` option of Playwright.
- An animation never changes what the data says. A citation chip that failed validation renders `unverified` with no animation. A banner's text is in the DOM before the banner moves.
- Motion runs only on the client. No animation state reaches the API or the audit log.
- The variants and transitions live in 1 module, `web/src/motion/presets.ts`. The module has 1 named export per moment in the table. A reviewer can find and remove any of them. Components import the presets and never define inline transitions.
- Motion and Tailwind are npm dependencies with exact versions in `web/package-lock.json`. The build bundles them, so the page loads no CDN at the venue.

### 14.9 Front-end stack, standards, and tests

The stack: React 19 with TypeScript in strict mode, and Vite for the dev server and the build. Styles come from Tailwind CSS 4 through the Vite plugin. Animations come from Motion for React. The answer markdown goes through `marked` with `DOMPurify`. `npm run build --prefix web` writes `web/dist`. FastAPI serves it at `/` with a fallback to `index.html` for the client routes (`/a/{request_id}`, `/history`). The container image builds the front-end in a Node stage and copies `web/dist` into the Python stage. The image holds every asset, and the runtime needs no CDN. In development, `npm run dev --prefix web` proxies `/api` to the service on port 8000.

The layout is in chapter 17.6. The 11 UI states of table 14.6 are a union type in `web/src/state.ts`. One reducer moves between them on the SSE events and the HTTP results. A state that the table names cannot be absent from the code. `web/src/api/client.ts` reads the stream with `fetch` and a `ReadableStream` parser, because `EventSource` cannot send the bearer token header. `web/src/api/types.ts` mirrors the schemas of chapter 14.2, 1 interface per event and per response.

Standards: the Google TypeScript Style Guide, enforced by `gts` (the Google TypeScript Style package). The package provides the ESLint flat config and the Prettier settings. The React hooks and jsx-a11y plugins add their rules. The type check is `tsc --noEmit` in strict mode. A reviewer checks these rules by hand:

- Named exports only, and no default exports.
- No `any`: use `unknown` and narrow.
- Interfaces for object types.
- `import type` for types.
- `readonly` where a value does not change.
- `T[]` for arrays.
- camelCase for values, PascalCase for types and components.
- 1 component per file, named after the component.
- JSDoc on every exported symbol.
- No `namespace`, and no `enum` with computed values.

Tests, 2 layers:

| Layer | Tool | What it covers |
| --- | --- | --- |
| Component and state | Vitest with React Testing Library and jsdom | `state.test.ts` drives the reducer through all 11 states. 1 test per component checks its render for each state it shows. `markdown.test.ts` checks the DOMPurify allow list, and `client.test.ts` parses a recorded SSE stream |
| End to end | Playwright (Chromium, desktop and phone viewports) in `web/e2e/` | The specs in the next table, against `keel serve` with the mini index and the mock provider |

Playwright specs:

| Spec | What it checks |
| --- | --- |
| `smoke.spec.ts` | The page loads, the coverage summary shows 3 companies from the mini corpus, and the health dot is green |
| `ask.spec.ts` | Example question 1 streams. The 3 steps light up in order, and the answer grows. The citation chips open the right panel. The trace drawer shows `model requests: 1` |
| `states.spec.ts` | Each of the 11 states of table 14.6, driven by the mock provider's fault header: `partial_coverage`, `out_of_scope`, `rate_limited`, `provider_unavailable`, `index_not_built`, `stale_index`, `network_offline` (through the Playwright `offline` option) |
| `security.spec.ts` | `test_ui_escapes_model_text`: a direct answer with `<script>` renders as text, and a chunk URL outside `https://www.sec.gov` renders as text |
| `motion.spec.ts` | `test_ui_reduced_motion`: with `reducedMotion: 'reduce'` the complete state appears with no transition and the same content |
| `mobile.spec.ts` | The phone layout: 1 column, the right panel as a drawer, every control reachable |

The mock provider reads the header `X-Keel-Mock: <fault>` only when `llm.provider` is `mock`, and the service ignores the header with any other provider. The CI job `web e2e` builds the mini index, starts `keel serve` with the mock provider, and runs the specs. The job passes with no API key, so every PR runs it. The job `web lint, types, tests, build` runs `gts lint`, `tsc --noEmit`, Vitest, and the Vite build.
