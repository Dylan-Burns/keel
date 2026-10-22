"""The `/api` routes of chapter 14.1.

`POST /api/ask` streams the events of chapter 14.3 or returns the JSON of
chapter 14.2. The read routes serve the readiness, the coverage, 1 chunk,
the examples, the index status, and a stored answer by request ID. With
`llm.provider: mock`, the header `X-Keel-Mock: <fault>` drives the states
of table 14.6 for the front-end tests; with any other provider the service
ignores it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import re
import sqlite3
from typing import Annotated
from typing import Any
import uuid

import fastapi
from fastapi import responses
import pydantic
import yaml

from keel import __version__ as keel_version
from keel import answer
from keel import citations
from keel import errors
from keel import understanding
from keel import users
from keel.api import auth
from keel.api import eval_page
from keel.api import sse
from keel.api import state
from keel.providers import mock

logger = logging.getLogger(__name__)

VERSION = keel_version
MAX_BODY_BYTES = 16 * 1024  # control S-04
MOCK_PACE_SECONDS = 0.05  # the pause between events of the mock provider
FAULT_HEADER = "x-keel-mock"
RATE_LIMITED_FAULT_WAIT = 3
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
UNTRUSTED_URL = "https://evil.example/filing.htm"
# The front-end fault names (web/e2e) and the mock provider fault each one
# drives; the API itself answers rate_limited, index_not_built, and
# stale_index.
PROVIDER_FAULTS = {
    "partial_coverage": "partial-coverage",
    "out_of_scope": "refusal",
    "script_injection": "script-injection",
}
API_FAULTS = frozenset({"rate_limited", "index_not_built", "stale_index"})
# The primary model fails its 3 requests and the fallback model answers.
FALLBACK_FAULT = "fallback_model"
EMPTY_ANALYSIS: dict[str, Any] = {
    "tickers": [],
    "primary_type": "unknown",
    "time_scope": {"kind": "none"},
}
EMPTY_RETRIEVAL: dict[str, Any] = {
    "chunks": [],
    "collapsed_near_duplicates": 0,
    "dropped_candidates": 0,
    "token_estimate": 0,
}

router = fastapi.APIRouter(prefix="/api")


class AskOptions(pydantic.BaseModel):
    """The options of an answer request (chapter 14.2).

    Attributes:
        stream: False returns JSON even when the client accepts SSE.
        max_context_tokens: A lower context budget, or None.
        max_chunks: A lower chunk budget, or None.
        use_cache: Serve the answer cache when it holds the question.
        model: Reserved; the service answers with the configured model.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    stream: bool = True
    max_context_tokens: int | None = pydantic.Field(default=None, ge=1)
    max_chunks: int | None = pydantic.Field(default=None, ge=1)
    use_cache: bool = True
    model: str | None = None


class AskRequest(pydantic.BaseModel):
    """The body of `POST /api/ask`.

    Attributes:
        question: The question; the length check runs after parsing, so a
            bad length gets HTTP 400 or 413, not 422.
        options: The options.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    question: str
    options: AskOptions = pydantic.Field(default_factory=AskOptions)


def error_body(
    code: str, message: str, retry_after: int | None = None
) -> dict[str, Any]:
    """The JSON error body of chapter 14.3.

    Args:
        code: The error code.
        message: The message; never a secret.
        retry_after: Seconds to wait, when known.

    Returns:
        The body.
    """
    body: dict[str, Any] = {"code": code, "message": message}
    if retry_after is not None:
        body["retry_after"] = retry_after
    return body


def http_error(
    status: int, code: str, message: str, retry_after: int | None = None
) -> fastapi.HTTPException:
    """An HTTP error with the body of chapter 14.3.

    Args:
        status: The HTTP status.
        code: The error code.
        message: The message.
        retry_after: Seconds to wait; also sent as `Retry-After`.

    Returns:
        The exception.
    """
    headers = None
    if retry_after is not None:
        headers = {"Retry-After": str(retry_after)}
    return fastapi.HTTPException(
        status_code=status,
        detail=error_body(code, message, retry_after),
        headers=headers,
    )


def get_services(request: fastapi.Request) -> state.Services:
    """The services of the app.

    Args:
        request: The request.

    Returns:
        The shared services.
    """
    services: state.Services = request.app.state.services
    return services


Services = Annotated["state.Services", fastapi.Depends(get_services)]


def require_principal(
    request: fastapi.Request, services: Services
) -> auth.Principal:
    """Check the bearer token (control S-06).

    Args:
        request: The request.
        services: The shared services.

    Returns:
        The Principal of the caller.

    Raises:
        HTTPException: 401 when the token is absent or wrong.
    """
    return auth.authenticate(
        services.settings, request.headers.get("authorization"), services.users
    )


Caller = Annotated[auth.Principal, fastapi.Depends(require_principal)]


def fault_of(request: fastapi.Request, services: Services) -> str | None:
    """The fault of the `X-Keel-Mock` header, only with the mock provider.

    Args:
        request: The request.
        services: The shared services.

    Returns:
        A front-end fault name or a mock provider fault name, else None.
    """
    if not services.is_mock:
        return None
    value = request.headers.get(FAULT_HEADER, "").strip()
    known = (
        value in PROVIDER_FAULTS
        or value in API_FAULTS
        or value in {"provider_unavailable", FALLBACK_FAULT}
        or value.partition(":")[0] in mock.FAULTS
    )
    if value and not known:
        logger.warning("ignoring the unknown X-Keel-Mock fault %r", value)
    return value if value and known else None


Fault = Annotated[str | None, fastapi.Depends(fault_of)]


def require_answerer(services: state.Services) -> answer.Answerer:
    """The pipeline, or HTTP 503 without a sound index (E-F-01, 16.7).

    Args:
        services: The shared services.

    Returns:
        The pipeline.

    Raises:
        HTTPException: 503 with the code `index_not_built`, or with
            `index_corrupt` when a checksum or a row count did not match.
    """
    if services.answerer is None:
        raise http_error(
            503,
            "index_not_built",
            "no index is loaded; run keel index, then restart keel serve",
        )
    if not services.index_verified:
        raise http_error(
            503,
            "index_corrupt",
            "the index failed its checks (a checksum, a row count, or a "
            "missing file); run keel index",
        )
    return services.answerer


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process runs.

    Returns:
        The status and the version.
    """
    return {"status": "ok", "version": VERSION}


@router.get("/ready")
async def ready(services: Services, fault: Fault) -> fastapi.Response:
    """Readiness: the index, the models, the provider key, the breaker.

    Args:
        services: The shared services.
        fault: The mock fault; `index_not_built` reports no index.

    Returns:
        `ready`, the index version, the checks, the breaker state as 1
        word, whether the daily budget stopped the model, and whether the
        answer cache exists; no amount and no model name. HTTP 503
        with `index_corrupt` when the index failed its checks (16.7); the
        other failed checks keep HTTP 200, so the front-end can show the
        matching banner.
    """
    answerer = services.answerer
    loaded = answerer is not None and fault != "index_not_built"
    models = False
    if answerer is not None:
        step = answerer.retriever
        reranker_ok = step.reranker is not None or not (
            services.settings.reranker.enabled
        )
        models = step.embedder is not None and reranker_ok
    checks = {
        "index_loaded": loaded,
        "index_verified": loaded and services.index_verified,
        "models_loaded": loaded and models,
        "provider_key": services.provider_key,
    }
    corrupt = loaded and not services.index_verified
    body: dict[str, Any] = {
        "ready": all(checks.values()),
        "index_version": answerer.index_version
        if loaded and answerer
        else None,
        "checks": checks,
        "index_corrupt": corrupt,
        "offline": services.settings.offline,
    }
    if answerer is not None:
        # Coarse values only: this route needs no token (S-06), so the
        # spend, the limits, and the model names stay on /api/status.
        body.update(
            breaker=answerer.breaker.snapshot().state,
            budget_stopped=await asyncio.to_thread(answerer.budget.exhausted),
            answer_cache=answerer.cache.directory.is_dir(),
        )
    return responses.JSONResponse(body, status_code=503 if corrupt else 200)


@router.get("/status")
async def service_status(services: Services, caller: Caller) -> dict[str, Any]:
    """The reliability details behind the token (chapters 16.3, 16.10).

    Args:
        services: The shared services.
        caller: The Principal.

    Returns:
        The breaker counters, the models, and the daily spend and budget.

    Raises:
        HTTPException: 503 when no index is loaded.
    """
    del caller
    answerer = require_answerer(services)
    limit = answerer.budget.limit_usd
    spent = await asyncio.to_thread(answerer.budget.spent)
    return {
        "breaker": answerer.breaker.snapshot().as_dict(),
        "model": answerer.model,
        "fallback_model": answerer.fallback.model
        if answerer.fallback
        else None,
        "budget": {
            "daily_usd": limit,
            "spent_usd": spent,
            "stopped": spent >= limit,
        },
        "offline": services.settings.offline,
    }


def _fiscal_label(year: int | None, period: str | None) -> str:
    """The fiscal label of the prefix line, as `context.Candidate` names it."""
    if year is None:
        return "unknown"
    if period in {None, "FY", "unknown"}:
        return f"FY{year}"
    return f"{period} FY{year}"


@router.get("/coverage")
async def coverage(services: Services, caller: Caller) -> dict[str, Any]:
    """The filings per ticker, with forms and fiscal periods, and quarantine.

    Args:
        services: The shared services.
        caller: The Principal.

    Returns:
        The companies, the filing count, and the quarantined files.

    Raises:
        HTTPException: 503 when no index is loaded.
    """
    del caller
    answerer = require_answerer(services)
    rows = answerer.retriever.conn.execute(
        "SELECT ticker, company, form, fiscal_year, fiscal_period "
        "FROM filings ORDER BY ticker, period_end_date, form"
    ).fetchall()
    companies: dict[str, dict[str, Any]] = {}
    for ticker, company, form, year, period in rows:
        entry = companies.setdefault(
            ticker,
            {"ticker": ticker, "company": company, "forms": [], "periods": []},
        )
        if form not in entry["forms"]:
            entry["forms"].append(form)
        label = _fiscal_label(year, period)
        if label not in entry["periods"]:
            entry["periods"].append(label)
    return {
        "companies": [
            {
                "ticker": c["ticker"],
                "company": c["company"],
                "forms": sorted(c["forms"]),
                "fiscal_periods": c["periods"],
            }
            for c in companies.values()
        ],
        "filing_count": len(rows),
        "quarantined": [
            {"ticker": q.ticker, "file_name": q.file_name, "reason": q.reason}
            for q in answerer.retriever.catalog.quarantined
        ],
    }


@router.get("/chunks/{chunk_id}")
async def chunk(
    chunk_id: str, services: Services, caller: Caller
) -> dict[str, Any]:
    """The full text and the metadata of 1 chunk for the citation panel.

    Args:
        chunk_id: The chunk ID.
        services: The shared services.
        caller: The Principal.

    Returns:
        The chunk fields of chapter 14.2, the section title, and the text.
        `sec_url` is None unless the filing URL is trusted (E-D-28).

    Raises:
        HTTPException: 404 for an unknown chunk ID.
        HTTPException: 503 when no index is loaded.
    """
    del caller
    answerer = require_answerer(services)
    row = answerer.retriever.conn.execute(
        "SELECT chunk_id, filing_id, ticker, company, form, fiscal_year, "
        "fiscal_period, period_end_date, filing_date, section, text "
        "FROM chunks WHERE chunk_id = ?",
        (chunk_id,),
    ).fetchone()
    if row is None:
        raise http_error(404, "not_found", "no chunk with this ID")
    (
        found_id,
        filing_id,
        ticker,
        company,
        form,
        year,
        period,
        period_end,
        filing_date,
        section,
        text,
    ) = row
    label = _fiscal_label(year, period)
    urls = answer.sec_urls(answerer.retriever.conn, [filing_id])
    return {
        "chunk_id": found_id,
        "ticker": ticker,
        "form": form,
        "fiscal_label": label,
        "period_end": period_end,
        "filing_date": filing_date,
        "section": section,
        "section_title": citations.SECTION_TITLES.get(section, section),
        "filing_name": f"{company} {form} {label}",
        "sec_url": urls.get(filing_id),
        "text": text,
    }


@router.get("/examples")
async def examples(services: Services, caller: Caller) -> dict[str, Any]:
    """The 3 example questions and the golden set questions.

    Args:
        services: The shared services.
        caller: The Principal.

    Returns:
        The examples, and the golden questions of `eval/golden.yaml` when
        the file exists (stage 10 writes it).
    """
    del caller
    return {
        "examples": list(services.settings.demo.example_questions),
        "golden": golden_questions(pathlib.Path("eval/golden.yaml")),
    }


def golden_questions(path: pathlib.Path) -> list[dict[str, Any]]:
    """Read the questions of the golden set, when it exists.

    Args:
        path: The golden set file.

    Returns:
        1 entry per question with its ID, or an empty list.
    """
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        logger.warning("golden set unreadable: %s", error)
        return []
    items = data.get("questions", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [
        {"id": item.get("id"), "question": item["question"]}
        for item in items
        if isinstance(item, dict) and isinstance(item.get("question"), str)
    ]


corpus_check = state.corpus_check


def _build_warnings(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT file_name, warnings FROM filings "
        "WHERE warnings IS NOT NULL AND warnings != '[]' ORDER BY file_name"
    ).fetchall()
    found: list[str] = []
    for file_name, raw in rows:
        try:
            names = json.loads(raw)
        except ValueError:
            names = [raw]
        found.extend(f"{file_name}: {name}" for name in names)
    return found


@router.get("/index/status")
async def index_status(
    services: Services, caller: Caller, fault: Fault
) -> dict[str, Any]:
    """The manifest, the corpus checksum match, and the build warnings.

    Args:
        services: The shared services.
        caller: The Principal.
        fault: The mock fault; `stale_index` reports a mismatch.

    Returns:
        The index version, the match, the warnings, and the manifest.
    """
    del caller
    answerer = services.answerer
    warnings: list[str] = []
    if services.index_error:
        warnings.append(services.index_error)
    if services.corpus_note:
        warnings.append(services.corpus_note)
    if answerer is not None:
        warnings.extend(_build_warnings(answerer.retriever.conn))
    match = services.corpus_match is not False and fault != "stale_index"
    manifest = services.manifest
    return {
        "index_version": answerer.index_version if answerer else None,
        "corpus_checksum_match": match,
        "warnings": warnings,
        "manifest": manifest.model_dump(mode="json") if manifest else None,
    }


@router.get("/eval")
async def eval_report(services: Services, caller: Caller) -> eval_page.EvalPage:
    """The eval page data (W-02): the report, the prompt log, the gates.

    The markdown goes out as text and the front-end renders it through the
    answer renderer and DOMPurify (chapter 15 allow list), read-only.

    Args:
        services: The shared services.
        caller: The Principal.

    Returns:
        Both documents (`markdown` is None for a missing file) and the
        regression gates read from the report.
    """
    del caller
    server = services.settings.server
    return await asyncio.to_thread(
        eval_page.load, server.eval_report, server.prompt_log
    )


@router.post("/feedback")
async def feedback(caller: Caller) -> responses.JSONResponse:
    """The feedback stub of phase 1 of the roadmap.

    Args:
        caller: The Principal.

    Returns:
        HTTP 501 in this release.
    """
    del caller
    return responses.JSONResponse(
        error_body("not_implemented", "feedback arrives in phase 1"),
        status_code=501,
    )


@router.get("/results/{request_id}")
async def result(
    request_id: str, services: Services, caller: Caller
) -> dict[str, Any]:
    """The stored answer of a request ID (E-F-04).

    Args:
        request_id: The request ID.
        services: The shared services.
        caller: The Principal.

    Returns:
        The answer of chapter 14.2 from the idempotency store (10 minutes)
        or the answer cache.

    Raises:
        HTTPException: 404 while the answer runs, and for an unknown ID.
    """
    del caller
    known, record = services.results.state(request_id)
    if record is not None:
        return record
    if known:
        raise http_error(404, "pending", "the answer is not complete yet")
    if services.answerer is not None and REQUEST_ID.match(request_id):
        cached = await asyncio.to_thread(
            services.answerer.cache.find, request_id
        )
        if cached is not None:
            return response_body(cached)
    raise http_error(404, "not_found", "no stored answer for this request")


def _placeholder_answer(record: dict[str, Any]) -> dict[str, Any]:
    """The answer object of a response with no model answer."""
    message = record.get("message") or "No model answer."
    refusal = None
    if record.get("outcome") == "out_of_scope":
        refusal = {"reason": message}
    return {
        "direct_answer": message,
        "company_findings": [],
        "comparison_table": None,
        "citations": [],
        "coverage": {
            "companies_used": [],
            "companies_missing": [],
            "data_as_of": "",
        },
        "gaps": [],
        "confidence": "low",
        "confidence_reason": message,
        "next_questions": [],
        "refusal": refusal,
    }


def _untrusted(retrieval: dict[str, Any]) -> dict[str, Any]:
    """The retrieval with a URL outside www.sec.gov (the injection drill)."""
    chunks = [{**c, "sec_url": UNTRUSTED_URL} for c in retrieval["chunks"]]
    return {**retrieval, "chunks": chunks}


def response_body(
    record: dict[str, Any], fault: str | None = None
) -> dict[str, Any]:
    """The response of chapter 14.2 from a pipeline record.

    A response without a model answer (out of scope, no context, offline,
    provider error, schema violation) gets an answer object that holds the
    message, with the refusal for an out-of-scope question, so every
    response has the same shape.

    Args:
        record: The `final` record of the pipeline.
        fault: The mock fault of the request.

    Returns:
        The response.
    """
    body = dict(record)
    body["analysis"] = record.get("analysis") or dict(EMPTY_ANALYSIS)
    body["retrieval"] = record.get("retrieval") or dict(EMPTY_RETRIEVAL)
    body["citations_resolved"] = record.get("citations_resolved") or []
    body["meta"] = record.get("meta") or {}
    if record.get("answer") is None:
        body["answer"] = _placeholder_answer(record)
    if fault == "script_injection":
        body["retrieval"] = _untrusted(body["retrieval"])
    return body


def wants_stream(request: fastapi.Request, options: AskOptions) -> bool:
    """True when the answer goes out as SSE (chapter 14.1).

    Args:
        request: The request.
        options: The options of the body.

    Returns:
        True when the client accepts `text/event-stream` and did not set
        `stream: false`.
    """
    accept = request.headers.get("accept", "")
    return options.stream and sse.MEDIA_TYPE in accept


async def read_body(request: fastapi.Request) -> AskRequest:
    """Read and parse the body of `POST /api/ask` (control S-04).

    Args:
        request: The request.

    Returns:
        The parsed request.

    Raises:
        HTTPException: 413 over 16 KB, 400 for a body that does not parse.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise http_error(413, "body_too_large", "the body is over 16 KB")
    raw = b""
    async for part in request.stream():
        raw += part
        if len(raw) > MAX_BODY_BYTES:
            raise http_error(413, "body_too_large", "the body is over 16 KB")
    try:
        return AskRequest.model_validate_json(raw)
    except pydantic.ValidationError as error:
        raise http_error(
            400,
            "invalid_request",
            "the body needs a question string and valid options "
            f"({error.error_count()} errors)",
        ) from error


def check_question(services: state.Services, question: str) -> None:
    """Run the length and language checks of chapter 10.7 (E-Q-10, E-Q-11).

    Args:
        services: The shared services.
        question: The question.

    Raises:
        HTTPException: 400 for an empty or non-English question, 413 for a
            question over the limit.
    """
    limits = services.settings.limits
    try:
        understanding.check_input(
            question, limits.question_min_chars, limits.question_max_chars
        )
    except errors.QuestionInputError as error:
        raise http_error(
            error.http_status, "invalid_question", str(error)
        ) from error


def request_id_of(request: fastapi.Request) -> str:
    """The request ID: the Idempotency-Key header, or a new server ID.

    Args:
        request: The request.

    Returns:
        The ID.

    Raises:
        HTTPException: 400 for a key outside `[A-Za-z0-9._:-]{1,128}`.
    """
    key = request.headers.get("idempotency-key")
    if key is None:
        return uuid.uuid4().hex
    if not REQUEST_ID.match(key):
        raise http_error(
            400,
            "invalid_idempotency_key",
            "use 1 to 128 of A-Z a-z 0-9 . _ : -",
        )
    return key


async def _no_wait(seconds: float) -> None:
    """The retry wait of a fault drill: the retries run, the waits do not."""
    del seconds
    await asyncio.sleep(0)


def answerer_for(
    services: state.Services, fault: str | None
) -> answer.Answerer:
    """The pipeline of 1 request, with the mock fault when there is one.

    Args:
        services: The shared services.
        fault: The fault of the request.

    Returns:
        The shared pipeline, or a copy over a mock provider with the fault.

    Raises:
        HTTPException: 503 when no index is loaded.
    """
    shared = require_answerer(services)
    if fault is None or fault in API_FAULTS:
        return shared
    llm = services.settings.llm
    down = f"500-before-content:{llm.max_retries + 1}"
    if fault == FALLBACK_FAULT:
        name, fallback_fault = down, "none"
    elif fault == "provider_unavailable":
        # Both models fail: the degraded mode (chapter 16.5).
        name = fallback_fault = down
    else:
        # A raw fault before content hits the fallback model too.
        name = fallback_fault = PROVIDER_FAULTS.get(fault, fault)
    provider = mock.MockProvider(llm.model, fault=name)
    fallback = mock.MockProvider(llm.fallback_model, fault=fallback_fault)
    return shared.with_provider(provider, sleep=_no_wait, fallback=fallback)


class _Outcome:
    """The final record and the error of 1 run; private and mutable."""

    def __init__(self) -> None:
        self.final: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None


async def run_answer(  # pylint: disable=too-many-arguments
    services: state.Services,
    answerer: answer.Answerer,
    body: AskRequest,
    request_id: str,
    *,
    fault: str | None,
    channel: sse.Channel | None,
    user: str | None = None,
) -> _Outcome:
    """Run the pipeline of 1 question and store its answer.

    Args:
        services: The shared services.
        answerer: The pipeline of the request.
        body: The request.
        request_id: The request ID.
        fault: The mock fault.
        channel: The SSE channel, or None for a JSON answer.
        user: The user who asks, for the audit record.

    Returns:
        The final record and the error event, when any.
    """
    outcome = _Outcome()
    paced = channel is not None and answerer.provider.name == "mock"
    pace = MOCK_PACE_SECONDS if paced else 0.0
    options = body.options
    try:
        async for event in answerer.ask(
            body.question,
            request_id=request_id,
            # A fault drill never serves the answer cache.
            use_cache=options.use_cache and fault is None,
            max_context_tokens=options.max_context_tokens,
            max_chunks=options.max_chunks,
            user=user,
        ):
            data = event.data
            if event.name == "retrieval" and fault == "script_injection":
                data = _untrusted(data)
            elif event.name == "final":
                data = response_body(data, fault)
                outcome.final = data
            elif event.name == "error" and outcome.error is None:
                outcome.error = data
            if channel is not None:
                channel.send(event.name, data)
                if pace:
                    await asyncio.sleep(pace)
    except Exception:  # pylint: disable=broad-exception-caught
        # The client must see an end; the log keeps the trace.
        logger.exception("the answer of %s failed", request_id)
        outcome.error = error_body("internal_error", "the answer failed")
        if channel is not None:
            channel.send("error", outcome.error)
            channel.send("done", {})
    finally:
        if outcome.final is not None:
            services.results.finish(request_id, outcome.final)
        else:
            services.results.drop(request_id)
        if channel is not None:
            channel.close()
    return outcome


def _replay(record: dict[str, Any], stream: bool) -> fastapi.Response:
    """The stored answer of a repeated Idempotency-Key."""
    if not stream:
        return responses.JSONResponse(record)
    meta = record.get("meta", {})
    channel = sse.Channel()
    channel.send(
        "meta",
        {
            "request_id": record.get("request_id"),
            "index_version": meta.get("index_version"),
            "prompt_version": meta.get("prompt_version"),
            "model": meta.get("model"),
        },
    )
    channel.send("final", record)
    channel.send("done", {})
    channel.close()
    return sse.response(channel)


def client_of(request: fastapi.Request, caller: auth.Principal) -> str:
    """The bucket key of the rate limit (control S-05).

    A named user has 1 bucket wherever they ask from, which also holds
    behind a proxy; the shared legacy token keeps 1 bucket per peer
    address.

    Args:
        request: The request.
        caller: The Principal.

    Returns:
        `user:<name>`, or the peer address (`unknown` without one).
    """
    if caller.user != users.LEGACY:
        return f"user:{caller.user.name}"
    return request.client.host if request.client else "unknown"


@router.post("/ask")
async def ask(
    request: fastapi.Request,
    services: Services,
    caller: Caller,
    fault: Fault,
) -> fastapi.Response:
    """Answer a question: SSE with `Accept: text/event-stream`, else JSON.

    Args:
        request: The request.
        services: The shared services.
        caller: The Principal.
        fault: The mock fault.

    Returns:
        The event stream or the response of chapter 14.2.

    Raises:
        HTTPException: 400 or 413 for the input checks, 409 for a key
            whose answer still runs, 429 over the rate limit, 503 without
            an index.
    """
    body = await read_body(request)
    check_question(services, body.question)
    if fault == "rate_limited":
        raise http_error(
            429,
            "rate_limited",
            "too many questions; wait and ask again",
            RATE_LIMITED_FAULT_WAIT,
        )
    request_id = request_id_of(request)
    stream = wants_stream(request, body.options)
    known, record = services.results.state(request_id)
    if record is not None:
        return _replay(record, stream)
    if known:
        raise http_error(
            409, "request_in_progress", "the answer of this key still runs"
        )
    answerer = answerer_for(services, fault)
    decision = services.limiter.check(client_of(request, caller))
    if not decision.allowed:
        raise http_error(
            429,
            "rate_limited",
            "too many questions; wait and ask again",
            decision.retry_after,
        )
    if not services.results.start(request_id):
        raise http_error(
            409, "request_in_progress", "the answer of this key still runs"
        )
    if not stream:
        outcome = await run_answer(
            services,
            answerer,
            body,
            request_id,
            fault=fault,
            channel=None,
            user=caller.user.name,
        )
        if outcome.final is None:
            raise http_error(500, "internal_error", "the answer failed")
        response = dict(outcome.final)
        if outcome.error is not None:
            response["error"] = outcome.error
        return responses.JSONResponse(response)
    channel = sse.Channel()
    services.keep(
        asyncio.create_task(
            run_answer(
                services,
                answerer,
                body,
                request_id,
                fault=fault,
                channel=channel,
                user=caller.user.name,
            )
        )
    )
    return sse.response(channel)
