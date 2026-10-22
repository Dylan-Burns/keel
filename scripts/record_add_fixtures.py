"""Record the `keel add` test fixtures once, with the network.

The tests never touch the network (chapter 26.5), so `test_submissions_pick`,
`test_html_to_text`, and `test_add_incremental` read responses recorded by
this script. It fetches the ZTS submissions and the primary documents of the
latest ZTS 10-K and 10-Q through `keel.edgar.EdgarClient` (the same
User-Agent, rate limit, and allow list as production), then trims them:

- the submissions keep the company keys, the newest 40 rows, and every
  periodic report row (10-K, 10-Q, and their amendments);
- each document keeps its head, 3 of the hidden XBRL facts in the
  `ix:header`, a few whole pages cut at the page-break rules (the cover
  page, the start of the risk factors or the MD&A, and a page with a
  table), and the closing script and tags. The 10-K sample is about 60 KB.

The files land in the cache layout under `tests/fixtures/edgar/`, so a test
copies that directory as the cache of an offline client.

Run from the repository root:

    uv run python scripts/record_add_fixtures.py
"""

from __future__ import annotations

import argparse
import itertools
import pathlib
import re
import tempfile

from keel import config
from keel import edgar

TICKER = "ZTS"
KEEP_FILINGS = 40
HIDDEN_FACTS = 3
PAGE_BREAK = '<hr style="page-break-after:always"/>'
# The pages to keep per form, by a phrase of their text.
PAGES = {
    "10-K": (
        "SECURITIES AND EXCHANGE COMMISSION",
        "Item 1A. Risk Factors.",
        "Financing activities2025 vs. 2024",
    ),
    "10-Q": (
        "SECURITIES AND EXCHANGE COMMISSION",
        "Item 2.&#160;&#160;&#160;&#160;Management&#8217;s Discussion",
    ),
}
DEFAULT_OUT = pathlib.Path("tests/fixtures/edgar")
_TAGS = re.compile(r"<[^>]+>")
_FACT = re.compile(r"<ix:nonNumeric\b.*?</ix:nonNumeric>", re.DOTALL)


def trim_submissions(document: edgar.CachedDocument) -> edgar.CachedDocument:
    """Keep the company keys, the newest rows, and every periodic report.

    Args:
        document: The cached submissions of the company.

    Returns:
        The document with the trimmed body and the same fetch time.

    Raises:
        KeyError: The body has no `filings.recent` arrays.
    """
    data = document.data
    recent = data["filings"]["recent"]
    rows = [
        index
        for index, form in enumerate(recent["form"])
        if index < KEEP_FILINGS or form.startswith("10-")
    ]
    kept = {key: [values[i] for i in rows] for key, values in recent.items()}
    trimmed = {
        key: data[key]
        for key in ("cik", "name", "tickers", "exchanges", "fiscalYearEnd")
        if key in data
    }
    trimmed["filings"] = {"recent": kept, "files": []}
    return document.model_copy(update={"data": trimmed})


def trim_document(html: str, phrases: tuple[str, ...]) -> str:
    """Keep the head, 3 hidden facts, the chosen pages, and the tail.

    Args:
        html: The document text.
        phrases: 1 phrase of the text of each page to keep, in order.

    Returns:
        The sample document.

    Raises:
        ValueError: The document has no body, ix:header, or script.
        StopIteration: No page holds a phrase.
    """
    body = html.index("<body>") + len("<body>")
    header_end = html.index("</ix:header>")
    facts = _FACT.findall(html, body, header_end)[:HIDDEN_FACTS]
    hidden = (
        '<div style="display:none"><ix:header><ix:hidden>'
        + "".join(facts)
        + "</ix:hidden></ix:header></div>"
    )
    starts = [header_end + len("</ix:header></div>")]
    starts += [m.end() for m in re.finditer(re.escape(PAGE_BREAK), html)]
    pages = [html[a:b] for a, b in itertools.pairwise(starts)]
    chosen = []
    for phrase in phrases:
        page = next(
            p for p in pages if phrase in _TAGS.sub("", p) and p not in chosen
        )
        chosen.append(page)
    tail = html[html.rindex("<script") :]
    return html[:body] + hidden + "".join(chosen) + tail


def main() -> int:
    """Fetch, trim, and write the fixtures.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    settings = config.load_settings()
    out: pathlib.Path = args.out
    with tempfile.TemporaryDirectory() as scratch:
        client = edgar.EdgarClient(
            settings.edgar.user_agent,
            pathlib.Path(scratch),
            min_interval=settings.edgar.min_request_interval_seconds,
        )
        with client:
            cik = client.cik(TICKER)
            submissions = client.submissions(cik)
            edgar.write_cached(
                out / "submissions" / f"CIK{cik}.json",
                trim_submissions(submissions),
            )
            for ref in edgar.pick_latest(submissions.data):
                html = client.filing_document(ref).decode("ascii")
                sample = trim_document(html, PAGES[ref.form]).encode("ascii")
                path = client.document_path(ref)
                target = out / path.relative_to(client.cache_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(sample)
                sidecar = edgar.read_cached(path.with_name(path.name + ".json"))
                edgar.write_cached(
                    target.with_name(target.name + ".json"),
                    sidecar.model_copy(
                        update={
                            "data": {
                                "bytes": len(sample),
                                "form": ref.form,
                                "sample_of_bytes": len(html),
                            }
                        }
                    ),
                )
                print(f"{ref.form} {ref.accession}: {len(sample):,} bytes")
    print(f"{TICKER} CIK {cik}; wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
