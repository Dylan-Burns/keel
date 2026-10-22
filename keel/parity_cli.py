"""The CLI twins of the web pages: history, share links, coverage, jobs.

`keel history` prints the questions of the History page from the audit
log (every user, or `--user NAME`), newest first. `keel share REQUEST_ID`
prints the shareable link that **Copy link** gives: the path
`/a/<request ID>`, or a full URL with `--base-url`. `keel coverage`
prints the companies and filings of the coverage page from the current
index. `keel jobs` lists the admin jobs of the job runner from the state
store, and `keel jobs ID` shows 1 job with its log tail.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import dataclasses
import json
import re
from typing import Any

from keel import cache
from keel import config
from keel import coverage
from keel import errors
from keel import indexer
from keel import understanding
from keel.api import history as history_log
from keel.stores import admin_store
from keel.stores import chunk_store
from keel.stores import state_store

COMMANDS = frozenset({"history", "share", "coverage", "jobs"})
SHARE_PATH = "/a/"
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
BASE_URL = re.compile(r"^https?://[^\s/?#]+(?:/[^\s?#]*)?$")


def _limit(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a number: {value}") from error
    if not 1 <= number <= history_log.MAX_LIMIT:
        raise argparse.ArgumentTypeError(
            f"must be 1 to {history_log.MAX_LIMIT}: {value}"
        )
    return number


def add_parsers(add_command: Callable[..., argparse.ArgumentParser]) -> None:
    """Add the `history`, `share`, `coverage`, and `jobs` commands.

    Args:
        add_command: The `add_parser` of the `keel` subcommands.
    """
    history_parser = add_command(
        "history", help="the questions of the History page, newest first"
    )
    history_parser.add_argument(
        "--user", default=None, help="1 user's questions (default: every user)"
    )
    history_parser.add_argument(
        "--limit",
        type=_limit,
        default=history_log.DEFAULT_LIMIT,
        help=f"the most questions (default {history_log.DEFAULT_LIMIT})",
    )
    history_parser.add_argument(
        "--json", action="store_true", help="print JSON lines"
    )

    share_parser = add_command(
        "share", help="print the shareable link of an answer (/a/<ID>)"
    )
    share_parser.add_argument("request_id", help="the request ID")
    share_parser.add_argument(
        "--base-url",
        default=None,
        help="the pilot address, such as https://keel.example.com",
    )

    coverage_parser = add_command(
        "coverage", help="the companies and filings of the current index"
    )
    coverage_parser.add_argument(
        "--json", action="store_true", help="print the report as JSON"
    )

    jobs_parser = add_command(
        "jobs", help="list the admin jobs, or show 1 with its log"
    )
    jobs_parser.add_argument(
        "job_id", nargs="?", default=None, help="the job ID to show"
    )
    jobs_parser.add_argument(
        "--limit", type=_limit, default=20, help="the most jobs (default 20)"
    )
    jobs_parser.add_argument("--json", action="store_true", help="print JSON")


def run(
    settings: config.Settings, args: argparse.Namespace
) -> tuple[int, list[str]]:
    """Run 1 of the commands; `keel.cli` prints the lines.

    Args:
        settings: The loaded settings.
        args: The parsed arguments.

    Returns:
        The exit code and the lines to print.

    Raises:
        IndexMissingError: `keel coverage` without a published index.
        StateStoreError: The state store cannot be read.
    """
    if args.command == "history":
        return run_history(settings, args.user, args.limit, args.json)
    if args.command == "share":
        return run_share(settings, args.request_id, args.base_url)
    if args.command == "coverage":
        return run_coverage(settings, args.json)
    return run_jobs(settings, args.job_id, args.limit, args.json)


def run_history(
    settings: config.Settings, user: str | None, limit: int, as_json: bool
) -> tuple[int, list[str]]:
    """`keel history`: the questions of the audit log, newest first.

    Args:
        settings: The loaded settings.
        user: 1 user, or None for every user.
        limit: The most questions.
        as_json: Print 1 JSON object per line.

    Returns:
        0 and the lines; a question's control characters print as spaces.
    """
    items = history_log.history(
        settings.logs.dir,
        cache.AnswerCache(settings.cache.answers_dir),
        user,
        limit=limit,
    )
    if as_json:
        return 0, [item.model_dump_json() for item in items]
    lines = [
        "\t".join(
            (
                item.timestamp,
                item.request_id,
                item.user or "-",
                item.outcome or "-",
                f"${item.cost_usd:.4f}",
                "stored" if item.stored else "expired",
                _CONTROL.sub(" ", item.question),
            )
        )
        for item in items
    ]
    lines.append(f"{len(items)} questions from {settings.logs.dir}")
    return 0, lines


def share_link(request_id: str, base_url: str | None = None) -> str:
    """The shareable link of an answer, as **Copy link** builds it.

    Args:
        request_id: The request ID.
        base_url: The pilot address, or None for the path only.

    Returns:
        `/a/<request ID>`, or the address with that path.

    Raises:
        ValueError: The request ID or the address is malformed.
    """
    if not REQUEST_ID.match(request_id):
        raise ValueError("not a request ID")
    path = SHARE_PATH + request_id
    if not base_url:
        return path
    if not BASE_URL.match(base_url):
        raise ValueError("the base URL is http(s)://host[/path]")
    return base_url.rstrip("/") + path


def run_share(
    settings: config.Settings, request_id: str, base_url: str | None
) -> tuple[int, list[str]]:
    """`keel share`: the link, and whether the answer still opens.

    Args:
        settings: The loaded settings.
        request_id: The request ID.
        base_url: The pilot address, or None.

    Returns:
        0 when the audit log knows the request, else 1; the link line
        and a note.
    """
    try:
        link = share_link(request_id, base_url)
    except ValueError as error:
        return 1, [f"keel share: {error}"]
    record = history_log.find_record(settings.logs.dir, request_id)
    if record is None:
        return 1, [link, "note: the audit log has no question with this ID"]
    answers = cache.AnswerCache(settings.cache.answers_dir)
    key = history_log.cache_key_of(record)
    stored = key is not None and answers.path(key).is_file()
    note = (
        "the answer cache holds the answer: the link opens for any token"
        if stored
        else "the answer cache does not hold it: the link opens only for "
        "10 minutes after the answer, on the server that answered"
    )
    return 0, [link, f"note: {note}"]


def coverage_of(settings: config.Settings) -> dict[str, Any]:
    """The coverage report of the current index.

    Args:
        settings: The loaded settings.

    Returns:
        The report of `keel.coverage.coverage_report`.

    Raises:
        IndexMissingError: No published index.
    """
    build = indexer.current_build(settings.index.dir)
    if build is None:
        raise errors.IndexMissingError(
            f"no index at {settings.index.dir}/current; run keel index"
        )
    conn = chunk_store.open_read_only(build / chunk_store.FILE_NAME)
    try:
        catalog = understanding.Catalog.from_store(conn)
        return coverage.coverage_report(conn, catalog.quarantined)
    finally:
        conn.close()


def run_coverage(
    settings: config.Settings, as_json: bool
) -> tuple[int, list[str]]:
    """`keel coverage`: the companies, forms, and fiscal periods.

    Args:
        settings: The loaded settings.
        as_json: Print the report as JSON.

    Returns:
        0 and the lines.

    Raises:
        IndexMissingError: No published index.
    """
    report = coverage_of(settings)
    if as_json:
        return 0, [json.dumps(report, indent=2)]
    companies = report["companies"]
    quarantined = report["quarantined"]
    lines = []
    for company in companies:
        ticker, name = company["ticker"], company["company"]
        forms = ", ".join(company["forms"])
        periods = ", ".join(company["fiscal_periods"])
        lines.append(f"{ticker:<8} {forms:<12} {periods}  ({name})")
    for item in quarantined:
        ticker, file_name = item["ticker"], item["file_name"]
        reason = item["reason"]
        lines.append(f"quarantined: {ticker} {file_name}: {reason}")
    count = report["filing_count"]
    lines.append(
        f"{len(companies)} companies, {count} filings, "
        f"{len(quarantined)} quarantined"
    )
    return 0, lines


def _job_line(job: admin_store.JobRecord) -> str:
    total = "?" if job.total is None else str(job.total)
    return (
        f"{job.id}  {job.kind:<10} {job.status:<9} {job.done}/{total}  "
        f"{job.requested_by:<12} {job.created_at}  {job.phase}"
    )


def run_jobs(
    settings: config.Settings,
    job_id: str | None,
    limit: int,
    as_json: bool,
) -> tuple[int, list[str]]:
    """`keel jobs`: the admin jobs, or 1 job with its log tail.

    Args:
        settings: The loaded settings.
        job_id: The job to show, or None to list.
        limit: The most jobs listed.
        as_json: Print JSON.

    Returns:
        0, or 1 for an unknown job ID; and the lines.

    Raises:
        StateStoreError: The state database cannot be read.
    """
    path = state_store.state_path(settings)
    if job_id is None:
        jobs = admin_store.list_jobs(path, limit=limit)
        if as_json:
            return 0, [
                json.dumps({**dataclasses.asdict(j), "log": []}) for j in jobs
            ]
        return 0, [_job_line(j) for j in jobs] + [f"{len(jobs)} jobs in {path}"]
    job = admin_store.get_job(path, job_id)
    if job is None:
        return 1, [f"no job {job_id} in {path}"]
    if as_json:
        return 0, [json.dumps(dataclasses.asdict(job), indent=2)]
    lines = [_job_line(job), f"params: {json.dumps(job.params)}"]
    if job.started_at or job.finished_at:
        lines.append(f"started {job.started_at}, finished {job.finished_at}")
    if job.error:
        lines.append(f"error: {job.error}")
    if job.result is not None:
        lines.append(f"result: {json.dumps(job.result)}")
    lines.extend(f"  {line}" for line in job.log)
    return 0, lines
