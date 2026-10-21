"""The exception hierarchy of Keel.

Every error that Keel raises subclasses `KeelError`. The condition names of
the module contracts (chapter 6.5) map to classes with the `Error` suffix.
"""


class KeelError(Exception):
    """The base class of every Keel error."""


class ConfigError(KeelError):
    """A config file is absent, unreadable, or fails validation."""


class BadZipError(KeelError):
    """A zip archive is corrupt or exceeds the entry and size limits."""


class UnsafePathError(KeelError):
    """A zip entry is absolute, climbs out of the target, or is a link."""


class ExtractTargetError(KeelError):
    """The extraction target already holds files."""


class CorpusMissingError(KeelError):
    """The corpus directory is absent and no zip can fill it."""


class ManifestMissingError(KeelError):
    """The manifest file is absent or unreadable (a warning in inventory)."""


class FilingDecodeError(KeelError):
    """A filing is not valid UTF-8 (E-D-27); the file goes to quarantine."""


class HeaderError(KeelError):
    """A filing header lacks a key or names an unknown form (CK-01)."""


class SeparatorMissingError(KeelError):
    """No separator line within the first 20 lines of a filing (CK-02)."""


class CoverPageNotFoundError(KeelError):
    """A filing has no cover page period and no period code (CK-07).

    Reserved: the parser records this condition as the quarantine reason
    `cover_page_not_found` instead of raising (chapter 6.5 names it).
    """


class ModelMissingError(KeelError):
    """A pinned model or its tokenizer is not in the local cache."""


class FilingNotIndexableError(KeelError):
    """A quarantined filing or a filing without an ID reached the chunker."""


class EmbeddingModelUnavailableError(KeelError):
    """The pinned embedding model cannot load (chapter 6.5)."""


class IndexWriteError(KeelError):
    """An index build cannot write or publish its files (chapter 6.5)."""


class IndexMissingError(KeelError):
    """No index build sits behind the `current` pointer (chapter 6.5)."""


class IndexCorruptError(KeelError):
    """An index file does not match its manifest checksum (chapter 16)."""


class InvalidFilingIdError(KeelError):
    """A filing ID does not have the chapter 7.11 shape, so no file uses it."""


class QuestionInputError(KeelError):
    """A question fails an input check of chapter 10.7.

    Attributes:
        http_status: The HTTP status the API returns for it.
    """

    http_status = 400


class EmptyQuestionError(QuestionInputError):
    """The trimmed question is shorter than the minimum (HTTP 400)."""


class QuestionTooLongError(QuestionInputError):
    """The question is longer than the limit (HTTP 413, chapter 10.7)."""

    http_status = 413


class NonEnglishQuestionError(QuestionInputError):
    """The question is not in English (HTTP 400, chapter 10.7)."""
