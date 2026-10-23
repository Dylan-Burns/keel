# Admin, watch list, and debug API

The contract of the routes that bring the operational CLI commands to the web UI. The question routes of chapter 14 (`/api/ask`, `/api/results`, `/api/shared`, `/api/history`, `/api/coverage`, and the rest) are unchanged. Every route below needs `Authorization: Bearer <token>`; the role comes from the users file (`config/users.yaml`, chapter 27.2), and `KEEL_API_TOKEN` passes as the admin user `legacy`.

## Roles

| Route | analyst | partner | admin |
| --- | --- | --- | --- |
| `GET /api/watch` | yes | yes | yes |
| `POST /api/watch`, `DELETE /api/watch/{ticker}` | 403 | 403 | yes |
| `POST /api/debug/understand`, `POST /api/debug/retrieve` | yes | yes | yes |
| every `/api/admin/...` route | 403 | 403 | yes |

No token or a wrong token gets HTTP 401 before the role check. Analysts and partners keep everything they had: ask, export, history, share links, comp sets, feedback, templates, and the watch list view.

## Errors

Every error has the body of chapter 14.3 under `detail`, and some add fields:

```json
{"detail": {"code": "job_running", "message": "the backup job 3f2a... is running", "job_id": "3f2a9c0d1e4b5a67"}}
```

| HTTP | `code` | When | Extra fields |
| --- | --- | --- | --- |
| 400 | `invalid_params` | the job parameters do not fit the kind, or the eval subset names no question | `fields`: the parameter names that failed (never their values) |
| 400 | `confirm_required` | the job needs a typed confirmation and none came | `confirm`: the value to type; `estimate` for a job that calls the model |
| 400 | `confirm_mismatch` | the confirmation differs from the value asked for | same as above |
| 400 | `invalid_ticker` | a watch list ticker cannot name a corpus file | |
| 400 | `invalid_user` | `POST /api/admin/users` with the reserved name `legacy` | |
| 400, 413 | `invalid_question` | a debug question fails the input checks of `/api/ask` | |
| 401 | `unauthorized` | no token or a wrong token | |
| 403 | `forbidden` | the route is for admins | |
| 404 | `not_found`, `archive_not_found` | an unknown job, user, watch row, or archive | |
| 409 | `job_running` | a heavy job is queued or running, or the first-start bootstrap or a nightly refresh or backup runs | `job_id`: the job that holds the slot (null for the bootstrap and the nightly jobs) |
| 409 | `not_cancellable` | cancel of a job that is not queued | |
| 409 | `user_exists`, `self_delete` | the user exists; an admin removes their own user | |
| 422 | (FastAPI) | the body is not JSON of the right shape, an unknown job kind, a bad path or query value | |
| 429 | `rate_limited` | the debug routes count against the question rate limit | `retry_after` and the `Retry-After` header |
| 503 | `jobs_unavailable`, `store_unavailable`, `users_unavailable`, `prices_unavailable`, `index_not_built`, `index_corrupt` | a store, file, or the index is not available | |

## Jobs

The operational commands run as background jobs on 1 worker thread in the server process (`keel/api/jobs.py`). The worker calls the library functions behind each CLI command; it never starts a shell. A job record lives in the `jobs` table of `<logs.dir>/state.sqlite`, so it survives a restart; a job that was queued or running when the server stopped is marked `failed` with the error `interrupted: the server stopped before the job finished` at the next start.

Every kind but `facts` is heavy. While a heavy job is queued or running, a second heavy job gets HTTP 409 `job_running` with the `job_id` that holds the slot, and the nightly refresh and backup of the in-app scheduler skip their run; while a nightly job runs, a heavy job gets 409 with `job_id` null. The worker writes the progress and the log to the record at most every 0.5 s and at the end, and the phase at once. A light job (`facts`) is accepted at any time and queues behind the running job. A job that publishes a new index build (an `add` or a `refresh` that indexed a filing, a `restore`, an `index`) reloads the index at its end, so the server serves the new build without a restart; when the new build cannot be opened, the old one stays in service and the job result has `"reloaded": false`.

### Job kinds

| `kind` | CLI twin | `params` (defaults) | `confirm` | Reloads the index |
| --- | --- | --- | --- | --- |
| `add` | `keel add TICKER` | `ticker` (required; letters, digits, `.`, `-`, at most 10) | none | when a build was published |
| `refresh` | `keel refresh [--dry-run]` | `dry_run` (false) | none | when a filing was added |
| `warm_cache` | `keel warm-cache [--refresh] [--facts-only]` | `refresh` (false), `facts_only` (false) | `cost` unless `facts_only` | no |
| `eval` | `keel eval [--answers] [--no-judge] [--subset S] [--no-ablation]` | `answers` (false), `judge` (true), `subset` (null; a tag or `G-01,G-02`), `ablation` (true) | `cost` when `answers` is true | no |
| `facts` | `keel facts TICKER` | `ticker` (required) | none | no |
| `backup` | `keel backup [--index-only]` | `index_only` (false) | none | no |
| `restore` | `keel restore ARCHIVE` | `archive` (required; a name from `GET /api/admin/backups`) | the exact archive name | yes |
| `index` | `keel index [--incremental]` | `incremental` (false) | `rebuild` | yes |

Notes per kind:

- `add`, `refresh`, `facts`, and `warm_cache` reach the SEC (EDGAR) with the configured `User-Agent` and pacing (chapter 26). `add` and `index` extract the corpus zip first when the corpus directory is empty.
- `warm_cache` answers through the server's pipeline, so the daily budget, the circuit breaker, and the audit log apply as for any question (1 model request per question that the answer cache does not hold; `refresh` answers all of them again).
- `eval` writes `<run id>.md` and `<run id>.json` to `eval.report_dir` (`KEEL_EVAL__REPORT_DIR`; null is `<logs.dir>/eval`), never under the application root, which is read-only on the host; `keel eval` on the command line keeps writing `eval/report.md`. The eval page shows the newest job report, else the committed `eval/report.md`. The job checks that the folder is writable before the first question, so a read-only path fails before any model request; a folder that fails after the run gets the report in a new private temporary folder instead (`<tmp>/keel-eval-*`), which the eval page does not list and a restart clears, so the job log and `report` name the path to copy it from; the job result keeps the gates either way. With `answers` it makes 2 model requests per golden question (the answer and the judge): about 4 USD for the 24 questions.
- `restore` validates the name against the listing of the backup directory (`scheduler.backup_dir`); a path, a link, or any other file is never reachable. The current build stays as `previous`.
- `index` warns: a full build needs about 6.6 GB of memory and runs for more than an hour on the pilot host. Questions keep the current build until the new one is published.
- `add`, `refresh`, and `index` reuse the embedding model the server loaded, batch by batch under the pipeline's retrieval lock, so the memory does not double.

### `POST /api/admin/jobs`

Request:

```json
{"kind": "restore", "params": {"archive": "keel-2026-10-22T023000Z.tar.gz"}, "confirm": "keel-2026-10-22T023000Z.tar.gz"}
```

`params` is optional (the defaults above); an unknown parameter is `invalid_params`. `confirm` is a string of at most 200 characters.

Response HTTP 202:

```json
{
  "job": {
    "id": "3f2a9c0d1e4b5a67",
    "kind": "restore",
    "params": {"archive": "keel-2026-10-22T023000Z.tar.gz"},
    "requested_by": "carol",
    "heavy": true,
    "status": "queued",
    "progress": {"done": 0, "total": null},
    "phase": "queued",
    "created_at": "2026-10-22T18:00:00+00:00",
    "started_at": null,
    "finished_at": null,
    "result": null,
    "error": null,
    "log": [],
    "step_count": 12,
    "current_step": null,
    "steps": [{"key": "corpus", "name": "Prepare the corpus", "status": "pending", "started_at": null, "finished_at": null, "progress": null, "log": []}, "..."]
  },
  "warnings": ["the restored build replaces the current build; the current build stays as `previous`"],
  "estimate": null
}
```

`estimate` is the cost estimate (below) for `eval` and `warm_cache`, else null. A missing or wrong confirmation returns HTTP 400 with the value to type, so the UI can show it in the confirmation dialog:

```json
{"detail": {"code": "confirm_required", "message": "this job needs a typed confirmation", "confirm": "cost", "estimate": {"kind": "eval", "questions": 24, "model_requests": 24, "judge_requests": 24, "answer_usd": 0.0936, "judge_usd": 0.084, "usd": 4.26, "basis": "audit", "confirm": "cost"}}}
```

### The job record

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | 16 hex characters |
| `kind` | string | the job kind |
| `params` | object | the validated parameters with their defaults |
| `requested_by` | string | the admin who asked |
| `heavy` | bool | true when the job holds the maintenance slot |
| `status` | string | `queued`, `running`, `succeeded`, `failed`, or `cancelled` |
| `progress` | object | `done` and `total` (null when not known); for a job with steps, the ended steps of all steps (each step counts its own work in `steps[].progress`) |
| `phase` | string | a few words: `queued`, `waiting for the nightly job`, `running`, the name of the running step (such as `Embed`), `reloading the index`, `done`, `failed`, `interrupted` |
| `step_count` | int | the steps of the plan; 0 for a job recorded before the steps existed |
| `current_step` | int or null | the index of the running step |
| `created_at`, `started_at`, `finished_at` | string or null | UTC, ISO 8601 |
| `result` | object or null | the summary of a succeeded job (per kind, below) |
| `error` | string or null | `<ErrorClass>: <message>` of a failed job, or `internal error: <class>`; an `OSError` adds its errno, reason, and path (`internal error: OSError: [Errno 30] Read-only file system: '/app/eval/report.md'`), with secrets masked |
| `log` | list of strings | the last 200 lines, oldest first, each at most 400 characters, secrets masked, control characters and line breaks replaced by spaces (1 report is 1 line); only `GET /api/admin/jobs/{id}` and `POST` return it |
| `steps` | list of objects | the steps in plan order (below); only `GET /api/admin/jobs/{id}` and `POST` return it; empty for a job recorded before the steps existed |

### Steps

Each job kind declares its steps up front, so a queued job lists them as `pending`. The library function behind the job reports the step it enters, its log lines, and its counts; entering a step ends the running one as `succeeded` and marks the steps it jumps over `skipped`. When the job ends, the running step is `succeeded` or `failed` (its log ends with `error: <the job error>`; a job that fails before its first step fails its first step), and every step not reached is `skipped`. A cancelled or interrupted job skips its pending steps. A failed reload leaves the job `succeeded` with `"reloaded": false` and marks the `reload` step `failed`.

| Field | Type | Meaning |
| --- | --- | --- |
| `key` | string | the stable step key, such as `embed` |
| `name` | string | the step name, such as `Embed` |
| `status` | string | `pending`, `running`, `succeeded`, `failed`, or `skipped` |
| `started_at`, `finished_at` | string or null | UTC, ISO 8601 |
| `progress` | object or null | `done`, `total` (or null), and `unit` (such as `chunks`, `questions`, `tickers`, `members`) |
| `log` | list of strings | the step's last 200 lines, cleaned like the job log |

The steps per kind (key: name):

- `add`: `corpus` Prepare the corpus, `resolve` Resolve the ticker, `filings` Fetch the filing list from EDGAR, `download_10k` Download the 10-K, `download_10q` Download the 10-Q (skipped when no 10-Q is picked), `convert` Convert to text, `parse` Parse and section, `chunk` Chunk, `embed` Embed (counts chunks, 1 line per shard), `store` Write the chunk store, `publish` Publish the index build, `reload` Reload the server. When no file changed, the steps after `parse` are skipped.
- `refresh`: `watch` Read the watch list, `check` Check EDGAR for new filings (counts tickers, 1 line per ticker), `add` Add the new filings (counts tickers; the add steps of each ticker are lines such as `ZTS: Embed`; skipped on a dry run or with nothing new), `reload`.
- `warm_cache`: `index` Check the loaded index, `facts` Fetch the company facts (counts tickers), `questions` Select the demo questions, `answer` Answer the demo questions (counts questions, a line before and after each answer). `facts_only` stops after `facts`.
- `eval`: `report_dir` Check the report directory, `golden` Load the golden set and labels, `harness` Open the index and load the models, `questions` Run the golden questions (counts questions, a retrieval, answer, and judge line per question), `score` Score the answers (with `answers` only), `report` Write the report (with 1 line per gate).
- `facts`: `resolve`, `fetch` Fetch the company facts, `map` Map the facts lines.
- `backup`: `build` Find the current build, `index` Copy and check the index files, `logs` Copy the logs and databases (skipped with `index_only`), `archive` Write the archive (counts members), `checksum` Write the checksum.
- `restore`: `find` Find the archive, `verify` Verify the archive checksum, `extract`, `check` Check the index files, `shards` Rebuild the shards, `logs` Set the restored logs aside, `swap` Point current at the restored build, `reload`.
- `index`: `corpus` Prepare the corpus, then the build steps of `add` from `parse` to `publish`, then `reload`.

A database written before the steps gets the `steps` column on its first connection; its old rows have no steps, and the page shows them with the job log as before. The payload stays bounded: at most 24 steps of at most 200 lines of at most 400 characters.

Results: `add` returns the `keel add` report (ticker, CIK, company, filings, index version, embedded counts, EDGAR requests); `refresh` the refresh report plus `new_count`, `added_count`, `error_count`; `warm_cache` the `facts` counts and, unless `facts_only`, the `answers` counts (`answered`, `refusal`, `skipped`, `failed`, `model_requests`, `cost_usd`) and `ok`; `eval` the `run_id`, the `gates` (name, value, status), `report` (the markdown path, null when no folder took it), `results` (the JSON file name), `answers_usd`, and `judge_usd`; `facts` the facts `lines`; `backup` the `archive` name, `sha256`, `members`, and `size_bytes`; `restore` the `build`, `previous`, and `index_version`; `index` the `build`, `index_version`, `counts`, and `seconds`. A job that reloads adds `reloaded`.

### The other job routes

| Route | Response |
| --- | --- |
| `GET /api/admin/jobs?limit=50` (1 to 200) | `{"items": [job without log and steps, ...], "active": job or null}`, newest first; `active` is the heavy job that holds the slot |
| `GET /api/admin/jobs/{id}` | the job with its log and steps; poll it every 1 to 2 s while it runs |
| `POST /api/admin/jobs/{id}/cancel` | the cancelled job; only a `queued` job cancels (409 `not_cancellable` otherwise), a running job runs to its end |

## Cost preview

`GET /api/admin/costs/preview?kind=eval&answers=true&judge=true&subset=G-01,G-02` or `?kind=warm_cache&refresh=false&facts_only=false`:

```json
{"kind": "eval", "questions": 2, "model_requests": 2, "judge_requests": 2, "answer_usd": 0.0936, "judge_usd": 0.084, "usd": 0.36, "basis": "audit", "confirm": "cost"}
```

The price of 1 answer is measured: the mean `cost_usd` of the newest 200 answered records of `llm.model` in the audit log (`basis: "audit"`). With none yet, it prices about 33,000 input and 2,800 output tokens with `config/prices.yaml` (`basis: "prices"`). The judge prices about 11,000 input and 2,000 output tokens of `llm.judge_model`. For `warm_cache`, `model_requests` counts the demo questions the answer cache does not hold (all of them with `refresh`, none with `facts_only`). `confirm` is `cost` for an eval with answers and for a warm-cache run that is not `facts_only` (even when every answer is cached now: a reload before the job runs changes the cache keys), else null. An out-of-scope golden question counts as a question but makes no request.

## Users

| Route | Request | Response |
| --- | --- | --- |
| `GET /api/admin/users` | | `{"items": [{"name": "alice", "role": "analyst"}], "legacy_enabled": true}`; no token and no hash |
| `POST /api/admin/users` | `{"name": "dave", "role": "analyst"}` (name: lowercase letters, digits, `.`, `_`, `-`, at most 64; role: `analyst`, `partner`, `admin`) | HTTP 201 `{"name": "dave", "role": "analyst", "token": "..."}` with `Cache-Control: no-store`. The only response that holds the token; the users file keeps its sha256, no log line or audit row holds it |
| `DELETE /api/admin/users/{name}` | | HTTP 204; the token stops passing at the next request. 404 for an unknown user, 409 `self_delete` for the caller's own user |

## System

`GET /api/admin/system` returns 1 object for the system page:

| Field | Content |
| --- | --- |
| `version`, `offline`, `provider`, `model` | the service |
| `doctor`, `doctor_failed` | the checks of `keel doctor` (`name`, `status` `ok`/`warn`/`fail`, `detail`), without the model download; the port check reports the server's own port as in use |
| `inventory` | `keel inventory` counts: `file_count`, `total_bytes`, `ticker_count`, `form_counts`, `first_filing`, `last_filing`, `manifest_present`, `discrepancy_count`, the first 20 `discrepancies`; or `{"error": ...}` |
| `index` | `loaded`, `index_version`, `build_id`, `verified`, `error`, `corpus_checksum_match`, `corpus_note`, `built_at`, `counts` (the manifest), `filings`, `quarantined` |
| `backups` | `directory` and `items` (as `GET /api/admin/backups`) |
| `scheduler` | `enabled`, `running`, `refresh_at`, `backup_at`, `backup_keep`, `backup_bucket_set`, `jobs` (`name`, `next_run`) |
| `budget` | `daily_usd`, `spent_usd`, `stopped`; null without an index |
| `active_job` | the heavy job that holds the slot, or null |
| `bootstrap` | the bootstrap status of `keel serve --bootstrap`, or null |

## Backups

| Route | Response |
| --- | --- |
| `GET /api/admin/backups` | `{"directory": "backups", "items": [{"name": "keel-2026-10-22T023000Z.tar.gz", "size_bytes": 123, "created_at": "2026-10-22T02:30:00+00:00", "sha256": "..."}]}`, newest first; only regular files named `keel-<stamp>.tar.gz` |
| `GET /api/admin/backups/{name}` | the archive as `application/gzip`, streamed, `Cache-Control: no-store`; 404 for any name outside the listing. The archive holds the audit log and the pilot store unless it was written with `index_only` |

## Admin audit

`GET /api/admin/audit?limit=100` (1 to 500) returns `{"items": [{"at", "user", "action", "target", "params", "outcome"}]}`, newest first, from the `admin_audit` table of `state.sqlite`. Every change writes 1 row, the refused attempts included: `job.<kind>` (outcome `ok`, `invalid_params`, `confirm_required`, `confirm_mismatch`, `archive_not_found`, `job_running`), `job.cancel`, `users.add`, `users.remove`, `watch.add`, `watch.remove`, `backups.download`. Parameters named like a secret (`token`, `api_key`, `password`, `secret`) are dropped before the write.

## Watch list

| Route | Request | Response |
| --- | --- | --- |
| `GET /api/watch` (any user) | | `{"items": [{"ticker": "ZTS", "user": "carol", "added_date": "2026-10-22", "mine": false}], "tickers": ["ZTS"]}`; `user` is null on another user's row unless the caller is an admin |
| `POST /api/watch` (admin) | `{"tickers": ["ZTS", "brk-b"], "user": "alice"}` (1 to 25 tickers; `user` defaults to the caller) | `{"user": "alice", "added": ["ZTS", "BRK.B"], "unchanged": []}` |
| `DELETE /api/watch/{ticker}?user=alice` (admin) | `user` defaults to the caller | HTTP 204, or 404 when that user did not watch it |

`keel refresh` (and the `refresh` job) checks the union of every user's tickers.

## Debug

Both routes take `{"question": "..."}` with the length checks of `/api/ask`, run on the pipeline the server loaded, make no model request (decision D-02), and count against the caller's question rate limit.

- `POST /api/debug/understand` returns the `QuestionAnalysis` of `keel understand` as JSON (tickers, types, time scope, comp sets, out-of-scope reason).
- `POST /api/debug/retrieve` returns `question`, `primary_type`, `types`, `tickers`, `out_of_scope`, `out_of_scope_reason`, and `retrieval`: the summary of `keel retrieve --summary` with `sub_queries` (`label`, `dense_text`, `terms`), `candidates`, `collapsed`, `after_collapse`, `reranked`, `fills` (`label`, `taken`, `quota`, `candidates`, `tokens`), `context` (`chunks`, `token_estimate`, `max_tokens`, `max_chunks`, `dropped`, `items` with `chunk_id`, `ticker`, `form`, `section`, `period_end_date`, `estimated_tokens`, `truncated`, and the rerank `score`), `sections`, `timings_ms` (`lexical`, `dense`, `rerank`, `total`), `gaps`, and `degraded`. `retrieval` is null for an out-of-scope question.

## CLI parity

| Web page | CLI |
| --- | --- |
| History | `keel history [--user NAME] [--limit N] [--json]` (every user by default) |
| Copy link | `keel share REQUEST_ID [--base-url URL]` prints `/a/<ID>` or the full URL and says whether the answer cache still holds the answer |
| Coverage | `keel coverage [--json]` |
| Admin jobs | `keel jobs [ID] [--limit N] [--json]` lists the jobs or shows 1 with its log |
| Admin job kinds | `keel add`, `keel refresh`, `keel warm-cache`, `keel eval`, `keel facts`, `keel backup`, `keel restore`, `keel index` |
| Users, watch list | `keel users`, `keel watch` |
| System | `keel doctor`, `keel inventory` |
| Debug | `keel understand`, `keel retrieve --summary` |

The question templates stay read-only in both: `config/templates.yaml` is edited in the repository, `keel template` and `GET /api/templates` read it.
