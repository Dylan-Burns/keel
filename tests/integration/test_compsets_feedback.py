"""Comp sets, question templates, and feedback through the API (27.2).

The app runs on the small synthetic index of tests/integration/
test_users_api.py with the mock provider, 2 analysts, and an admin.
"""

from collections.abc import Iterator
import pathlib
import sqlite3

import pydantic
import pytest
from starlette import testclient
import test_users_api as base

import conftest
from keel import cli
from keel import config
from keel import errors
from keel import templates
from keel import users
from keel.api import app as api_app
from keel.api import routes
from keel.stores import pilot

pytestmark = pytest.mark.integration

LEGACY_TOKEN = "legacy-token"  # noqa: S105
QUESTION = "How do the risk factors of my auto comps compare?"


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
            f"Risk factors: {filing.ticker} names {base.WORDS[k]} risk in "
            f"{2020 + k} with {k + 1},000 million exposure "
            + " ".join(f"{w}{k}{filing.ticker}" for w in base.WORDS),
        )
        for filing in base.FILINGS
        for k in range(len(base.WORDS))
    ]
    return conftest.build_store(tmp_path / "index", base.FILINGS, chunks)


@pytest.fixture
def api_settings(
    settings: config.Settings, tmp_path: pathlib.Path
) -> config.Settings:
    return settings.model_copy(
        update={
            "api_token": pydantic.SecretStr(LEGACY_TOKEN),
            "llm": settings.llm.model_copy(update={"provider": "mock"}),
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "auth": config.AuthConfig(users_file=tmp_path / "users.yaml"),
            "server": config.ServerConfig(web_dist=tmp_path / "no-dist"),
            "corpus": settings.corpus.model_copy(
                update={"dir": tmp_path / "no-corpus"}
            ),
        }
    )


@pytest.fixture
def tokens(api_settings: config.Settings) -> dict[str, str]:
    path = api_settings.auth.users_file
    return {
        "alice": users.add_user(path, "alice", "analyst"),
        "bob": users.add_user(path, "bob", "analyst"),
        "carol": users.add_user(path, "carol", "admin"),
    }


@pytest.fixture
def services(api_settings, index_dir) -> api_app.Services:
    return api_app.Services(
        api_settings,
        base.make_answerer(api_settings, index_dir),
        clock=base.FakeClock(),
    )


@pytest.fixture
def client(services, tokens) -> Iterator[testclient.TestClient]:
    del tokens
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


def feedback_rows(settings: config.Settings) -> list[tuple]:
    with sqlite3.connect(settings.pilot.db) as conn:
        return conn.execute(
            "SELECT request_id, user_name, vote, note, question "
            "FROM feedback ORDER BY id"
        ).fetchall()


def test_compset_resolves(client, services, api_settings, tokens) -> None:
    saved = client.put(
        "/api/compsets/My Auto Comps",
        json={"tickers": ["tsla", "AAPL, ZZZZ"]},
        headers=bearer(tokens["alice"]),
    )
    assert saved.status_code == 200, saved.text
    item = saved.json()
    assert item["name"] == "auto"
    assert item["tickers"] == ["TSLA", "AAPL", "ZZZZ"]
    assert item["owner"] == "alice"
    assert item["missing"] == ["ZZZZ"]  # `keel add` adds it (chapter 26)
    assert item["editable"] is True
    # The question names the set; the analysis expands it in saved order.
    analysis = services.answerer.understander.analyze(QUESTION)
    assert analysis.tickers == ("TSLA", "AAPL")
    assert [u.name for u in analysis.comp_sets] == ["auto"]
    assert analysis.comp_sets[0].text == "my auto comps"
    assert analysis.comp_sets[0].missing == ("ZZZZ",)
    assert "ZZZZ (comp set, not in the corpus)" in analysis.out_of_scope_parts
    assert analysis.primary_type == "comparison"
    # The answer runs on the expanded tickers with 1 model request.
    body = ask(client, tokens["bob"], QUESTION, "set-1")
    assert body["analysis"]["tickers"] == ["TSLA", "AAPL"]
    assert body["analysis"]["comp_sets"][0]["name"] == "auto"
    assert body["meta"]["model_requests"] == 1
    # An edit takes effect on the next question, with no restart.
    client.put(
        "/api/compsets/auto",
        json={"tickers": ["JPM"]},
        headers=bearer(tokens["alice"]),
    )
    assert services.answerer.understander.analyze(QUESTION).tickers == ("JPM",)
    # The answer cache skips a question that names a comp set.
    assert services.answerer._cacheable(QUESTION) is False
    assert services.answerer._cacheable("Apple risks?") is True
    listed = client.get("/api/compsets", headers=bearer(tokens["bob"]))
    assert [i["name"] for i in listed.json()["items"]] == ["auto"]
    assert listed.json()["items"][0]["editable"] is False


def test_compset_owner_rules(client, tokens) -> None:
    alice, bob, carol = (bearer(tokens[n]) for n in ("alice", "bob", "carol"))
    body = {"tickers": ["AAPL"]}
    assert client.put("/api/compsets/tech", json=body, headers=alice).is_success
    denied = client.put("/api/compsets/tech", json=body, headers=bob)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"
    assert client.delete("/api/compsets/tech", headers=bob).status_code == 403
    assert client.put("/api/compsets/tech", json=body, headers=carol).is_success
    assert client.delete("/api/compsets/tech", headers=carol).status_code == 204
    assert client.delete("/api/compsets/tech", headers=carol).status_code == 404
    bad = client.put(
        "/api/compsets/tech", json={"tickers": ["AB$C"]}, headers=alice
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "invalid_comp_set"
    empty = client.put("/api/compsets/x", json={"tickers": []}, headers=alice)
    assert empty.status_code == 422
    assert client.get("/api/compsets").status_code == 401


def test_template_fill(client, services, api_settings, tokens) -> None:
    loaded = templates.load(api_settings.pilot.templates)
    assert [t.id for t in loaded] == [
        "public_comparables",
        "risk_benchmark",
        "portfolio_review",
        "regulatory_scan",
        "memo_paragraph",
    ]
    risk = templates.find(loaded, "risk_benchmark")
    question = templates.fill(risk, " Apple and  Tesla ", "fiscal 2025")
    assert question == (
        "What are the primary risk factors facing Apple and Tesla in "
        "fiscal 2025, and how do they compare?"
    )
    # An empty period takes the default; a brace in a value stays text.
    assert "the latest fiscal year" in templates.fill(risk, "Apple")
    assert "{period}" in templates.fill(risk, "{period}", "x")
    with pytest.raises(errors.TemplateError):
        templates.fill(risk, "  ")
    with pytest.raises(errors.TemplateError):
        templates.find(loaded, "nope")
    with pytest.raises(errors.TemplateError):
        templates.fill(risk, "A" * 301)
    # A filled template is an ordinary question for the understanding.
    analysis = services.answerer.understander.analyze(question)
    assert analysis.tickers == ("AAPL", "TSLA")
    assert analysis.time_scope.fiscal_year == 2025
    response = client.get("/api/templates", headers=bearer(tokens["bob"]))
    assert response.status_code == 200
    assert len(response.json()["items"]) == 5
    assert response.json()["items"][1]["label"] == "Risk benchmark"


def test_template_file_errors(tmp_path) -> None:
    path = tmp_path / "templates.yaml"
    path.write_text(
        "one:\n  label: One\n  text: no slots\n  default_period: x\n"
    )
    with pytest.raises(errors.ConfigError):
        templates.load(path)
    path.write_text("one: [1, 2]\n")
    with pytest.raises(errors.ConfigError):
        templates.load(path)


def test_templates_unavailable(client, services, tokens, tmp_path) -> None:
    services.settings = services.settings.model_copy(
        update={
            "pilot": config.PilotConfig(
                db=tmp_path / "p.sqlite", templates=tmp_path / "none.yaml"
            )
        }
    )
    response = client.get("/api/templates", headers=bearer(tokens["bob"]))
    assert response.status_code == 503


def test_feedback_vote(client, api_settings, tokens) -> None:
    question = api_settings.demo.example_questions[0]
    ask(client, tokens["alice"], question, "vote-1")
    up = client.post(
        "/api/feedback",
        json={"request_id": "vote-1", "vote": "up"},
        headers=bearer(tokens["alice"]),
    )
    assert up.status_code == 200, up.text
    assert up.json() == {
        "request_id": "vote-1",
        "vote": "up",
        "note": None,
        "user": "alice",
    }
    # The vote lands in the feedback table with the question.
    assert feedback_rows(api_settings) == [
        ("vote-1", "alice", "up", None, question)
    ]
    # A link viewer votes too; a second vote of a user replaces the first.
    client.post(
        "/api/feedback",
        json={"request_id": "vote-1", "vote": "down", "note": " wrong year "},
        headers=bearer(tokens["bob"]),
    )
    client.post(
        "/api/feedback",
        json={"request_id": "vote-1", "vote": "down"},
        headers=bearer(tokens["alice"]),
    )
    rows = feedback_rows(api_settings)
    assert [(r[1], r[2], r[3]) for r in rows] == [
        ("alice", "down", None),
        ("bob", "down", "wrong year"),
    ]
    store = pilot.PilotStore(api_settings.pilot.db)
    assert all(f.flagged for f in store.feedback(flagged_only=True))
    # Unknown answers, bad votes, and missing tokens are refused.
    unknown = client.post(
        "/api/feedback",
        json={"request_id": "nope", "vote": "up"},
        headers=bearer(tokens["bob"]),
    )
    assert unknown.status_code == 404
    bad = client.post(
        "/api/feedback",
        json={"request_id": "vote-1", "vote": "meh"},
        headers=bearer(tokens["bob"]),
    )
    assert bad.status_code == 422
    long_note = {"request_id": "vote-1", "vote": "up", "note": "x" * 2001}
    too_long = client.post(
        "/api/feedback", json=long_note, headers=bearer(tokens["bob"])
    )
    assert too_long.status_code == 422
    assert client.post("/api/feedback", json={}).status_code == 401
    assert len(feedback_rows(api_settings)) == 2


def test_store_failure_is_503(client, services, tokens, tmp_path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    services.settings = services.settings.model_copy(
        update={"pilot": config.PilotConfig(db=blocker / "pilot.sqlite")}
    )
    alice = bearer(tokens["alice"])
    saved = client.put(
        "/api/compsets/tech", json={"tickers": ["AAPL"]}, headers=alice
    )
    assert saved.status_code == 503
    assert saved.json()["detail"]["code"] == "store_unavailable"
    blocker.unlink()
    blocker.mkdir()
    (blocker / "pilot.sqlite").mkdir()
    assert client.get("/api/compsets", headers=alice).status_code == 503


def test_pilot_commands(api_settings, tmp_path, monkeypatch, capsys) -> None:
    config_file = tmp_path / "keel.yaml"
    config_file.write_text(conftest.CONFIG_FILE.read_text())
    monkeypatch.setenv("KEEL_PILOT__DB", str(api_settings.pilot.db))
    monkeypatch.setenv(
        "KEEL_PILOT__TEMPLATES", str(api_settings.pilot.templates)
    )
    assert cli.main(["--config", str(config_file), "compsets", "add",
                     "Our Big Tech comps", "MSFT", "goog"]) == 0  # fmt: skip
    assert "saved big tech: MSFT GOOG" in capsys.readouterr().out
    assert cli.main(["--config", str(config_file), "compsets", "list"]) == 0
    assert "big tech\tMSFT GOOG" in capsys.readouterr().out
    args = ["--config", str(config_file), "compsets", "remove", "big tech"]
    assert cli.main(args) == 0
    assert cli.main(args) == 1
    assert "no comp set big tech" in capsys.readouterr().out
    pilot.PilotStore(api_settings.pilot.db).record_vote(
        request_id="r1", user_name="alice", vote="down", note="n"
    )
    assert (
        cli.main(["--config", str(config_file), "feedback", "--flagged"]) == 0
    )
    assert '"request_id": "r1"' in capsys.readouterr().out
    assert cli.main(["--config", str(config_file), "template"]) == 0
    assert capsys.readouterr().out.count("\n") == 5
    fill = ["template", "regulatory_scan", "--companies", "my pharma comps"]
    assert cli.main(["--config", str(config_file), *fill]) == 0
    assert "my pharma comps" in capsys.readouterr().out
    bad = ["--config", str(config_file), "compsets", "add", "!", "AAPL"]
    assert cli.main(bad) == 2
