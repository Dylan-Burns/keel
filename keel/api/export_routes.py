"""The memo export route of chapter 27.2: `GET /api/export/{request_id}`.

The route finds the stored answer of a request ID in the result store (10
minutes), then in the answer cache through the audit record, and returns
the memo as a Markdown or DOCX download. It sits behind the bearer token
like every read route.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from typing import Any

import fastapi

from keel import export
from keel.api import routes

logger = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix="/api")
FORMAT_NAMES = {
    "md": export.MARKDOWN,
    "markdown": export.MARKDOWN,
    "docx": export.DOCX,
}


@router.get("/export/{request_id}")
async def export_memo(
    request_id: str,
    services: routes.Services,
    caller: routes.Caller,
    memo_format: Annotated[str, fastapi.Query(alias="format")] = "md",
) -> fastapi.Response:
    """The memo of a stored answer as a file download.

    Args:
        request_id: The request ID.
        services: The shared services.
        caller: The Principal.
        memo_format: `md` (the default) or `docx`.

    Returns:
        The memo with its media type and an attachment file name.

    Raises:
        HTTPException: 400 for an unknown format, 404 when no stored answer
            holds the request ID or the answer is still running, and 501
            when python-docx is not installed.
    """
    del caller
    fmt = FORMAT_NAMES.get(memo_format.lower())
    if fmt is None:
        raise routes.http_error(400, "bad_format", "the format is md or docx")
    if not export.REQUEST_ID.match(request_id):
        raise routes.http_error(404, "not_found", "no stored answer")
    known, record = services.results.state(request_id)
    if known and record is None:
        raise routes.http_error(404, "pending", "the answer is not complete")
    try:
        if record is None:
            record = await asyncio.to_thread(
                export.find_record, services.settings, request_id
            )
        memo = export.build_memo(record, request_id)
    except export.ExportError as error:
        logger.info("no memo for %s: %s", request_id, error)
        raise routes.http_error(
            404, "not_found", "no stored answer for this request"
        ) from None
    try:
        data = await asyncio.to_thread(export.render, memo, fmt)
    except export.ExportError as error:
        raise routes.http_error(501, "export_unavailable", str(error)) from None
    name = export.file_name(request_id, fmt)
    headers: dict[str, Any] = {
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store",
    }
    return fastapi.Response(
        content=data, media_type=export.MEDIA_TYPES[fmt], headers=headers
    )
