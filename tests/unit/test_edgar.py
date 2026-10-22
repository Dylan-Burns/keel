"""The EDGAR client and the facts lines (chapter 26.1, tests of 26.5).

Every test runs with the network blocked: the client reads the recorded
responses under `tests/fixtures/edgar/` (fetched once by
`scripts/record_edgar_fixtures.py` on 2026-10-21) or a mock transport.
"""

from collections.abc import Callable
from collections.abc import Iterator
import datetime
import decimal
import json
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

pytestmark = pytest.mark.unit

EDGAR_FIXTURES = conftest.FIXTURES / "edgar"
NVDA_CIK = "0001045810"
NVDA_FACTS = EDGAR_FIXTURES / "companyfacts" / f"CIK{NVDA_CIK}.json"
FACTS_CONFIG = conftest.REPO_ROOT / "config" / "facts.yaml"
USER_AGENT = "Keel Test test@example.com"
PUBLIC_IP = "93.184.215.14"

# The window of "fiscal 2025 and fiscal 2024" for NVDA (fiscal years end
# in late January): period ends from 2023-02-01 to 2025-01-31.
FY2024_START = datetime.date(2023, 2, 1)
FY2025_END = datetime.date(2025, 1, 31)


class NetworkBlockedError(OSError):
    """A test tried to open a socket or resolve a name."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block every socket connect and name lookup (test_no_network)."""

    def blocked(*args: object, **kwargs: object) -> None:
        raise NetworkBlockedError(f"network access in a test: {args}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def cache_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """A cache directory that holds the recorded responses."""
    target = tmp_path / "edgar"
    shutil.copytree(EDGAR_FIXTURES, target)
    return target


@pytest.fixture
def facts_config() -> edgar.FactsConfig:
    """The repository `config/facts.yaml`."""
    return edgar.load_facts_config(FACTS_CONFIG)


@pytest.fixture
def nvda_facts() -> dict[str, Any]:
    """The recorded NVDA company facts body."""
    return edgar.read_cached(NVDA_FACTS).data  # type: ignore[no-any-return]


def public_resolver(host: str) -> list[str]:
    del host
    return [PUBLIC_IP]


class Recorder:
    """A mock transport handler that records the requests it answers."""

    def __init__(
        self, respond: Callable[[httpx.Request], httpx.Response]
    ) -> None:
        self.respond = respond
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)


def json_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"url": str(request.url)})


def make_client(
    cache: pathlib.Path,
    handler: Callable[[httpx.Request], httpx.Response] = json_response,
    **options: Any,
) -> edgar.EdgarClient:
    return edgar.EdgarClient(
        USER_AGENT,
        cache,
        transport=httpx.MockTransport(handler),
        resolver=options.pop("resolver", public_resolver),
        **options,
    )


@pytest.fixture
def client(cache_dir: pathlib.Path) -> Iterator[edgar.EdgarClient]:
    with make_client(cache_dir) as value:
        yield value


# --- test_no_network ----------------------------------------------------------


def test_no_network(cache_dir: pathlib.Path) -> None:
    """The cached responses serve the client with 0 requests."""
    handler = Recorder(json_response)
    with make_client(cache_dir, handler, resolver=edgar.resolve_host) as c:
        cik = c.cik("NVDA")
        facts = c.company_facts(cik)
    assert cik == NVDA_CIK
    assert facts.data["entityName"] == "NVIDIA CORP"
    assert facts.fetched_at.date() == datetime.date(2026, 10, 21)
    assert c.requests == 0
    assert not handler.requests


def test_no_network_offline_cache_miss(tmp_path: pathlib.Path) -> None:
    handler = Recorder(json_response)
    with (
        make_client(tmp_path, handler, offline=True) as c,
        pytest.raises(errors.EdgarCacheMissError, match="offline"),
    ):
        c.submissions(NVDA_CIK)
    assert c.requests == 0
    assert not handler.requests


def test_no_network_guard_blocks_sockets() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("data.sec.gov", 443))
    with pytest.raises(errors.OutboundBlockedError, match="cannot resolve"):
        edgar.check_url(edgar.TICKER_MAP_URL)


# --- test_ticker_to_cik -------------------------------------------------------


def test_ticker_to_cik(client: edgar.EdgarClient) -> None:
    """The saved slice of the ticker map resolves NVDA to its CIK."""
    assert client.cik("NVDA") == NVDA_CIK
    assert client.cik(" nvda ") == NVDA_CIK
    assert client.ticker_map().lookup("NVDA").title == "NVIDIA CORP"


def test_ticker_to_cik_share_class_spelling(
    client: edgar.EdgarClient,
) -> None:
    tickers = client.ticker_map()
    assert tickers.cik("BRK.B") == tickers.cik("brk-b") == "0001067983"
    assert "BRK.B" in tickers
    assert 3 not in tickers
    assert len(tickers) == 7


def test_ticker_to_cik_unknown_names_lookup(
    client: edgar.EdgarClient,
) -> None:
    with pytest.raises(errors.UnknownTickerError) as caught:
        client.cik("ZZZZ")
    assert edgar.LOOKUP_URL in str(caught.value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1045810, NVDA_CIK), ("320193", "0000320193"), (NVDA_CIK, NVDA_CIK)],
)
def test_cik10(value: int | str, expected: str) -> None:
    assert edgar.cik10(value) == expected


@pytest.mark.parametrize("value", ["", "0", "abc", "12345678901", -5])
def test_cik10_rejects(value: int | str) -> None:
    with pytest.raises(errors.EdgarError, match="not a CIK"):
        edgar.cik10(value)


@pytest.mark.parametrize(
    "data", [[], {"0": {"ticker": "X"}}, {"0": {"cik_str": "x", "ticker": "X"}}]
)
def test_ticker_map_rejects_bad_body(data: object) -> None:
    with pytest.raises(errors.EdgarError):
        edgar.TickerMap.from_json(data)


# --- test_facts_block ---------------------------------------------------------


def test_facts_block(
    nvda_facts: dict[str, Any], facts_config: edgar.FactsConfig
) -> None:
    """The saved company facts yield the revenue lines of the window."""
    block = edgar.facts_lines(
        nvda_facts,
        "NVDA",
        facts_config,
        start=FY2024_START,
        end=FY2025_END,
    )
    by_id = {line.fact_id: line for line in block.lines}
    fy2025 = by_id["facts:NVDA:Revenues:FY2025"]
    fy2024 = by_id["facts:NVDA:Revenues:FY2024"]
    assert fy2025.value == decimal.Decimal(130_497_000_000)
    assert (fy2025.display_value, fy2025.display_unit) == (
        "130,497",
        "USD millions",
    )
    assert fy2025.period_end == datetime.date(2025, 1, 26)
    assert fy2024.display_value == "60,922"
    assert fy2024.period_end == datetime.date(2024, 1, 28)
    assert fy2024.fiscal_label == "FY2024"
    assert len(block.lines) <= edgar.MAX_FACT_LINES
    assert block.cik == NVDA_CIK
    assert block.entity_name == "NVIDIA CORP"
    assert all(
        FY2024_START <= line.period_end <= FY2025_END for line in block.lines
    )


def test_facts_block_line_format(
    nvda_facts: dict[str, Any], facts_config: edgar.FactsConfig
) -> None:
    block = edgar.facts_lines(
        nvda_facts, "NVDA", facts_config, start=FY2024_START, end=FY2025_END
    )
    assert block.text().splitlines()[0] == (
        "facts:NVDA:Revenues:FY2025 | 130,497 | USD millions | FY2025 | "
        "period end 2025-01-26 | 10-K filed 2026-02-25 | accession "
        "0001045810-26-000021"
    )
    assert len(block.fact_ids()) == len(block.lines)
    assert block.lines[0].filing_index_url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000104581026000021/0001045810-26-000021-index.htm"
    )


def test_facts_block_latest_filing_per_period(
    nvda_facts: dict[str, Any], facts_config: edgar.FactsConfig
) -> None:
    """FY2025 appears in 2 10-Ks; the later filing wins."""
    block = edgar.facts_lines(
        nvda_facts,
        "NVDA",
        facts_config,
        start=datetime.date(2025, 1, 26),
        end=datetime.date(2025, 1, 26),
    )
    revenue = next(line for line in block.lines if line.concept == "revenue")
    assert revenue.filed == datetime.date(2026, 2, 25)
    assert revenue.form == "10-K"


def test_facts_block_quarter_labels_and_no_year_to_date(
    nvda_facts: dict[str, Any], facts_config: edgar.FactsConfig
) -> None:
    block = edgar.facts_lines(
        nvda_facts, "NVDA", facts_config, start=FY2024_START, end=FY2025_END
    )
    labels = {line.fact_id: line.fiscal_label for line in block.lines}
    assert labels["facts:NVDA:Revenues:Q3FY2025"] == "Q3 FY2025"
    eps = next(
        line
        for line in block.lines
        if line.fact_id == "facts:NVDA:EarningsPerShareDiluted:Q1FY2025"
    )
    assert (eps.display_value, eps.display_unit) == ("0.60", "USD per share")
    for line in block.lines:
        if line.period_start is not None:
            days = (line.period_end - line.period_start).days + 1
            assert days < 100 or days > 350, line.fact_id


def test_facts_block_limit_keeps_annual_lines(
    nvda_facts: dict[str, Any], facts_config: edgar.FactsConfig
) -> None:
    block = edgar.facts_lines(
        nvda_facts, "NVDA", facts_config, start=FY2024_START, max_lines=8
    )
    assert len(block.lines) == 8
    assert block.dropped > 0
    assert all(" " not in line.fiscal_label for line in block.lines)
    concepts = [line.concept for line in block.lines]
    assert concepts == sorted(
        concepts, key=[c.key for c in facts_config.concepts].index
    )


def test_facts_block_no_mapped_concept(
    facts_config: edgar.FactsConfig,
) -> None:
    document = {"cik": 1, "entityName": "X", "facts": {"us-gaap": {}}}
    block = edgar.facts_lines(document, "X", facts_config)
    assert block.lines == ()
    assert not block.text()
    assert edgar.facts_lines({}, "X", facts_config).cik == ""


def _row(**fields: Any) -> dict[str, Any]:
    row = {
        "start": "2023-01-01",
        "end": "2023-12-31",
        "val": 100_000_000,
        "accn": "0000000001-24-000001",
        "fy": 2023,
        "fp": "FY",
        "form": "10-K",
        "filed": "2024-02-01",
    }
    row.update(fields)
    return row


def test_facts_block_priority_and_restatement(
    facts_config: edgar.FactsConfig,
) -> None:
    """The first XBRL name in priority order wins, then the latest filing."""
    document = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "SalesRevenueNet": {"units": {"USD": [_row(val=1)]}},
                "Revenues": {
                    "units": {
                        "USD": [
                            _row(),
                            _row(
                                val=120_500_000,
                                accn="0000000001-25-000001",
                                fy=2024,
                                filed="2025-02-01",
                            ),
                            _row(form="8-K", val=7),
                            _row(start="2023-07-01", fp="Q3", form="10-Q"),
                            _row(val="bad"),
                        ]
                    }
                },
            }
        },
    }
    block = edgar.facts_lines(document, "x", facts_config)
    assert [line.text() for line in block.lines] == [
        "facts:X:Revenues:FY2023 | 120.5 | USD millions | FY2023 | period "
        "end 2023-12-31 | 10-K filed 2025-02-01 | accession "
        "0000000001-25-000001"
    ]


def test_facts_block_q4_and_instant_labels(
    facts_config: edgar.FactsConfig,
) -> None:
    quarter = _row(start="2023-10-01", val=30_000_000)
    assets = _row(val=5_000_000_000)
    del assets["start"]
    old = _row(start="2021-01-01", end="2021-12-31")
    document = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [_row(), quarter, old]}},
                "Assets": {"units": {"USD": [assets]}},
            },
            "dei": {"EntityCommonStockSharesOutstanding": "not a mapping"},
        },
    }
    block = edgar.facts_lines(document, "X", facts_config)
    labels = {line.fact_id: line.fiscal_label for line in block.lines}
    assert labels == {
        "facts:X:Revenues:FY2023": "FY2023",
        "facts:X:Revenues:Q4FY2023": "Q4 FY2023",
        "facts:X:Revenues:FY2021": "FY2021",
        "facts:X:Assets:FY2023": "FY2023",
    }


def test_load_facts_config_has_8_concepts(
    facts_config: edgar.FactsConfig,
) -> None:
    keys = [concept.key for concept in facts_config.concepts]
    assert keys == [
        "revenue",
        "net_income",
        "diluted_eps",
        "operating_income",
        "total_assets",
        "cash",
        "shares_outstanding",
        "long_term_debt",
    ]
    revenue = facts_config.concepts[0]
    assert revenue.names[:2] == (
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert "us-gaap:SalesRevenueNet" in revenue.names


@pytest.mark.parametrize(
    "text",
    [
        "concepts: []\n",
        "concepts:\n  revenue: {label: R, unit: USD, names: [Revenues]}\n",
        "concepts:\n  revenue: {label: R, unit: USD, names: []}\n",
        "concepts:\n  revenue: 3\n",
    ],
)
def test_load_facts_config_rejects(tmp_path: pathlib.Path, text: str) -> None:
    path = tmp_path / "facts.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(errors.ConfigError):
        edgar.load_facts_config(path)


# --- The fetch path (mock transport) ------------------------------------------


def test_fetch_sends_user_agent_and_caches(tmp_path: pathlib.Path) -> None:
    handler = Recorder(json_response)
    with make_client(tmp_path, handler) as c:
        first = c.company_facts("1045810")
        second = c.company_facts(NVDA_CIK)
    assert len(handler.requests) == 1
    request = handler.requests[0]
    assert request.headers["User-Agent"] == USER_AGENT
    assert str(request.url) == (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"
    )
    assert first == second
    cached = json.loads(c.company_facts_path(NVDA_CIK).read_text())
    assert set(cached) == {"url", "fetched_at", "data"}
    assert first.fetched_at.tzinfo is not None


def test_fetch_refresh_and_submissions(tmp_path: pathlib.Path) -> None:
    handler = Recorder(json_response)
    with make_client(tmp_path, handler) as c:
        c.submissions(NVDA_CIK)
        document = c.submissions(NVDA_CIK, refresh=True)
    assert len(handler.requests) == 2
    assert document.url == edgar.SUBMISSIONS_URL.format(cik=NVDA_CIK)
    assert c.submissions_path(NVDA_CIK).exists()


def test_fetch_ticker_map(tmp_path: pathlib.Path) -> None:
    body = json.loads((EDGAR_FIXTURES / "company_tickers.json").read_text())
    handler = Recorder(lambda request: httpx.Response(200, json=body["data"]))
    with make_client(tmp_path, handler) as c:
        assert c.cik("WDAY") == "0001327811"
        assert c.cik("ZTS") == "0001555280"
    assert [str(r.url) for r in handler.requests] == [edgar.TICKER_MAP_URL]


def test_rate_limit_waits_between_requests(tmp_path: pathlib.Path) -> None:
    now = [100.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    with make_client(
        tmp_path, clock=lambda: now[0], sleep=sleep, min_interval=0.2
    ) as c:
        c.fetch(edgar.TICKER_MAP_URL)
        now[0] += 0.05
        c.fetch(edgar.TICKER_MAP_URL)
        now[0] += 1.0
        c.fetch(edgar.TICKER_MAP_URL)
    assert waits == [pytest.approx(0.15)]
    assert c.requests == 3


def test_redirect_to_allowed_host_is_followed(tmp_path: pathlib.Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.sec.gov":
            return httpx.Response(
                301, headers={"location": "https://data.sec.gov/x.json"}
            )
        return httpx.Response(200, content=b"{}")

    handler = Recorder(respond)
    with make_client(tmp_path, handler) as c:
        assert c.fetch(edgar.TICKER_MAP_URL) == b"{}"
    assert [r.url.host for r in handler.requests] == [
        "www.sec.gov",
        "data.sec.gov",
    ]


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example.com/x",
        "http://data.sec.gov/x",
        "https://169.254.169.254/latest/meta-data/",
    ],
)
def test_redirect_target_is_checked(
    tmp_path: pathlib.Path, location: str
) -> None:
    handler = Recorder(
        lambda request: httpx.Response(302, headers={"location": location})
    )
    with (
        make_client(tmp_path, handler) as c,
        pytest.raises(errors.OutboundBlockedError),
    ):
        c.fetch(edgar.TICKER_MAP_URL)
    assert len(handler.requests) == 1


@pytest.mark.parametrize(
    ("respond", "message"),
    [
        (lambda request: httpx.Response(403), "HTTP 403"),
        (lambda request: httpx.Response(302), "without target"),
        (
            lambda request: httpx.Response(
                302, headers={"location": str(request.url)}
            ),
            "redirects",
        ),
    ],
)
def test_fetch_errors(
    tmp_path: pathlib.Path,
    respond: Callable[[httpx.Request], httpx.Response],
    message: str,
) -> None:
    with (
        make_client(tmp_path, respond) as c,
        pytest.raises(errors.EdgarFetchError, match=message),
    ):
        c.fetch(edgar.TICKER_MAP_URL)


def test_fetch_transport_error(tmp_path: pathlib.Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with (
        make_client(tmp_path, respond) as c,
        pytest.raises(errors.EdgarFetchError, match="refused"),
    ):
        c.fetch(edgar.TICKER_MAP_URL)
    assert c.requests == 1


def test_fetch_body_not_json(tmp_path: pathlib.Path) -> None:
    with (
        make_client(
            tmp_path, lambda request: httpx.Response(200, content=b"<html>")
        ) as c,
        pytest.raises(errors.EdgarFetchError, match="not JSON"),
    ):
        c.submissions(NVDA_CIK)
    assert not c.submissions_path(NVDA_CIK).exists()


# --- Control S-11 -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://data.sec.gov/x.json",
        "https://sec.gov/x.json",
        "https://data.sec.gov.evil.com/x.json",
        "https://user:pw@data.sec.gov/x.json",
        "https://data.sec.gov:8443/x.json",
        "file:///etc/passwd",
    ],
)
def test_check_url_rejects(url: str) -> None:
    with pytest.raises(errors.OutboundBlockedError):
        edgar.check_url(url, public_resolver)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "fe80::1%en0",
        "0.0.0.0",  # noqa: S104
        "not an ip",
    ],
)
def test_check_url_rejects_non_public_addresses(address: str) -> None:
    with pytest.raises(errors.OutboundBlockedError, match="non-public"):
        edgar.check_url(edgar.TICKER_MAP_URL, lambda host: [PUBLIC_IP, address])


def test_check_url_accepts_sec_hosts() -> None:
    for url in (edgar.TICKER_MAP_URL, "https://DATA.SEC.GOV:443/x.json"):
        assert edgar.check_url(url, public_resolver) == url
    with pytest.raises(errors.OutboundBlockedError, match="no address"):
        edgar.check_url(edgar.TICKER_MAP_URL, lambda host: [])


def test_resolve_host_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    infos = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 443)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kw: infos)
    assert edgar.resolve_host("data.sec.gov") == [PUBLIC_IP]


# --- Config and the cache -----------------------------------------------------


def test_client_from_settings(settings: config.Settings) -> None:
    with edgar.EdgarClient.from_settings(settings) as c:
        assert c.cache_dir == pathlib.Path("cache/edgar")
        assert c.min_interval == pytest.approx(0.2)
        assert not c.offline
    assert settings.edgar.facts == pathlib.Path("config/facts.yaml")
    with edgar.EdgarClient.from_settings(settings, offline=True) as c:
        assert c.offline


def test_client_rejects_empty_user_agent(tmp_path: pathlib.Path) -> None:
    with pytest.raises(errors.EdgarError, match="user_agent"):
        edgar.EdgarClient(" ", tmp_path)


def test_bad_cache_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "company_tickers.json"
    path.write_text("{}", encoding="utf-8")
    with (
        make_client(tmp_path) as c,
        pytest.raises(errors.EdgarError, match="bad EDGAR cache"),
    ):
        c.ticker_map()


def test_cache_write_failure(tmp_path: pathlib.Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    document = edgar.CachedDocument(
        url="u", fetched_at=datetime.datetime.now(datetime.UTC), data={}
    )
    with pytest.raises(errors.EdgarError, match="cannot write"):
        edgar.write_cached(blocker / "sub" / "x.json", document)
