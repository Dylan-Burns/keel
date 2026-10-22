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

/**
 * The audit record of 1 answer (chapter 15 S-07, chapter 25.1). Stage 12
 * renders it in the trace drawer; until then the client only carries it.
 */
export interface AuditRecord {
  readonly model_requests: number;
  readonly [field: string]: unknown;
}

/**
 * The answer response: the JSON of `POST /api/ask` without streaming, of
 * `GET /api/results/{request_id}`, and the payload of the `final` event.
 */
export interface AskResponse {
  readonly request_id: string;
  readonly analysis: AnalysisSummary;
  readonly retrieval: RetrievalSummary;
  readonly answer: Answer;
  readonly citations_resolved: ResolvedCitation[];
  readonly meta: ResponseMeta;
  /** The audit record; the `final` event carries it from stage 12. */
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
}
