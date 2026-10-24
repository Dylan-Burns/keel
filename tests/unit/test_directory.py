"""The company browser: the SIC codes, the EDGAR company feed, the join.

The feed pages under `tests/fixtures/edgar_sic/` are recorded EDGAR
responses for SIC 3674 (fetched on 2026-10-24): the first page trimmed to
4 entries (a company without a ticker, AMD, Intel, NVIDIA) with its next
link, and the real last page of 6 entries. No test touches the network.
"""

from collections.abc import Callable
import datetime
import pathlib
import shutil
import socket
import sqlite3

import httpx
import pytest

import conftest
from keel import directory
from keel import edgar
from keel import errors

pytestmark = pytest.mark.unit

FEED = conftest.FIXTURES / "edgar_sic"
PAGE_1 = (FEED / "atom_3674_start0.xml").read_bytes()
PAGE_2 = (FEED / "atom_3674_start100.xml").read_bytes()
SIC_CODES = conftest.REPO_ROOT / "config" / "sic_codes.yaml"
USER_AGENT = "Keel Test test@example.com"
NVDA, AMD, INTC = "0001045810", "0000002488", "0000050863"
NOW = datetime.datetime(2026, 10, 25, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise OSError(f"network access in a test: {args}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


class Feed:
    """A mock EDGAR that serves the 2 recorded pages by offset."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if self.status != 200:
            return httpx.Response(self.status)
        start = request.url.params.get("start")
        return httpx.Response(200, content=PAGE_1 if start == "0" else PAGE_2)


def make_client(
    cache: pathlib.Path,
    handler: Callable[[httpx.Request], httpx.Response],
    offline: bool = False,
) -> edgar.EdgarClient:
    return edgar.EdgarClient(
        USER_AGENT,
        cache,
        offline=offline,
        min_interval=0.0,
        transport=conftest.peer_transport(handler),
        resolver=lambda host: ["93.184.215.14"],
    )


def ticker_map() -> edgar.TickerMap:
    return edgar.TickerMap(
        [
            edgar.TickerEntry(ticker="NVDA", cik=NVDA, title="NVIDIA CORP"),
            edgar.TickerEntry(
                ticker="AMD", cik=AMD, title="ADVANCED MICRO DEVICES INC"
            ),
            edgar.TickerEntry(ticker="INTC", cik=INTC, title="INTEL CORP"),
            edgar.TickerEntry(
                ticker="BRK-B", cik="0001067983", title="BERKSHIRE HATHAWAY"
            ),
            edgar.TickerEntry(
                ticker="BRK-A", cik="0001067983", title="BERKSHIRE HATHAWAY"
            ),
        ]
    )


# --- The SIC codes ------------------------------------------------------------


def test_sic_codes_load_and_group() -> None:
    """The committed list loads; offices become sectors."""
    industries = directory.load_sic_codes(SIC_CODES)
    by_code = {i.code: i for i in industries}
    assert len(industries) > 400
    assert by_code["3674"].title == "SEMICONDUCTORS & RELATED DEVICES"
    assert by_code["3674"].sector == "Manufacturing"
    assert by_code["2834"].sector == "Life Sciences"
    assert by_code["0100"].sector == "Industrial Applications and Services"
    # An office of 2 names files under the first.
    assert by_code["6211"].sector == "Finance"
    names = [name for name, _ in directory.sectors(industries)]
    assert names == sorted(names)
    assert "Technology" in names


def test_sic_codes_reject_bad_rows(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "sic.yaml"
    path.write_text("industries: []\n", encoding="utf-8")
    with pytest.raises(errors.ConfigError):
        directory.load_sic_codes(path)
    row = '{code: "3674", office: "Office of Manufacturing", title: "SEMIS"}'
    path.write_text(f"industries:\n  - {row}\n  - {row}\n", encoding="utf-8")
    with pytest.raises(errors.ConfigError, match="repeats"):
        directory.load_sic_codes(path)
    path.write_text('industries:\n  - {code: "36x4"}\n', encoding="utf-8")
    with pytest.raises(errors.ConfigError, match="invalid"):
        directory.load_sic_codes(path)


def test_sector_of() -> None:
    assert directory.sector_of("Office of Technology") == "Technology"
    assert (
        directory.sector_of(
            "Office of Trade & Services or Office of Energy & Transportation"
        )
        == "Trade & Services"
    )
    assert directory.sector_of("Multiple Offices") == "Multiple Offices"


# --- The feed parser ----------------------------------------------------------


def test_parse_feed_recorded_pages() -> None:
    """The recorded pages give their CIKs and the next link."""
    first = directory.parse_feed(PAGE_1)
    assert first.ciks == ("0001025881", AMD, INTC, NVDA)
    assert first.has_next is True
    last = directory.parse_feed(PAGE_2)
    assert len(last.ciks) == 6
    assert last.has_next is False


@pytest.mark.parametrize(
    "body",
    [
        b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "x">]><feed/>',
        b'<?xml version="1.0"?><!doctype feed SYSTEM "http://x/"><feed/>',
    ],
)
def test_parse_feed_rejects_doctype_and_entities(body: bytes) -> None:
    with pytest.raises(errors.EdgarFetchError, match="document type"):
        directory.parse_feed(body)


@pytest.mark.parametrize(
    "body",
    [
        '<?xml version="1.0" encoding="UTF-16"?><feed/>'.encode("utf-16"),
        b'<?xml version="1.0" encoding="cp037"?>'
        + '<!DOCTYPE feed [<!ENTITY a "x">]><feed/>'.encode("cp037"),
    ],
)
def test_parse_feed_rejects_other_encodings(body: bytes) -> None:
    """A declaration in a non-ASCII encoding would pass the byte check."""
    with pytest.raises(errors.EdgarFetchError, match="encoding"):
        directory.parse_feed(body)


def test_fetch_stops_past_the_byte_limit(tmp_path: pathlib.Path) -> None:
    """The client stops reading the decoded body past the limit."""
    with (
        make_client(tmp_path, Feed()) as client,
        pytest.raises(errors.EdgarFetchError, match="more than 100 bytes"),
    ):
        client.fetch(directory.feed_url("3674", 0), max_bytes=100)
    with make_client(tmp_path, Feed()) as client:
        body = client.fetch(directory.feed_url("3674", 0), max_bytes=10**6)
    assert body == PAGE_1


def test_parse_feed_rejects_large_and_broken_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(directory, "MAX_FEED_BYTES", 100)
    with pytest.raises(errors.EdgarFetchError, match="bytes"):
        directory.parse_feed(PAGE_2)
    monkeypatch.setattr(directory, "MAX_FEED_BYTES", 2_000_000)
    with pytest.raises(errors.EdgarFetchError, match="not XML"):
        directory.parse_feed(b"<feed><entry></feed>")


def test_parse_feed_skips_entries_without_a_cik() -> None:
    body = (
        b'<feed xmlns="http://www.w3.org/2005/Atom">'
        b"<entry><content><company-info><cik>abc</cik></company-info>"
        b"</content></entry><entry/></feed>"
    )
    assert directory.parse_feed(body).ciks == ()


# --- The cache ----------------------------------------------------------------


def test_industry_pages_and_caches(tmp_path: pathlib.Path) -> None:
    """The first call pages through the feed; the second reads the cache."""
    feed = Feed()
    with make_client(tmp_path, feed) as client:
        listed = directory.industry_ciks(client, "3674", ttl_days=30)
        assert listed.requests == 2
        assert len(listed.ciks) == 10
        assert listed.stale is False
        assert "SIC=3674" in feed.urls[0]
        assert "start=0" in feed.urls[0]
        assert "start=100" in feed.urls[1]
        again = directory.industry_ciks(client, "3674", ttl_days=30)
    assert again.requests == 0
    assert again.ciks == listed.ciks
    assert len(feed.urls) == 2
    assert (tmp_path / "sic" / "3674.json").is_file()


def test_industry_refetches_after_the_ttl(tmp_path: pathlib.Path) -> None:
    feed = Feed()
    with make_client(tmp_path, feed) as client:
        first = directory.industry_ciks(client, "3674", ttl_days=30)
        later = first.fetched_at + datetime.timedelta(days=31)
        directory.industry_ciks(client, "3674", ttl_days=30, now=later)
    assert len(feed.urls) == 4


def test_industry_serves_stale_when_the_refresh_fails(
    tmp_path: pathlib.Path,
) -> None:
    with make_client(tmp_path, Feed()) as client:
        first = directory.industry_ciks(client, "3674", ttl_days=30)
    later = first.fetched_at + datetime.timedelta(days=31)
    with make_client(tmp_path, Feed(status=503)) as client:
        stale = directory.industry_ciks(client, "3674", ttl_days=30, now=later)
    assert stale.stale is True
    assert stale.ciks == first.ciks


def test_industry_fetch_error_without_cache(tmp_path: pathlib.Path) -> None:
    with (
        make_client(tmp_path, Feed(status=500)) as client,
        pytest.raises(errors.EdgarFetchError),
    ):
        directory.industry_ciks(client, "3674", ttl_days=30)


def test_industry_offline_reads_cache_only(tmp_path: pathlib.Path) -> None:
    """Offline, the cache serves whatever its age; a miss raises."""
    feed = Feed()
    with make_client(tmp_path, feed, offline=True) as client:
        with pytest.raises(errors.EdgarCacheMissError):
            directory.industry_ciks(client, "3674", ttl_days=30)
        shutil.copytree(conftest.FIXTURES / "edgar" / "sic", tmp_path / "sic")
        old = NOW + datetime.timedelta(days=400)
        listed = directory.industry_ciks(client, "3674", ttl_days=30, now=old)
    assert feed.urls == []
    assert len(listed.ciks) == 506
    assert NVDA in listed.ciks


def test_industry_stops_at_the_page_limit(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(directory, "MAX_PAGES", 1)
    with make_client(tmp_path, Feed()) as client:
        listed = directory.industry_ciks(client, "3674", ttl_days=30)
    assert listed.truncated is True
    assert listed.requests == 1


def test_bad_cache_file_is_skipped(tmp_path: pathlib.Path) -> None:
    path = directory.cache_path(tmp_path, "3674")
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    assert directory.read_industry(tmp_path, "3674") is None
    with pytest.raises(errors.EdgarError):
        directory.cache_path(tmp_path, "../x")


# --- The join -----------------------------------------------------------------


def test_join_keeps_ciks_with_a_ticker() -> None:
    """A CIK without a ticker is left out; the rest sort by ticker."""
    marks = directory.Marks(
        indexed_ciks=frozenset({NVDA}), watched=frozenset({"INTC"})
    )
    companies = directory.join_companies(
        directory.parse_feed(PAGE_1).ciks, ticker_map(), marks
    )
    assert [c.ticker for c in companies] == ["AMD", "INTC", "NVDA"]
    by = {c.ticker: c for c in companies}
    assert by["NVDA"].indexed is True
    assert by["NVDA"].watched is False
    assert by["INTC"].watched is True
    assert by["INTC"].indexed is False
    assert by["AMD"].name == "ADVANCED MICRO DEVICES INC"


def test_share_classes_join_under_the_first_ticker() -> None:
    tickers = ticker_map()
    rows = tickers.by_cik("1067983")
    assert [r.ticker for r in rows] == ["BRK-B", "BRK-A"]
    marks = directory.Marks(indexed_tickers=frozenset({"BRK.A"}))
    company = directory.company_of(rows, marks)
    assert company is not None
    assert company.ticker == "BRK-B"
    assert company.tickers == ("BRK-B", "BRK-A")
    assert company.indexed is True
    assert company.addable is True
    digits = edgar.TickerEntry(ticker="X1", cik="0000000009", title="X ONE")
    lone = directory.company_of((digits,), marks)
    assert lone is not None
    assert lone.addable is False
    assert directory.company_of((), marks) is None
    assert tickers.by_cik("0000000001") == ()
    assert len(list(tickers)) == 5


def test_search_ranks_ticker_then_name() -> None:
    marks = directory.Marks()
    tickers = ticker_map()
    assert [c.ticker for c in directory.search(tickers, "intc", marks)] == [
        "INTC"
    ]
    assert [c.ticker for c in directory.search(tickers, "in", marks)] == [
        "INTC",
        "AMD",
    ]
    assert directory.search(tickers, "nvidia", marks)[0].ticker == "NVDA"
    berkshire = directory.search(tickers, "brk", marks)
    assert [c.ticker for c in berkshire] == ["BRK-B"]
    assert directory.search(tickers, "brk.a", marks)[0].ticker == "BRK-B"
    assert directory.search(tickers, " x ", marks) == []
    assert len(directory.search(tickers, "c", marks)) == 0
    assert len(directory.search(tickers, "in", marks, limit=1)) == 1


def test_indexed_marks_read_the_current_build(tmp_path: pathlib.Path) -> None:
    assert directory.indexed_marks(tmp_path).indexed_ciks == frozenset()
    build = tmp_path / "builds" / "b1"
    build.mkdir(parents=True)
    conn = sqlite3.connect(build / "chunks.sqlite")
    conn.execute("CREATE TABLE filings (ticker TEXT, cik TEXT)")
    conn.executemany(
        "INSERT INTO filings VALUES (?, ?)",
        [("NVDA", "1045810"), ("BRK.B", None), ("X", "bad")],
    )
    conn.commit()
    conn.close()
    (tmp_path / "current").symlink_to(build)
    marks = directory.indexed_marks(tmp_path, ["ZTS"])
    assert marks.indexed_ciks == frozenset({NVDA})
    assert marks.indexed_tickers == frozenset({"NVDA", "BRK.B", "X"})
    assert marks.watched == frozenset({"ZTS"})
