#!/usr/bin/env python3
"""Pilot metrics from the audit log (chapter 27.6).

Usage:
    uv run python scripts/pilot_metrics.py [AUDIT ...] [--since DATE]
        [--exclude-user NAME ...] [--feedback-db PATH] [--manifest PATH]
        [--refresh-log PATH] [--config PATH] [--json]

The script reads the audit log and its daily rotations
(`audit-<date>.jsonl` next to it; a directory argument reads every audit
file in it) and prints the weekly numbers of the pilot: active users,
questions, cost, cost per question, thumbs-up rate, memos exported,
companies added, and filings added by the refresh, then the outcomes and
the 4 success metrics of chapter 27.6 with the week 4 decision rule.
`--json` prints the same numbers as JSON.

Every default comes from `config/keel.yaml` (and its `KEEL_` overrides):
the audit log `<logs.dir>/audit.jsonl` (stage 7), whose records carry
`user_name` (stage 17; a record without it counts as the `legacy` token
user); the `feedback` table of the pilot store (`pilot.db`, by default
`<logs.dir>/pilot.sqlite`, stage 18); the `added` entries with `source:
edgar` of the corpus manifest (stage 14), dated by the modification time
of the corpus file that `keel add` wrote; and the `added` lines of
`<logs.dir>/refresh.log` (stage 20). Memo exports (stage 19) leave no log
line or audit record, so that column reads n/a. An absent source reads
n/a. The script only reads; it never prints a token or a question.
"""

from __future__ import annotations

import argparse
import collections
from collections.abc import Iterable
from collections.abc import Sequence
import contextlib
import dataclasses
import datetime
import json
import logging
import pathlib
import re
import sys
from typing import Any

from keel import audit
from keel import config
from keel import errors
from keel import refresh
from keel.stores import pilot

logger = logging.getLogger(__name__)

# Stage 17: the shared `KEEL_API_TOKEN` is the admin user `legacy`, and a
# record written before stage 17 has no `user_name`.
LEGACY_USER = "legacy"
TICKER_PATTERN = re.compile(r"^([A-Z][A-Z0-9.\-]{0,9})_")

# The success metrics of chapter 27.6, step 3.
TARGET_ACTIVE_USERS = 3
ACTIVE_USERS_FROM_WEEK = 2
TARGET_WEEKLY_QUESTIONS = 30
QUESTIONS_FROM_WEEK = 3
TARGET_THUMBS_UP = 0.70
TARGET_MEMOS = 3
# Step 4: continue to phase 2 when 3 of the 4 log metrics hold.
METRICS_TO_CONTINUE = 3


@dataclasses.dataclass(frozen=True)
class Week:
    """The numbers of 1 ISO week.

    Attributes:
        week: The ISO week, such as `2026-W43`.
        active_users: The distinct users who asked a question.
        questions: The question records.
        cost_usd: The summed model cost.
        cost_per_question: The cost divided by the questions, or None.
        thumbs_up_rate: The share of up votes, or None without votes.
        votes: The feedback votes of the week.
        memos_exported: The memo exports, or None (not logged).
        companies_added: The tickers `keel add` brought in, or None.
        filings_refreshed: The filings `keel refresh` added, or None.
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
    filings_refreshed: int | None


@dataclasses.dataclass(frozen=True)
class Metrics:
    """The pilot metrics over every week of the log.

    Attributes:
        weeks: The weekly rows, oldest first, with no week missing.
        outcomes: The count per outcome over the whole log.
        users: The distinct users over the whole log.
        questions: The question records over the whole log.
        cost_usd: The summed cost over the whole log.
        thumbs_up_rate: The overall share of up votes, or None.
        votes: The feedback votes over the whole log.
        memos_exported: The memo exports, or None (not logged).
        companies_added: The distinct tickers added by `keel add`, or None.
        filings_refreshed: The filings added by `keel refresh`, or None.
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
    filings_refreshed: int | None
    files: tuple[str, ...]
    skipped_lines: int
    undated_records: int
    sources: dict[str, bool]


@dataclasses.dataclass(frozen=True)
class Vote:
    """1 feedback vote.

    Attributes:
        positive: True for a thumbs up.
        week: The ISO week of the vote, or None when its time is not one.
    """

    positive: bool
    week: str | None


@dataclasses.dataclass(frozen=True)
class Addition:
    """1 ticker that `keel add` brought into the corpus.

    Attributes:
        ticker: The ticker.
        week: The ISO week of its first file, or None when no file exists.
    """

    ticker: str
    week: str | None


@dataclasses.dataclass(frozen=True)
class Sources:
    """The file locations the script reads.

    Attributes:
        audit: The audit files or directories.
        feedback_db: The pilot store with the `feedback` table.
        manifest: The corpus manifest.
        refresh_log: The refresh log.
    """

    audit: tuple[pathlib.Path, ...]
    feedback_db: pathlib.Path
    manifest: pathlib.Path
    refresh_log: pathlib.Path


def _from_text(text: str) -> datetime.date | None:
    """Read an ISO 8601 time, or the date at its start."""
    text = text.strip().replace("Z", "+00:00")
    with contextlib.suppress(ValueError):
        return datetime.datetime.fromisoformat(text)
    with contextlib.suppress(ValueError):
        return datetime.date.fromisoformat(text[:10])
    return None


def _moment(value: object) -> datetime.date | None:
    """Read a timestamp as an aware UTC time or a date."""
    moment: datetime.date | None = None
    if isinstance(value, bool):
        moment = None
    elif isinstance(value, (int, float)):
        with contextlib.suppress(OverflowError, OSError, ValueError):
            moment = datetime.datetime.fromtimestamp(value, tz=datetime.UTC)
    elif isinstance(value, datetime.date):
        moment = value
    elif isinstance(value, str):
        moment = _from_text(value)
    if isinstance(moment, datetime.datetime):
        if moment.tzinfo is None:
            return moment.replace(tzinfo=datetime.UTC)
        return moment.astimezone(datetime.UTC)
    return moment


def iso_week(value: object) -> str | None:
    """Return the ISO week of a timestamp.

    Args:
        value: An ISO 8601 string, a date or time, or epoch seconds.

    Returns:
        The week as `YYYY-Www`, or None when the value is not a time.
    """
    moment = _moment(value)
    if moment is None:
        return None
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def week_range(first: str, last: str) -> list[str]:
    """List every ISO week from `first` to `last`, both included.

    Args:
        first: The first week, `YYYY-Www`.
        last: The last week, `YYYY-Www`.

    Returns:
        The weeks in order; empty when `last` is before `first`.
    """
    start = datetime.date.fromisocalendar(int(first[:4]), int(first[6:]), 1)
    end = datetime.date.fromisocalendar(int(last[:4]), int(last[6:]), 1)
    weeks = []
    while start <= end:
        year, week, _ = start.isocalendar()
        weeks.append(f"{year}-W{week:02d}")
        start += datetime.timedelta(weeks=1)
    return weeks


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
            current = path / audit.FILE_NAME
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
                if isinstance(value, dict) and "request_id" in value:
                    records.append(value)
                else:
                    skipped += 1
    return records, skipped


def user_of(record: dict[str, Any]) -> tuple[str, bool]:
    """Name the user of an audit record.

    Args:
        record: The audit record.

    Returns:
        The `user_name` and True, or `legacy` and False for a record
        written before stage 17.
    """
    value = record.get("user_name")
    if isinstance(value, str) and value:
        return value, True
    return LEGACY_USER, False


def read_votes(path: pathlib.Path | None) -> list[Vote] | None:
    """Read the thumbs votes of the `feedback` table (stage 18).

    Args:
        path: The pilot store, or None.

    Returns:
        The votes (1 per answer and user), or None when the store is
        absent or unreadable.
    """
    if path is None or not path.is_file():
        return None
    try:
        rows = pilot.PilotStore(path).feedback()
    except errors.PilotStoreError as error:
        logger.warning("feedback table unreadable: %s", error)
        return None
    return [Vote(row.vote == "up", iso_week(row.created_at)) for row in rows]


def _corpus_tickers(files: object, added: dict[str, Any]) -> set[str]:
    """The tickers of the zip files: every listed file not under `added`."""
    tickers = set()
    for name in files if isinstance(files, list) else ():
        if isinstance(name, str) and name not in added:
            match = TICKER_PATTERN.match(name)
            if match:
                tickers.add(match.group(1))
    return tickers


def read_additions(path: pathlib.Path | None) -> list[Addition] | None:
    """Read the companies that `keel add` brought in (stage 14).

    A manifest entry under `added` with `source: edgar` names a file that
    `keel add` or `keel refresh` wrote. A ticker of the original zip that
    gets a newer filing through the refresh is not a company added. The
    entries carry no time, so the week is that of the earliest
    modification time of the ticker's corpus files next to the manifest.

    Args:
        path: The corpus manifest, or None.

    Returns:
        1 addition per ticker, an empty list when the manifest has none,
        or None when the manifest is absent or unreadable.
    """
    if path is None or not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        logger.warning("manifest unreadable: %s", error)
        return None
    if not isinstance(manifest, dict):
        return []
    added = manifest.get("added")
    added = added if isinstance(added, dict) else {}
    original = _corpus_tickers(manifest.get("files"), added)
    first: dict[str, datetime.datetime | None] = {}
    for name, entry in added.items():
        if not isinstance(entry, dict) or entry.get("source") != "edgar":
            continue
        ticker = str(entry.get("ticker") or "").upper()
        if not ticker or ticker in original:
            continue
        file = path.parent / pathlib.PurePath(str(name)).name
        when = (
            datetime.datetime.fromtimestamp(
                file.stat().st_mtime, tz=datetime.UTC
            )
            if file.is_file()
            else None
        )
        known = first.get(ticker)
        if ticker not in first or (when and (known is None or when < known)):
            first[ticker] = when
    return [
        Addition(ticker, iso_week(when))
        for ticker, when in sorted(first.items())
    ]


def read_refreshed(path: pathlib.Path | None) -> list[str | None] | None:
    """Read the weeks of the filings `keel refresh` added (stage 20).

    Args:
        path: The refresh log, or None.

    Returns:
        The ISO week of each `added` line of a real run (not a dry run),
        or None when the log is absent or unreadable.
    """
    if path is None or not path.is_file():
        return None
    try:
        entries = refresh.read_log(path)
    except errors.KeelError as error:
        logger.warning("refresh log unreadable: %s", error)
        return None
    return [
        iso_week(entry.time)
        for entry in entries
        if entry.event == "added" and not entry.dry_run
    ]


def _rate(positive: int, total: int) -> float | None:
    return positive / total if total else None


@dataclasses.dataclass
class _Tally:
    """The running counts per week while the records are read."""

    users: dict[str, set[str]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(set)
    )
    questions: collections.Counter[str] = dataclasses.field(
        default_factory=collections.Counter
    )
    cost: dict[str, float] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(float)
    )
    outcomes: collections.Counter[str] = dataclasses.field(
        default_factory=collections.Counter
    )
    all_users: set[str] = dataclasses.field(default_factory=set)
    named_user: bool = False
    undated: int = 0

    def add(self, record: dict[str, Any], week: str) -> None:
        """Count 1 question record in its week."""
        user, named = user_of(record)
        self.named_user = self.named_user or named
        self.users[week].add(user)
        self.all_users.add(user)
        self.questions[week] += 1
        value = record.get("cost_usd")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self.cost[week] += float(value)
        self.outcomes[str(record.get("outcome") or "unknown")] += 1


def compute(  # pylint: disable=too-many-arguments,too-many-locals
    records: Sequence[dict[str, Any]],
    votes: Sequence[Vote] | None = None,
    additions: Sequence[Addition] | None = None,
    refreshed: Sequence[str | None] | None = None,
    *,
    since: str | None = None,
    exclude_users: Iterable[str] = (),
    files: Sequence[str] = (),
    skipped_lines: int = 0,
) -> Metrics:
    """Compute the weekly and overall pilot metrics.

    Args:
        records: The audit records.
        votes: The feedback votes, or None when the table is absent.
        additions: The tickers added by `keel add`, or None.
        refreshed: The week of each filing the refresh added, or None.
        since: The ISO week the pilot starts; earlier entries are left
            out, and it is week 1 of the success metrics.
        exclude_users: Users left out of every count (the engineer).
        files: The audit files read, for the report.
        skipped_lines: The lines that were not a JSON object.

    Returns:
        The metrics.
    """
    excluded = set(exclude_users)
    tally = _Tally()
    seen: set[str] = set()

    def keep(week: str | None) -> bool:
        return week is not None and (since is None or week >= since)

    for record in records:
        week = iso_week(record.get("timestamp"))
        if week is None:
            tally.undated += 1
        elif keep(week) and user_of(record)[0] not in excluded:
            tally.add(record, week)
            seen.add(week)
    vote_weeks: dict[str, list[bool]] = collections.defaultdict(list)
    for vote in votes or ():
        if keep(vote.week):
            vote_weeks[str(vote.week)].append(vote.positive)
    # An addition without a corpus file has no week; it still counts.
    kept_additions = [
        a for a in additions or () if a.week is None or keep(a.week)
    ]
    added_weeks = collections.Counter(a.week for a in kept_additions if a.week)
    refresh_weeks = collections.Counter(w for w in refreshed or () if keep(w))
    seen.update(vote_weeks, (str(w) for w in added_weeks))
    seen.update(str(w) for w in refresh_weeks)
    if since is not None and seen:
        seen.add(since)
    rows = []
    for week in week_range(min(seen), max(seen)) if seen else ():
        week_votes = vote_weeks.get(week, [])
        count = tally.questions[week]
        rows.append(
            Week(
                week=week,
                active_users=len(tally.users.get(week, ())),
                questions=count,
                cost_usd=round(tally.cost[week], 6),
                cost_per_question=round(tally.cost[week] / count, 6)
                if count
                else None,
                thumbs_up_rate=_rate(sum(week_votes), len(week_votes)),
                votes=len(week_votes),
                memos_exported=None,
                companies_added=added_weeks[week]
                if additions is not None
                else None,
                filings_refreshed=refresh_weeks[week]
                if refreshed is not None
                else None,
            )
        )
    all_votes = [v for week in vote_weeks.values() for v in week]
    return Metrics(
        weeks=tuple(rows),
        outcomes=dict(tally.outcomes.most_common()),
        users=len(tally.all_users),
        questions=sum(tally.questions.values()),
        cost_usd=round(sum(tally.cost.values()), 6),
        thumbs_up_rate=_rate(sum(all_votes), len(all_votes)),
        votes=len(all_votes),
        memos_exported=None,
        companies_added=len(kept_additions) if additions is not None else None,
        filings_refreshed=sum(refresh_weeks.values())
        if refreshed is not None
        else None,
        files=tuple(files),
        skipped_lines=skipped_lines,
        undated_records=tally.undated,
        sources={
            "user_name": tally.named_user,
            "feedback_table": votes is not None,
            "export_log": False,
            "manifest": additions is not None,
            "refresh_log": refreshed is not None,
        },
    )


def _every_week_from(
    values: Sequence[int], from_week: int, target: int
) -> bool | None:
    """True when every week from `from_week` (1-based) meets the target."""
    tail = values[from_week - 1 :]
    if not tail:
        return None
    return all(value >= target for value in tail)


def targets(metrics: Metrics) -> list[dict[str, Any]]:
    """Check the success metrics of chapter 27.6 step 3.

    Week 1 is the first week of the metrics (`--since` sets it).

    Args:
        metrics: The computed metrics.

    Returns:
        1 row per metric: the name, the target, the value, and whether it
        holds (None while the pilot has too few weeks or the source is
        absent).
    """
    users = [w.active_users for w in metrics.weeks]
    questions = [w.questions for w in metrics.weeks]
    rate = metrics.thumbs_up_rate
    memos = metrics.memos_exported
    return [
        {
            "metric": "active users each week",
            "target": f">= {TARGET_ACTIVE_USERS} of 5 from week "
            f"{ACTIVE_USERS_FROM_WEEK}",
            "value": min(users[ACTIVE_USERS_FROM_WEEK - 1 :], default=None),
            "holds": _every_week_from(
                users, ACTIVE_USERS_FROM_WEEK, TARGET_ACTIVE_USERS
            ),
        },
        {
            "metric": "questions each week",
            "target": f">= {TARGET_WEEKLY_QUESTIONS} from week "
            f"{QUESTIONS_FROM_WEEK}",
            "value": min(questions[QUESTIONS_FROM_WEEK - 1 :], default=None),
            "holds": _every_week_from(
                questions, QUESTIONS_FROM_WEEK, TARGET_WEEKLY_QUESTIONS
            ),
        },
        {
            "metric": "thumbs-up rate",
            "target": f">= {TARGET_THUMBS_UP:.0%}",
            "value": rate,
            "holds": None if rate is None else rate >= TARGET_THUMBS_UP,
        },
        {
            "metric": "memos exported",
            "target": f">= {TARGET_MEMOS}",
            "value": memos,
            "holds": None if memos is None else memos >= TARGET_MEMOS,
        },
    ]


def decision(rows: Sequence[dict[str, Any]]) -> str:
    """State the week 4 rule of chapter 27.6 step 4 on the target rows.

    Args:
        rows: The rows of `targets`.

    Returns:
        1 sentence with the metrics that hold and the ones still open.
    """
    held = sum(1 for row in rows if row["holds"] is True)
    open_rows = sum(1 for row in rows if row["holds"] is None)
    if held >= METRICS_TO_CONTINUE:
        verdict = "continue to phase 2"
    elif held + open_rows >= METRICS_TO_CONTINUE:
        verdict = "too early to decide"
    else:
        verdict = "fix the top 3 feedback reasons and run 2 more weeks"
    return (
        f"{held} of {len(rows)} metrics hold, {open_rows} open: {verdict}. "
        "Hours saved (step 3) come from the users, not from the logs."
    )


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
        "| Thumbs-up rate | Votes | Memos exported | Companies added "
        "| Filings refreshed |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for w in metrics.weeks:
        lines.append(
            f"| {w.week} | {w.active_users} | {w.questions} "
            f"| {w.cost_usd:.2f} | {_cell(w.cost_per_question)} "
            f"| {_percent(w.thumbs_up_rate)} | {w.votes} "
            f"| {_cell(w.memos_exported)} | {_cell(w.companies_added)} "
            f"| {_cell(w.filings_refreshed)} |"
        )
    per_question = (
        metrics.cost_usd / metrics.questions if metrics.questions else None
    )
    lines.append(
        f"| Total | {metrics.users} | {metrics.questions} "
        f"| {metrics.cost_usd:.2f} | {_cell(per_question)} "
        f"| {_percent(metrics.thumbs_up_rate)} | {metrics.votes} "
        f"| {_cell(metrics.memos_exported)} "
        f"| {_cell(metrics.companies_added)} "
        f"| {_cell(metrics.filings_refreshed)} |"
    )
    lines += ["", "| Outcome | Questions |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in metrics.outcomes.items()]
    rows = targets(metrics)
    lines += [
        "",
        "| Success metric (27.6) | Target | Value | Holds |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        metric, target, value, holds = (
            row["metric"],
            row["target"],
            row["value"],
            row["holds"],
        )
        shown = _percent(value) if metric == "thumbs-up rate" else value
        lines.append(
            f"| {metric} | {target} | {_cell(shown)} | {_cell(holds)} |"
        )
    lines += [
        "",
        f"Decision rule (27.6 step 4): {decision(rows)}",
        "",
        f"Files read: {len(metrics.files)}; lines skipped: "
        f"{metrics.skipped_lines}; records without a timestamp: "
        f"{metrics.undated_records}.",
    ]
    if not metrics.sources["user_name"]:
        lines.append(
            "No record carries a user_name: the legacy token counts as 1 user."
        )
    lines.append(
        "Memo exports leave no log line or audit record (stage 19): n/a."
    )
    absent = [
        k
        for k, found in metrics.sources.items()
        if not found and k not in ("user_name", "export_log")
    ]
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
    rows = targets(metrics)
    body["targets"] = rows
    body["decision"] = decision(rows)
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
        help="audit files or directories (default: <logs.dir>/audit.jsonl); "
        "the rotations next to each file are read too",
    )
    parser.add_argument(
        "--since",
        type=datetime.date.fromisoformat,
        default=None,
        help="the first day of the pilot (YYYY-MM-DD): its week is week 1, "
        "and earlier records are left out",
    )
    parser.add_argument(
        "--exclude-user",
        action="append",
        default=[],
        metavar="NAME",
        help="a user left out of every count, such as the engineer "
        "(repeatable)",
    )
    parser.add_argument(
        "--feedback-db",
        type=pathlib.Path,
        default=None,
        help="the pilot store with the feedback table (default: pilot.db, "
        "or <logs.dir>/pilot.sqlite)",
    )
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=None,
        help="the corpus manifest (default: corpus.manifest)",
    )
    parser.add_argument(
        "--refresh-log",
        type=pathlib.Path,
        default=None,
        help="the refresh log (default: <logs.dir>/refresh.log)",
    )
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        default=None,
        help="the YAML config (default: KEEL_CONFIG_FILE or config/keel.yaml)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print JSON instead of Markdown"
    )
    return parser


def resolve_sources(args: argparse.Namespace) -> Sources:
    """Fill the paths the command line left out from the config.

    Args:
        args: The parsed arguments.

    Returns:
        The paths to read.

    Raises:
        ConfigError: The config file is unreadable or not valid.
    """
    settings = config.load_settings(args.config, env_file=None)
    logs = settings.logs.dir
    return Sources(
        audit=tuple(args.audit) or (logs / audit.FILE_NAME,),
        feedback_db=args.feedback_db or pilot.db_path(settings),
        manifest=args.manifest or settings.corpus.manifest,
        refresh_log=args.refresh_log or refresh.log_path(settings),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the script.

    Args:
        argv: The arguments, or None for the command line.

    Returns:
        0 after the report, 1 when no audit file exists or the config
        fails to load.
    """
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = build_parser().parse_args(argv)
    try:
        sources = resolve_sources(args)
    except errors.ConfigError as error:
        logger.error("%s", error)
        return 1
    files = audit_files(sources.audit)
    if not files:
        logger.error(
            "no audit file found in %s", [str(p) for p in sources.audit]
        )
        return 1
    records, skipped = read_records(files)
    metrics = compute(
        records,
        votes=read_votes(sources.feedback_db),
        additions=read_additions(sources.manifest),
        refreshed=read_refreshed(sources.refresh_log),
        since=iso_week(args.since) if args.since else None,
        exclude_users=args.exclude_user,
        files=[str(f) for f in files],
        skipped_lines=skipped,
    )
    print(to_json(metrics) if args.json else to_markdown(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
