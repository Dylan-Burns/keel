## 16. Reliability and operations

Keel keeps the demo alive through 3 layers. The first layer is a provider adapter with timeouts, retries, a circuit breaker, and a fallback model. The second layer is a degraded mode that still shows the retrieved chunks. The third layer is an offline fallback with cached answers for the example questions. The SLOs below are for the 30-minute demo, and every mechanism has a drill in chapter 21.

### 16.1 Timeouts, retries, and backoff

| Operation | Timeout | Retries | Backoff | Note |
| --- | --- | --- | --- | --- |
| Provider connect | 10 seconds | 2 | 1 second, then 3 seconds, with jitter | Retry on connect errors only |
| Provider stream, idle gap between events | 30 seconds | 0 after the first content event | None | D-04 forbids a retry after content |
| Provider request, total | 120 seconds | 0 | None | The stream ends with an `error` event |
| Provider HTTP 429 or 529 | Not applicable | 2 | The `Retry-After` header, else 2 seconds and 6 seconds | Before any content only |
| Provider HTTP 5xx | Not applicable | 2 | 2 seconds and 6 seconds | Before any content only |
| Reranker | 10 seconds | 0 | None | On timeout, skip the rerank and keep the fused order |
| Embedding of the query | 5 seconds | 0 | None | On failure, use lexical retrieval only and set `degraded_retrieval` |
| SQLite query | 5 seconds | 0 | None | Return HTTP 503 |

### 16.2 Idempotency

Each request carries a request ID. The browser sends an `Idempotency-Key` header equal to the request ID. A repeat of the same key within 10 minutes returns the stored result instead of a new model request. A question gets at most 3 requests before any content arrives. These are the first request and the 2 retries of D-04. They are byte-identical, so the provider cache hits. The halved-context retry of chapter 16.6 is the only retry with a different prompt, and it consumes 1 of the 2.

### 16.3 Circuit breaker

1. Count provider failures in a 60-second window.
2. After 3 consecutive failures, open the breaker for 30 seconds. While the breaker is open, every question goes to the fallback model. If the fallback fails, the question goes to the degraded mode.
3. After 30 seconds, let 1 probe request through. On success, close the breaker. On failure, open the breaker for another 30 seconds.
4. Show the breaker state in `/api/ready` and in the health dot of the front-end.

### 16.4 Fallback model

The fallback model is Claude Haiku 5.5 at a pinned snapshot (D-11). The adapter uses the fallback after the 3 requests of chapter 16.2 fail on the primary model (the first request and the 2 retries of D-04), or while the breaker is open. The fallback gets the same budget of 3. The answer `meta` names the model that produced the answer, and the front-end shows a note. The fallback uses the same prompt and the same schema, so the eval harness also runs the golden set against the fallback once.

### 16.5 Degraded mode

When the primary and the fallback models are both unavailable, the service returns the retrieval result with `degraded: true` and no answer. The front-end shows the red banner, the retrieved chunks with their SEC links, the collapse counts, and a Retry button. The audit record marks the request as degraded. The user still gets the sources, which is the part of the work that a human can finish by hand.

### 16.6 Context overflow

1. Estimate the prompt tokens before the request with the calibrated factor (chapter 11).
2. If the estimate exceeds the model limit minus the output limit, drop chunks from the lowest rank. Stop when the estimate fits.
3. If the provider still returns a context error before any content, halve the context budget. Rebuild the prompt and retry once. This is the only retry with a different prompt, and it consumes 1 of the 2 retries of D-04. The failed request returned no answer.
4. Log `context_overflow` with the estimate and the real count, and raise the calibration factor by 5% for the session.

### 16.7 Index integrity checks

1. At start, check the sha256 of `chunks.sqlite` and `vectors.npy` against the manifest. On mismatch, refuse to serve and report `index_corrupt` in `/api/ready`.
2. At start, make sure that the row count of `chunks` equals the row count of `vectors.npy`.
3. At start, compare the manifest `corpus_sha256` with the hash of the corpus directory when the directory exists. On mismatch, serve the index and report `index_stale` in `/api/index/status` and in the front-end banner.
4. Every 60 seconds, re-check the modification time of the manifest file. Reload the index when a new build is present.

### 16.8 Health endpoints

| Endpoint | Checks | Response |
| --- | --- | --- |
| `GET /api/health` | The process answers | `200 {"status": "ok", "version": "0.3.1"}` |
| `GET /api/ready` | Index loaded and verified, embedding model loaded, reranker loaded or disabled, provider key present, breaker state, answer cache present | `200` with `ready: true`, or `503` with the failed checks |

### 16.9 Structured logs and traces

The service writes JSON lines to standard output with `request_id`, `level`, `event`, and the fields of the event. Every stage of the question pipeline logs 1 `stage_done` event with its duration. The audit log is a separate file (S-07). OpenTelemetry traces with 1 span per stage are production work. The `request_id` appears in the front-end footer, so a reviewer can find the log lines of any answer.

### 16.10 Cost tracking

1. Read the input, cached input, and output token counts from the provider response.
2. Multiply by the price table in `config/prices.yaml`, which holds the prices and their check date (A-10).
3. Write the cost into the audit record and the `meta` object.
4. Keep a session total in memory and show the total in the front-end top bar.
5. Stop model requests when the spend reaches the daily budget in config. Serve cached answers and the degraded mode.

### 16.11 SLOs for the demo

| SLO | Target | Measurement |
| --- | --- | --- |
| First streamed token | p50 of 6 seconds or less | `latency_ms.first_token` |
| Complete answer | p95 of 40 seconds or less | `latency_ms.total` |
| Availability during the 30-minute demo | 100%, with the offline fallback counted as available | The failure drills and the audit log |
| Cost per question | $0.25 or less | `cost_usd` |
| Citation validity | 95% or more of citations valid | `citation_drift` |

### 16.12 Offline fallback for the live demo

1. Before the demo, run `keel warm-cache` with the 3 example questions and the golden set. The command stores each answer, the retrieval result, and the stream events in `demo/answer_cache/`.
2. Set `KEEL_OFFLINE=1` to serve every question from the cache. A question that is not in the cache gets the retrieval result in the degraded mode.
3. With `KEEL_OFFLINE` unset, the service uses the cache only after the provider fails, so the live path stays the default.
4. Record a full run of the 3 example questions as a video in `demo/recording.mp4`. Export the 3 answers as static HTML in `demo/static/`.
5. Keep a printed copy of the 3 answers for a total failure of the laptop.

CAUTION: If the index version, the prompt version, or the model snapshot changes after `keel warm-cache`, run the command again. The cache key includes all 3 values, so a stale cache gives no hits.

### 16.13 Tests and drills

| Test | Expected result |
| --- | --- |
| `test_retry_before_content` | A 529 before content triggers a retry, and a second request appears on the mock provider |
| `test_no_retry_after_content` | A disconnect after the first content event ends with an `error` event and no second request |
| `test_breaker_opens` | 3 failures open the breaker and the 4th question uses the fallback model |
| `test_fallback_model_named` | The `meta.model` value names the fallback snapshot |
| `test_degraded_mode` | With both models down, the response has `degraded: true` and the chunks |
| `test_context_overflow_halves` | A context error before content halves the budget and retries once |
| `test_index_checksum_mismatch` | A changed byte in `vectors.npy` makes `/api/ready` return 503 |
| `test_stale_index_flag` | A new file in the corpus directory sets `index_stale` |
| `test_budget_stop` | A daily budget of $0 serves only cached answers |
| `test_offline_cache_hit` | With `KEEL_OFFLINE=1`, example question 1 returns the cached answer with `from_cache: true` |
