"""Record the EDGAR test fixtures once, with the network.

The tests never touch the network (chapter 26.5), so they read responses
recorded by this script. It fetches the ticker map and the company facts of
NVDA through `keel.edgar.EdgarClient` (the same User-Agent, rate limit, and
allow list as production), trims both to keep the fixtures small, and
writes them in the cache format, with the fetch time, under
`tests/fixtures/edgar/`.

Run from the repository root:

    uv run python scripts/record_edgar_fixtures.py
"""

from __future__ import annotations

import argparse
import pathlib
import tempfile

from keel import config
from keel import edgar

TICKERS = (
    "NVDA",
    "AAPL",
    "MSFT",
    "JPM",
    "ZTS",
    "WDAY",
    "BRK-B",
    "AMD",
    "INTC",
)
FACTS_TICKER = "NVDA"
DEFAULT_OUT = pathlib.Path("tests/fixtures/edgar")


def _trim_tickers(document: edgar.CachedDocument) -> edgar.CachedDocument:
    """Keep the ticker map rows of `TICKERS`, with their original keys."""
    rows = {
        key: row
        for key, row in document.data.items()
        if str(row.get("ticker")) in TICKERS
    }
    return document.model_copy(update={"data": rows})


def _trim_facts(
    document: edgar.CachedDocument, facts_config: edgar.FactsConfig
) -> edgar.CachedDocument:
    """Keep the XBRL names of `config/facts.yaml` and drop their labels."""
    wanted = {name for c in facts_config.concepts for name in c.names}
    facts: dict[str, dict[str, object]] = {}
    for taxonomy, items in document.data["facts"].items():
        for local, item in items.items():
            if f"{taxonomy}:{local}" in wanted:
                facts.setdefault(taxonomy, {})[local] = {"units": item["units"]}
    data = {
        "cik": document.data["cik"],
        "entityName": document.data["entityName"],
        "facts": facts,
    }
    return document.model_copy(update={"data": data})


def main() -> int:
    """Fetch, trim, and write the fixtures.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    settings = config.load_settings()
    facts_config = edgar.load_facts_config(settings.edgar.facts)
    with tempfile.TemporaryDirectory() as scratch:
        client = edgar.EdgarClient(
            settings.edgar.user_agent,
            pathlib.Path(scratch),
            min_interval=settings.edgar.min_request_interval_seconds,
        )
        with client:
            tickers = client.ticker_map()
            cik = tickers.cik(FACTS_TICKER)
            ticker_doc = edgar.read_cached(client.ticker_map_path())
            facts_doc = client.company_facts(cik)
    out = args.out
    edgar.write_cached(out / "company_tickers.json", _trim_tickers(ticker_doc))
    edgar.write_cached(
        out / "companyfacts" / f"CIK{cik}.json",
        _trim_facts(facts_doc, facts_config),
    )
    print(f"{len(tickers)} tickers; {FACTS_TICKER} CIK {cik}")
    print(f"fetched at {facts_doc.fetched_at.isoformat()}; wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
