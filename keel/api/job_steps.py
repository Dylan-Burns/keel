"""The step list of an admin job, as a CI run shows it.

A job kind declares its plan up front (`keel.steps.StepDef`), so a
queued job already lists its steps as pending. While the job runs, the
library functions report through the job's `Reporter` (`keel.steps`);
the `StepBook` turns those reports into the step records of the job row:

- `enter(key)` finishes the running step as succeeded, skips the
  pending steps it jumps over, and starts the step. It moves forward
  only; an earlier or the same key does nothing. An unknown key is
  inserted after the running step (at most `MAX_STEPS` steps).
- `skip(key, reason)` marks a pending step skipped with its reason.
- `log(line)` appends to the running step (the last `STEP_LOG_LINES`).
- `progress(done, total, unit)` sets the counts of the running step.
- `finish(ok, error)` ends the running step as succeeded or failed and
  skips the steps never reached.

Each record is a JSON-ready mapping: `key`, `name`, `status`
(`pending`, `running`, `succeeded`, `failed`, `skipped`), `started_at`,
`finished_at`, `progress` (`{done, total, unit}` or None), and `log`.
The lines arrive cleaned by the runner (secrets masked, control
characters removed, cut to 1 short line).
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Literal

from keel import steps
from keel.stores import admin_store

StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
STEP_LOG_LINES = admin_store.STEP_LOG_LINES
MAX_STEPS = 24
FINISHED: frozenset[str] = frozenset({"succeeded", "failed", "skipped"})
RELOAD = steps.StepDef("reload", "Reload the server")


def plan_records(plan: Sequence[steps.StepDef]) -> list[dict[str, Any]]:
    """The pending step records of a plan.

    Args:
        plan: The steps in order; a repeated key is kept once.

    Returns:
        1 pending record per step, at most `MAX_STEPS`.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in plan:
        if step.key in seen or len(records) >= MAX_STEPS:
            continue
        seen.add(step.key)
        records.append(_pending(step.key, step.name))
    return records


def _pending(key: str, name: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "progress": None,
        "log": [],
    }


def _name_of(key: str) -> str:
    words = key.replace("_", " ").replace("-", " ").strip()
    return (words[:1].upper() + words[1:])[:80] or "Step"


class StepBook:
    """The steps of 1 running job.

    Args:
        records: The step records of the job row.
        clock: The UTC time text of a start or a finish.
    """

    def __init__(
        self,
        records: Sequence[Mapping[str, Any]],
        clock: Callable[[], str] = admin_store.now_text,
    ) -> None:
        self.clock = clock
        self._steps: list[dict[str, Any]] = [
            {**record, "log": list(record.get("log") or [])}
            for record in records
        ]
        self._finished = False
        self._current: int | None = next(
            (
                i
                for i, step in enumerate(self._steps)
                if step.get("status") == "running"
            ),
            None,
        )

    def __bool__(self) -> bool:
        """True when the job has a plan."""
        return bool(self._steps)

    @property
    def current(self) -> int | None:
        """The index of the running step, or None."""
        return self._current

    def index_of(self, key: str) -> int | None:
        """The index of a step key, or None.

        Args:
            key: The step key.

        Returns:
            The index.
        """
        for index, step in enumerate(self._steps):
            if step.get("key") == key:
                return index
        return None

    def enter(self, key: str) -> str | None:
        """Start a step.

        Args:
            key: The step key.

        Returns:
            The name of the started step, or None when nothing changed
            (an earlier step, or a book that finished).
        """
        if self._finished:
            return None
        index = self.index_of(key)
        if index is None:
            if len(self._steps) >= MAX_STEPS:
                return None
            index = 0 if self._current is None else self._current + 1
            self._steps.insert(index, _pending(key, _name_of(key)))
        elif self._current is not None and index <= self._current:
            return None
        now = self.clock()
        start = 0
        if self._current is not None:
            self._end(self._current, "succeeded", now)
            start = self._current + 1
        for between in range(start, index):
            if self._steps[between]["status"] == "pending":
                self._steps[between]["status"] = "skipped"
        step = self._steps[index]
        step.update(status="running", started_at=now, finished_at=None)
        self._current = index
        return str(step["name"])

    def skip(self, key: str, reason: str) -> bool:
        """Mark a pending step skipped.

        Args:
            key: The step key; an unknown or started step stays as it is.
            reason: Why, as the step's log line.

        Returns:
            True when the step changed.
        """
        index = self.index_of(key)
        if (
            self._finished
            or index is None
            or self._steps[index]["status"] != "pending"
        ):
            return False
        step = self._steps[index]
        step["status"] = "skipped"
        self._append(step, f"skipped: {reason}")
        return True

    def log(self, line: str) -> bool:
        """Append a line to the running step.

        Args:
            line: The cleaned line.

        Returns:
            True when a step took it.
        """
        if self._finished or self._current is None:
            return False
        self._append(self._steps[self._current], line)
        return True

    def progress(self, done: int, total: int | None, unit: str) -> bool:
        """Set the counts of the running step.

        Args:
            done: The units done.
            total: The units in all, or None.
            unit: The plural noun of the unit.

        Returns:
            True when a step took it.
        """
        if self._finished or self._current is None:
            return False
        self._steps[self._current]["progress"] = {
            "done": max(0, done),
            "total": total,
            "unit": unit[:24],
        }
        return True

    def finish(self, ok: bool, error: str | None = None) -> None:
        """End the job: the running step and the steps never reached.

        A job that fails before its first step fails its first pending
        step, so the error stands next to a step. Later reports change
        nothing.

        Args:
            ok: True when the job succeeded.
            error: The error line of a failed step, or None.
        """
        if self._finished:
            return
        self._finished = True
        now = self.clock()
        if self._current is None and not ok:
            first = next(
                (
                    i
                    for i, step in enumerate(self._steps)
                    if step["status"] == "pending"
                ),
                None,
            )
            if first is not None:
                self._steps[first]["started_at"] = now
                self._current = first
        if self._current is not None:
            step = self._steps[self._current]
            if not ok and error:
                self._append(step, f"error: {error}")
            self._end(self._current, "succeeded" if ok else "failed", now)
            self._current = None
        for step in self._steps:
            if step["status"] == "pending":
                step["status"] = "skipped"

    def counts(self) -> tuple[int, int]:
        """The finished steps and the steps in all.

        Returns:
            (finished, total).
        """
        finished = sum(1 for s in self._steps if s["status"] in FINISHED)
        return finished, len(self._steps)

    def snapshot(self) -> list[dict[str, Any]]:
        """A copy of the records for the job row.

        Returns:
            The step records.
        """
        return [{**step, "log": list(step["log"])} for step in self._steps]

    def _end(self, index: int, status: StepStatus, when: str) -> None:
        step = self._steps[index]
        step.update(status=status, finished_at=when)

    @staticmethod
    def _append(step: dict[str, Any], line: str) -> None:
        log: list[str] = step["log"]
        log.append(line)
        if len(log) > STEP_LOG_LINES:
            del log[: len(log) - STEP_LOG_LINES]
