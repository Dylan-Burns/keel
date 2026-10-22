"""Comp sets in question understanding and the pilot store (27.2)."""

import datetime

import pytest

import conftest
from keel import config
from keel import errors
from keel import understanding
from keel.stores import pilot

SETS = {
    "software": ("MSFT", "ORCL", "CRM", "ADBE", "ZTS"),
    "big tech": ("AAPL", "MSFT"),
    "industrial": ("GE", "LMT"),
    "outside": ("ZTS", "WDAY"),
}


def _catalog(dictionaries: understanding.Dictionaries) -> understanding.Catalog:
    end = datetime.date(2024, 12, 31)
    filings = tuple(
        understanding.FilingRef(
            ticker=ticker,
            form="10-K",
            period_end_date=end,
            fiscal_year=2024,
            fiscal_period="FY",
            filing_date=end + datetime.timedelta(days=40),
        )
        for ticker in dictionaries.companies
        if ticker != "GE"
    )
    quarantined = (
        understanding.QuarantineNote(
            ticker="GE",
            file_name="GE_10K_2015-02-27_full.txt",
            reason="registrant_mismatch",
            detail="cover registrant differs",
        ),
    )
    return understanding.Catalog(
        filings=filings, quarantined=quarantined, year_end_months={}
    )


@pytest.fixture(scope="module")
def step() -> understanding.Understander:
    root = conftest.REPO_ROOT / "config"
    dictionaries = understanding.Dictionaries.from_mappings(
        config.read_yaml(root / "companies.yaml"),
        config.read_yaml(root / "groups.yaml"),
        config.read_yaml(root / "known_external.yaml"),
    )
    return understanding.Understander(
        dictionaries, _catalog(dictionaries), comp_sets=lambda: SETS
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "my software comps",
        "our software comp set",
        "the Software Comps",
        "software peers",
        "software  comparables",
    ],
)
def test_comp_set_phrases(step, phrase: str) -> None:
    analysis = step.analyze(f"How do the margins of {phrase} compare?")
    assert [u.name for u in analysis.comp_sets] == ["software"]
    assert analysis.tickers == ("MSFT", "ORCL", "CRM", "ADBE")
    assert analysis.comp_sets[0].missing == ("ZTS",)
    assert analysis.primary_type == "comparison"
    assert analysis.groups == ()  # "software" is not read as the group


def test_comp_set_before_group_and_entities(step) -> None:
    analysis = step.analyze("Compare Tesla with my big tech comps on risks")
    assert analysis.tickers == ("TSLA", "AAPL", "MSFT")
    assert analysis.groups == ()  # "big tech" belongs to the comp set
    assert [e.ticker for e in analysis.entities] == ["TSLA"]


def test_comp_set_without_suffix_is_not_named(step) -> None:
    analysis = step.analyze("What are the risks of software companies?")
    assert analysis.comp_sets == ()
    assert analysis.groups == ("software",)
    assert not step.names_comp_set("What are the risks of software companies?")
    assert step.names_comp_set("Risks of my software comps?")


def test_comp_set_quarantined_and_outside(step) -> None:
    analysis = step.analyze("What risks do my industrial comps report?")
    assert analysis.tickers == ("LMT",)
    assert [n.ticker for n in analysis.not_indexed] == ["GE"]
    assert analysis.not_indexed[0].status == "in_manifest_not_indexed"
    outside = step.analyze("What risks do my outside comps report?")
    assert outside.tickers == ()
    assert outside.out_of_scope_reason == "not_indexed"
    assert outside.out_of_scope_parts == (
        "ZTS (comp set, not in the corpus)",
        "WDAY (comp set, not in the corpus)",
    )


def test_comp_set_store_error_is_skipped(step) -> None:
    def broken() -> dict[str, tuple[str, ...]]:
        raise errors.PilotStoreError("disk gone")

    failing = understanding.Understander(
        step.dictionaries, step.catalog, comp_sets=broken
    )
    analysis = failing.analyze("What are Apple's risks?")
    assert analysis.tickers == ("AAPL",)
    assert analysis.comp_sets == ()
    assert not failing.names_comp_set("my software comps")


def test_comp_set_from_store(tmp_path, step) -> None:
    path = tmp_path / "pilot.sqlite"
    source = understanding.store_comp_sets(path)
    assert source() == {}
    pilot.PilotStore(path).save_comp_set("Banks", ["jpm", "bac"], "alice")
    assert source() == {"banks": ("JPM", "BAC")}
    live = understanding.Understander(
        step.dictionaries, step.catalog, comp_sets=source
    )
    assert live.analyze("Credit risk of my banks comps?").tickers == (
        "JPM",
        "BAC",
    )


@pytest.mark.parametrize(
    ("typed", "name"),
    [
        ("Software", "software"),
        ("my  Software Comps", "software"),
        ("the big tech peer set", "big tech"),
        ("A&D", "a&d"),
    ],
)
def test_normalize_name(typed: str, name: str) -> None:
    assert pilot.normalize_name(typed) == name


@pytest.mark.parametrize("typed", ["", "comps", "x" * 41, "semi/conductors"])
def test_normalize_name_rejects(typed: str) -> None:
    with pytest.raises(errors.InvalidCompSetError):
        pilot.normalize_name(typed)


def test_normalize_tickers() -> None:
    assert pilot.normalize_tickers(["msft, orcl", "MSFT", " brk.b "]) == (
        "MSFT",
        "ORCL",
        "BRK.B",
    )
    for bad in ([], [" "], ["A" * 11], [f"T{n}" for n in range(26)]):
        with pytest.raises(errors.InvalidCompSetError):
            pilot.normalize_tickers(bad)


def test_store_round_trip(tmp_path) -> None:
    store = pilot.PilotStore(tmp_path / "sub" / "pilot.sqlite")
    assert store.comp_sets() == {}
    assert store.feedback() == []
    assert store.delete_comp_set("none") is False
    store.save_comp_set("energy", ["XOM"])
    store.save_comp_set("energy", ["XOM", "CVX"], "bob")
    entry = store.comp_sets()["energy"]
    assert (entry.tickers, entry.owner) == (("XOM", "CVX"), "bob")
    assert store.delete_comp_set("Energy comps") is True
    assert store.comp_sets() == {}
    with pytest.raises(errors.PilotStoreError):
        store.record_vote(request_id="r", user_name="u", vote="meh")  # type: ignore[arg-type]
    with pytest.raises(errors.PilotStoreError):
        store.record_vote(
            request_id="r", user_name="u", vote="up", note="x" * 2001
        )
    store.record_vote(request_id="r", user_name="u", vote="up", note="  ")
    assert store.feedback()[0].note is None
    assert store.feedback(flagged_only=True) == []
