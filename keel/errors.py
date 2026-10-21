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
