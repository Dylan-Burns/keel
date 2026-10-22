"""Tests for the build-time token calibration (chapter 11.6 step 2)."""

import pathlib
import sqlite3

import anthropic
import httpx2
import pytest

from keel import calibrate
from keel import cli
from keel import config
from keel import context
from keel import errors

_COLUMNS = (
    "id INTEGER PRIMARY KEY, chunk_id TEXT, filing_id TEXT, ticker TEXT, "
    "company TEXT, form TEXT, fiscal_year INTEGER, fiscal_period TEXT, "
    "period_end_date TEXT, filing_date TEXT, section TEXT, item_label TEXT, "
    "text TEXT, token_count INTEGER, is_table INTEGER, delta_only INTEGER, "
    "boilerplate_flag TEXT, simhash INTEGER, vector_row INTEGER"
)


def store(rows: int) -> sqlite3.Connection:
    """An in-memory chunk table with `rows` chunks of 100 tokens."""
    conn = sqlite3.connect(":memory:")
    conn.execute(f"CREATE TABLE chunks ({_COLUMNS})")
    for i in range(1, rows + 1):
        conn.execute(
            "INSERT INTO chunks VALUES "
            "(?, ?, 'f1', 'AAPL', 'Apple Inc.', '10-K', 2025, 'FY', "
            "'2025-09-27', '2025-10-31', 'risk_factors', 'Item 1A', ?, 100, "
            "0, 0, NULL, 0, ?)",
            (i, f"c{i}", f"chunk text {i}", i - 1),
        )
    return conn


class FakeCounter:
    """Counts 2 tokens per character and records the calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, model: str, text: str) -> int:
        self.calls.append((model, text))
        return 2 * len(text)


def test_sample_is_spread_and_stable() -> None:
    conn = store(1000)
    first = calibrate.sample_chunks(conn, 200)
    again = calibrate.sample_chunks(conn, 200)
    assert len(first) == 200
    assert [c.chunk_id for c in first] == [c.chunk_id for c in again]
    assert first[0].chunk_id == "c5"
    assert first[-1].chunk_id == "c1000"


def test_sample_of_a_small_store() -> None:
    conn = store(3)
    assert [c.chunk_id for c in calibrate.sample_chunks(conn, 200)] == [
        "c1",
        "c2",
        "c3",
    ]


def test_render_sample_matches_the_context() -> None:
    chunks = calibrate.sample_chunks(store(2), 200)
    rendered = calibrate.render_sample(chunks)
    assert rendered.count("<chunk id=") == 2
    assert 'section="risk_factors"' in rendered
    assert "chunk text 2" in rendered


def test_solve_factor() -> None:
    # 2 chunks of 100 tokens: 2 x (100 x f + 60) = 500 gives f = 1.9.
    assert calibrate.solve_factor(500, [100, 100]) == 1.9
    # The factor rounds up to 2 decimals.
    assert calibrate.solve_factor(501, [100, 100]) == 1.91
    assert calibrate.solve_factor(50, [100]) == 0.0
    with pytest.raises(ValueError, match="no tokens"):
        calibrate.solve_factor(10, [])


def test_measure_makes_1_count_call() -> None:
    counter = FakeCounter()
    result = calibrate.measure(
        store(400), counter, "claude-sonnet-5-5", factor_before=1.15
    )
    assert len(counter.calls) == 1
    assert counter.calls[0][0] == "claude-sonnet-5-5"
    assert result.chunks == 200
    assert result.embedding_tokens == 20_000
    assert result.counted_tokens == 2 * len(counter.calls[0][1])
    assert result.estimate_before == 200 * context.estimate_tokens(100, 1.15)
    assert result.factor == calibrate.solve_factor(
        result.counted_tokens, [100] * 200
    )


def test_anthropic_counter() -> None:
    class Messages:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        def count_tokens(self, **kwargs: object) -> object:
            self.kwargs = kwargs
            return type("Count", (), {"input_tokens": 42})()

    class Client:
        messages = Messages()

    client = Client()
    count = calibrate.anthropic_counter(client)
    assert count("m", "text") == 42
    assert client.messages.kwargs == {
        "model": "m",
        "messages": [{"role": "user", "content": "text"}],
    }


def test_calibrate_command(
    settings: config.Settings,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    build = tmp_path / "b1"
    build.mkdir()
    (tmp_path / "current").symlink_to(build)
    conn = sqlite3.connect(build / "chunks.sqlite")
    conn.execute(f"CREATE TABLE chunks ({_COLUMNS})")
    conn.execute(
        "INSERT INTO chunks VALUES (1, 'c1', 'f1', 'AAPL', 'Apple Inc.', "
        "'10-K', 2025, 'FY', '2025-09-27', '2025-10-31', 'mdna', NULL, "
        "'text', 10, 0, 0, NULL, 0, 0)"
    )
    conn.commit()
    conn.close()
    code = cli.run_calibrate(settings, 200, tmp_path, counter=FakeCounter())
    out = capsys.readouterr().out
    assert code == 0
    assert "sample: 1 chunks" in out
    assert "calibration factor:" in out


def test_calibrate_command_needs_an_index_and_a_key(
    settings: config.Settings, tmp_path: pathlib.Path
) -> None:
    with pytest.raises(errors.IndexMissingError):
        cli.run_calibrate(settings, 200, tmp_path)
    build = tmp_path / "b1"
    build.mkdir()
    (tmp_path / "current").symlink_to(build)
    sqlite3.connect(build / "chunks.sqlite").close()
    with pytest.raises(errors.ProviderRequestError):
        cli.run_calibrate(settings, 200, tmp_path)


def test_sample_spans_the_whole_store() -> None:
    # 399 rows over 200: every 2nd row, so the sample reaches the end.
    chunks = calibrate.sample_chunks(store(399), 200)
    assert len(chunks) == 199
    assert chunks[0].chunk_id == "c2"
    assert chunks[-1].chunk_id == "c398"


def test_measure_needs_chunks() -> None:
    counter = FakeCounter()
    with pytest.raises(errors.IndexMissingError):
        calibrate.measure(store(0), counter, "m", factor_before=1.15)
    with pytest.raises(errors.IndexMissingError):
        calibrate.measure(store(5), counter, "m", factor_before=1.15, size=0)
    assert not counter.calls


def test_anthropic_counter_maps_errors() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/x")
    response = httpx2.Response(429, request=request)

    class Messages:
        def count_tokens(self, **kwargs: object) -> object:
            del kwargs
            raise anthropic.RateLimitError(
                "HTTP 429", response=response, body=None
            )

    class Client:
        messages = Messages()

    count = calibrate.anthropic_counter(Client())
    with pytest.raises(errors.ProviderRateLimitedError):
        count("m", "text")


@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_sample_flag_rejects_bad_values(value: str) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["calibrate", "--sample", value])
    assert (
        cli.build_parser().parse_args(["calibrate", "--sample", "5"]).sample
        == 5
    )
