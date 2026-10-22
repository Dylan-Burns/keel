"""The answer cache (decision D-29, chapter 16.12).

The key is the sha256 of the normalized question, the index version, the
prompt version, and the model, so a new index, prompt, or model gives no
stale hit. Each entry is 1 JSON file under `cache.answers_dir` with the
sha256 of its payload; a read checks it, and a mismatch is a miss with a
warning. Writes go to a temporary file and replace the entry atomically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import tempfile
from typing import Any

from keel import errors
from keel import understanding

logger = logging.getLogger(__name__)

ENTRY_SUFFIX = ".json"
DIRECTORY_MODE = 0o700


def normalize_question(question: str) -> str:
    """The question part of the key: normalized and case-folded.

    Args:
        question: The question as asked.

    Returns:
        The normalized question.
    """
    return understanding.normalize(question).casefold()


def cache_key(
    question: str, index_version: str, prompt_version: str, model: str
) -> str:
    """Hash the 4 parts of the key of decision D-29.

    Args:
        question: The question as asked.
        index_version: The index version of the manifest.
        prompt_version: The prompt version.
        model: The model identifier.

    Returns:
        The hex sha256 of the parts.
    """
    parts = [normalize_question(question), index_version, prompt_version, model]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _checksum(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AnswerCache:
    """The answer cache on disk.

    Args:
        directory: The `cache.answers_dir` directory.
    """

    def __init__(self, directory: pathlib.Path) -> None:
        self.directory = directory

    def path(self, key: str) -> pathlib.Path:
        """Return the entry file of a key.

        Args:
            key: The cache key.

        Returns:
            The file path.
        """
        return self.directory / f"{key}{ENTRY_SUFFIX}"

    def get(self, key: str) -> dict[str, Any] | None:
        """Read an entry and check its sha256.

        Args:
            key: The cache key.

        Returns:
            The stored record, or None on a miss or a bad entry.
        """
        path = self.path(key)
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            record = entry["record"]
            if entry.get("sha256") != _checksum(record):
                raise errors.AnswerCacheError("checksum mismatch")
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("answer cache entry %s unreadable: %s", key, error)
            return None
        except errors.AnswerCacheError as error:
            logger.warning("answer cache entry %s rejected: %s", key, error)
            return None
        if not isinstance(record, dict):
            return None
        return record

    def find(self, request_id: str) -> dict[str, Any] | None:
        """Find the stored record of a request ID (chapter 14.1 results).

        Args:
            request_id: The request ID of the answer that filled the entry.

        Returns:
            The record, or None when no valid entry holds the request ID.
        """
        if not self.directory.is_dir():
            return None
        for path in sorted(self.directory.glob(f"*{ENTRY_SUFFIX}")):
            if path.name.startswith(".tmp-"):
                continue
            record = self.get(path.name[: -len(ENTRY_SUFFIX)])
            if record is not None and record.get("request_id") == request_id:
                return record
        return None

    def put(self, key: str, record: dict[str, Any]) -> None:
        """Store a record; a write failure is logged, never raised.

        Args:
            key: The cache key.
            record: The answer record (chapter 14.2).
        """
        # The file name holds the key; a hex value under a `key` field
        # reads as a secret to the scanner.
        entry = {"sha256": _checksum(record), "record": record}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Control S-16 step 3: the service user alone writes entries.
            self.directory.chmod(DIRECTORY_MODE)
            handle, temporary = tempfile.mkstemp(
                dir=self.directory, prefix=".tmp-", suffix=ENTRY_SUFFIX
            )
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(entry, stream, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary, self.path(key))
        except OSError as error:
            logger.warning("answer cache write failed for %s: %s", key, error)
