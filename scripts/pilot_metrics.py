#!/usr/bin/env python3
"""Pilot metrics from the audit log (chapter 27.6).

Usage:
    uv run python scripts/pilot_metrics.py [logs/audit.jsonl ...] [--json]
        [--manifest corpus/edgar/manifest.json] [--feedback-db PATH]

The script reads the audit log and its daily rotations
(`audit-<date>.jsonl` next to it; a directory argument reads every audit
file in it) and prints the weekly numbers of the pilot: active users,
questions, cost, cost per question, thumbs-up rate, memos exported, and
companies added, then the outcomes and the success metrics of chapter
27.6. `--json` prints the same numbers as JSON.

Sources that later stages add are optional, and an absent one reads as
"n/a": the `user` of each audit record (stage 17; a record without one
counts as the 1 legacy token user), the `feedback` table (stage 18), the
memo export events in the audit log (stage 19), and the `source: edgar`
entries that `keel add` writes into the corpus manifest (stage 14). The
script only reads; it never prints a token or a question.
"""

from __future__ import annotations

import argparse
import collections
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Sequence
import contextlib
import dataclasses
import datetime
import json
import logging
import pathlib
import re
import sqlite3
import sys
from typing import Any

logger = logging.getLogger(__name__)

LEGACY_USER = "legacy-token"
USER_KEYS = ("user", "user_id", "user_name", "username")
EXPORT_EVENTS = frozenset({"export", "memo_export", "memo_exported"})
TIME_KEYS = ("timestamp", "created_at", "time", "ts", "added_at")
VOTE_KEYS = ("vote", "thumbs", "rating", "value", "helpful")
POSITIVE_VOTES = frozenset({"1", "+1", "up", "thumbs_up", "true", "yes"})
NEGATIVE_VOTES = frozenset({"-1", "0", "down", "thumbs_down", "false", "no"})
EDGAR_DATE_KEYS = ("added_at", "fetched_at", "ingested_at", "added")
TICKER_PATTERN = re.compile(r"^([A-Z][A-Z0-9.\-]{0,9})_")

# The success metrics of chapter 27.6.
TARGET_ACTIVE_USERS = 3
TARGET_WEEKLY_QUESTIONS = 30
TARGET_THUMBS_UP = 0.70
TARGET_MEMOS = 3


@dataclasses.dataclass(frozen=True)
class Week:
    """The numbers of 1 ISO week.

    Attributes:
        week: The ISO week, such as `2026-W43`.
        active_users: The distinct users who asked a question.
        questions: The question records.
        cost_usd: The summed model cost.
        cost_per_question: The cost divided by the questions, or None.
        thumbs_up_rate: The share of positive votes, or None without votes.
        votes: The feedback votes of the week.
        memos_exported: The memo export events, or None without any source.
        companies_added: The tickers added by `keel add`, or None.
    """

    week: str
    active_users: int
    questions: int
    cost_usd: float
    cost_per_question: float | None
    thumbs_up_rate: float | None
    votes: int
    memos_exported: int | None
    companies_added: int | None


@dataclasses.dataclass(frozen=True)
class Metrics:
    """The pilot metrics over every week of the log.

    Attributes:
        weeks: The weekly rows, oldest first.
        outcomes: The count per outcome over the whole log.
        users: The distinct users over the whole log.
        questions: The question records over the whole log.
        cost_usd: The summed cost over the whole log.
        thumbs_up_rate: The overall share of positive votes, or None.
        votes: The feedback votes over the whole log.
        memos_exported: The memo exports, or None when no source exists.
        companies_added: The distinct tickers added by `keel add`, or None.
        files: The audit files read.
        skipped_lines: The lines that were not a JSON object.
        undated_records: The records left out of every count because
            their timestamp is missing or not a time.
        sources: Which optional sources were found.
    """

    weeks: tuple[Week, ...]
    outcomes: dict[str, int]
    users: int
    questions: int
    cost_usd: float
    thumbs_up_rate: float | None
    votes: int
    memos_exported: int | None
    companies_added: int | None
    files: tuple[str, ...]
    skipped_lines: int
    undated_records: int
    sources: dict[str, bool]


@dataclasses.dataclass(frozen=True)
class Vote:
    """1 feedback vote.

    Attributes:
        positive: True for a thumbs up.
        week: The ISO week of the vote, or None when the table has no time.
    """

    positive: bool
    week: str | None


@dataclasses.dataclass(frozen=True)
class Addition:
    """1 ticker that `keel add` brought into the manifest.

    Attributes:
        ticker: The ticker.
        week: The ISO week of the first addition, or None without a date.
    """

    ticker: str
    week: str | None


def iso_week(value: object) -> str | None:
    """Return the ISO week of a timestamp.

    Args:
        value: An ISO 8601 string, a date, or epoch seconds.

    Returns:
        The week as `YYYY-Www`, or None when the value is not a time.
    """
    moment: datetime.date | None = None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        with contextlib.suppress(OverflowError, OSError, ValueError):
            moment = datetime.datetime.fromtimestamp(value, tz=datetime.UTC)
    elif isinstance(value, str) and value:
        text = value.strip().replace("Z", "+00:00")
        with contextlib.suppress(ValueError):
            moment = datetime.datetime.fromisoformat(text)
        if moment is None:
            with contextlib.suppress(ValueError):
                moment = datetime.date.fromisoformat(text[:10])
    if moment is None:
        return None
    if isinstance(moment, datetime.datetime) and moment.tzinfo is not None:
        moment = moment.astimezone(datetime.UTC)
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def audit_files(paths: Sequence[pathlib.Path]) -> list[pathlib.Path]:
    """Expand the arguments into the audit files and their rotations.

    Args:
        paths: Audit files or directories.

    Returns:
        The existing files, rotations first by name, without duplicates.
    """
    found: dict[pathlib.Path, None] = {}
    for path in paths:
        directory = path if path.is_dir() else path.parent
        for rotated in sorted(directory.glob("audit-*.jsonl")):
            found[rotated.resolve()] = None
        if path.is_dir():
            current = path / "audit.jsonl"
            if current.is_file():
                found[current.resolve()] = None
        elif path.is_file():
            found[path.resolve()] = None
        else:
            logger.warning("no audit file at %s", path)
    return list(found)


def read_records(
    files: Iterable[pathlib.Path],
) -> tuple[list[dict[str, Any]], int]:
    """Read the JSON lines of the audit files.

    Args:
        files: The audit files.

    Returns:
        The records and the count of skipped lines (not a JSON object).
    """
    records: list[dict[str, Any]] = []
    skipped = 0
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if isinstance(value, dict):
                    records.append(value)
                else:
                    skipped += 1
    return records, skipped


def user_of(record: dict[str, Any]) -> tuple[str, bool]:
    """Name the user of an audit record.

    Args:
        record: The audit record.

    Returns:
        The user and whether the record named one (False for the legacy
        token, which counts as 1 user).
    """
    for key in USER_KEYS:
        value = record.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("id")
        if value not in (None, ""):
            return str(value), True
    return LEGACY_USER, False


def is_export(record: dict[str, Any]) -> bool:
    """Tell whether an audit record is a memo export event (stage 19).

    Args:
        record: The audit record.

    Returns:
        True for an export event.
    """
    event = str(record.get("event") or record.get("type") or "").lower()
    return event in EXPORT_EVENTS


def is_question(record: dict[str, Any]) -> bool:
    """Tell whether an audit record is a question.

    Args:
        record: The audit record.

    Returns:
        True when the record has a request ID and no other event type.
    """
    event = record.get("event")
    if event not in (None, "question", "ask", "answer"):
        return False
    return "request_id" in record and not is_export(record)


def _time_of(row: dict[str, Any]) -> object:
    for key in TIME_KEYS:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _vote_value(row: dict[str, Any]) -> bool | None:
    for key in VOTE_KEYS:
        if key in row and row[key] is not None:
            text = str(row[key]).strip().lower()
            if text in POSITIVE_VOTES:
                return True
            if text in NEGATIVE_VOTES:
                return False
            return None
    return None


def read_votes(path: pathlib.Path | None) -> list[Vote] | None:
    """Read the thumbs votes of the `feedback` table (stage 18).

    Args:
        path: The SQLite file that holds the table, or None.

    Returns:
        The votes, or None when the file or the table is absent.
    """
    if path is None or not path.is_file():
        return None
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'feedback'"
            ).fetchone()
            if exists is None:
                return None
            rows = [dict(r) for r in conn.execute("SELECT * FROM feedback")]
    except sqlite3.Error as error:
        logger.warning("feedback table unreadable: %s", error)
        return None
    votes: list[Vote] = []
    for row in rows:
        positive = _vote_value(row)
        if positive is not None:
            votes.append(Vote(positive, iso_week(_time_of(row))))
    return votes


def _edgar_entries(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if str(value.get("source", "")).lower() == "edgar":
            yield value
        for child in value.values():
            yield from _edgar_entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from _edgar_entries(child)


def _ticker_of(entry: dict[str, Any]) -> str | None:
    ticker = entry.get("ticker")
    if isinstance(ticker, str) and ticker:
        return ticker.upper()
    for key in ("file", "name", "filename", "file_name", "filing_id"):
        name = entry.get(key)
        if isinstance(name, str):
            match = TICKER_PATTERN.match(pathlib.PurePath(name).name)
            if match:
                return match.group(1)
    return None


def read_additions(path: pathlib.Path | None) -> list[Addition] | None:
    """Read the tickers that `keel add` wrote into the manifest (stage 14).

    Args:
        path: The corpus manifest, or None.

    Returns:
        1 addition per ticker with `source: edgar` entries (the earliest
        dated one), an empty list when the manifest has none, or None when
        the manifest is absent or unreadable.
    """
    if path is None or not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("manifest unreadable: %s", error)
        return None
    first: dict[str, str | None] = {}
    for entry in _edgar_entries(manifest):
        ticker = _ticker_of(entry)
        if ticker is None:
            continue
        week = next(
            (
                iso_week(entry[k])
                for k in EDGAR_DATE_KEYS
                if entry.get(k) not in (None, "")
            ),
            None,
        )
        known = first.get(ticker)
        if ticker not in first or (week and (known is None or week < known)):
            first[ticker] = week
    return [Addition(t, w) for t, w in sorted(first.items())]


def _rate(positive: int, total: int) -> float | None:
    return positive / total if total else None


def compute(
    records: Sequence[dict[str, Any]],
    votes: Sequence[Vote] | None = None,
    additions: Sequence[Addition] | None = None,
    files: Sequence[str] = (),
    skipped_lines: int = 0,
) -> Metrics:
    """Compute the weekly and overall pilot metrics.

    Args:
        records: The audit records.
        votes: The feedback votes, or None when the table is absent.
        additions: The tickers added by `keel add`, or None.
        files: The audit files read, for the report.
        skipped_lines: The lines that were not a JSON object.

    Returns:
        The metrics.
    """
    users: dict[str, set[str]] = collections.defaultdict(set)
    questions: collections.Counter[str] = collections.Counter()
    cost: dict[str, float] = collections.defaultdict(float)
    exports: collections.Counter[str] = collections.Counter()
    outcomes: collections.Counter[str] = collections.Counter()
    all_users: set[str] = set()
    named_user = False
    export_source = False
    weeks: set[str] = set()
    undated = 0
    for record in records:
        week = iso_week(record.get("timestamp"))
        if week is None:
            undated += 1
            continue
        if is_export(record):
            export_source = True
            exports[week] += 1
            weeks.add(week)
        elif is_question(record):
            user, named = user_of(record)
            named_user = named_user or named
            users[week].add(user)
            all_users.add(user)
            questions[week] += 1
            value = record.get("cost_usd")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cost[week] += float(value)
            outcomes[str(record.get("outcome") or "unknown")] += 1
            weeks.add(week)
    vote_weeks: dict[str, list[bool]] = collections.defaultdict(list)
    for vote in votes or ():
        if vote.week is not None:
            vote_weeks[vote.week].append(vote.positive)
            weeks.add(vote.week)
    added_weeks: collections.Counter[str] = collections.Counter(
        a.week for a in additions or () if a.week is not None
    )
    weeks.update(added_weeks)
    rows = []
    for week in sorted(weeks):
        week_votes = vote_weeks.get(week, [])
        rows.append(
            Week(
                week=week,
                active_users=len(users.get(week, ())),
                questions=questions[week],
                cost_usd=round(cost[week], 6),
                cost_per_question=round(cost[week] / questions[week], 6)
                if questions[week]
                else None,
                thumbs_up_rate=_rate(sum(week_votes), len(week_votes)),
                votes=len(week_votes),
                memos_exported=exports[week] if export_source else None,
                companies_added=added_weeks[week]
                if additions is not None
                else None,
            )
        )
    all_votes = [v.positive for v in votes or ()]
    return Metrics(
        weeks=tuple(rows),
        outcomes=dict(outcomes.most_common()),
        users=len(all_users),
        questions=sum(questions.values()),
        cost_usd=round(sum(cost.values()), 6),
        thumbs_up_rate=_rate(sum(all_votes), len(all_votes)),
        votes=len(all_votes),
        memos_exported=sum(exports.values()) if export_source else None,
        companies_added=len(additions) if additions is not None else None,
        files=tuple(files),
        skipped_lines=skipped_lines,
        undated_records=undated,
        sources={
            "user_field": named_user,
            "feedback_table": votes is not None,
            "export_events": export_source,
            "manifest": additions is not None,
        },
    )


def targets(metrics: Metrics) -> list[dict[str, Any]]:
    """Check the success metrics of chapter 27.6 over the whole log.

    Args:
        metrics: The computed metrics.

    Returns:
        1 row per metric: the name, the target, the value, and whether it
        holds (None when the source is absent).
    """
    best_users = max((w.active_users for w in metrics.weeks), default=0)
    best_questions = max((w.questions for w in metrics.weeks), default=0)
    return [
        {
            "metric": "active users in the best week",
            "target": f">= {TARGET_ACTIVE_USERS} of 5",
            "value": best_users,
            "holds": best_users >= TARGET_ACTIVE_USERS,
        },
        {
            "metric": "questions in the best week",
            "target": f">= {TARGET_WEEKLY_QUESTIONS}",
            "value": best_questions,
            "holds": best_questions >= TARGET_WEEKLY_QUESTIONS,
        },
        {
            "metric": "thumbs-up rate",
            "target": f">= {TARGET_THUMBS_UP:.0%}",
            "value": metrics.thumbs_up_rate,
            "holds": None
            if metrics.thumbs_up_rate is None
            else metrics.thumbs_up_rate >= TARGET_THUMBS_UP,
        },
        {
            "metric": "memos exported",
            "target": f">= {TARGET_MEMOS}",
            "value": metrics.memos_exported,
            "holds": None
            if metrics.memos_exported is None
            else metrics.memos_exported >= TARGET_MEMOS,
        },
    ]


def _cell(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def to_markdown(metrics: Metrics) -> str:
    """Render the metrics as Markdown tables.

    Args:
        metrics: The computed metrics.

    Returns:
        The report text.
    """
    lines = [
        "## Pilot metrics",
        "",
        "| Week | Active users | Questions | Cost (USD) | Cost per question "
        "| Thumbs-up rate | Memos exported | Companies added |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for w in metrics.weeks:
        lines.append(
            f"| {w.week} | {w.active_users} | {w.questions} "
            f"| {w.cost_usd:.2f} | {_cell(w.cost_per_question)} "
            f"| {_percent(w.thumbs_up_rate)} | {_cell(w.memos_exported)} "
            f"| {_cell(w.companies_added)} |"
        )
    per_question = (
        metrics.cost_usd / metrics.questions if metrics.questions else None
    )
    lines.append(
        f"| Total | {metrics.users} | {metrics.questions} "
        f"| {metrics.cost_usd:.2f} | {_cell(per_question)} "
        f"| {_percent(metrics.thumbs_up_rate)} "
        f"| {_cell(metrics.memos_exported)} "
        f"| {_cell(metrics.companies_added)} |"
    )
    lines += ["", "| Outcome | Questions |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in metrics.outcomes.items()]
    lines += [
        "",
        "| Success metric (27.6) | Target | Value | Holds |",
        "| --- | --- | --- | --- |",
    ]
    for row in targets(metrics):
        name, target, value, holds = (
            row["metric"],
            row["target"],
            row["value"],
            row["holds"],
        )
        shown = _percent(value) if name == "thumbs-up rate" else value
        lines.append(f"| {name} | {target} | {_cell(shown)} | {_cell(holds)} |")
    absent = [k for k, found in metrics.sources.items() if not found]
    lines += [
        "",
        f"Files read: {len(metrics.files)}; lines skipped: "
        f"{metrics.skipped_lines}; records without a timestamp: "
        f"{metrics.undated_records}.",
    ]
    if not metrics.sources["user_field"]:
        lines.append(
            "Records carry no user field: the legacy token counts as 1 user."
        )
    if absent:
        joined = ", ".join(absent)
        lines.append(f"Sources absent (n/a): {joined}.")
    return "\n".join(lines) + "\n"


def to_json(metrics: Metrics) -> str:
    """Render the metrics as JSON.

    Args:
        metrics: The computed metrics.

    Returns:
        The JSON text.
    """
    body = dataclasses.asdict(metrics)
    body["targets"] = targets(metrics)
    return json.dumps(body, indent=2)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        description="Pilot metrics from the audit log (chapter 27.6)."
    )
    parser.add_argument(
        "audit",
        nargs="*",
        type=pathlib.Path,
        default=[pathlib.Path("logs/audit.jsonl")],
        help="audit files or directories (default: logs/audit.jsonl); "
        "the rotations next to each file are read too",
    )
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=pathlib.Path("corpus/edgar/manifest.json"),
        help="the corpus manifest with the `source: edgar` entries",
    )
    parser.add_argument(
        "--feedback-db",
        type=pathlib.Path,
        default=None,
        help="the SQLite file with the `feedback` table (stage 18)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print JSON instead of Markdown"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the script.

    Args:
        argv: The arguments, or None for the command line.

    Returns:
        0 after the report, 1 when no audit file exists.
    """
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = build_parser().parse_args(argv)
    files = audit_files(args.audit)
    if not files:
        logger.error("no audit file found in %s", [str(p) for p in args.audit])
        return 1
    records, skipped = read_records(files)
    metrics = compute(
        records,
        votes=read_votes(args.feedback_db),
        additions=read_additions(args.manifest),
        files=[str(f) for f in files],
        skipped_lines=skipped,
    )
    print(to_json(metrics) if args.json else to_markdown(metrics), end="")
    if args.json:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
