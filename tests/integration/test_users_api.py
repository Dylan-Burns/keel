"""Users, history, and shareable links through the API (chapter 27.2).

The app runs on a small synthetic index with the mock provider, as in
tests/integration/test_api.py, with a users file of 2 analysts and an
admin next to the legacy `KEEL_API_TOKEN`.
"""

from collections.abc import Iterator
import json
import pathlib

import pydantic
import pytest
from starlette import testclient

import conftest
from keel import answer
from keel import config
from keel import retriever
from keel import users
from keel.api import app as api_app
from keel.api import history
from keel.api import ratelimit
from keel.api import routes
from keel.providers import mock
from keel.stores import chunk_store
from keel.stores import numpy_dense

pytestmark = pytest.mark.integration

LEGACY_TOKEN = "legacy-token"  # noqa: S105
FILINGS = (
    conftest.FakeFiling("AAPL", "10-K", "2025-09-27", "2025-10-31", 2025),
    conftest.FakeFiling("TSLA", "10-K", "2025-12-31", "2026-01-29", 2025),
    conftest.FakeFiling("JPM", "10-K", "2025-12-31", "2026-02-13", 2025),
)
WORDS = ("supply", "tariffs", "privacy", "antitrust", "credit", "labor")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class NoSleep:
    async def __call__(self, _seconds: float) -> None:
        return None


@pytest.fixture(autouse=True)
def no_pace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "MOCK_PACE_SECONDS", 0.0)


@pytest.fixture
def index_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    chunks = [
        conftest.make_chunk(
            filing,
            "risk_factors",
            k,
            f"Risk factors: {filing.ticker} names {WORDS[k]} risk in "
            f"{2020 + k} with {k + 1},000 million exposure "
            + " ".join(f"{w}{k}{filing.ticker}" for w in WORDS),
        )
        for filing in FILINGS
        for k in range(len(WORDS))
    ]
    return conftest.build_store(tmp_path / "index", FILINGS, chunks)


@pytest.fixture
def users_file(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "users.yaml"


@pytest.fixture
def tokens(users_file: pathlib.Path) -> dict[str, str]:
    return {
        "alice": users.add_user(users_file, "alice", "analyst"),
        "bob": users.add_user(users_file, "bob", "partner"),
        "carol": users.add_user(users_file, "carol", "admin"),
    }


@pytest.fixture
def api_settings(
    settings: config.Settings,
    tmp_path: pathlib.Path,
    users_file: pathlib.Path,
) -> config.Settings:
    return settings.model_copy(
        update={
            "api_token": pydantic.SecretStr(LEGACY_TOKEN),
            "llm": settings.llm.model_copy(update={"provider": "mock"}),
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "auth": config.AuthConfig(users_file=users_file),
            "server": config.ServerConfig(web_dist=tmp_path / "no-dist"),
            "corpus": settings.corpus.model_copy(
                update={"dir": tmp_path / "no-corpus"}
            ),
        }
    )


def make_answerer(
    settings: config.Settings, index_dir: pathlib.Path
) -> answer.Answerer:
    build = index_dir / "current"
    step = retriever.Retriever(
        chunk_store.open_read_only(build / chunk_store.FILE_NAME),
        numpy_dense.load(build / numpy_dense.FILE_NAME),
        conftest.FakeEmbedder(),
        conftest.FakeReranker(),
        settings,
    )
    return answer.Answerer(
        settings,
        step,
        mock.MockProvider(settings.llm.model),
        "1.0.0",
        sleep=NoSleep(),
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def services(api_settings, index_dir, clock) -> api_app.Services:
    return api_app.Services(
        api_settings, make_answerer(api_settings, index_dir), clock=clock
    )


@pytest.fixture
def client(services, tokens) -> Iterator[testclient.TestClient]:
    del tokens  # the users exist before the app starts
    with testclient.TestClient(api_app.create_app(services)) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ask(client: testclient.TestClient, token: str, text: str, key: str) -> dict:
    response = client.post(
        "/api/ask",
        json={"question": text, "options": {"stream": False}},
        headers={**bearer(token), "Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def audit_lines(settings: config.Settings) -> list[dict]:
    path = settings.logs.dir / "audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_user_token_scope(client, api_settings, tokens) -> None:
    question = api_settings.demo.example_questions[0]
    # Every named token and the legacy token pass; anything else is 401.
    for token in (*tokens.values(), LEGACY_TOKEN):
        assert client.get("/api/coverage", headers=bearer(token)).is_success
    for header in ("Bearer nope", f"Basic {tokens['alice']}", tokens["bob"]):
        response = client.get("/api/history", headers={"Authorization": header})
        assert response.status_code == 401
    # A hash from the file is not a token.
    stored = users.load_file(api_settings.auth.users_file).users[0]
    assert stored.token_hash.startswith("sha256:")
    hashed = client.get("/api/history", headers=bearer(stored.token_hash))
    assert hashed.status_code == 401
    assert tokens["alice"] not in api_settings.auth.users_file.read_text()
    # The Principal carries the user into the audit record.
    ask(client, tokens["alice"], question, "scope-alice")
    ask(client, LEGACY_TOKEN, question, "scope-legacy")
    by_id = {r["request_id"]: r for r in audit_lines(api_settings)}
    assert by_id["scope-alice"]["user_name"] == "alice"
    assert by_id["scope-legacy"]["user_name"] == users.LEGACY_USER
    # Only an admin reads every history.
    own = client.get("/api/history", headers=bearer(tokens["alice"]))
    assert own.json()["user"] == "alice"
    assert own.json()["role"] == "analyst"
    denied = client.get(
        "/api/history?scope=all", headers=bearer(tokens["alice"])
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"
    for token in (tokens["carol"], LEGACY_TOKEN):
        every = client.get("/api/history?scope=all", headers=bearer(token))
        assert every.status_code == 200
        assert {i["user"] for i in every.json()["items"]} == {
            "alice",
            users.LEGACY_USER,
        }


def test_user_added_without_restart(client, api_settings) -> None:
    token = users.add_user(api_settings.auth.users_file, "dave", "analyst")
    response = client.get("/api/history", headers=bearer(token))
    assert response.status_code == 200
    assert response.json()["user"] == "dave"


def test_history_per_user(client, api_settings, tokens) -> None:
    first, second, third = api_settings.demo.example_questions[:3]
    ask(client, tokens["alice"], first, "a-1")
    ask(client, tokens["bob"], second, "b-1")
    ask(client, tokens["alice"], third, "a-2")
    alice = client.get("/api/history", headers=bearer(tokens["alice"]))
    bob = client.get("/api/history", headers=bearer(tokens["bob"]))
    alice_items = alice.json()["items"]
    bob_items = bob.json()["items"]
    # Newest first, own questions only.
    assert [i["request_id"] for i in alice_items] == ["a-2", "a-1"]
    assert [i["question"] for i in alice_items] == [third, first]
    assert [i["request_id"] for i in bob_items] == ["b-1"]
    assert {i["user"] for i in alice_items} == {"alice"}
    item = alice_items[0]
    assert item["outcome"] == "answered"
    assert item["stored"] is True  # in the result store for 10 minutes
    assert alice_items[1]["tickers"] == ["AAPL", "TSLA", "JPM"]
    limited = client.get(
        "/api/history?limit=1", headers=bearer(tokens["alice"])
    )
    assert [i["request_id"] for i in limited.json()["items"]] == ["a-2"]
    assert (
        client.get(
            "/api/history?limit=0", headers=bearer(tokens["alice"])
        ).status_code
        == 422
    )
    carol = client.get("/api/history", headers=bearer(tokens["carol"]))
    assert carol.json()["items"] == []
    every = client.get(
        "/api/history?scope=all", headers=bearer(tokens["carol"])
    )
    assert [i["request_id"] for i in every.json()["items"]] == [
        "a-2",
        "b-1",
        "a-1",
    ]


def test_share_link(client, services, api_settings, tokens, clock) -> None:
    question = api_settings.demo.example_questions[0]
    asked = ask(client, tokens["alice"], question, "share-1")
    assert asked["audit"]["user_name"] == "alice"
    # Any token holder opens the link, read-only; the asker stays private.
    shared = client.get("/api/shared/share-1", headers=bearer(tokens["bob"]))
    assert shared.status_code == 200
    body = shared.json()
    assert body["request_id"] == "share-1"
    assert body["answer"] == asked["answer"]
    assert body["audit"]["user_name"] is None
    own = client.get("/api/shared/share-1", headers=bearer(tokens["alice"]))
    assert own.json()["audit"]["user_name"] == "alice"
    admin = client.get("/api/shared/share-1", headers=bearer(tokens["carol"]))
    assert admin.json()["audit"]["user_name"] == "alice"
    # The own-result route stays with the asker and the admins.
    for token, status in (("alice", 200), ("carol", 200), ("bob", 404)):
        response = client.get(
            "/api/results/share-1", headers=bearer(tokens[token])
        )
        assert response.status_code == status
    assert (
        "answer"
        not in client.get(
            "/api/results/share-1", headers=bearer(tokens["bob"])
        ).json()
    )
    # After the result store expires, a cached answer still opens: the
    # audit record names the 4 parts of the cache key (decision D-29).
    answerer = services.answerer
    entry = {k: v for k, v in asked.items() if k != "audit"}
    answerer.cache.put(answerer.cache_key(question), entry)
    response = client.post(
        "/api/ask",
        json={"question": question, "options": {"stream": False}},
        headers={**bearer(tokens["alice"]), "Idempotency-Key": "share-2"},
    )
    assert response.json()["meta"]["from_cache"] is True
    other = api_settings.demo.example_questions[1]
    ask(client, tokens["bob"], other, "share-3")  # never cached
    clock.now += 3600  # past the 10 minutes of the result store
    assert services.results.state("share-2") == (False, None)
    later = client.get("/api/shared/share-2", headers=bearer(tokens["bob"]))
    assert later.status_code == 200
    stored = later.json()
    assert stored["request_id"] == "share-2"
    assert stored["answer"] == asked["answer"]
    assert stored["audit"]["request_id"] == "share-2"
    assert stored["audit"]["user_name"] is None
    items = client.get("/api/history", headers=bearer(tokens["alice"])).json()[
        "items"
    ]
    stored_flags = {i["request_id"]: i["stored"] for i in items}
    assert stored_flags == {"share-2": True, "share-1": True}
    # An unknown ID, or an expired answer outside the cache, is a 404.
    for route in ("results", "shared"):
        for request_id in ("share-3", "no-such-id"):
            missing = client.get(
                f"/api/{route}/{request_id}", headers=bearer(tokens["bob"])
            )
            assert missing.status_code == 404
            assert missing.json()["detail"]["code"] == "not_found"
    # After expiry the own-result route still knows the asker from the audit.
    assert (
        client.get(
            "/api/results/share-2", headers=bearer(tokens["alice"])
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/results/share-2", headers=bearer(tokens["bob"])
        ).status_code
        == 404
    )


def test_replay_is_scoped_to_the_owner(client, api_settings, tokens) -> None:
    question = api_settings.demo.example_questions[0]
    asked = ask(client, tokens["alice"], question, "owned-1")
    # Bob sends Alice's Idempotency-Key: no data of her answer comes back.
    for accept in ("application/json", "text/event-stream"):
        replay = client.post(
            "/api/ask",
            json={"question": "anything about Apple risk"},
            headers={
                **bearer(tokens["bob"]),
                "Idempotency-Key": "owned-1",
                "Accept": accept,
            },
        )
        assert replay.status_code == 409
        assert replay.json()["detail"]["code"] == "request_id_taken"
        assert asked["answer"]["direct_answer"] not in replay.text
    # Alice replays her own key and gets her answer.
    again = ask(client, tokens["alice"], question, "owned-1")
    assert again["answer"] == asked["answer"]


def test_rate_limit_per_user(
    client, services, api_settings, tokens, clock
) -> None:
    services.limiter = ratelimit.RateLimiter(1, 100, clock=clock)
    question = api_settings.demo.example_questions[0]
    ask(client, tokens["alice"], question, "rl-a1")
    # Alice's bucket is empty; Bob, on the same address, has his own.
    second = client.post(
        "/api/ask",
        json={"question": question, "options": {"stream": False}},
        headers={**bearer(tokens["alice"]), "Idempotency-Key": "rl-a2"},
    )
    assert second.status_code == 429
    ask(client, tokens["bob"], question, "rl-b1")


def test_history_reads_rotated_files(tmp_path: pathlib.Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    old = {"request_id": "old", "timestamp": "2026-10-01T10:00:00+00:00"}
    new = {"request_id": "new", "timestamp": "2026-10-02T10:00:00+00:00"}
    (logs / "audit-2026-10-01.jsonl").write_text(
        json.dumps({**old, "user_name": "alice"}) + "\nnot json\n\n"
    )
    (logs / "audit.jsonl").write_text(
        json.dumps({**new, "user_name": "alice", "cost_usd": 0.1}) + "\n"
    )
    answers = history.cache.AnswerCache(tmp_path / "answers")
    items = history.history(logs, answers, "alice")
    assert [i.request_id for i in items] == ["new", "old"]
    assert items[0].cost_usd == 0.1
    assert history.history(logs, answers, "bob") == []
    assert history.find_record(logs, "old")["user_name"] == "alice"
    assert history.stored_answer(logs, answers, "old") is None
    assert history.history(tmp_path / "absent", answers, None) == []
