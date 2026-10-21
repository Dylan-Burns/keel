## 9. Chunking and indexing

Keel splits each canonical section into chunks of about 400 tokens and stores the chunks with 20 metadata fields in SQLite. Keel builds a lexical index with FTS5 and a dense index with bge-small in NumPy. The full build of the 78 MB corpus takes about 27 minutes on an 8-core laptop. The cost is $0, because every model runs locally.

### 9.1 Chunk strategy

| Parameter | Value | Reason |
| --- | --- | --- |
| Target size | 400 tokens | Holds 1 full risk factor or 1 MD&A paragraph group in most filings |
| Hard maximum | 480 tokens | Stays under the 512-token input of the embedding model with room for the prefix line |
| Overlap | 50 tokens | Keeps a sentence that straddles a boundary in both chunks |
| Tokenizer for sizes | The tokenizer of the embedding model | The 512-token input limit is the constraint that matters at index time |
| Boundary rule | A chunk never crosses a canonical section boundary | Section filters and citations stay exact |
| Table rule | A table block becomes its own chunk, with the caption repeated on each part | Numbers keep their title, labels, and units |
| Prefix line | Each chunk starts with 1 line that names the company, the form, the fiscal label, and the section title, with a pipe character between them | The lexical index and the embedding see the context of every chunk, and a citation chip can show it without a lookup |

The chunker applies this procedure to each section span.

1. Split the prose into sentences with the repaired boundaries from chapter 7.
2. Pack sentences into a chunk until the addition of the next sentence pushes the chunk past 400 tokens.
3. If 1 sentence alone exceeds 480 tokens, split the sentence at a semicolon or a comma and set `split_sentence=true`.
4. Start the next chunk with the last sentences of the previous chunk, up to 50 tokens.
5. Emit each table block as 1 or more chunks of at most 400 tokens with `is_table=true`. Never merge a table with prose.
6. Compute the chunk ID, the chunk hash, the token count, and the 64-bit SimHash over lowercase word 3-grams.
7. Copy the filing metadata, the section, the item label, the section confidence, `delta_only`, and `boilerplate_flag` onto the chunk.

The estimated chunk count is 35,000 to 40,000. The estimate assumes 78 MB of raw text, about 19 MB of XBRL blocks removed, and about 3% of excluded spans. It also assumes 4.2 characters per token and 12% overlap.

### 9.2 Metadata schema per chunk

```sql
CREATE TABLE filings (
  filing_id TEXT PRIMARY KEY,          -- AAPL_10Q_2022-12-31
  ticker TEXT NOT NULL,
  company TEXT NOT NULL,
  cik TEXT,
  form TEXT NOT NULL,                  -- 10-K or 10-Q
  fiscal_year INTEGER,
  fiscal_period TEXT,                  -- FY, Q1, Q2, Q3, unknown
  period_end_date TEXT NOT NULL,       -- ISO date
  filing_date TEXT NOT NULL,           -- ISO date
  fiscal_year_end_month INTEGER,
  source_url TEXT,
  url_trusted INTEGER NOT NULL DEFAULT 0,
  file_name TEXT NOT NULL,
  file_sha256 TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  chunker_version TEXT NOT NULL,
  xbrl_block_chars INTEGER,
  warnings TEXT                        -- JSON list
);

CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY,           -- AAPL_10Q_2022-12-31__risk_factors__0007
  filing_id TEXT NOT NULL REFERENCES filings(filing_id),
  ticker TEXT NOT NULL,
  company TEXT NOT NULL,
  cik TEXT,
  form TEXT NOT NULL,
  fiscal_year INTEGER,
  fiscal_period TEXT,
  period_end_date TEXT NOT NULL,
  filing_date TEXT NOT NULL,
  section TEXT NOT NULL,               -- canonical section
  item_label TEXT,                     -- raw label, for diagnostics
  section_confidence REAL,
  sequence INTEGER NOT NULL,
  text TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  is_table INTEGER NOT NULL DEFAULT 0,
  delta_only INTEGER NOT NULL DEFAULT 0,
  boilerplate_flag TEXT,
  source_url TEXT,
  chunk_hash TEXT NOT NULL,
  simhash INTEGER NOT NULL,
  vector_row INTEGER NOT NULL
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text, content='chunks', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

CREATE INDEX idx_chunks_filter ON chunks(ticker, form, period_end_date, section);

CREATE TABLE quarantine (
  file_name TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  evidence TEXT                        -- JSON
);
```

### 9.3 Lexical index

The lexical index is the FTS5 table `chunks_fts` with the BM25 score function. The retriever builds the query from the topic words of the question, not from the company names, because the company filter already restricts the rows. The retriever expands the topic words with `config/synonyms.yaml`.

```yaml
revenue: ["net sales", "total revenues", "net revenue", "revenues"]
growth: ["increase", "increased", "growth", "grew"]
outlook: ["expect", "anticipate", "guidance", "outlook", "future"]
risk: ["risk factors", "adversely affect", "could harm", "uncertainties"]
regulatory: ["regulation", "regulatory", "FDA", "approval", "compliance", "antitrust", "legislation"]
```

A multi-word term becomes a phrase query. The terms join with OR, and the retriever reads the top 100 rows per sub-query with the metadata filter as a SQL join on `chunks`.

### 9.4 Dense index

The dense index is 1 NumPy file of float32 unit vectors with 384 columns. Row `i` holds the vector of the chunk whose `vector_row` is `i`. The build writes 1 shard per filing into `index/current/vectors/{filing_id}.npy`, then concatenates the shards into `vectors.npy` and assigns `vector_row` in shard order. The embedding model is `BAAI/bge-small-en-v1.5` at a pinned revision hash from `config/keel.yaml`.

At question time, the retriever embeds the dense query with the model's query instruction `Represent this sentence for searching relevant passages:`. The retriever selects the candidate rows with the metadata filter in SQL and computes `scores = vectors[rows] @ query`. A scan of 40,000 rows takes a few milliseconds.

### 9.5 Index versions with checksums

```json
{
  "index_version": "1.0.0",
  "built_at": "2026-10-24T18:20:00Z",
  "corpus_sha256": "<sha256 of the sorted file hash list>",
  "parser_version": "1.0.0",
  "chunker_version": "1.0.0",
  "embedding_model": {"name": "BAAI/bge-small-en-v1.5", "revision": "<hash>", "dimensions": 384},
  "reranker_model": {"name": "cross-encoder/ms-marco-MiniLM-L-6-v2", "revision": "<hash>"},
  "counts": {"files": 246, "indexed": 245, "quarantined": 1, "chunks": 0, "table_chunks": 0},
  "files": {"chunks.sqlite": "<sha256>", "vectors.npy": "<sha256>"},
  "compatible_prompt_versions": ">=1.0.0,<2.0.0"
}
```

The index version uses semantic versions. A change to the parser or the chunker that changes chunk IDs increments the major version. A change that adds filings increments the minor version. A rebuild with no text change increments the patch version. The service verifies the 2 file checksums at start and refuses to serve an index with a mismatch (chapter 16).

### 9.6 Build time and cost estimate

| Stage | Estimate | Assumption |
| --- | --- | --- |
| Model downloads | 1 to 2 minutes | About 130 MB for the embedding model and 90 MB for the reranker (A-03) |
| Parse 246 files | 2 minutes | 0.5 seconds per file for regular expressions over lines up to 287,855 characters |
| Section detection and chunks | 2 minutes | Python over about 57 MB of clean text |
| SQLite rows and the FTS5 build | 1 minute | 40,000 rows |
| SimHash | 1 minute | Pure Python over word 3-grams |
| Embeddings | 21 minutes on a CPU | 38,000 chunks at 30 chunks per second with batches of 32 (A-03). About 6 minutes on Apple silicon with MPS. About 2 minutes on a CUDA GPU. |
| Total | About 27 minutes on a CPU | Within NFR-07 |
| Cost | $0 | Every model runs locally, and D-02 excludes index-time LLM calls |

Inside the 4-hour timebox, the embedding stage starts in the background at about minute 75 and ends before the retrieval work needs it (chapter 20). The lexical index is ready after the SQLite stage, so retrieval tests start with lexical results while the embeddings run.

### 9.7 Incremental rebuilds

1. Run the per-file hash comparison from chapter 7.
2. Parse, chunk, and embed only the new or changed files, and write their shards.
3. Delete the shards and the rows of removed files.
4. Concatenate the shards into a new `vectors.npy` and reassign `vector_row`.
5. Rebuild `chunks_fts` from the `chunks` table.
6. Write the manifest and rename the directory atomically.

An incremental build for 1 new 10-K takes about 2 minutes on a CPU, most of it in the embeddings for about 600 chunks.

### 9.8 Tests

| Test | Expected result |
| --- | --- |
| `test_chunk_size_limits` | Every chunk has 480 tokens or fewer, and 95% of prose chunks have 300 to 480 tokens |
| `test_no_section_crossing` | Every chunk has 1 section and 1 item label |
| `test_table_caption` | Every table chunk starts with `TABLE:` and holds the units when the source table had units |
| `test_overlap` | Consecutive prose chunks share 20 to 50 tokens |
| `test_deterministic_build` | 2 builds of the same mini corpus give identical chunk IDs, hashes, and manifest checksums |
| `test_manifest_checksums` | The sha256 of each index file equals the manifest value |
| `test_lexical_known_phrase` | A query with a phrase copied from a known chunk returns that chunk in the top 3 |
| `test_dense_self_retrieval` | A dense query with the text of a known chunk returns that chunk at rank 1 |
| `test_vector_rows` | `vectors.npy` has exactly as many rows as the `chunks` table |
