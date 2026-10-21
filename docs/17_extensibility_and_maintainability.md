## 17. Extensibility and maintainability

Keel isolates the 3 parts that change most often behind interfaces. These are the model provider, the retriever with its store, and the parser for each filing type. A YAML config drives the pipeline, so a new corpus or a new model is a config change plus a rebuild. The repo layout, the test pyramid, the CI workflow, and the version rules below keep the system maintainable after the hand-off.

### 17.1 Provider adapter

```python
class LLMProvider(Protocol):
    name: str
    model: str                      # pinned snapshot identifier

    async def answer(self, bundle: PromptBundle) -> AsyncIterator[AnswerEvent]:
        """Send exactly 1 request and yield events: delta, usage, done, error."""

    async def count_tokens(self, bundle: PromptBundle) -> int:
        """Optional. Used once at build time for the calibration factor."""
```

There are 3 implementations. `AnthropicProvider` uses the Messages API with streams, structured output, and prompt caching. `MockProvider` replays recorded events for tests and counts requests. A stub `OpenAICompatibleProvider` is the start of a second vendor adapter. The request counter in `MockProvider` is the test for FR-05.

### 17.2 Pluggable retriever and store

```python
class LexicalStore(Protocol):
    def search(self, query: str, filters: Filters, k: int) -> list[Hit]: ...

class DenseStore(Protocol):
    def search(self, vector: np.ndarray, filters: Filters, k: int) -> list[Hit]: ...

class ChunkStore(Protocol):
    def get(self, chunk_ids: list[str]) -> list[Chunk]: ...
    def filter_rows(self, filters: Filters) -> list[int]: ...
```

The release ships `SqliteFtsStore`, `NumpyDenseStore`, and `SqliteChunkStore`. The migration to pgvector replaces the 3 stores behind the same interfaces. The new stores are `PgLexicalStore` (Postgres full-text search or `pg_trgm`), `PgVectorStore` (a `vector(384)` column with an HNSW index), and `PgChunkStore`. The migration procedure:

1. Create the `chunks` table in Postgres with the schema of chapter 9 plus a `embedding vector(384)` column.
2. Copy the rows from SQLite and the vectors from `vectors.npy` with 1 script, `scripts/migrate_to_pgvector.py`.
3. Build the HNSW index with `m = 16` and `ef_construction = 128`.
4. Point `config/keel.yaml` at the Postgres stores and restart.
5. Run the retrieval regression tests, which must give the same top 10 for the golden set within 1 rank.

### 17.3 Config-driven pipeline

```yaml
# config/keel.yaml
corpus:
  dir: corpus/edgar
  manifest: corpus/edgar/manifest.json
  date_filter: null                 # or {min: 2023-01-01, max: 2025-12-31}
parser:
  version: 1.0.0
  protected_names: config/protected_names.txt
  abbreviations: config/abbreviations.txt
  overrides: config/overrides.yaml
chunker:
  version: 1.0.0
  target_tokens: 400
  max_tokens: 480
  overlap_tokens: 50
embedding:
  model: BAAI/bge-small-en-v1.5
  revision: <hash>
  batch_size: 32
reranker:
  enabled: true
  model: cross-encoder/ms-marco-MiniLM-L-6-v2
  revision: <hash>
  top_n: 80
retrieval:
  lexical_k: 100
  dense_k: 100
  rrf_k: 60
  max_context_tokens: 32000
  max_chunks: 48
  simhash_max_distance: 3
  calibration_factor: 1.15
llm:
  provider: anthropic
  model: claude-sonnet-5-5-<snapshot>
  fallback_model: claude-haiku-5-5-<snapshot>
  temperature: 0
  max_output_tokens: 4000
  prompt_version: 1.0.0
  cache_system_block: true
limits:
  question_max_chars: 1000
  rate_per_minute: 10
  daily_budget_usd: 20
```

Environment variables override any key with the prefix `KEEL_`, for example `KEEL_LLM__MODEL`. Secrets never live in the file.

### 17.4 How to add filings, filing types, and corpora

| Change | Procedure |
| --- | --- |
| Add a filing of a known type | Copy the file into the corpus directory with the file name pattern, add the file to the manifest, run `keel index --incremental`. |
| Add a company | Add the ticker, the aliases, and the groups to `config/companies.yaml`, then add the filings. |
| Add an 8-K | Write `keel/parsers/form_8k.py` with the item scheme of the 8-K (Items 1.01 to 9.01). Map the items to `other` plus a new section `events`. Register the parser in `keel/parsers/__init__.py` by form code. |
| Add a DEF 14A proxy statement | Write a parser that detects sections by headings instead of items: compensation, governance, and proposals. Map the sections to `other` plus `governance`. |
| Add earnings call transcripts | Write a parser that splits by speaker turn and sets `section = transcript`. Store the speaker and the role in the metadata. The chunker keeps 1 speaker turn per chunk when possible. |
| Add a new corpus | Create a corpus config with its own directory and manifest. Build a separate index with its own version, and give the index a `corpus_id`. The service can load several indexes, and the Principal decides which indexes a request can search. |

### 17.5 Multi-tenant readiness

The Principal object (S-06) carries `tenant_id`, `allowed_tickers`, and `allowed_sources`. The retriever applies the Principal filters to every query. Production adds `tenant_id` to the tables, 1 dense index per tenant, and the isolation test of S-17. Private data of a tenant never shares an index with public data.

### 17.6 Repo layout

```
keel/
  README.md
  Makefile
  docker-compose.yml
  Dockerfile
  pyproject.toml
  uv.lock
  .env.example
  .github/workflows/ci.yml
  config/
    keel.yaml
    companies.yaml
    groups.yaml
    synonyms.yaml
    known_external.yaml
    fiscal_year_ends.yaml
    overrides.yaml
    protected_names.txt
    abbreviations.txt
    prices.yaml
  prompts/
    answer_system_v1.0.0.md
    answer_user_v1.0.0.md
    answer_schema_v1.0.0.json
    judge_v1.0.0.md
  keel/
    __init__.py
    cli.py                 # keel inventory, parse, chunk, index, understand, retrieve, ask, eval, serve, warm-cache, doctor, add, refresh, export, bootstrap
    config.py
    extractor.py
    inventory.py
    parsers/
      __init__.py
      base.py
      form_10k_10q.py
    sections.py
    tables.py
    chunker.py
    indexer.py
    stores/
      sqlite_fts.py
      numpy_dense.py
      chunk_store.py
    understanding.py
    retriever.py
    context.py
    prompt.py
    providers/
      base.py
      anthropic.py
      mock.py
    citations.py
    api/
      app.py
      routes.py
      sse.py
      auth.py
      ratelimit.py
    audit.py
    cache.py
    reliability.py         # breaker, retries, fallback
  web/
    index.html
    package.json
    package-lock.json
    vite.config.ts
    tsconfig.json
    playwright.config.ts
    eslint.config.js
    .prettierrc.cjs
    src/
      main.tsx
      App.tsx
      state.ts           # the 11 UI states as a union type, and the reducer
      api/               # client.ts (fetch and the SSE parser), types.ts
      components/        # 1 file per region of 14.5 and per banner of 14.6
      motion/presets.ts  # 1 export per moment of 14.8
      lib/markdown.ts    # marked and the DOMPurify allow list
      styles.css         # the Tailwind entry
    e2e/                 # the Playwright specs of 14.9
    dist/                # the build output, not committed
  eval/
    golden.yaml
    labels/
    run_eval.py
    judge.py
    report.md
  tests/
    fixtures/snippets/
    fixtures/mini_corpus/  # 3 small filings
    unit/
    integration/
    eval/
  docs/
    01_reader_map_and_executive_summary.md ... 29_engineering_standards.md
    adr/
    PROMPT_LOG.md
    EVALUATION.md
    RUNBOOK.md
  demo/
    answer_cache/
    static/
    recording.mp4
  scripts/
    migrate_to_pgvector.py
    label_helper.py
```

### 17.7 Module ownership

| Module | Owner | Reviewer |
| --- | --- | --- |
| `parsers`, `sections`, `tables`, `chunker` | Data engineer | AI engineer |
| `understanding`, `retriever`, `context` | AI engineer | Data engineer |
| `prompt`, `providers`, `citations`, `eval` | AI engineer | Domain analyst from the client |
| `api`, `web`, `reliability`, `audit` | Platform engineer | Security reviewer |
| `config`, `docs`, `adr` | Tech lead | All |

In the demo build, the consultant owns all modules. The table names the roles for the hand-off.

### 17.8 Types and lint rules

- `ruff` with the rule sets E, F, I, B, UP, and S (bandit), and a line length of 80 (chapter 29.1).
- `mypy --strict` on the `keel/` package. The `web/` and `scripts/` directories stay out of the check.
- `pydantic` models for every object that crosses a module boundary.
- A pre-commit config with `ruff`, `mypy`, and `gitleaks`.

### 17.9 Test pyramid

| Level | Scope | Count target | Runs |
| --- | --- | --- | --- |
| Unit | Parser rules from real snippets, section classification, fiscal math, alias resolution, time scope, fusion, quotas, budget, citation validation, cache keys | 60 or more | Every commit, under 30 seconds |
| Integration | A full build of the 3-file mini corpus, and lexical and dense retrieval on the mini index. The API with the mock provider, the SSE stream, the breaker, and the fallback | 15 or more | Every commit, under 3 minutes |
| Eval regression | The golden set on the full index, with recorded provider answers for the retrieval metrics. The live provider for the answer metrics on a tagged subset | 28 questions | Nightly, and on demand before a release |

### 17.10 CI workflow

The CI workflow is in chapter 29.5, and the starter kit ships it as `.github/workflows/ci.yml` with 9 jobs. The nightly eval is a separate workflow, `eval.yml`, with the `eval` environment that holds the provider key.

The `--gate` flag fails the job when a metric is below its regression gate (chapter 18). The full-corpus eval runs on a schedule, not on every push, because the full index is not in the repo.

### 17.11 Architecture decision records

Each decision in chapter 4 with reversibility Low or Medium gets 1 file in `docs/adr/`. The template holds the title, the status, the context, the decision, the alternatives, the consequences, and the date. The first 6 records are D-05, D-06, D-07, D-21, D-23, and D-08 (High reversibility, but the panel asks about it). A new decision adds a record before the code change merges.

### 17.12 Semantic versions for prompts and indexes

| Artifact | Version rule | Where recorded |
| --- | --- | --- |
| Prompt | Major for a schema change, minor for a rule change, patch for wording | The file name, the prompt hash, and the audit record |
| Index | Major for a chunk ID change, minor for added filings, patch for a rebuild | The manifest and the audit record |
| Golden set | Minor for added questions, major for changed expected sources | `eval/golden.yaml` |
| Compatibility | The manifest states the prompt versions that the index supports | `compatible_prompt_versions` |

The service refuses to start when the prompt version is outside the manifest range.

### 17.13 One-command setup

```
make demo          # creates .env from .env.example if absent, installs, builds the index if absent, starts the service
make index         # full build
make test          # ruff, mypy, pytest
make eval          # golden set run with a report
make warm-cache    # answer cache for the offline fallback
docker compose up  # the same as make demo inside a container, with the corpus and index as mounted volumes
```

The `docker-compose.yml` file mounts `corpus/` and `index/` as volumes. The 27-minute build runs once on the host, and the container starts in seconds.
