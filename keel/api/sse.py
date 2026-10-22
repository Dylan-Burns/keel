"""Server-sent events for `POST /api/ask` (chapter 14.3, docs/GOTCHAS.md).

The pipeline runs in its own task and puts each event into a `Channel`.
The response reads the channel: every event goes out as 1 frame at once
(no buffering between the provider stream and the client), and an idle
stream gets a `: ping` comment every 15 seconds so a proxy keeps it open.
A client that disconnects stops only the reader; the pipeline task ends
the answer and stores it for `GET /api/results/{request_id}` (E-F-04).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any

from starlette import responses

MEDIA_TYPE = "text/event-stream"
PING_SECONDS = 15.0
PING_FRAME = ": ping\n\n"
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def frame(name: str, data: dict[str, Any] | None) -> str:
    """Format 1 event as an SSE frame.

    Args:
        name: The event name.
        data: The JSON payload, or None for an empty data line.

    Returns:
        `event: <name>` and 1 `data:` line, closed by a blank line. JSON
        escapes every newline, so the payload fits on 1 line.
    """
    payload = "" if data is None else json.dumps(data, ensure_ascii=False)
    return f"event: {name}\ndata: {payload}\n\n"


class Channel:
    """The events of 1 answer, from the pipeline task to the response.

    Args:
        ping_seconds: The idle time before a keep-alive comment.
    """

    def __init__(self, ping_seconds: float = PING_SECONDS) -> None:
        self.ping_seconds = ping_seconds
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()

    def send(self, name: str, data: dict[str, Any] | None) -> None:
        """Queue 1 event.

        Args:
            name: The event name.
            data: The payload.
        """
        self._queue.put_nowait(frame(name, data))

    def close(self) -> None:
        """End the stream after the queued events."""
        self._queue.put_nowait(None)

    async def frames(self) -> AsyncIterator[str]:
        """Yield the frames as they arrive, with pings while idle.

        Yields:
            SSE frames, until the channel closes.
        """
        while True:
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self.ping_seconds
                )
            except TimeoutError:
                yield PING_FRAME
                continue
            if item is None:
                return
            yield item


def response(channel: Channel) -> responses.StreamingResponse:
    """The streaming response of a channel.

    Args:
        channel: The channel the pipeline task fills.

    Returns:
        A `text/event-stream` response with the no-buffer headers.
    """
    return responses.StreamingResponse(
        channel.frames(), media_type=MEDIA_TYPE, headers=dict(HEADERS)
    )
