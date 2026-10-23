"""The step reports of the long operations behind the admin jobs.

An admin job (`keel.api.jobs`) shows its work as an ordered list of
named steps, as a CI run does: each step is pending, running,
succeeded, failed, or skipped, with its own log and, when it counts
work, its own progress. The library functions that the jobs call
(`add.add_ticker`, `refresh.run_refresh`, `indexer.build_index`,
`warm_cache.warm_answers`, the eval runner, the backup functions) take an
optional `Reporter` and say which step they enter, what they did, and
how far they are. The CLI passes none and gets `NULL`, which does
nothing, so the commands print what they printed before.

Each library module declares its step keys and names next to the code
that reports them (`add.STEPS`, `indexer.STEPS`, ...), and the job kinds
of `keel.api.job_kinds` join them into the plan of a job. A reporter
moves forward only: entering a later step finishes the running one and
skips the steps in between; entering an earlier or the same step does
nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
from typing import Protocol


@dataclasses.dataclass(frozen=True)
class StepDef:
    """1 step of a job plan.

    Attributes:
        key: The stable key the library reports, such as `embed`.
        name: The name the page shows, such as `Embed`.
    """

    key: str
    name: str


class Reporter(Protocol):
    """What a long operation reports while it runs."""

    def step(self, key: str) -> None:
        """Enter a step; the running step before it succeeded.

        Args:
            key: The step key.
        """

    def skip(self, key: str, reason: str) -> None:
        """Mark a step that is not reached yet as skipped.

        Args:
            key: The step key.
            reason: Why, for the step log.
        """

    def log(self, line: str) -> None:
        """Append 1 line to the log of the running step.

        Args:
            line: The line.
        """

    def progress(self, done: int, total: int | None, unit: str = "") -> None:
        """Record the progress of the running step.

        Args:
            done: The units done.
            total: The units in all, or None when not known.
            unit: The plural noun of the unit, such as `chunks`.
        """


class NullReporter:
    """A reporter that drops every report (the CLI default)."""

    def step(self, key: str) -> None:
        """Drop a step report.

        Args:
            key: The step key.
        """
        del key

    def skip(self, key: str, reason: str) -> None:
        """Drop a skip report.

        Args:
            key: The step key.
            reason: Why.
        """
        del key, reason

    def log(self, line: str) -> None:
        """Drop a log line.

        Args:
            line: The line.
        """
        del line

    def progress(self, done: int, total: int | None, unit: str = "") -> None:
        """Drop a progress report.

        Args:
            done: The units done.
            total: The units in all.
            unit: The unit.
        """
        del done, total, unit


NULL: Reporter = NullReporter()


class Prefixed:
    """Folds the steps of a nested operation into log lines of 1 step.

    The refresh adds each ticker's new filings inside its own `add` step;
    the add reports its own steps, which become lines such as `ZTS:
    Embed` of the refresh step, and its progress is dropped.

    Args:
        outer: The reporter of the enclosing job.
        prefix: The text before each line, such as the ticker.
        names: The step names by key, for the step lines.
    """

    def __init__(
        self,
        outer: Reporter,
        prefix: str,
        names: Mapping[str, str] | None = None,
    ) -> None:
        self.outer = outer
        self.prefix = prefix
        self.names = dict(names or {})
        self._last = ""

    def step(self, key: str) -> None:
        """Log the nested step as a line of the outer step, once.

        Args:
            key: The nested step key; the step just entered again is
                not logged twice.
        """
        if key == self._last:
            return
        self._last = key
        self.outer.log(f"{self.prefix}: {self.names.get(key, key)}")

    def skip(self, key: str, reason: str) -> None:
        """Log a nested skip as a line of the outer step.

        Args:
            key: The nested step key.
            reason: Why.
        """
        name = self.names.get(key, key)
        self.outer.log(f"{self.prefix}: {name} skipped: {reason}")

    def log(self, line: str) -> None:
        """Forward a line with the prefix.

        Args:
            line: The line.
        """
        self.outer.log(f"{self.prefix}: {line}")

    def progress(self, done: int, total: int | None, unit: str = "") -> None:
        """Drop the nested progress; the outer step counts its own.

        Args:
            done: The units done.
            total: The units in all.
            unit: The unit.
        """
        del done, total, unit


def names_of(*plans: tuple[StepDef, ...]) -> dict[str, str]:
    """The step names by key of 1 or more plans.

    Args:
        *plans: The plans.

    Returns:
        The names by key; a later plan wins a repeated key.
    """
    return {step.key: step.name for plan in plans for step in plan}
