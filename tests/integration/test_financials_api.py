"""The financials routes over the mini index with the mock provider.

The EDGAR cache holds the trimmed NVIDIA company facts of the unit tests
and nothing else, and the service runs offline: no test touches the
network.
"""

from collections.abc import Iterator
import pathlib
import shutil

import pydantic
import pytest
from starlette import testclient

import conftest
from keel import answer
from keel import config
from keel import errors
from keel import indexer
from keel import retriever
from keel import users
from keel.api import app as api_app
from keel.api import financials as financials_api
from keel.providers import mock
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

LEGACY_TOKEN = "legacy-token-for-financials-tests"  # noqa: S105
FACTS = conftest.FIXTURES / "financials" / "CIK0001045810.json"


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    out = tmp_path_factory.mktemp("financials") / "index"
    loaded = config.load_settings(conftest.CONFIG_FILE, env_file=None)
    embedder = conftest.FakeEmbedder()
    indexer.build_index(loaded, conftest.MINI_CORPUS, out, lambda: embedder)
    return out


@pytest.fixture
def api_settings(
    settings: config.Settings,
    tmp_path: pathlib.Path,
    index_dir: pathlib.Path,
) -> config.Settings:
    edgar_dir = tmp_path / "edgar"
    (edgar_dir / "companyfacts").mkdir(parents=True)
    shutil.copy(FACTS, edgar_dir / "companyfacts" / FACTS.name)
    return settings.model_copy(
        update={
            "offline": True,
            "api_token": pydantic.SecretStr(LEGACY_TOKEN),
            "llm": settings.llm.model_copy(update={"provider": "mock"}),
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "auth": config.AuthConfig(users_file=tmp_path / "users.yaml"),
            "server": config.ServerConfig(
                web_dist=tmp_path / "no-dist",
                eval_report=tmp_path / "eval" / "report.md",
            ),
            "index": settings.index.model_copy(update={"dir": index_dir}),
            "edgar": settings.edgar.model_copy(update={"cache_dir": edgar_dir}),
        }
    )


@pytest.fixture
def client(
    api_settings: config.Settings, index_dir: pathlib.Path
) -> Iterator[testclient.TestClient]:
    financials_api.clear_cache()
    build = index_dir / "current"
    step = retriever.Retriever(
        chunk_store.open_read_only(build / chunk_store.FILE_NAME),
        numpy_dense.load(build / numpy_dense.FILE_NAME),
        conftest.FakeEmbedder(),
        conftest.FakeReranker(),
        api_settings,
    )
    answerer = answer.Answerer(
        api_settings,
        step,
        mock.MockProvider(api_settings.llm.model),
        indexer.load_manifest(build).index_version,
    )
    services = api_app.Services(api_settings, answerer)
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        yield test_client


@pytest.fixture
def analyst(api_settings: config.Settings) -> dict[str, str]:
    token = users.add_user(api_settings.auth.users_file, "alice", "analyst")
    return {"Authorization": f"Bearer {token}"}


def item(body: dict, statement: str, item_id: str) -> dict:
    found = next(s for s in body["statements"] if s["id"] == statement)
    return next(i for i in found["items"] if i["id"] == item_id)


def value(body: dict, statement: str, item_id: str, label: str) -> float:
    points = item(body, statement, item_id)["points"]
    return next(p["value"] for p in points if p["label"] == label)


def test_routes_need_a_token(client):
    assert client.get("/api/financials").status_code == 401
    assert client.get("/api/financials/NVDA").status_code == 401


def test_list_names_the_indexed_companies(client, analyst):
    response = client.get("/api/financials", headers=analyst)
    assert response.status_code == 200
    companies = response.json()["companies"]
    assert [c["ticker"] for c in companies] == ["AAPL", "JPM", "NVDA"]
    nvda = companies[-1]
    assert nvda["cik"] == "0001045810"


def test_annual_statements_for_an_analyst(client, analyst):
    response = client.get("/api/financials/nvda", headers=analyst)
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "NVDA"
    assert body["period"] == "annual"
    assert body["cik"] == "0001045810"
    assert body["fiscal_year_end_month"] == 1
    assert [s["id"] for s in body["statements"]] == [
        "income",
        "balance",
        "cash",
    ]
    assert value(body, "income", "revenue", "FY2025") == 130_497_000_000
    assert value(body, "income", "net_income", "FY2025") == 72_880_000_000
    point = next(
        p
        for p in item(body, "income", "revenue")["points"]
        if p["label"] == "FY2025"
    )
    source = body["sources"][point["source"]]
    assert source["form"] == "10-K"
    assert source["url"].startswith(
        "https://www.sec.gov/Archives/edgar/data/1045810/"
    )
    assert [s["ratio"] for s in body["splits"]] == [4.0, 10.0]
    # The hidden helper row never ships.
    ids = {i["id"] for s in body["statements"] for i in s["items"]}
    assert "liabilities_and_equity" not in ids
    assert item(body, "cash", "fcf")["rule"] == (
        "operating cash flow minus capital expenditures"
    )
    # The statements come from the facts alone: no model request (D-02).
    provider = client.app.state.services.answerer.provider
    assert provider.requests == 0


def test_quarterly_statements_carry_derived_points(client, analyst):
    response = client.get(
        "/api/financials/NVDA?period=quarterly", headers=analyst
    )
    assert response.status_code == 200
    body = response.json()
    assert value(body, "income", "revenue", "Q2 FY2025") == 30_040_000_000
    q4 = next(
        p
        for p in item(body, "income", "revenue")["points"]
        if p["label"] == "Q4 FY2025"
    )
    assert q4["derived"] is True
    assert q4["note"] == "fiscal year minus the nine-month year-to-date"
    # The second request is served from memory.
    again = client.get("/api/financials/NVDA?period=quarterly", headers=analyst)
    assert again.json() == body


def test_unknown_ticker_is_404(client, analyst):
    response = client.get("/api/financials/ZZZZ", headers=analyst)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_ticker"


def test_bad_ticker_and_period_are_refused(client, analyst):
    assert (
        client.get("/api/financials/1BAD", headers=analyst).status_code == 422
    )
    response = client.get(
        "/api/financials/NVDA?period=monthly", headers=analyst
    )
    assert response.status_code == 422


def test_offline_cache_miss_is_503(client, analyst):
    response = client.get("/api/financials/JPM", headers=analyst)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "facts_unavailable"


def test_failed_fetch_is_502(client, analyst, monkeypatch):
    def fail(*_args: object) -> None:
        raise errors.EdgarFetchError("HTTP 500 from data.sec.gov")

    monkeypatch.setattr(financials_api, "load_statements", fail)
    response = client.get("/api/financials/NVDA", headers=analyst)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "edgar_error"
