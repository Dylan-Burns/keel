## 15. Security

The demo runs on 1 laptop with public data. The main risks are a leaked API key, injected instructions inside filing text, and script injection through rendered text. The threat model below uses STRIDE. Each control is a CAUTION with a procedure, and the demo build applies the controls marked Timebox. The other controls are production hardening.

### 15.1 Threat model

| ID | Threat | STRIDE | Asset | Likelihood | Impact | Control |
| --- | --- | --- | --- | --- | --- | --- |
| T-01 | The provider API key leaks through a log, a commit, or a screen share | Information disclosure | Provider account and budget | Medium | High | S-01 |
| T-02 | Filing text or a planted chunk carries instructions that change the answer | Tampering | Answer integrity | Medium | Medium | S-02 |
| T-03 | Model text or filing text holds HTML or script that runs in the browser | Tampering, elevation of privilege | User session | Medium | High | S-03 |
| T-04 | A very long question or a flood of questions exhausts the context budget or the provider budget | Denial of service | Availability, cost | Medium | Medium | S-04, S-05 |
| T-05 | A person on the venue network uses the API without permission | Spoofing | Provider budget, audit trail | Medium | Medium | S-06 |
| T-06 | A user disputes an answer and no record exists | Repudiation | Trust | Low | Medium | S-07 |
| T-07 | A dependency with a known vulnerability ships in the image | Elevation of privilege | Host | Medium | High | S-08 |
| T-08 | The container runs as root with a writable file system | Elevation of privilege | Host | Low | High | S-09 |
| T-09 | A crafted zip writes a file outside the corpus directory | Tampering | Host file system | Low | High | S-10 |
| T-10 | An attacker redirects a future fetch of SEC URLs to an internal address | Spoofing, information disclosure | Internal network | Low | High | S-11 |
| T-11 | The corpus license does not permit commercial use | Repudiation | Legal position | Low | Medium | S-12 |
| T-12 | The provider changes the model under an alias and the answers change | Tampering | Reproducibility | Medium | Medium | S-13 |
| T-13 | The audit log or the answer cache holds secrets or personal data | Information disclosure | Users | Low | Medium | S-14 |
| T-14 | A second origin reads the API from a browser | Spoofing | API | Low | Medium | S-15 |
| T-15 | A tampered answer cache file serves a wrong answer | Tampering | Answer integrity | Low | Medium | S-16 |
| T-16 | A private data room in phase 3 leaks across tenants | Information disclosure | Client data | Medium | High | S-06, S-17 |

### 15.2 Controls

**S-01 Secret controls (Timebox)**

CAUTION: If the API key appears in a log line, a commit, a screenshot, or a URL, rotate the key at once.

1. Read `ANTHROPIC_API_KEY` and `KEEL_API_TOKEN` from environment variables only. Never read them from config files in the repo.
2. Keep `.env` in `.gitignore`, and commit `.env.example` with empty values.
3. Redact every value of a key that ends in `KEY` or `TOKEN` in the log formatter.
4. Never return a secret in an API response or in an error message.
5. Add a pre-commit hook with `gitleaks` to block a commit that holds a key pattern.

**S-02 Prompt injection through retrieved filing text (Timebox)**

CAUTION: If an answer obeys an instruction that is not in the question, treat the context as compromised. Inspect the cited chunks.

1. Wrap every chunk in a `<chunk>` element. Declare the context as untrusted data in the system block and in the last line of the user block.
2. Keep the question in a separate `<question>` element.
3. Validate every citation against the context, so a planted instruction cannot cite itself as evidence from another filing.
4. Flag a question that matches an injection pattern and log the flag.
5. Add 3 adversarial cases to the golden set. Case 1 is a chunk with an injected instruction. Case 2 is a question that asks for the system prompt. Case 3 is a question that tells the model to ignore its rules.
6. Never let the model write a URL. The server attaches the SEC URL from the chunk table.

**S-03 Rendered output (Timebox)**

CAUTION: If any model text or filing text reaches `innerHTML` without sanitization, the page is open to script injection.

1. Render model text through a markdown renderer and then through DOMPurify with a strict allow list. The allow list holds p, strong, em, ul, ol, li, table, thead, tbody, tr, th, td, code, and a.
2. Permit `href` only for `https://www.sec.gov`. Strip every other link.
3. Set `rel="noopener noreferrer"` and `target="_blank"` on every permitted link.
4. Render chunk text and citation quotes as JSX text nodes, which React escapes, never through dangerouslySetInnerHTML. The only sanitized HTML on the page is the answer markdown after DOMPurify. The vanilla equivalent: `textContent`, never with `innerHTML`.
5. Send a Content-Security-Policy header that permits scripts from `'self'` only and blocks inline scripts.

**S-04 Input limits (Timebox)**

1. Reject a question shorter than 3 characters with HTTP 400.
2. Reject a question longer than 1,000 characters with HTTP 413.
3. Reject a request body larger than 16 KB.
4. Clamp `max_context_tokens` to 64,000 and `max_chunks` to 96 from the config.

**S-05 Rate limits (Timebox)**

1. Apply a token bucket per client address: 10 questions per minute and 100 per hour.
2. Return HTTP 429 with a `Retry-After` header.
3. Apply a daily provider budget in USD from config. When the spend reaches the budget, serve cached answers and the degraded mode.

**S-06 Authentication for the demo and authorization hooks (Timebox for the token, production for the rest)**

1. Require `Authorization: Bearer <token>` on every `/api/` route except health and ready.
2. Compare the token with a constant-time comparison.
3. Build a `Principal` object for every request with `tenant_id`, `allowed_tickers`, and `allowed_sources`. In this release, the Principal permits every ticker.
4. Pass the Principal into the retriever, which adds the tenant and ticker filters to every SQL clause. Private data in phase 3 uses the same path.
5. Replace the shared token with OpenID Connect in phase 1 of the roadmap.

**S-07 Audit log (Timebox)**

1. Write 1 JSON line per question to `logs/audit.jsonl`. The line holds `request_id`, the timestamp, the question, and the resolved tickers. It also holds the chunk IDs in the context and the prompt hash. The line also holds the prompt version, the index version, and the model snapshot. The latency breakdown, the token counts, the cost, the drift counts, and the flags complete it.
2. Never write the full prompt or the API key into the audit log. The prompt hash and the chunk IDs reproduce the prompt from the index.
3. Rotate the file daily and keep it readable only by the service user.

**S-08 Dependency pins and vulnerability scans (Timebox for the lock file, production for the scan gate)**

1. Pin every dependency with a lock file (`uv.lock`).
2. Pin the embedding model and the reranker to revision hashes in `config/keel.yaml`.
3. Run `pip-audit` in CI and fail the build on a known vulnerability of high severity.
4. Run `trivy` on the container image in CI.

**S-09 Container hardening (Production)**

1. Run the service as a non-root user.
2. Mount the index and the corpus read-only, and mount only `logs/` and `cache/` as writable.
3. Drop all Linux capabilities and set a memory limit of 4 GB.
4. Expose only port 8000.

**S-10 Zip extraction safety (Timebox)**

CAUTION: If a zip entry resolves to a path outside the target directory, stop the extraction and report the entry name.

1. For each entry, compute the absolute target path and check that the path starts with the absolute target directory.
2. Reject an entry with an absolute path, a `..` component, or a symbolic link.
3. Reject a zip with more than 10,000 entries or an uncompressed size above 2 GB.
4. Extract into a temporary directory, then move the directory into place.

**S-11 SSRF protection for future fetches (Production)**

1. Permit outbound fetches only to `https://www.sec.gov` and `https://data.sec.gov`, resolved through an allow list of hosts.
2. Resolve the host before the request and reject private, loopback, and link-local addresses.
3. Disable redirects, or re-check every redirect target against the allow list.
4. Send the User-Agent header that the SEC requires, with a contact address.

**S-12 Data license (Timebox for the record, production for legal review)**

1. Read the `license` key in `manifest.json` and record the value in the build report.
2. Note in the README that SEC EDGAR filings are public domain works of the United States government (A-05). Note also that the client's legal team must confirm the terms for commercial use.
3. Keep the source URL of every filing in the metadata for attribution.

**S-13 Model version pin (Timebox)**

1. Set the model to the dated snapshot identifier in `config/keel.yaml`, never to a bare alias.
2. Record the model snapshot in every audit record and in the eval report.
3. Re-run the golden set when the snapshot changes, and record the result in the prompt log.

**S-14 Logs without secrets or personal data (Timebox)**

1. Log the question text, which is business content, and no user identity beyond a hashed client address.
2. Redact key patterns in every log line.
3. Store no browser data except the token in session storage.

**S-15 Browser origin policy (Timebox)**

1. Serve the front-end and the API from 1 origin, and set no CORS headers.
2. Set `SameSite=Strict` on any future cookie.

**S-16 Answer cache integrity (Timebox)**

1. Key each cache entry with the question hash, the index version, the prompt version, and the model snapshot.
2. Store a sha256 of the answer inside each entry and check the hash on read.
3. Make the cache directory writable by the service user only.

**S-17 Multi-tenant isolation (Production)**

1. Add `tenant_id` to the `filings` and `chunks` tables and to every index manifest.
2. Build 1 dense index per tenant, so a cross-tenant scan is impossible by construction.
3. Add a test that proves a Principal of tenant A never receives a chunk of tenant B.
