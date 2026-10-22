"""A tolerant reader of the answer JSON while it streams (chapter 12.7).

The provider sends the tool input as JSON fragments. The reader scans each
new character once and reports 2 things as they appear: the new characters
of the top-level `direct_answer` string (the `answer_delta` event) and each
object of the top-level `company_findings` array when it closes (the
`findings` event). It never parses the whole text again per fragment; the
final parse after the stream is `json.loads` on the full text.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

ANSWER_KEY = "direct_answer"
FINDINGS_KEY = "company_findings"
_ESCAPE_LENGTHS = {"u": 5}


def _high_surrogate(digits: str) -> bool:
    return 0xD800 <= int(digits, 16) <= 0xDBFF


@dataclasses.dataclass(frozen=True)
class StreamUpdate:
    """What 1 fragment added.

    Attributes:
        answer_delta: New decoded characters of `direct_answer`.
        findings: The company objects that closed in this fragment.
    """

    answer_delta: str = ""
    findings: tuple[dict[str, Any], ...] = ()


def _decodable(raw: str) -> str:
    """Cut a trailing incomplete escape off a raw JSON string body."""
    index = raw.rfind("\\")
    if index < 0:
        return raw
    # Count the backslashes before the last one: an even run is literal.
    run = index - len(raw[:index].rstrip("\\"))
    if run % 2 == 1:
        return raw  # the last backslash is itself escaped
    tail = raw[index + 1 :]
    if not tail:
        return _decodable(raw[:index])
    needed = _ESCAPE_LENGTHS.get(tail[0], 1)
    if len(tail) < needed:
        return _decodable(raw[:index])
    if tail[0] == "u" and len(tail) == needed and _high_surrogate(tail[1:]):
        return raw[:index]  # wait for the low half of the pair
    return raw


class AnswerStream:  # pylint: disable=too-many-instance-attributes
    """Read the answer JSON fragment by fragment.

    Attributes:
        text: The full text received so far.
        answer: The decoded `direct_answer` so far.
    """

    def __init__(self) -> None:
        self.text = ""
        self.answer = ""
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._string_start = 0
        self._key: str | None = None
        self._expect_key = False
        self._value_key: str | None = None
        self._answer_start: int | None = None
        self._answer_end: int | None = None
        self._element_start: int | None = None

    def feed(self, fragment: str) -> StreamUpdate:
        """Add 1 fragment and report what it completed.

        Args:
            fragment: The next characters of the JSON text.

        Returns:
            The new answer characters and the closed company objects.
        """
        start = len(self.text)
        self.text += fragment
        findings: list[dict[str, Any]] = []
        for index in range(start, len(self.text)):
            closed = self._step(index, self.text[index])
            if closed is not None:
                findings.append(closed)
        delta = self._answer_delta()
        return StreamUpdate(answer_delta=delta, findings=tuple(findings))

    def _answer_delta(self) -> str:
        if self._answer_start is None:
            return ""
        end = len(self.text) if self._answer_end is None else self._answer_end
        raw = _decodable(self.text[self._answer_start : end])
        try:
            decoded = json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return ""
        if not isinstance(decoded, str) or len(decoded) <= len(self.answer):
            return ""
        delta = decoded[len(self.answer) :]
        self.answer = decoded
        return delta

    def _step(self, index: int, char: str) -> dict[str, Any] | None:
        if self._in_string:
            self._string_char(index, char)
            return None
        if char == '"':
            self._in_string = True
            self._string_start = index + 1
            if (
                self._depth == 1
                and not self._expect_key
                and self._value_key == ANSWER_KEY
                and self._answer_start is None
            ):
                self._answer_start = index + 1
            return None
        return self._structure(index, char)

    def _string_char(self, index: int, char: str) -> None:
        if self._escape:
            self._escape = False
            return
        if char == "\\":
            self._escape = True
            return
        if char != '"':
            return
        self._in_string = False
        if self._depth == 1 and self._expect_key:
            self._key = json.loads(
                self.text[self._string_start - 1 : index + 1]
            )
        elif (
            self._answer_start is not None
            and self._answer_end is None
            and self._depth == 1
            and self._value_key == ANSWER_KEY
        ):
            self._answer_end = index

    def _structure(self, index: int, char: str) -> dict[str, Any] | None:
        closed: dict[str, Any] | None = None
        if char in "{[":
            self._depth += 1
            if self._depth == 1:
                self._expect_key = char == "{"
            elif (
                self._depth == 3
                and char == "{"
                and self._value_key == FINDINGS_KEY
            ):
                self._element_start = index
        elif char in "}]":
            if (
                self._depth == 3
                and char == "}"
                and self._element_start is not None
            ):
                closed = self._element(index)
            self._depth -= 1
        elif self._depth == 1:
            if char == ":":
                self._expect_key = False
                self._value_key = self._key
            elif char == ",":
                self._expect_key = True
                self._value_key = None
        return closed

    def _element(self, index: int) -> dict[str, Any] | None:
        start = self._element_start
        self._element_start = None
        if start is None:
            return None
        try:
            value = json.loads(self.text[start : index + 1])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
