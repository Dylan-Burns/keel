"""The active 10-K and 10-Q filers of the company browser.

The index bodies are short copies of the EDGAR `xbrl.idx` format: the
recorded header of 2022 QTR1 (fetched on 2026-10-24), then a few lines.
No test touches the network.
"""

from collections.abc import Callable
import datetime
import pathlib
import socket

import httpx
import pytest

import conftest
from keel import edgar
from keel import errors
from keel import filers

pytestmark = pytest.mark.unit

USER_AGENT = "Keel Test test@example.com"
HEADER = (
    "Description:           XBRL Index of EDGAR Dissemination Feed\n"
    "Last Data Received:    March 31, 2022\n"
    "Comments:              webmaster@sec.gov\n"
    "Anonymous FTP:         ftp://ftp.sec.gov/edgar/\n"
    "\n\n\n\n"
    "CIK|Company Name|Form Type|Date Filed|Filename\n" + "-" * 80 + "\n"
)
NOW = datetime.datetime(2026, 10, 24, 12, tzinfo=datetime.UTC)


def body(*lines: str) -> bytes:
    return (HEADER + "\n".join(lines) + "\n").encode("latin-1")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise OSError(f"network access in a test: {args}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture(autouse=True)
def fresh_memo() -> None:
    filers.clear_memo()


class Index:
    """A mock EDGAR that serves 1 index body for every quarter."""

    def __init__(self, content: bytes, status: int = 200) -> None:
        self.content = content
        self.status = status
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if self.status != 200:
            return httpx.Response(self.status)
        return httpx.Response(200, content=self.content)


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


def test_quarters_run_through_today() -> None:
    found = filers.quarters(2025, datetime.date(2026, 5, 2))
    assert [(q.year, q.quarter) for q in found] == [
        (2025, 1),
        (2025, 2),
        (2025, 3),
        (2025, 4),
        (2026, 1),
        (2026, 2),
    ]
    assert filers.Quarter(2026, 1).end == datetime.date(2026, 3, 31)
    assert filers.Quarter(2026, 4).end == datetime.date(2026, 12, 31)
    assert filers.index_url(filers.Quarter(2022, 3)) == (
        "https://www.sec.gov/Archives/edgar/full-index/2022/QTR3/xbrl.idx"
    )


def test_parse_index_keeps_the_latest_original_form() -> None:
    latest = filers.parse_index(
        body(
            "1045810|NVIDIA CORP|10-Q|2022-05-27|edgar/data/1045810/a.txt",
            "1045810|NVIDIA CORP|10-K|2022-03-18|edgar/data/1045810/b.txt",
            "1045810|NVIDIA CORP|8-K|2022-06-30|edgar/data/1045810/c.txt",
            "2488|ADVANCED MICRO DEVICES INC|10-K/A|2022-04-01|x.txt",
            "1000184|SAP SE|20-F|2022-03-03|edgar/data/1000184/d.txt",
            "50863|INTEL CORP|10-KT|2022-01-26|edgar/data/50863/e.txt",
            "50863|INTEL CORP|10-Q|not-a-date|edgar/data/50863/f.txt",
        )
    )
    # 8-K, 20-F, and an amendment alone do not count.
    assert latest == {"0001045810": "2022-05-27", "0000050863": "2022-01-26"}


def test_parse_index_rejects_a_body_without_lines() -> None:
    with pytest.raises(errors.EdgarError, match="no filing line"):
        filers.parse_index(b"<html>not the index</html>")


def summary(year: int, quarter: int, **dates: str) -> tuple:
    return filers.Quarter(year, quarter), dict(dates)


def test_active_needs_every_year_and_a_recent_filing() -> None:
    today = datetime.date(2026, 10, 24)
    summaries = [
        summary(2022, 2, steady="2022-05-01", gap="2022-05-01"),
        summary(2023, 2, steady="2023-05-01", late="2023-05-01"),
        summary(2024, 2, steady="2024-05-01", gap="2024-05-01"),
        summary(2025, 2, steady="2025-05-01", gap="2025-05-01"),
        summary(2026, 2, steady="2026-05-01", gap="2026-05-01"),
        summary(2022, 1, gone="2022-02-01", late="2022-03-01"),
        summary(2023, 1, gone="2023-02-01"),
        summary(2024, 1, gone="2024-02-01", late="2024-02-01"),
        summary(2025, 3, gone="2025-08-01"),
        summary(2025, 4, late="2025-12-01"),
    ]
    found = filers.active(summaries, 2022, today)
    # gap misses 2023; gone stopped filing more than 365 days ago; late
    # filed every year and within the last 365 days.
    assert found == frozenset({"steady", "late"})


def test_active_does_not_need_the_current_year_in_january() -> None:
    today = datetime.date(2027, 1, 10)
    summaries = [
        summary(year, 4, steady=f"{year}-11-05") for year in range(2022, 2027)
    ]
    assert filers.active(summaries, 2022, today) == frozenset({"steady"})


INDEX = body("1045810|NVIDIA CORP|10-Q|2026-08-27|edgar/data/1045810/a.txt")


def test_complete_quarter_is_fetched_once(tmp_path: pathlib.Path) -> None:
    handler = Index(INDEX)
    quarter = filers.Quarter(2026, 2)
    with make_client(tmp_path, handler) as client:
        first = filers.quarter_filers(client, quarter, NOW)
        later = NOW + datetime.timedelta(days=90)
        again = filers.quarter_filers(client, quarter, later)
    assert first == again == {"0001045810": "2026-08-27"}
    assert len(handler.urls) == 1
    assert filers.cache_path(tmp_path, quarter).is_file()


def test_current_quarter_is_fetched_again_after_a_day(
    tmp_path: pathlib.Path,
) -> None:
    handler = Index(INDEX)
    quarter = filers.Quarter(2026, 4)
    with make_client(tmp_path, handler) as client:
        filers.quarter_filers(client, quarter, NOW)
        filers.quarter_filers(
            client, quarter, NOW + datetime.timedelta(hours=2)
        )
        assert len(handler.urls) == 1
        filers.quarter_filers(client, quarter, NOW + datetime.timedelta(days=2))
    assert len(handler.urls) == 2


def test_failed_refresh_serves_the_cached_quarter(
    tmp_path: pathlib.Path,
) -> None:
    quarter = filers.Quarter(2026, 4)
    with make_client(tmp_path, Index(INDEX)) as client:
        filers.quarter_filers(client, quarter, NOW)
    with make_client(tmp_path, Index(b"", status=503)) as client:
        later = NOW + datetime.timedelta(days=2)
        found = filers.quarter_filers(client, quarter, later)
    assert found == {"0001045810": "2026-08-27"}


def test_fetch_error_without_cache_raises(tmp_path: pathlib.Path) -> None:
    with (
        make_client(tmp_path, Index(b"", status=503)) as client,
        pytest.raises(errors.EdgarError),
    ):
        filers.quarter_filers(client, filers.Quarter(2026, 4), NOW)


def test_offline_without_cache_is_a_cache_miss(tmp_path: pathlib.Path) -> None:
    handler = Index(INDEX)
    with (
        make_client(tmp_path, handler, offline=True) as client,
        pytest.raises(errors.EdgarCacheMissError),
    ):
        filers.quarter_filers(client, filers.Quarter(2026, 4), NOW)
    assert not handler.urls


def test_bad_cache_file_is_fetched_again(tmp_path: pathlib.Path) -> None:
    quarter = filers.Quarter(2026, 2)
    path = filers.cache_path(tmp_path, quarter)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    handler = Index(INDEX)
    with make_client(tmp_path, handler) as client:
        found = filers.quarter_filers(client, quarter, NOW)
    assert found == {"0001045810": "2026-08-27"}
    assert len(handler.urls) == 1


def test_active_ciks_reads_each_quarter_and_keeps_the_day(
    tmp_path: pathlib.Path,
) -> None:
    lines = [
        f"1045810|NVIDIA CORP|10-Q|{year}-05-01|edgar/data/1045810/a.txt"
        for year in range(2022, 2027)
    ]
    handler = Index(body(*lines))
    with make_client(tmp_path, handler) as client:
        found = filers.active_ciks(client, 2022, NOW)
        assert found == frozenset({"0001045810"})
        # 2022 Q1 through 2026 Q4: 20 quarters, 1 request each.
        assert len(handler.urls) == 20
        assert filers.active_ciks(client, 2022, NOW) == found
    assert len(handler.urls) == 20
