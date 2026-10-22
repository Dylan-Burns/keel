"""The watch list store and the pure parts of `keel refresh` (26.3)."""

import datetime
import json
import pathlib

import pytest

import conftest
from keel import errors
from keel import refresh
from keel.stores import state_store

ZTS_SUBMISSIONS = (
    conftest.FIXTURES / "edgar" / "submissions" / "CIK0001555280.json"
)
DAY = datetime.date(2026, 10, 21)


def test_watch_list_add_remove_list(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "state" / state_store.FILE_NAME
    assert state_store.list_watch(path) == []
    assert not path.exists()
    assert state_store.add_watch(path, "ZTS", today=DAY)
    assert not state_store.add_watch(path, "ZTS", today=DAY)
    assert state_store.add_watch(path, "WDAY", "ana", today=DAY)
    assert state_store.add_watch(path, "ZTS", "ana", today=DAY)
    assert state_store.list_watch(path) == [
        state_store.WatchEntry("WDAY", "ana", DAY),
        state_store.WatchEntry("ZTS", "ana", DAY),
        state_store.WatchEntry("ZTS", "cli", DAY),
    ]
    assert [e.ticker for e in state_store.list_watch(path, "cli")] == ["ZTS"]
    assert state_store.remove_watch(path, "ZTS", "ana")
    assert not state_store.remove_watch(path, "ZTS", "ana")
    assert len(state_store.list_watch(path)) == 2


def test_state_store_errors(tmp_path: pathlib.Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(errors.StateStoreError, match="cannot open"):
        state_store.connect(blocker / "state.sqlite")
    garbage = tmp_path / "garbage.sqlite"
    garbage.write_bytes(b"not a database" * 100)
    with pytest.raises(errors.StateStoreError):
        state_store.add_watch(garbage, "ZTS")


def test_accession_of() -> None:
    url = (
        "https://www.sec.gov/Archives/edgar/data/19617/"
        "000162828026008131/jpm-20251231.htm"
    )
    assert refresh.accession_of(url) == "0001628280-26-008131"
    assert refresh.accession_of("https://www.sec.gov/") is None
    assert refresh.accession_of(None) is None


def test_new_filings() -> None:
    data = json.loads(ZTS_SUBMISSIONS.read_text())["data"]
    found = refresh.new_filings(data, {"0001555280-26-000011"})
    assert [(r.form, r.accession) for r in found] == [
        ("10-Q", "0001555280-26-000040")
    ]
    known = {"0001555280-26-000011", "0001555280-26-000040"}
    assert refresh.new_filings(data, known) == []
    # A company with none of the forms has nothing new.
    assert refresh.new_filings(data, set(), forms=("20-F",)) == []


def test_added_since_reads_naive_time(tmp_path: pathlib.Path) -> None:
    path = tmp_path / refresh.LOG_NAME
    assert refresh.read_log(path) == []
    t1 = datetime.datetime(2026, 10, 21, 2, 0, tzinfo=datetime.UTC)
    t2 = t1 + datetime.timedelta(days=1)
    refresh.append_log(
        path,
        [
            refresh.LogEntry(time=t1, event="added", ticker="WDAY"),
            refresh.LogEntry(time=t2, event="added", ticker="ZTS"),
            refresh.LogEntry(time=t2, event="new", ticker="NVDA"),
        ],
    )
    found = refresh.added_since(path, datetime.datetime(2026, 10, 20))
    assert [e.ticker for e in found] == ["ZTS", "WDAY"]
    assert [e.ticker for e in refresh.added_since(path, t1)] == ["ZTS"]


def test_refresh_log_errors(tmp_path: pathlib.Path) -> None:
    with pytest.raises(errors.StateStoreError, match="cannot write"):
        refresh.append_log(tmp_path, [])
    with pytest.raises(errors.StateStoreError, match="cannot read"):
        refresh.read_log(tmp_path)


def test_log_entry_naive_time_is_utc() -> None:
    entry = refresh.LogEntry(
        time=datetime.datetime(2026, 10, 21, 2, 0), event="added"
    )
    assert entry.time.tzinfo == datetime.UTC
