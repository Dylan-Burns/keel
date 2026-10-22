"""The debug routes: `keel understand` and `keel retrieve --summary`.

`POST /api/debug/understand` returns the question analysis of chapter 10
and `POST /api/debug/retrieve` the retrieval plan, the counts, the quota
fills, the context chunks, and the timings of chapter 11, for any token
holder. Neither calls the model (decision D-02): they reuse the
understanding step and the retriever that the server loaded, and the
retrieval runs under the pipeline's retrieval lock. Each request counts
against the caller's question rate limit, because a retrieval runs the
reranker on the CPU.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import fastapi
import pydantic

from keel import answer
from keel import errors
from keel import retriever
from keel import understanding
from keel.api import auth
from keel.api import routes
from keel.api import state

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/api/debug")


class DebugRequest(pydantic.BaseModel):
    """The body of the debug routes.

    Attributes:
        question: The question; the length checks of `/api/ask` apply.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    question: str


def _limit(
    request: fastapi.Request,
    services: state.Services,
    caller: auth.Principal,
) -> None:
    decision = services.limiter.check(routes.client_of(request, caller))
    if not decision.allowed:
        raise routes.http_error(
            429,
            "rate_limited",
            "too many requests; wait and try again",
            decision.retry_after,
        )


def _analyze(
    answerer: answer.Answerer, question: str
) -> understanding.QuestionAnalysis:
    try:
        return answerer.understander.analyze(question)
    except errors.QuestionInputError as error:
        raise routes.http_error(
            error.http_status, "invalid_question", str(error)
        ) from None


@router.post("/understand")
async def understand(
    body: DebugRequest,
    request: fastapi.Request,
    services: routes.Services,
    caller: routes.Caller,
) -> dict[str, Any]:
    """The question analysis, as `keel understand` prints it.

    Args:
        body: The question.
        request: The request, for the rate limit key.
        services: The shared services.
        caller: The Principal.

    Returns:
        The `QuestionAnalysis` as JSON.

    Raises:
        HTTPException: 400 or 413 for the input checks, 429 over the rate
            limit, 503 without an index.
    """
    routes.check_question(services, body.question)
    answerer = routes.require_answerer(services)
    _limit(request, services, caller)
    analysis = await asyncio.to_thread(_analyze, answerer, body.question)
    result: dict[str, Any] = analysis.model_dump(mode="json")
    return result


def retrieval_summary(result: retriever.RetrievalResult) -> dict[str, Any]:
    """The retrieval as `keel retrieve --summary` prints it, as JSON.

    Args:
        result: The retrieval.

    Returns:
        The sub-queries, the counts, the quota fills, the context with its
        chunks, the sections, the timings, the gaps, and the degraded
        notes.
    """
    built = result.context
    timings = result.timings
    return {
        "sub_queries": [
            {"label": s.label, "dense_text": s.dense_text, "terms": s.terms}
            for s in result.plan.sub_queries
        ],
        "candidates": result.candidates,
        "collapsed": result.collapsed,
        "after_collapse": result.candidates - result.collapsed,
        "reranked": result.reranked,
        "fills": [
            {
                "label": f.label,
                "taken": f.taken,
                "quota": f.quota,
                "candidates": f.candidates,
                "tokens": f.tokens,
            }
            for f in built.fills
        ],
        "context": {
            "chunks": len(built.chunks),
            "token_estimate": built.token_estimate,
            "max_tokens": built.budget.max_tokens,
            "max_chunks": built.budget.max_chunks,
            "dropped": built.dropped,
            "items": [
                {
                    "chunk_id": c.candidate.chunk_id,
                    "ticker": c.candidate.ticker,
                    "form": c.candidate.form,
                    "section": c.candidate.section,
                    "period_end_date": c.candidate.period_end_date,
                    "estimated_tokens": c.estimated_tokens,
                    "truncated": c.truncated,
                }
                for c in built.chunks
            ],
        },
        "sections": built.sections(),
        "timings_ms": {
            "lexical": timings.lexical_ms,
            "dense": timings.dense_ms,
            "rerank": timings.rerank_ms,
            "total": timings.total_ms,
        },
        "gaps": list(result.gaps),
        "degraded": list(result.degraded),
    }


def _retrieve(
    answerer: answer.Answerer, analysis: understanding.QuestionAnalysis
) -> retriever.RetrievalResult:
    with answerer.retrieval_lock:
        return answerer.retriever.retrieve(analysis)


@router.post("/retrieve")
async def retrieve(
    body: DebugRequest,
    request: fastapi.Request,
    services: routes.Services,
    caller: routes.Caller,
) -> dict[str, Any]:
    """The retrieval of a question without a model call.

    Args:
        body: The question.
        request: The request, for the rate limit key.
        services: The shared services.
        caller: The Principal.

    Returns:
        The question, its type and tickers, and `retrieval` (the summary
        of `retrieval_summary`); for an out-of-scope question
        `out_of_scope` is true with its reason and `retrieval` is None.

    Raises:
        HTTPException: 400 or 413 for the input checks, 429 over the rate
            limit, 503 without an index.
    """
    routes.check_question(services, body.question)
    answerer = routes.require_answerer(services)
    _limit(request, services, caller)
    analysis = await asyncio.to_thread(_analyze, answerer, body.question)
    head: dict[str, Any] = {
        "question": body.question,
        "primary_type": analysis.primary_type,
        "types": list(analysis.types),
        "tickers": list(analysis.tickers),
        "out_of_scope": analysis.out_of_scope,
        "out_of_scope_reason": analysis.out_of_scope_reason,
    }
    if analysis.out_of_scope:
        return {**head, "retrieval": None}
    result = await asyncio.to_thread(_retrieve, answerer, analysis)
    return {**head, "retrieval": retrieval_summary(result)}
