/**
 * The wire types of the Keel API (chapter 14.2 and 14.3). Field names are
 * the snake_case names of the Python API, unchanged, so the pydantic models
 * of keel/api and these interfaces describe the same JSON.
 */

/** The options of an answer request (chapter 14.2). */
export interface AskOptions {
  readonly stream?: boolean;
  readonly max_context_tokens?: number;
  readonly max_chunks?: number;
  readonly use_cache?: boolean;
  readonly model?: string | null;
}

/** The body of `POST /api/ask`. The question holds 3 to 1000 characters. */
export interface AskRequest {
  readonly question: string;
  readonly options?: AskOptions;
}

/** One resolved company mention (keel.understanding.Entity). */
export interface Entity {
  readonly ticker: string;
  readonly company: string;
  readonly text: string;
  readonly rule: string;
  readonly fuzzy?: boolean;
  readonly score?: number | null;
}

/** The time scope of a question (keel.understanding.TimeScope). */
export interface TimeScope {
  readonly kind: string;
  readonly fiscal_year?: number | null;
  readonly fiscal_period?: string | null;
}

/**
 * The `QuestionAnalysis` summary: the `analysis` field of the response and
 * the payload of the `analysis` event. The 3 first fields are required; the
 * others are optional extras of keel.understanding.QuestionAnalysis.
 */
export interface AnalysisSummary {
  readonly tickers: string[];
  readonly primary_type: string;
  readonly time_scope: TimeScope;
  readonly entities?: Entity[];
  readonly groups?: string[];
  /** The saved comp sets the question names (chapter 27.2). */
  readonly comp_sets?: CompSetUse[];
  readonly unknown_entities?: string[];
  readonly suggested_tickers?: string[];
  readonly out_of_scope_reason?: string | null;
}

/** One retrieved chunk in the context (chapter 14.2 `retrieval.chunks`). */
export interface RetrievedChunk {
  readonly chunk_id: string;
  readonly ticker: string;
  readonly form: string;
  readonly fiscal_label: string;
  readonly section: string;
  readonly score: number;
  readonly filing_name: string;
  /** Null when the chunk URL is not trusted (`url_trusted = 0`). */
  readonly sec_url: string | null;
}

/** The retrieval summary: the `retrieval` field and the `retrieval` event. */
export interface RetrievalSummary {
  readonly chunks: RetrievedChunk[];
  readonly collapsed_near_duplicates: number;
  readonly dropped_candidates: number;
  readonly token_estimate: number;
}

/** One finding of a company (chapter 12.4). */
export interface Finding {
  readonly point: string;
  readonly citations: string[];
  /** Set by the validator when the finding has 0 valid citations (12.9). */
  readonly unverified?: boolean;
}

/** The findings of 1 company: the payload of the `findings` event. */
export interface CompanyFindings {
  readonly ticker: string;
  readonly company: string;
  readonly findings: Finding[];
}

/** The comparison table of a multi-company or multi-period answer. */
export interface ComparisonTable {
  readonly columns: string[];
  readonly rows: string[][];
}

/** One citation as the model writes it (chapter 12.4). */
export interface Citation {
  readonly chunk_id: string;
  readonly claim: string;
  readonly quote: string;
}

/** The forms and fiscal periods used for 1 company. */
export interface CompanyCoverage {
  readonly ticker: string;
  readonly forms: string[];
  readonly fiscal_periods: string[];
}

/** The coverage statement of an answer. */
export interface AnswerCoverage {
  readonly companies_used: CompanyCoverage[];
  readonly companies_missing: string[];
  readonly data_as_of: string;
}

/** The refusal of an out-of-scope answer. */
export interface Refusal {
  readonly reason: string;
}

/** The answer object of the model, after validation (chapter 12.4). */
export interface Answer {
  readonly direct_answer: string;
  readonly company_findings: CompanyFindings[];
  readonly comparison_table: ComparisonTable | null;
  readonly citations: Citation[];
  readonly coverage: AnswerCoverage;
  readonly gaps: string[];
  readonly confidence: 'high' | 'medium' | 'low';
  readonly confidence_reason: string;
  readonly next_questions: string[];
  readonly refusal: Refusal | null;
}

/** Where a cited chunk sits in its filing (`keel/locations.py`). */
export interface ChunkLocation {
  /** Such as `Part I, Item 1A. Risk Factors`. */
  readonly section_label: string;
  /** The item heading, such as `Risk Factors`. */
  readonly heading: string;
  /** The raw item label, such as `Item 1A` or `Part II Item 1A`. */
  readonly item_label: string | null;
  /** The 1-based position of the chunk within its item. */
  readonly passage: number;
  /** The chunks of the item. */
  readonly passages: number;
  readonly is_table: boolean;
  /** The table title, the deep link anchor of a table passage. */
  readonly anchor?: string | null;
  readonly filing_date: string;
  /** Such as `0000320193-25-000079`, or null. */
  readonly accession: string | null;
}

/** A citation with the server-side metadata (chapter 12.9 step 6). */
export interface ResolvedCitation {
  readonly chunk_id: string;
  readonly filing_name: string;
  readonly section_title: string;
  readonly fiscal_label: string;
  readonly sec_url: string | null;
  readonly valid: boolean;
  /** Validator flags such as `quote_mismatch` (chapter 12.5). */
  readonly flags?: string[];
  /** The company ticker of the cited chunk or fact. */
  readonly ticker?: string;
  /** `chunk` for a filing chunk, `fact` for an XBRL company fact. */
  readonly kind?: 'chunk' | 'fact';
  /** The quote of the citation, verbatim from the chunk. */
  readonly quote?: string;
  readonly filing_date?: string;
  /** The place in the filing; null for a fact or an unknown chunk. */
  readonly location?: ChunkLocation | null;
}

/** The latency breakdown in milliseconds. */
export interface LatencyMs {
  readonly understanding?: number;
  readonly retrieval?: number;
  readonly rerank?: number;
  readonly first_token?: number;
  readonly total: number;
}

/** The token usage of the 1 model request. */
export interface Usage {
  readonly input_tokens: number;
  readonly cached_input_tokens: number;
  readonly output_tokens: number;
}

/** The flags of the response meta. */
export interface ResponseFlags {
  readonly citation_drift: number;
  readonly injection_suspect: boolean;
}

/** The `meta` field of the response (chapter 14.2). */
export interface ResponseMeta {
  readonly model: string;
  readonly prompt_version: string;
  readonly index_version: string;
  readonly prompt_hash: string;
  readonly latency_ms: LatencyMs;
  readonly usage: Usage;
  readonly cost_usd: number;
  readonly degraded: boolean;
  readonly from_cache: boolean;
  readonly flags: ResponseFlags;
}

/** The metadata filter of 1 sub-query in the audit record (chapter 11.2). */
export interface AuditFilter {
  readonly label: string;
  readonly tickers: string[];
  readonly sections: string[];
  /** The number of filings the filter names (0 for no filing filter). */
  readonly filings: number;
  /** [ticker, start, end] period end windows. */
  readonly windows: string[][];
}

/** The candidates of 1 company before and after the near-duplicate collapse. */
export interface AuditCompanyCandidates {
  readonly ticker: string;
  readonly before: number;
  readonly after: number;
}

/** The candidate counts of the retrieval in the audit record. */
export interface AuditCandidates {
  readonly gathered: number;
  readonly collapsed: number;
  readonly reranked: number;
  readonly per_company: AuditCompanyCandidates[];
}

/** How 1 quota group filled, such as `JPM: 11 of 16`. */
export interface AuditQuotaFill {
  readonly label: string;
  readonly taken: number;
  readonly quota: number;
  readonly candidates: number;
  readonly tokens: number;
}

/** The flags of the audit record. */
export interface AuditFlags {
  readonly injection_suspect?: boolean;
  readonly schema_violation?: boolean;
  readonly confidence_lowered?: boolean;
  readonly degraded?: boolean;
  readonly from_cache?: boolean;
}

/**
 * The audit record of 1 answer (chapter 15 S-07, chapter 25.1): the line of
 * `logs/audit.jsonl` that the `final` event carries, rendered by the trace
 * drawer. Every field but `model_requests` is optional, so an older record
 * or a record of another stage still renders; the facts fields arrive with
 * the company facts of chapter 26.1.
 */
export interface AuditRecord {
  readonly model_requests: number;
  /** The requests that failed before any content and were retried (D-04). */
  readonly failed_before_content?: number;
  readonly request_id?: string;
  readonly tickers?: string[];
  readonly question_type?: string | null;
  readonly time_scope?: string | null;
  readonly filters?: AuditFilter[];
  readonly candidates?: AuditCandidates | null;
  readonly quota_fills?: AuditQuotaFill[];
  readonly chunk_count?: number;
  readonly token_estimate?: number;
  readonly prompt_hash?: string;
  readonly prompt_version?: string;
  readonly index_version?: string;
  readonly model?: string;
  readonly usage?: Partial<Usage> & {readonly cache_write_tokens?: number};
  readonly cost_usd?: number;
  readonly latency_ms?: Partial<LatencyMs> | null;
  readonly citation_drift?: number;
  readonly inline_drift?: number;
  readonly unverified?: number;
  readonly flags?: AuditFlags;
  readonly outcome?: string;
  readonly error?: string | null;
  /** The facts lines of the prompt (chapter 26.1), when present. */
  readonly facts_lines?: number;
  /** Where the facts came from, such as `cache` or `live`. */
  readonly facts_source?: string | null;
  /** The fact IDs of the facts block. */
  readonly fact_ids?: string[];
}

/**
 * The answer response: the JSON of `POST /api/ask` without streaming, of
 * `GET /api/results/{request_id}`, and the payload of the `final` event.
 */
export interface AskResponse {
  readonly request_id: string;
  /** The question of the stored record; a shareable link renders it. */
  readonly question?: string | null;
  readonly analysis: AnalysisSummary;
  readonly retrieval: RetrievalSummary;
  readonly answer: Answer;
  readonly citations_resolved: ResolvedCitation[];
  readonly meta: ResponseMeta;
  /** The audit record of the answer, rendered by the trace drawer (W-01). */
  readonly audit?: AuditRecord | null;
}

/** The payload of the `meta` event. */
export interface MetaEvent {
  readonly request_id: string;
  readonly index_version: string;
  readonly prompt_version: string;
  readonly model: string;
}

/** The payload of the `answer_delta` event: new characters of the answer. */
export interface AnswerDeltaEvent {
  readonly text: string;
}

/** The payload of the `error` event and of an HTTP error body. */
export interface ErrorEvent {
  readonly code: string;
  readonly message: string;
  readonly retry_after?: number | null;
}

/** One parsed server-sent event, discriminated by the event name. */
export type SseEvent =
  | {readonly event: 'meta'; readonly data: MetaEvent}
  | {readonly event: 'analysis'; readonly data: AnalysisSummary}
  | {readonly event: 'retrieval'; readonly data: RetrievalSummary}
  | {readonly event: 'answer_delta'; readonly data: AnswerDeltaEvent}
  | {readonly event: 'findings'; readonly data: CompanyFindings}
  | {readonly event: 'final'; readonly data: AskResponse}
  | {readonly event: 'error'; readonly data: ErrorEvent}
  | {readonly event: 'done'; readonly data: null};

/** The names of the server-sent events of chapter 14.3. */
export type SseEventName = SseEvent['event'];

/** `GET /api/health`. */
export interface HealthResponse {
  readonly status: string;
  readonly version: string;
}

/** The checks of `GET /api/ready`. */
export interface ReadyChecks {
  readonly index_loaded: boolean;
  readonly provider_key: boolean;
  readonly index_verified?: boolean;
  readonly models_loaded?: boolean;
}

/** `GET /api/ready`. */
export interface ReadyResponse {
  readonly ready: boolean;
  readonly index_version: string | null;
  readonly checks: ReadyChecks;
}

/** `GET /api/index/status`. */
export interface IndexStatusResponse {
  readonly index_version: string | null;
  readonly corpus_checksum_match: boolean;
  readonly warnings: string[];
  readonly manifest?: unknown;
}

/** The filings of 1 company in `GET /api/coverage`. */
export interface CoverageCompany {
  readonly ticker: string;
  readonly company: string;
  readonly forms: string[];
  readonly fiscal_periods: string[];
}

/** 1 quarantined filing in `GET /api/coverage`. */
export interface QuarantinedFiling {
  readonly ticker: string;
  readonly file_name: string;
  readonly reason: string;
}

/** `GET /api/coverage`. */
export interface CoverageResponse {
  readonly companies: CoverageCompany[];
  readonly filing_count: number;
  readonly quarantined: QuarantinedFiling[];
}

/** `GET /api/chunks/{chunk_id}`. */
export interface ChunkResponse {
  readonly chunk_id: string;
  readonly ticker: string;
  readonly form: string;
  readonly fiscal_label: string;
  readonly section: string;
  readonly section_title: string;
  readonly filing_name: string;
  readonly sec_url: string | null;
  readonly text: string;
  /** The place in the filing, when the server reports it. */
  readonly location?: ChunkLocation | null;
}

/** The filing of the reader header. */
export interface ReaderFiling {
  readonly filing_id: string;
  readonly ticker: string;
  readonly company: string;
  readonly form: string;
  readonly fiscal_label: string;
  readonly period_end: string;
  readonly filing_date: string;
  readonly filing_name: string;
  readonly sec_url: string | null;
}

/** 1 chunk of the filing reader; the overlap with its neighbour is cut. */
export interface ReaderPassage {
  readonly chunk_id: string;
  readonly sequence: number;
  readonly is_table: boolean;
  readonly text: string;
  readonly cited: boolean;
}

/** `GET /api/chunks/{id}/context`: the cited chunk in its section. */
export interface ChunkContext {
  readonly chunk_id: string;
  readonly filing: ReaderFiling;
  readonly location: ChunkLocation | null;
  readonly passages: ReaderPassage[];
}

/** 1 markdown file of the eval page (`markdown` is null when absent). */
export interface EvalDocument {
  readonly source: string;
  readonly markdown: string | null;
  readonly truncated: boolean;
}

/** 1 regression gate of chapter 18.8, read from the eval report. */
export interface EvalGate {
  readonly name: string;
  readonly comparator: '>=' | '<=' | '>' | '<';
  readonly threshold: number;
  readonly threshold_text: string;
  readonly value: number | null;
  readonly value_text: string;
  readonly status: string | null;
  /** Whether the value meets the gate; null while the value is pending. */
  readonly passed: boolean | null;
}

/** `GET /api/eval` (chapter 25.2). */
export interface EvalResponse {
  readonly report: EvalDocument;
  readonly prompt_log: EvalDocument;
  readonly gates: EvalGate[];
}

/** 1 question of `GET /api/history` (chapter 27.2). */
export interface HistoryItem {
  readonly request_id: string;
  readonly timestamp: string;
  readonly question: string;
  /** The user who asked; null for a record from before the users file. */
  readonly user: string | null;
  readonly tickers: string[];
  readonly outcome: string | null;
  readonly model: string | null;
  readonly cost_usd: number;
  readonly from_cache: boolean;
  readonly degraded: boolean;
  /** True when the link `/a/{request_id}` can still open the answer. */
  readonly stored: boolean;
}

/** Whose questions the history lists: the caller's, or every user's. */
export type HistoryScope = 'own' | 'all';

/** `GET /api/history`: the questions of the caller, newest first. */
export interface HistoryResponse {
  readonly user: string;
  readonly role: string;
  readonly scope: HistoryScope;
  readonly items: HistoryItem[];
}

/** 1 comp set that a question names (the `comp_sets` of the analysis). */
export interface CompSetUse {
  readonly name: string;
  /** The text of the question that named the set. */
  readonly text: string;
  readonly tickers: string[];
  /** The tickers of the set without an indexed filing. */
  readonly missing: string[];
}

/** 1 saved comp set of `GET /api/compsets` (chapter 27.2). */
export interface CompSetItem {
  /** The name a question uses as `my <name> comps`. */
  readonly name: string;
  readonly tickers: string[];
  readonly owner: string | null;
  readonly updated_at: string;
  /** The tickers outside the index; `keel add` adds them (chapter 26). */
  readonly missing: string[];
  /** True when the caller may replace or delete the set. */
  readonly editable: boolean;
}

/** `GET /api/compsets`: the saved comp sets in name order. */
export interface CompSetList {
  readonly items: CompSetItem[];
}

/** 1 question template of `GET /api/templates` (chapter 27.2). */
export interface QuestionTemplate {
  readonly id: string;
  readonly label: string;
  /** The question with the `{companies}` and `{period}` placeholders. */
  readonly text: string;
  readonly default_period: string;
}

/** `GET /api/templates`: the templates in file order. */
export interface TemplateList {
  readonly items: QuestionTemplate[];
}

/** A thumbs vote on an answer. */
export type Vote = 'up' | 'down';

/** `POST /api/feedback`: the stored vote. */
export interface FeedbackSaved {
  readonly request_id: string;
  readonly vote: Vote;
  readonly note: string | null;
  readonly user: string;
}

// The admin, watch list, and debug routes (docs/API_ADMIN.md).

/** The kinds of admin job, each the twin of a CLI command. */
export type JobKind =
  | 'add'
  | 'refresh'
  | 'warm_cache'
  | 'eval'
  | 'facts'
  | 'backup'
  | 'restore'
  | 'index';

/** The status of a job. */
export type JobStatus =
  'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

/** The progress of a job: steps done and the total when known. */
export interface JobProgress {
  readonly done: number;
  readonly total: number | null;
}

/** A job record; `log` is present on the detail and the submit response. */
export interface Job {
  readonly id: string;
  readonly kind: JobKind;
  readonly params: Readonly<Record<string, unknown>>;
  readonly requested_by: string;
  readonly heavy: boolean;
  readonly status: JobStatus;
  /** Absent on a record created before its first progress report. */
  readonly progress?: JobProgress;
  readonly phase: string;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly finished_at: string | null;
  readonly result: Readonly<Record<string, unknown>> | null;
  readonly error: string | null;
  readonly log?: readonly string[];
}

/** `GET /api/admin/jobs`. */
export interface JobList {
  readonly items: readonly Job[];
  readonly active: Job | null;
}

/** The cost estimate of a job that calls the model. */
export interface CostEstimate {
  readonly kind: 'eval' | 'warm_cache';
  readonly questions: number;
  readonly model_requests: number;
  readonly judge_requests: number;
  readonly answer_usd: number;
  readonly judge_usd: number;
  readonly usd: number;
  readonly basis: 'audit' | 'prices';
  readonly confirm: string | null;
}

/** `POST /api/admin/jobs` HTTP 202. */
export interface JobSubmitted {
  readonly job: Job;
  readonly warnings: readonly string[];
  readonly estimate: CostEstimate | null;
}

/** The body of `POST /api/admin/jobs`. */
export interface JobRequest {
  readonly kind: JobKind;
  readonly params?: Readonly<Record<string, unknown>>;
  readonly confirm?: string;
}

/** A user role. */
export type Role = 'analyst' | 'partner' | 'admin';

/** A user of the users file; never a token or a hash. */
export interface UserItem {
  readonly name: string;
  readonly role: Role;
}

/** `GET /api/admin/users`. */
export interface UserList {
  readonly items: readonly UserItem[];
  readonly legacy_enabled: boolean;
}

/** `POST /api/admin/users` HTTP 201: the only response with the token. */
export interface UserCreated extends UserItem {
  readonly token: string;
}

/** 1 check of `keel doctor`. */
export interface DoctorCheck {
  readonly name: string;
  readonly status: 'ok' | 'warn' | 'fail';
  readonly detail: string;
}

/** The `keel inventory` counts, or an error. */
export interface InventorySummary {
  readonly error?: string;
  readonly corpus_dir?: string;
  readonly file_count?: number;
  readonly total_bytes?: number;
  readonly ticker_count?: number;
  readonly form_counts?: Readonly<Record<string, number>>;
  readonly first_filing?: string | null;
  readonly last_filing?: string | null;
  readonly manifest_present?: boolean;
  readonly discrepancy_count?: number;
  readonly discrepancies?: readonly string[];
}

/** The index build in service. */
export interface IndexSummary {
  readonly loaded: boolean;
  readonly index_version: string | null;
  readonly build_id: string | null;
  readonly verified: boolean | null;
  readonly error: string | null;
  readonly corpus_checksum_match: boolean | null;
  readonly corpus_note: string | null;
  readonly built_at: string | null;
  readonly counts: Readonly<Record<string, number>> | null;
  readonly filings: number | null;
  readonly quarantined: number | null;
}

/** A backup archive. */
export interface BackupItem {
  readonly name: string;
  readonly size_bytes: number;
  readonly created_at: string;
  readonly sha256: string | null;
}

/** `GET /api/admin/backups`. */
export interface BackupList {
  readonly directory: string;
  readonly items: readonly BackupItem[];
}

/** The in-app scheduler. */
export interface SchedulerSummary {
  readonly enabled: boolean;
  readonly running: boolean;
  readonly refresh_at: string;
  readonly backup_at: string;
  readonly backup_keep: number;
  readonly backup_bucket_set: boolean;
  readonly jobs: readonly {readonly name: string; readonly next_run: string}[];
}

/** The daily budget. */
export interface BudgetSummary {
  readonly daily_usd: number;
  readonly spent_usd: number;
  readonly stopped: boolean;
}

/** `GET /api/admin/system`. */
export interface SystemResponse {
  readonly version: string;
  readonly offline: boolean;
  readonly provider: string;
  readonly model: string;
  readonly doctor: readonly DoctorCheck[];
  readonly doctor_failed: boolean;
  readonly inventory: InventorySummary;
  readonly index: IndexSummary;
  readonly backups: BackupList;
  readonly scheduler: SchedulerSummary;
  readonly budget: BudgetSummary | null;
  readonly active_job: Job | null;
  readonly bootstrap: Readonly<Record<string, unknown>> | null;
}

/** 1 row of the admin audit. */
export interface AuditItem {
  readonly at: string;
  readonly user: string;
  readonly action: string;
  readonly target: string | null;
  readonly params: Readonly<Record<string, unknown>> | null;
  readonly outcome: string;
}

/** `GET /api/admin/audit`. */
export interface AuditList {
  readonly items: readonly AuditItem[];
}

/** 1 watch list row. */
export interface WatchItem {
  readonly ticker: string;
  readonly user: string | null;
  readonly added_date: string;
  readonly mine: boolean;
}

/** `GET /api/watch`. */
export interface WatchList {
  readonly items: readonly WatchItem[];
  readonly tickers: readonly string[];
}

/** `POST /api/watch`. */
export interface WatchAdded {
  readonly user: string;
  readonly added: readonly string[];
  readonly unchanged: readonly string[];
}

/** A resolved company of `POST /api/debug/understand`. */
export interface DebugEntity {
  readonly ticker: string;
  readonly company: string;
  readonly text: string;
  readonly rule: string;
  readonly fuzzy: boolean;
  readonly score: number | null;
}

/** The time scope of the question analysis. */
export interface DebugTimeScope {
  readonly kind: string;
  readonly scopes: readonly unknown[];
  readonly fiscal_year: number | null;
  readonly fiscal_period: string | null;
}

/** `POST /api/debug/understand`: the `QuestionAnalysis` as JSON. */
export interface DebugUnderstand {
  readonly question: string;
  readonly tickers: readonly string[];
  readonly entities: readonly DebugEntity[];
  readonly groups: readonly unknown[];
  readonly unknown_entities: readonly unknown[];
  readonly not_indexed: readonly unknown[];
  readonly time_scope: DebugTimeScope;
  readonly primary_type: string;
  readonly types: readonly string[];
  readonly topic_terms: readonly string[];
  readonly section_weights: Readonly<Record<string, number>>;
  readonly flags: Readonly<Record<string, boolean>>;
  readonly out_of_scope_reason: string | null;
  readonly suggested_tickers: readonly string[];
  readonly elapsed_ms: number;
  readonly comp_sets: readonly unknown[];
}

/** 1 sub-query of the retrieval plan. */
export interface DebugSubQuery {
  readonly label: string;
  readonly dense_text: string;
  readonly terms: readonly string[];
}

/** The quota fill of 1 sub-query. */
export interface DebugFill {
  readonly label: string;
  readonly taken: number;
  readonly quota: number;
  readonly candidates: number;
  readonly tokens: number;
}

/** 1 chunk of the built context. */
export interface DebugContextItem {
  readonly chunk_id: string;
  readonly ticker: string;
  readonly form: string;
  readonly section: string;
  readonly period_end_date: string | null;
  readonly estimated_tokens: number;
  readonly truncated: boolean;
  /** The rerank score; older servers leave it out. */
  readonly score?: number;
}

/** The summary of `keel retrieve --summary`. */
export interface DebugRetrieval {
  readonly sub_queries: readonly DebugSubQuery[];
  readonly candidates: number;
  readonly collapsed: number;
  readonly after_collapse: number;
  readonly reranked: number;
  readonly fills: readonly DebugFill[];
  readonly context: {
    readonly chunks: number;
    readonly token_estimate: number;
    readonly max_tokens: number;
    readonly max_chunks: number;
    readonly dropped: number;
    readonly items: readonly DebugContextItem[];
  };
  readonly sections: Readonly<Record<string, number>>;
  readonly timings_ms: Readonly<Record<string, number>>;
  readonly gaps: readonly string[];
  readonly degraded: readonly string[];
}

/** `POST /api/debug/retrieve`. */
export interface DebugRetrieve {
  readonly question: string;
  readonly primary_type: string;
  readonly types: readonly string[];
  readonly tickers: readonly string[];
  readonly out_of_scope: boolean;
  readonly out_of_scope_reason: string | null;
  readonly retrieval: DebugRetrieval | null;
}

/** The parameters of a cost preview. */
export type CostQuery =
  | {
      readonly kind: 'eval';
      readonly answers: boolean;
      readonly judge: boolean;
      readonly subset: string | null;
    }
  | {
      readonly kind: 'warm_cache';
      readonly refresh: boolean;
      readonly facts_only: boolean;
    };
