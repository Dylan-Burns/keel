"""The companies and filings that the index covers.

`GET /api/coverage` (the watch list of the empty state and the coverage
page) and `keel coverage` print the same report: per ticker the company,
the forms, and the fiscal periods of the indexed filings, the filing
count, and the quarantined files with their reasons.
"""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3
from typing import Any

from keel import understanding


def fiscal_label(year: int | None, period: str | None) -> str:
    """The fiscal label of the prefix line, as `context.Candidate` names it.

    Args:
        year: The fiscal year, or None.
        period: The fiscal period (`FY`, `Q1` to `Q3`), or None.

    Returns:
        `FY2025`, `Q2 FY2025`, or `unknown`.
    """
    if year is None:
        return "unknown"
    if period in {None, "FY", "unknown"}:
        return f"FY{year}"
    return f"{period} FY{year}"


def coverage_report(
    conn: sqlite3.Connection,
    quarantined: Iterable[understanding.QuarantineNote],
) -> dict[str, Any]:
    """The coverage of an index.

    Args:
        conn: The chunk store with the `filings` table.
        quarantined: The quarantined files of the catalog.

    Returns:
        `companies` (ticker, company, forms, fiscal_periods), the
        `filing_count`, and the `quarantined` files (ticker, file_name,
        reason).
    """
    rows = conn.execute(
        "SELECT ticker, company, form, fiscal_year, fiscal_period "
        "FROM filings ORDER BY ticker, period_end_date, form"
    ).fetchall()
    companies: dict[str, dict[str, Any]] = {}
    for ticker, company, form, year, period in rows:
        entry = companies.setdefault(
            ticker,
            {"ticker": ticker, "company": company, "forms": [], "periods": []},
        )
        if form not in entry["forms"]:
            entry["forms"].append(form)
        label = fiscal_label(year, period)
        if label not in entry["periods"]:
            entry["periods"].append(label)
    return {
        "companies": [
            {
                "ticker": c["ticker"],
                "company": c["company"],
                "forms": sorted(c["forms"]),
                "fiscal_periods": c["periods"],
            }
            for c in companies.values()
        ],
        "filing_count": len(rows),
        "quarantined": [
            {"ticker": q.ticker, "file_name": q.file_name, "reason": q.reason}
            for q in quarantined
        ],
    }
