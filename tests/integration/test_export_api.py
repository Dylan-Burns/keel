"""The memo export route `GET /api/export/{request_id}` (chapter 27.2)."""

import io
import pathlib

import docx
import pydantic
import pytest
from starlette import testclient
from tests.unit import test_export as samples

from keel import audit
from keel import cache
from keel import config
from keel import export
from keel.api import app as api_app

pytestmark = pytest.mark.integration

TOKEN = "test-token"  # noqa: S105
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def services(
    settings: config.Settings, tmp_path: pathlib.Path
) -> api_app.Services:
    local = settings.model_copy(
        update={
            "api_token": pydantic.SecretStr(TOKEN),
            "llm": settings.llm.model_copy(update={"provider": "mock"}),
            "logs": config.LogsConfig(dir=tmp_path / "logs"),
            "cache": config.CacheConfig(answers_dir=tmp_path / "answers"),
            "server": config.ServerConfig(web_dist=tmp_path / "dist"),
        }
    )
    built = api_app.Services(local)
    built.loaded = True  # no index: the export reads the stores only
    return built


def test_export_route(services: api_app.Services) -> None:
    assert services.results.start("live-1")
    services.results.finish("live-1", samples.make_record("live-1"))
    assert services.results.start("running-1")
    key = cache.cache_key(
        samples.QUESTION, "1.0.0", "1.3.0", "claude-sonnet-5-5"
    )
    cache.AnswerCache(services.settings.cache.answers_dir).put(
        key, samples.make_record("first-1")
    )
    audit.AuditLog(services.settings.logs.dir).write(
        samples.audit_line("later-2")
    )
    with testclient.TestClient(api_app.create_app(services)) as client:
        assert client.get("/api/export/live-1").status_code == 401
        markdown = client.get("/api/export/live-1", headers=AUTH)
        assert markdown.status_code == 200
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert markdown.headers["content-disposition"] == (
            'attachment; filename="memo-live-1.md"'
        )
        assert markdown.text.startswith(f"# {samples.QUESTION}")
        word = client.get("/api/export/later-2?format=docx", headers=AUTH)
        assert word.status_code == 200
        assert word.headers["content-type"] == export.MEDIA_TYPES["docx"]
        document = docx.Document(io.BytesIO(word.content))
        links = [link.url for p in document.paragraphs for link in p.hyperlinks]
        assert samples.AAPL_URL in links
        bad = client.get("/api/export/live-1?format=pdf", headers=AUTH)
        assert bad.status_code == 400
        pending = client.get("/api/export/running-1", headers=AUTH)
        assert pending.json()["detail"]["code"] == "pending"
        unknown = client.get("/api/export/nothing", headers=AUTH)
        assert unknown.status_code == 404
        assert client.get("/api/export/a%20b", headers=AUTH).status_code == 404


def test_export_route_without_the_extra(
    services: api_app.Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(_memo: export.Memo) -> bytes:
        raise export.ExportError(export.EXTRA_HINT)

    monkeypatch.setattr(export, "render_docx", missing)
    services.results.start("live-1")
    services.results.finish("live-1", samples.make_record("live-1"))
    with testclient.TestClient(api_app.create_app(services)) as client:
        word = client.get("/api/export/live-1?format=docx", headers=AUTH)
    assert word.status_code == 501
    assert word.json()["detail"]["code"] == "export_unavailable"
