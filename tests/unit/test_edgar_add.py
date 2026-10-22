"""The submissions pick, the document download, and the HTML conversion.

Chapter 26.2 and the tests of 26.5. Every test runs with the network
blocked: the client reads the responses that `scripts/record_add_fixtures.py`
recorded on 2026-10-21 under `tests/fixtures/edgar/` (the ZTS submissions
and 2 samples of about 60 KB of the latest ZTS 10-K and 10-Q), or a mock
transport.
"""

from collections.abc import Callable
import copy
import datetime
import pathlib
import shutil
import socket
from typing import Any

import httpx
import pytest

import conftest
from keel import config
from keel import edgar
from keel import errors
from keel import html_text
from keel.parsers import base
from keel.parsers import form_10k_10q

pytestmark = pytest.mark.unit

EDGAR_FIXTURES = conftest.FIXTURES / "edgar"
ZTS_CIK = "0001555280"
ZTS_SUBMISSIONS = EDGAR_FIXTURES / "submissions" / f"CIK{ZTS_CIK}.json"
ZTS_10K = (
    EDGAR_FIXTURES
    / "Archives"
    / "1555280"
    / "000155528026000011"
    / "zts-20251231.htm"
)
ZTS_10K_URL = (
    "https://www.sec.gov/Archives/edgar/data/1555280/000155528026000011/"
    "zts-20251231.htm"
)
USER_AGENT = "Keel Test test@example.com"


class NetworkBlockedError(OSError):
    """A test tried to open a socket or resolve a name."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block every socket connect and name lookup (test_no_network)."""

    def blocked(*args: object, **kwargs: object) -> None:
        raise NetworkBlockedError(f"network access in a test: {args}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def submissions() -> dict[str, Any]:
    """The recorded ZTS submissions body."""
    return edgar.read_cached(ZTS_SUBMISSIONS).data  # type: ignore[no-any-return]


def zts_10k_ref() -> edgar.FilingRef:
    return edgar.FilingRef(
        cik=ZTS_CIK,
        form="10-K",
        accession="0001555280-26-000011",
        filing_date=datetime.date(2026, 2, 12),
        report_date=datetime.date(2025, 12, 31),
        primary_document="zts-20251231.htm",
    )


def make_client(
    cache: pathlib.Path,
    handler: Callable[[httpx.Request], httpx.Response],
    **options: Any,
) -> edgar.EdgarClient:
    return edgar.EdgarClient(
        USER_AGENT,
        cache,
        transport=conftest.peer_transport(handler),
        resolver=lambda host: ["93.184.215.14"],
        min_interval=0.0,
        **options,
    )


# --- test_submissions_pick ----------------------------------------------------


def test_submissions_pick(submissions: dict[str, Any]) -> None:
    """A saved submissions JSON yields the latest 10-K and 10-Q."""
    ten_k, ten_q = edgar.pick_latest(submissions)
    assert ten_k == zts_10k_ref()
    assert ten_k.url == ZTS_10K_URL
    assert (ten_q.form, ten_q.accession) == ("10-Q", "0001555280-26-000040")
    assert ten_q.filing_date == datetime.date(2026, 8, 6)
    assert ten_q.report_date == datetime.date(2026, 6, 30)
    assert ten_q.primary_document == "zts-20260630.htm"


def test_submissions_pick_lists_newest_first(
    submissions: dict[str, Any],
) -> None:
    refs = edgar.filings_of(submissions)
    assert {ref.form for ref in refs} == {"10-K", "10-Q"}
    dates = [ref.filing_date for ref in refs]
    assert dates == sorted(dates, reverse=True)
    assert len(refs) > 2


def _body(rows: list[tuple[str, str, str, str, str]]) -> dict[str, Any]:
    columns = (
        "form",
        "accessionNumber",
        "filingDate",
        "reportDate",
        "primaryDocument",
    )
    recent = {key: [row[i] for row in rows] for i, key in enumerate(columns)}
    return {"cik": "1555280", "filings": {"recent": recent}}


def test_submissions_pick_skips_amendments_and_bad_rows() -> None:
    body = _body(
        [
            (
                "10-K/A",
                "0001555280-26-000050",
                "2026-09-01",
                "2025-12-31",
                "a.htm",
            ),
            ("10-Q", "../../etc", "2026-08-30", "2026-06-30", "b.htm"),
            (
                "10-Q",
                "0001555280-26-000048",
                "2026-08-29",
                "2026-06-30",
                "../x.htm",
            ),
            (
                "10-Q",
                "0001555280-26-000047",
                "not a date",
                "2026-06-30",
                "c.htm",
            ),
            (
                "10-Q",
                "0001555280-26-000040",
                "2026-08-06",
                "2026-06-30",
                "d.htm",
            ),
            (
                "10-Q",
                "0001555280-26-000041",
                "2026-08-06",
                "2026-06-30",
                "e.htm",
            ),
            (
                "10-K",
                "0001555280-25-000011",
                "2025-02-12",
                "2024-12-31",
                "f.htm",
            ),
        ]
    )
    ten_k, ten_q = edgar.pick_latest(body)
    assert ten_k.accession == "0001555280-25-000011"
    # The same filing date: the higher accession number wins.
    assert ten_q.accession == "0001555280-26-000041"
    assert edgar.pick_latest(body, ("10-Q",)) == [ten_q]


def test_submissions_pick_errors(submissions: dict[str, Any]) -> None:
    with pytest.raises(errors.EdgarError, match="no 10-K or 10-Q"):
        edgar.pick_latest(_body([]))
    with pytest.raises(errors.EdgarError, match=r"filings\.recent"):
        edgar.pick_latest({"cik": "1"})
    broken = copy.deepcopy(submissions)
    del broken["filings"]["recent"]["primaryDocument"]
    with pytest.raises(errors.EdgarError, match=r"filings\.recent"):
        edgar.filings_of(broken)


# --- The document download ----------------------------------------------------


def test_filing_document_fetch_and_cache(tmp_path: pathlib.Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"<html>10-K</html>")

    ref = zts_10k_ref()
    with make_client(tmp_path, handler) as client:
        assert client.filing_document(ref) == b"<html>10-K</html>"
        assert client.filing_document(ref) == b"<html>10-K</html>"
        path = client.document_path(ref)
    assert [str(r.url) for r in seen] == [ZTS_10K_URL]
    assert seen[0].headers["User-Agent"] == USER_AGENT
    assert client.requests == 1
    assert path.relative_to(tmp_path).parts == (
        "Archives",
        "1555280",
        "000155528026000011",
        "zts-20251231.htm",
    )
    sidecar = edgar.read_cached(path.with_name(path.name + ".json"))
    assert sidecar.url == ZTS_10K_URL
    assert sidecar.data == {"bytes": 17, "form": "10-K"}


def test_filing_document_offline(tmp_path: pathlib.Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"request in offline mode: {request.url}")

    with (
        make_client(tmp_path, handler, offline=True) as client,
        pytest.raises(errors.EdgarCacheMissError, match="offline"),
    ):
        client.filing_document(zts_10k_ref())
    shutil.copytree(EDGAR_FIXTURES, tmp_path / "cache")
    with make_client(tmp_path / "cache", handler, offline=True) as client:
        assert client.filing_document(zts_10k_ref()) == ZTS_10K.read_bytes()
    assert client.requests == 0


def test_filing_document_http_error(tmp_path: pathlib.Path) -> None:
    with (
        make_client(tmp_path, lambda r: httpx.Response(404)) as client,
        pytest.raises(errors.EdgarFetchError, match="HTTP 404"),
    ):
        client.filing_document(zts_10k_ref())
    assert not client.document_path(zts_10k_ref()).exists()


# --- test_html_to_text --------------------------------------------------------


def zts_header() -> html_text.FilingHeader:
    return html_text.FilingHeader(
        company="Zoetis Inc.",
        ticker="ZTS",
        form="10-K",
        filing_date=datetime.date(2026, 2, 12),
        cik=ZTS_CIK,
        url=ZTS_10K_URL,
    )


def test_html_to_text(
    tmp_path: pathlib.Path, settings: config.Settings
) -> None:
    """A saved 60 KB sample of 1 real 10-K converts to the corpus format.

    The file has the header, the separator, and pipe rows, holds none of
    the hidden XBRL facts or the script, and the unchanged parser reads it
    without a quarantine.
    """
    text = html_text.to_corpus_text(ZTS_10K.read_bytes(), zts_header())
    lines = text.split("\n")
    assert lines[:8] == [
        "Company: Zoetis Inc.",
        "Ticker: ZTS",
        "Filing Type: 10-K (Annual Report)",
        "Filing Date: 2026-02-12",
        f"CIK: {ZTS_CIK}",
        "Source: edgar",
        f"URL: {ZTS_10K_URL}",
        "=" * 60,
    ]
    assert lines[8] == ""
    assert text.endswith("\n")
    # The hidden ix:header facts and the script are gone.
    assert "fasb.org" not in text
    assert "text/javascript" not in text
    assert "zts-20251231" not in text.split("=" * 60, 1)[1]
    # Pipe rows: 1 table row per line, empty cells kept between values.
    assert (
        "Large accelerated filer | ☒ | Accelerated filer | ☐ | "
        "Non-accelerated filer | ☐ | Smaller reporting company | ☐ | "
        "Emerging growth company | ☐"
    ) in lines
    assert "Delaware |  | 46-0696167" in lines
    # The cover page: the phrase and the date, the comma rejoined.
    assert "For the fiscal year ended" in lines
    assert "December 31, 2025" in lines
    assert "Item 1A. Risk Factors." in lines
    # Whitespace collapsed in every line and every cell.
    cells = [cell for line in lines for cell in line.split(" | ")]
    assert all(cell == cell.strip() and "  " not in cell for cell in cells)

    path = tmp_path / "ZTS_10K_2026-02-12_full.txt"
    path.write_text(text, encoding="utf-8")
    context = base.ParseContext.from_settings(settings)
    filing = form_10k_10q.TenKTenQParser().parse(path, context)
    assert filing.quarantine is None
    assert filing.filing_id == "ZTS_10K_2025-12-31"
    assert filing.metadata.period_source == "cover"
    assert filing.metadata.registrant == "Zoetis Inc"
    assert filing.metadata.url_trusted
    assert filing.tables
    # The hidden header is dropped, so no XBRL block precedes the cover.
    assert filing.warnings == ("no_xbrl_block",)


def test_html_to_lines_rules() -> None:
    document = """<html><head><title>t</title><style>p {}</style></head>
    <body><div style="display: none"><ix:header>hidden fact</ix:header></div>
    <p>First   paragraph<br/>after break</p><div>Revenue was <span>$5</span>
    <span>.</span></div><script>alert(1)</script>
    <table><tr><td></td><td>Label</td><td></td><td>( 12 )</td><td></td></tr>
    <tr><td> </td><td>&#160;</td></tr>
    <tr><td><p>Cell</p><p>two</p></td><td><table><tr><td>in</td><td>ner</td>
    </tr></table></td></tr><tr><td>alone</td></tr></table>
    <ul><li>one</li><li>two &amp; three</li></ul><unclosed>tail
    <p>open<b>bold</p></body></html>"""
    assert html_text.html_to_lines(document) == [
        "First paragraph",
        "after break",
        "Revenue was $5 .",
        "Label |  | (12)",
        "Cell two | in ner",
        "alone",
        "one",
        "two & three",
        "tail",
        "openbold",
    ]


def test_html_to_text_rules() -> None:
    assert html_text.table_row(["", "a", "", "b", ""]) == "a |  | b"
    assert html_text.table_row(["", ""]) == ""
    assert html_text.collapse(" December\xa031 , 2025 ") == "December 31, 2025"
    assert html_text.decode_html("caf\xe9".encode("cp1252")) == "caf\xe9"
    assert html_text.decode_html(b"\x81\x8d") == "\x81\x8d"
    with pytest.raises(errors.EdgarError, match="no text"):
        html_text.to_corpus_text(
            b"<html><script>x</script></html>", zts_header()
        )


def test_html_to_text_header_checks() -> None:
    header = zts_header()
    with pytest.raises(errors.HeaderError, match="filing type"):
        html_text.FilingHeader(**{**vars(header), "form": "8-K"}).lines()
    with pytest.raises(errors.HeaderError, match="Company"):
        html_text.FilingHeader(**{**vars(header), "company": "A\nB"}).lines()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cik", "1555280"),
        ("accession", "../../etc"),
        ("primary_document", "../x.htm"),
        ("primary_document", "a/b.htm"),
    ],
)
def test_filing_ref_rejects_path_values(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="not a"):
        edgar.FilingRef(**{**zts_10k_ref().model_dump(), field: value})


def test_submissions_columns_of_one_length() -> None:
    body = _body(
        [("10-K", "0001555280-25-000011", "2025-02-12", "2024-12-31", "f.htm")]
    )
    body["filings"]["recent"]["form"].append("10-Q")
    with pytest.raises(errors.EdgarError, match="length"):
        edgar.filings_of(body)
