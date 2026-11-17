# Security design

Keel serves public SEC filings. The main risks are a leaked API key,
instructions planted in filing text, script injection through rendered
model or filing text, and abuse of the model budget by anonymous traffic
on the public site. This document lists the threat model and the controls
S-01 to S-20. For each control it states what the control does, where it
lives in the code, how it is tested, and whether it is fully built.

To report a vulnerability, see [`SECURITY.md`](../SECURITY.md) at the
repository root. Decision IDs (D-xx) are in [DECISIONS.md](DECISIONS.md);
the request pipeline is in [ARCHITECTURE.md](ARCHITECTURE.md).

## Trust boundaries

| Zone | Trust level | What crosses the boundary | Control |
| --- | --- | --- | --- |
| Browser | Untrusted | Questions, a bearer token or a visitor's Anthropic key | Input limits, token check, rate limits, output escaping |
| Service process | Trusted | Config, secrets from environment variables | Secrets never logged, never returned |
| Corpus text | Untrusted data | Filing text inside the prompt | Declared as data in the prompt, never rendered as HTML |
| Model provider | External | The prompt, the answer | Timeouts, retries before content only, schema validation, pinned model |
| SEC EDGAR | External, public | Ticker map, company facts, filing documents | Host allow list, public address check, size limits |
| Disk (index, logs, cache) | Trusted | Index files, audit records, cached answers | Checksums, file modes, no secrets in logs |

## Threat model

The model uses STRIDE. Each threat names the control that answers it.

| ID | Threat | STRIDE | Asset | Likelihood | Impact | Control |
| --- | --- | --- | --- | --- | --- | --- |
| T-01 | The provider API key leaks through a log, a commit, or a screen share | Information disclosure | Provider account and budget | Medium | High | S-01 |
| T-02 | Filing text or a planted chunk carries instructions that change the answer | Tampering | Answer integrity | Medium | Medium | S-02 |
| T-03 | Model text or filing text holds HTML or script that runs in the browser | Tampering, elevation of privilege | User session | Medium | High | S-03 |
| T-04 | A very long question or a flood of questions exhausts the context budget or the provider budget | Denial of service | Availability, cost | Medium | Medium | S-04, S-05, S-20 |
| T-05 | Someone uses the API or the admin routes without permission | Spoofing | Provider budget, audit trail, admin jobs | Medium | Medium | S-06, S-19 |
| T-06 | A user disputes an answer and no record exists | Repudiation | Trust | Low | Medium | S-07 |
| T-07 | A dependency with a known vulnerability ships in the image | Elevation of privilege | Host | Medium | High | S-08 |
| T-08 | The container runs as root with a writable file system | Elevation of privilege | Host | Low | High | S-09 |
| T-09 | A crafted zip writes a file outside the corpus directory | Tampering | Host file system | Low | High | S-10 |
| T-10 | A fetch of SEC or download URLs is redirected to an internal address | Spoofing, information disclosure | Internal network, cloud metadata | Low | High | S-11 |
| T-11 | The corpus license does not permit the use | Repudiation | Legal position | Low | Medium | S-12 |
| T-12 | The provider changes the model under an alias and the answers change | Tampering | Reproducibility | Medium | Medium | S-13 |
| T-13 | The audit log or the answer cache holds secrets or personal data | Information disclosure | Users | Low | Medium | S-14 |
| T-14 | A second origin reads the API from a browser | Spoofing | API | Low | Medium | S-15 |
| T-15 | A tampered answer cache file serves a wrong answer | Tampering | Answer integrity | Low | Medium | S-16 |
| T-16 | A future private data feature leaks documents across tenants | Information disclosure | Private data | Medium | High | S-06, S-17 |
| T-17 | A visitor's own Anthropic key is stored, logged, or echoed | Information disclosure | The visitor's provider account | Medium | High | S-18 |
| T-18 | Anonymous visitors spend the service's model budget or reach operator features | Denial of service, elevation of privilege | Budget, admin jobs, other users' data | High | Medium | S-19, S-20 |

## Controls

Status: **built** means the control ships and has a test; **partial**
means some steps ship; **not built** means the control is designed but
waits for a feature that needs it.

### S-01 Secret handling (built)

If a key appears in a log line, a commit, a screenshot, or a URL, rotate
it at once.

- **What.** `ANTHROPIC_API_KEY` and `KEEL_API_TOKEN` come from environment
  variables only. A secret key in `config/keel.yaml` stops the config
  load. `.env` is in `.gitignore`; `.env.example` is committed with empty
  values. A redacting log formatter on every root handler (uvicorn
  included) masks the configured secret values and the value of any name
  that ends in `KEY` or `TOKEN`, in `key=value`, header, JSON, and query
  string forms. No secret appears in an API response or an error message.
  A `gitleaks` hook blocks commits that hold a key pattern, and CI runs
  `gitleaks` on every push.
- **Where.** `keel/config.py`, `keel/security.py`, `keel/api/app.py`,
  `.pre-commit-config.yaml`, `.github/workflows/ci.yml`.
- **Tested by.** `test_secrets_refused_in_config_file`,
  `test_log_lines_are_redacted`, `test_redact_patterns_and_values`,
  `test_redact_names_headers_and_queries`, `test_short_service_token_masked`,
  `test_config_error_never_shows_secrets`, and the other redaction tests
  in `tests/unit/test_security.py`.

### S-02 Prompt injection through retrieved filing text (built)

If an answer obeys an instruction that is not in the question, treat the
context as compromised and inspect the cited chunks.

- **What.** Every chunk sits in a `<chunk>` element, and the question in a
  separate `<question>` element. The system block (rule 4) and the last
  line of the user block declare the context as untrusted data. The
  citation validator rejects any citation to a chunk outside the context,
  so a planted instruction cannot cite itself as evidence from another
  filing. A question that matches an injection pattern is flagged
  (`injection_suspect`) in the log and the audit record and still runs.
  The model never writes a URL: the server attaches the SEC URL from the
  chunk table.
- **Where.** `keel/prompt.py`, `prompts/answer_system_v1.5.1.md`,
  `keel/citations.py`, `keel/understanding.py`.
- **Tested by.** `test_untrusted_context`, `test_injection_flag`,
  `test_sec_url_only`, and the adversarial golden questions G-27 (a
  planted instruction in a filing) and G-28 (advice and system prompt
  requests), scored by `keel eval`. Prompt 1.5.0 was rejected because a
  finding cited the planted chunk; 1.5.1 fixed it.

### S-03 Rendered output (built)

If any model text or filing text reaches `innerHTML` without
sanitization, the page is open to script injection.

- **What.** The answer markdown goes through `marked` and then DOMPurify
  with a strict allow list (p, strong, em, ul, ol, li, table, thead,
  tbody, tr, th, td, code, a). In model and filing text, links survive
  only for `https://www.sec.gov`, with `rel="noopener noreferrer"` and
  `target="_blank"`; the only other links on the page are the app's own
  routes, such as a company tag that opens `/financials`. Chunk text, citation quotes, and
  filing reader text render as JSX text nodes, which React escapes; the
  only sanitized HTML on the page is the answer markdown. Every response
  carries a Content-Security-Policy with `script-src 'self'`,
  `object-src 'none'`, `frame-ancestors 'none'`, plus `nosniff` and
  `no-referrer`.
- **Where.** `web/src/lib/markdown.ts`, `web/src/components/AnswerMarkdown.tsx`,
  `web/src/components/SecLink.tsx`, `keel/api/app.py` (`SecurityHeaders`).
- **Tested by.** `test_ui_escapes_model_text` (Playwright,
  `web/e2e/security.spec.ts`), `markdown.test.ts` (the allow list), and
  `test_frontend_fallback` (the CSP header).

### S-04 Input limits (built)

- **What.** A question shorter than 3 characters gets HTTP 400, one longer
  than 1,000 characters gets HTTP 413, and a request body over 16 KB gets
  HTTP 413. `max_context_tokens` is clamped to 64,000 and `max_chunks` to
  96.
- **Where.** `keel/api/routes.py` (`MAX_BODY_BYTES`), `keel/config.py`,
  `keel/understanding.py`.
- **Tested by.** `test_question_limits`, `test_context_caps`.

### S-05 Rate limits and the daily budget (built)

- **What.** A token bucket per client: 30 questions per minute and 300 per
  hour by default (`limits.rate_per_minute`, `limits.rate_per_hour`). A
  named user or a visitor with a key has a bucket per name; the shared
  legacy token and visitors without a key have a bucket per peer address.
  Over the limit, HTTP 429 with `Retry-After`. A daily provider budget in
  USD (`limits.daily_budget_usd`, 20 by default), summed from the
  `cost_usd` of the audit records of the current UTC day, stops model
  requests at the limit; the service then serves the answer cache and the
  degraded mode.
- **Where.** `keel/api/ratelimit.py`, `keel/api/routes.py`,
  `keel/reliability.py`.
- **Tested by.** `test_rate_limit`, `test_rate_limit_per_user`,
  `test_rate_limiter_minute_and_hour`, `test_budget_stop`.

### S-06 Authentication and the Principal (built for tokens; OpenID Connect not built)

- **What.** Every `/api/` route except `/api/health` and `/api/ready`
  needs `Authorization: Bearer <token>`, unless the public mode is on
  (S-19). Tokens are compared in constant time with the sha256 hashes in
  `config/users.yaml` and with `KEEL_API_TOKEN` (the admin user
  `legacy`). Roles are analyst, partner, and admin; the admin API checks
  the role on every call, and the front-end role gate is a convenience,
  not the control. Every request carries a `Principal` with `tenant_id`,
  `allowed_tickers`, and `allowed_sources`, which the retriever applies
  to its SQL; today it permits every ticker. A wrong bearer token is
  always HTTP 401, even in public mode, so a typo never turns an admin
  into a visitor.
- **Where.** `keel/api/auth.py`, `keel/users.py`, `keel/api/routes.py`.
- **Tested by.** `test_auth_required`, `test_wrong_token_stays_unauthorized_in_public_mode`,
  `test_admin_token_still_works_in_public_mode`, the role tests in
  `tests/integration/test_users_api.py`.

### S-07 Audit log (built)

- **What.** 1 JSON line per question in `logs/audit.jsonl`: request ID,
  timestamp, user name, question, resolved tickers, the chunk IDs in the
  context, prompt hash and version, index version, model, latency
  breakdown, token counts, cost, citation drift counts, flags, and the
  outcome. The full prompt and any key are never written; the prompt hash
  and the chunk IDs reproduce the prompt from the index. The file rotates
  daily and has mode 0600.
- **Where.** `keel/audit.py`, `keel/answer.py`.
- **Tested by.** `test_audit_line`, `test_audit_refuses_prompt_and_logs_failure`,
  `test_audit_rotates_daily`.

### S-08 Dependency pins and vulnerability scans (built)

- **What.** `uv.lock` and `web/package-lock.json` pin every dependency.
  The embedding model and the reranker are pinned to Hugging Face commit
  hashes in `config/keel.yaml`. CI runs `pip-audit --strict` on every PR;
  Dependabot runs weekly; the release workflow scans the image with Trivy
  and publishes an SBOM and provenance with it. CodeQL runs on the code.
- **Where.** `.github/workflows/ci.yml`, `.github/workflows/release.yml`,
  `.github/workflows/codeql.yml`, `config/keel.yaml`.
- **Tested by.** The CI jobs themselves; a finding fails the job.

### S-09 Container hardening (built)

- **What.** The image runs as the non-root user `keel`. In Docker Compose
  the root file system is read-only, with a 256 MB `/tmp` tmpfs and named
  writable volumes for state, index, cache, and logs. All Linux
  capabilities are dropped, `no-new-privileges` is set, and memory is
  capped at 4 GB. The app binds to `127.0.0.1:8000`; only Caddy exposes
  ports 80 and 443.
- **Where.** `Dockerfile`, `docker-compose.yml`, `infra/Caddyfile`.
- **Tested by.** `tests/integration/test_read_only_host.py` runs every
  admin job kind against the read-only layout.

### S-10 Zip extraction safety (built)

If a zip entry resolves outside the target directory, extraction stops
and reports the entry name.

- **What.** Each entry's absolute target path must sit inside the target
  directory. Absolute paths, `..` components, symbolic links, and
  duplicate entries are rejected. A zip with more than 10,000 entries or
  more than 2 GB uncompressed is rejected, and the size is checked again
  while writing. Extraction goes to a temporary directory, then moves into
  place.
- **Where.** `keel/extractor.py`.
- **Tested by.** `test_path_traversal_rejected`, `test_symlink_rejected`,
  `test_entry_resolving_outside_rejected`, `test_entry_count_cap`,
  `test_size_cap`, `test_size_cap_while_writing`,
  `test_duplicate_entry_rejected` in `tests/unit/test_extractor.py`.

### S-11 Outbound fetch protection (built)

- **What.** EDGAR fetches go only to `www.sec.gov` and `data.sec.gov`.
  `keel bootstrap` downloads only from the configured corpus and index
  URLs and the GitHub release asset hosts (D-38). Every request is https
  on port 443 with no credentials in the URL; the host is resolved first
  and every address must be public (private, loopback, link-local,
  NAT64, and IPv4-mapped forms are checked); redirects are followed by
  hand, at most 5, each target checked again. Logs and errors name only
  the host. EDGAR requests send the `User-Agent` with a contact address
  that the SEC requires, wait 0.2 seconds between requests, and cap
  untrusted response bodies (2 MB for the company feed, whose XML parser
  also refuses DTDs and entities).
- **Where.** `keel/net.py`, `keel/edgar.py`, `keel/bootstrap.py`,
  `keel/directory.py`.
- **Tested by.** `tests/unit/test_net.py` (`test_is_public_address`,
  `test_check_addresses`, `test_nat64_and_mapped_addresses_use_the_ipv4_part`,
  `test_redact_url`), `test_check_url_rejects_non_public_addresses` and
  `test_rate_limit_waits_between_requests` in `tests/unit/test_edgar.py`,
  `test_check_url_accepts_public_https` in `tests/unit/test_bootstrap.py`.

### S-12 Data license (built)

- **What.** `keel inventory` reads the `license` key of the corpus
  manifest (`Public domain (SEC filings are US government documents)`,
  A-05). Every filing keeps its source URL for attribution, and every
  citation links to the filing on sec.gov.
- **Where.** `keel/inventory.py`, the `filings` table.
- **Tested by.** `test_inventory_counts` and the inventory unit tests.

### S-13 Model version pin (built)

- **What.** `llm.model`, `llm.fallback_model`, and `llm.judge_model` name
  fixed model ids in `config/keel.yaml`. The model is recorded in every
  audit record, every cached answer key, and every eval report. A model
  change requires a config change and a golden set run.
- **Where.** `config/keel.yaml`, `keel/providers/anthropic.py`,
  `keel/cache.py`.
- **Tested by.** `test_model_pinned`.

### S-14 Logs without secrets or personal data (built)

- **What.** The service logs the question text, which is business
  content, and the user name of a token holder. It writes no client
  address at all: there is no uvicorn access log. A visitor is named by a
  hash of their key, never the key. Key patterns are redacted in every
  log line (S-01). The browser stores only the access token, in session
  storage, which ends with the tab.
- **Where.** `keel/security.py`, `keel/api/app.py`,
  `web/src/components/TokenField.tsx`.
- **Tested by.** The redaction tests of S-01 and
  `test_visitor_key_is_secret`.

### S-15 Browser origin policy (built)

- **What.** The front-end and the API share 1 origin, and the service
  sends no CORS headers, so no other origin can read the API from a
  browser. Any future cookie uses `SameSite=Strict`.
- **Where.** `keel/api/app.py`.
- **Tested by.** `test_frontend_fallback` asserts no
  `access-control-allow-origin` header.

### S-16 Answer cache integrity (built)

- **What.** Each cache entry is keyed by the hash of the normalized
  question, the index version, the prompt version, and the model (D-29).
  Each entry stores a sha256 of its answer, checked on read; a mismatch is
  a miss. The cache directory has mode 0700.
- **Where.** `keel/cache.py`.
- **Tested by.** `test_cache_key_parts`, `test_cache_round_trip_and_checksum`,
  `test_cache_directory_is_private`.

### S-17 Multi-tenant isolation (not built)

- **What.** For private documents: `tenant_id` on the `filings` and
  `chunks` tables and in every index manifest, 1 dense index per tenant so
  a cross-tenant scan is impossible by construction, and a test that a
  Principal of tenant A never receives a chunk of tenant B. Today the
  index holds only public filings and the Principal hook (S-06) is the
  seam this control will use.
- **Where.** Not built.
- **Tested by.** Not applicable yet.

### S-18 Visitor API keys (built)

The public site lets a visitor ask with their own Anthropic key. The key
belongs to the visitor and must never outlive the request.

- **What.** With `auth.public` on (`KEEL_AUTH__PUBLIC=1`), a request
  without an `Authorization` header is a visitor. A visitor may send an
  Anthropic key in the `X-Anthropic-Api-Key` header. The key must match
  `sk-ant-` plus 16 to 250 URL-safe characters, or the request gets HTTP
  400 `invalid_api_key` and the body never echoes the value. The key is
  held as a `pydantic.SecretStr` for the life of the request only: the
  question runs on a copy of the pipeline built with that key, and the key
  is never written to disk, the audit log, the answer cache, or a log
  line. Caddy deletes the header from its JSON access log. The visitor's
  name is `visitor-` plus the first 16 hex digits of the sha256 of the
  key, so their history stays theirs without storing the key. A key the
  provider rejects maps to a clear `ProviderAuthError` message. The spend
  is billed to the visitor's account and is excluded from the service's
  daily budget (S-05).
- **Where.** `keel/api/auth.py` (`visitor_key`, `visitor`),
  `keel/api/routes.py` (`_billing`), `keel/answer.py` (`for_visitor`),
  `keel/providers/anthropic.py`, `infra/Caddyfile`.
- **Tested by.** `test_visitor_key_is_secret`, `test_malformed_visitor_key`,
  `test_visitor_name_is_a_stable_hash_of_the_key` (unit);
  `test_visitor_key_answers_and_bills_the_visitor`,
  `test_visitor_spend_stays_out_of_the_budget`,
  `test_malformed_visitor_key_is_rejected_without_echo` (integration).

### S-19 Visitor role restrictions (built)

- **What.** A visitor is a separate role with no users file entry. A
  visitor without a key reads the answer cache only: a cached question
  (the example questions and the golden set) answers with a provider that
  refuses any request, so the service key is never spent, and an uncached
  question gets HTTP 401 `api_key_required`. A visitor cannot reach
  `GET /api/status` (spend, budget, breaker counters, models),
  `/api/debug/*`, any `/api/admin/*` route, or comp set writes; those
  return HTTP 403 `sign_in_required` (admin routes also check the admin
  role). Visitors without a key share 1 name, so the history route returns
  an empty list to them rather than anyone else's questions.
  `/api/ready` reports `access: public` and carries no spend or model
  data.
- **Where.** `keel/api/routes.py` (`require_member`, `Member`),
  `keel/api/debug.py`, `keel/api/workspace.py`, `keel/api/admin*.py`.
- **Tested by.** `test_public_mode_makes_a_visitor`,
  `test_token_mode_refuses_a_visitor` (unit);
  `test_visitor_without_key_needs_one_for_a_new_question`,
  `test_visitor_without_key_reads_the_answer_cache`,
  `test_visitor_cannot_reach_member_routes`,
  `test_visitor_history_is_their_own`, `test_public_ready_reports_access`,
  `test_ready_exposes_no_spend_or_models` (integration).

### S-20 Shared visitor rate limit (built)

- **What.** On top of the per-client bucket of S-05, every visitor
  question also takes 1 token from a single bucket shared by all visitors
  (`limits.public_rate_per_minute` 60, `limits.public_rate_per_hour` 600
  by default). A burst of anonymous traffic therefore cannot crowd out
  token holders, whatever addresses or keys it uses.
- **Where.** `keel/api/routes.py` (`_check_rate`), `keel/config.py`,
  `keel/api/state.py`.
- **Tested by.** `test_visitors_share_the_public_rate_limit`.

## Operational notes

- **Edge.** CloudFront terminates TLS for `keeldd.com` with an ACM
  certificate (`TLSv1.2_2021`), forwards every header but `Host` with
  caching off, and adds the managed security headers policy. Caddy
  terminates TLS again at the origin with a Let's Encrypt certificate.
- **Host access.** Deploys run through SSM Run Command from a GitHub OIDC
  role scoped to the `production` environment, which needs a reviewer.
  GitHub holds no AWS key. Port 22 admits only the admin CIDR.
- **Infrastructure checks.** `infra.yml` runs `terraform fmt`, `validate`,
  `tflint`, and `checkov` on infrastructure changes, and a read-only
  nightly `terraform plan` that fails on drift. Pull requests get no AWS
  credentials, because the repository is public.
- **Known gap.** The data use page states a 12-month audit retention;
  nothing prunes older lines automatically yet.
