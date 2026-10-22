"""The audit log: 1 JSON line per question (control S-07, decision D-27).

The line holds the request ID, the time, the question, the tickers, the
chunk IDs of the context, the prompt hash and version, the index version,
the model, the latency breakdown, the token counts, the cost, the number of
model requests, the drift counts, and the flags. It never holds the prompt
text or a key: the prompt hash and the chunk IDs rebuild the prompt from
the index. The file is readable by the owner only and rotates daily. A
write failure is logged and never blocks the answer.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
from typing import Any

from keel import errors

logger = logging.getLogger(__name__)

FILE_NAME = "audit.jsonl"
FILE_MODE = 0o600
FORBIDDEN_KEYS = frozenset({"prompt", "system", "user", "api_key", "token"})


class AuditLog:
    """Append audit records to `<logs.dir>/audit.jsonl`.

    Args:
        directory: The logs directory.
    """

    def __init__(self, directory: pathlib.Path) -> None:
        self.directory = directory
        self.path = directory / FILE_NAME

    def _rotate(self, today: datetime.date) -> None:
        """Move a file from an earlier day to `audit-<date>.jsonl`."""
        if not self.path.exists():
            return
        modified = datetime.datetime.fromtimestamp(
            self.path.stat().st_mtime, tz=datetime.UTC
        ).date()
        if modified < today:
            target = self.directory / f"audit-{modified.isoformat()}.jsonl"
            if not target.exists():
                self.path.rename(target)

    def write(self, record: dict[str, Any]) -> bool:
        """Append 1 record.

        Args:
            record: The audit record; a key that could hold the prompt or
                a secret is refused.

        Returns:
            True when the line was written; False after a logged failure.
        """
        try:
            bad = FORBIDDEN_KEYS & set(record)
            if bad:
                raise errors.AuditWriteError(
                    f"refused keys in an audit record: {sorted(bad)}"
                )
            line = json.dumps(record, ensure_ascii=False, sort_keys=False)
            self.directory.mkdir(parents=True, exist_ok=True)
            self._rotate(datetime.datetime.now(tz=datetime.UTC).date())
            handle = os.open(
                self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE
            )
            os.fchmod(handle, FILE_MODE)  # also tighten an older file
            with os.fdopen(handle, "a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except (
            OSError,
            TypeError,
            ValueError,
            errors.AuditWriteError,
        ) as error:
            logger.error("AuditWriteError: %s", error)
            return False
        return True
