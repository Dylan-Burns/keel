"""The company browser routes of the admin companies page.

The app runs on a small synthetic index (NVDA only) with the mock
provider. The EDGAR cache holds the recorded responses of
`tests/fixtures/edgar/` (the ticker map and the company list of SIC 3674);
a fetch goes to a mock transport that serves the recorded feed pages of
`tests/fixtures/edgar_sic/`. No test touches the network.
"""

from collections.abc import Callable
from collections.abc import Iterator
import json
import logging
import pathlib
import shutil

import httpx
import pydantic
import pytest
from starlette import testclient
import test_users_api as base

import conftest
from keel import config
from keel import edgar
from keel import errors
from keel import users
from keel.api import app as api_app
from keel.api import directory as directory_api
from keel.api import routes
from keel.stores import state_store

pytestmark = pytest.mark.integration

LEGACY_TOKEN = "legacy-token"  # noqa: S105
FILINGS = (
    conftest.FakeFiling("NVDA", "10-K", "2025-01-26", "2025-02-26", 2025),
)
FEED = conftest.FIXTURES / "edgar_sic"
MARKED_QUERY = "zz-private-query"


@pytest.fixture(autouse=True)
def no_pace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "MOCK_PACE_SECONDS", 0.0)


@pytest.fixture
def index_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    chunks = [
        conftest.make_chunk(
            FILINGS[0], "risk_factors", 0, "Risk factors: supply."
        )
    ]
    return conftest.build_store(tmp_path / "index", FILINGS, chunks)


@pytest.fixture
def tokens(tmp_path: pathlib.Path) -> dict[str, str]:
    path = tmp_path / "users.yaml"
    return {
        "alice": users.add_user(path, "alice", "analyst"),
        "carol": users.add_user(path, "carol", "admin"),
    }


@pytest.fixture
def api_settings(
    settings: config.Settings, tmp_path: pathlib.Path, index_dir: pathlib.Path
) -> config.Settings:
    cache = tmp_path / "edgar"
    shutil.copytree(conftest.FIXTURES / "edgar", cache)
    return settings.model_copy(
        update={
            "api_token": pydantic.SecretStr(LEGACY_TOKEN),
            "llm": settings.llm.model_copy(update={"provider": "mock"}),
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "auth": config.AuthConfig(users_file=tmp_path / "users.yaml"),
            "server": config.ServerConfig(web_dist=tmp_path / "no-dist"),
            "index": settings.index.model_copy(update={"dir": index_dir}),
            "edgar": settings.edgar.model_copy(update={"cache_dir": cache}),
        }
    )


class Feed:
    """A mock EDGAR: the recorded feed pages by offset, else a 404."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if request.url.params.get("SIC") != "3674":
            return httpx.Response(404)
        name = (
            "atom_3674_start0.xml"
            if request.url.params.get("start") == "0"
            else "atom_3674_start100.xml"
        )
        return httpx.Response(200, content=(FEED / name).read_bytes())


@pytest.fixture
def feed(monkeypatch: pytest.MonkeyPatch) -> Feed:
    """Route the EDGAR client of the routes to the mock feed."""
    handler = Feed()

    def client_of(settings: config.Settings) -> edgar.EdgarClient:
        return edgar.EdgarClient(
            settings.edgar.user_agent,
            settings.edgar.cache_dir,
            offline=settings.offline,
            min_interval=0.0,
            transport=conftest.peer_transport(handler),
            resolver=lambda host: ["93.184.215.14"],
        )

    monkeypatch.setattr(directory_api, "edgar_client", client_of)
    return handler


TICKERS = json.loads(
    (conftest.FIXTURES / "edgar" / "company_tickers.json").read_text(
        encoding="utf-8"
    )
)
ALL_CIKS = frozenset(
    f"{int(row['cik_str']):010d}" for row in TICKERS["data"].values()
)
AMD_CIK = "0000002488"


class Active:
    """The active filers the routes see; a test narrows them."""

    def __init__(self) -> None:
        self.ciks = ALL_CIKS
        self.calls = 0

    def __call__(
        self, settings: config.Settings, client: edgar.EdgarClient
    ) -> frozenset[str]:
        del settings, client
        self.calls += 1
        return self.ciks


@pytest.fixture(autouse=True)
def active(monkeypatch: pytest.MonkeyPatch) -> Active:
    """Every recorded company is an active filer unless a test says not."""
    holder = Active()
    monkeypatch.setattr(directory_api, "active_filers", holder)
    return holder


@pytest.fixture
def make_client(
    api_settings: config.Settings,
    index_dir: pathlib.Path,
    tokens: dict[str, str],
) -> Iterator[Callable[..., testclient.TestClient]]:
    del tokens
    opened: list[testclient.TestClient] = []

    def make(**update: object) -> testclient.TestClient:
        settings = api_settings.model_copy(update=update)
        services = api_app.Services(
            settings, base.make_answerer(settings, index_dir)
        )
        client = testclient.TestClient(api_app.create_app(services))
        client.__enter__()
        opened.append(client)
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


ROUTES = (
    "/api/admin/directory",
    "/api/admin/directory/sic/3674",
    "/api/admin/directory/search?q=nv",
)


def test_directory_routes_need_the_admin_role(
    make_client: Callable[..., testclient.TestClient],
    tokens: dict[str, str],
) -> None:
    client = make_client()
    for path in ROUTES:
        assert client.get(path).status_code == 401
        refused = client.get(path, headers=bearer(tokens["alice"]))
        assert refused.status_code == 403, path
        assert refused.json()["detail"]["code"] == "forbidden"


def test_directory_lists_sectors_and_cached_counts(
    make_client: Callable[..., testclient.TestClient],
    tokens: dict[str, str],
    feed: Feed,
) -> None:
    """The overview reads the yaml and the cache; it sends no request."""
    body = make_client().get(
        "/api/admin/directory", headers=bearer(tokens["carol"])
    )
    assert body.status_code == 200
    data = body.json()
    names = [s["name"] for s in data["sectors"]]
    assert names == sorted(names)
    assert data["industry_count"] > 400
    industries = {
        i["code"]: i for s in data["sectors"] for i in s["industries"]
    }
    # The cached list of 3674 has 3 CIKs in the recorded ticker map.
    assert industries["3674"]["companies"] == 3
    assert industries["3674"]["title"] == "SEMICONDUCTORS & RELATED DEVICES"
    assert industries["2834"]["companies"] is None
    assert feed.urls == []


def test_industry_from_the_cache_marks_indexed_and_watched(
    make_client: Callable[..., testclient.TestClient],
    tokens: dict[str, str],
    api_settings: config.Settings,
    feed: Feed,
) -> None:
    state_store.add_watch(state_store.state_path(api_settings), "INTC", "carol")
    response = make_client(offline=True).get(
        "/api/admin/directory/sic/3674", headers=bearer(tokens["carol"])
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["sector"] == "Manufacturing"
    assert data["registrants"] == 506
    assert data["sec_requests"] == 0
    assert data["stale"] is False
    by = {c["ticker"]: c for c in data["companies"]}
    assert list(by) == ["AMD", "INTC", "NVDA"]
    assert by["NVDA"]["indexed"] is True
    assert by["NVDA"]["cik"] == "0001045810"
    assert by["INTC"]["watched"] is True
    assert by["AMD"]["indexed"] is False
    assert feed.urls == []


def test_industry_fetch_pages_once_then_caches(
    make_client: Callable[..., testclient.TestClient],
    tokens: dict[str, str],
    api_settings: config.Settings,
    feed: Feed,
) -> None:
    (api_settings.edgar.cache_dir / "sic" / "3674.json").unlink()
    client = make_client()
    first = client.get(
        "/api/admin/directory/sic/3674", headers=bearer(tokens["carol"])
    ).json()
    assert first["sec_requests"] == 2
    assert first["registrants"] == 10
    assert [c["ticker"] for c in first["companies"]] == ["AMD", "INTC", "NVDA"]
    again = client.get(
        "/api/admin/directory/sic/3674", headers=bearer(tokens["carol"])
    ).json()
    assert again["sec_requests"] == 0
    assert len(feed.urls) == 2


def test_industry_errors(
    make_client: Callable[..., testclient.TestClient],
    tokens: dict[str, str],
    feed: Feed,
) -> None:
    headers = bearer(tokens["carol"])
    client = make_client()
    for code in ("36a4", "12345", "367"):
        response = client.get(
            f"/api/admin/directory/sic/{code}", headers=headers
        )
        assert response.status_code == 422, code
    unknown = client.get("/api/admin/directory/sic/0001", headers=headers)
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "unknown_industry"
    # EDGAR answers 404 for 2834 and nothing is cached: 502.
    failed = client.get("/api/admin/directory/sic/2834", headers=headers)
    assert failed.status_code == 502
    assert failed.json()["detail"]["code"] == "sec_unavailable"
    offline = make_client(offline=True).get(
        "/api/admin/directory/sic/2834", headers=headers
    )
    assert offline.status_code == 503
    assert offline.json()["detail"]["code"] == "directory_offline"
    assert len(feed.urls) == 1


def test_search_and_its_limits(
    make_client: Callable[..., testclient.TestClient],
    tokens: dict[str, str],
    feed: Feed,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    headers = bearer(tokens["carol"])
    client = make_client()
    found = client.get(
        "/api/admin/directory/search", params={"q": "nvidia"}, headers=headers
    )
    assert found.status_code == 200
    item = found.json()["items"][0]
    assert item["ticker"] == "NVDA"
    assert item["indexed"] is True
    brk = client.get(
        "/api/admin/directory/search", params={"q": "brk.b"}, headers=headers
    ).json()["items"]
    assert [c["ticker"] for c in brk] == ["BRK-B"]
    for q in ("n", "x" * 65):
        response = client.get(
            "/api/admin/directory/search", params={"q": q}, headers=headers
        )
        assert response.status_code == 422
    empty = client.get(
        "/api/admin/directory/search",
        params={"q": MARKED_QUERY},
        headers=headers,
    )
    assert empty.json() == {"items": []}
    # The query reaches no log line of the server (the test client logs
    # its own request URLs).
    server_lines = [
        r.getMessage() for r in caplog.records if not r.name.startswith("httpx")
    ]
    assert not any(MARKED_QUERY in line for line in server_lines)
    assert feed.urls == []


def test_only_active_filers_show(
    make_client: Callable[..., testclient.TestClient],
    tokens: dict[str, str],
    active: Active,
    feed: Feed,
) -> None:
    """A company that stopped filing a 10-K or 10-Q drops out everywhere."""
    active.ciks = ALL_CIKS - {AMD_CIK}
    headers = bearer(tokens["carol"])
    client = make_client()
    overview = client.get("/api/admin/directory", headers=headers).json()
    industries = {
        i["code"]: i for s in overview["sectors"] for i in s["industries"]
    }
    assert industries["3674"]["companies"] == 2
    industry = client.get(
        "/api/admin/directory/sic/3674", headers=headers
    ).json()
    assert [c["ticker"] for c in industry["companies"]] == ["INTC", "NVDA"]
    # The registrant count stays the raw feed count.
    assert industry["registrants"] == 506
    found = client.get(
        "/api/admin/directory/search", params={"q": "amd"}, headers=headers
    ).json()
    assert found == {"items": []}
    assert feed.urls == []


def test_overview_counts_wait_for_the_filer_list(
    make_client: Callable[..., testclient.TestClient],
    tokens: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    feed: Feed,
) -> None:
    """Without a cached filer list the overview sends no request."""

    def missing(
        settings: config.Settings, client: edgar.EdgarClient
    ) -> frozenset[str]:
        del settings
        assert client.offline
        raise errors.EdgarCacheMissError("no cached XBRL index")

    monkeypatch.setattr(directory_api, "active_filers", missing)
    overview = (
        make_client()
        .get("/api/admin/directory", headers=bearer(tokens["carol"]))
        .json()
    )
    counts = {
        i["companies"] for s in overview["sectors"] for i in s["industries"]
    }
    assert counts == {None}
    assert feed.urls == []
