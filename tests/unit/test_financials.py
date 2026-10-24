"""The statements of the financials page (`keel.financials`).

The golden values come from NVIDIA's 10-K for fiscal 2025 and its 10-Q
filings, read from a trimmed copy of the cached company facts (the rows of
the configured concepts that end after mid 2020). The other tests build
small company facts documents by hand.
"""

import datetime
import json
import pathlib
from typing import Any

import pytest

import conftest
from keel import edgar
from keel import errors
from keel import financials

FIXTURE = conftest.FIXTURES / "financials" / "CIK0001045810.json"
CONFIG = conftest.REPO_ROOT / "config" / "financials.yaml"
D = datetime.date.fromisoformat


@pytest.fixture(scope="module")
def statements_config() -> financials.FinancialsConfig:
    return financials.load_financials_config(CONFIG)


@pytest.fixture(scope="module")
def nvda(
    statements_config: financials.FinancialsConfig,
) -> financials.Statements:
    document = json.loads(FIXTURE.read_text())["data"]
    return financials.extract(document, statements_config, "0001045810")


def series(
    statements: financials.Statements, item_id: str
) -> financials.Series:
    for statement in statements.statements:
        for found in statement.series:
            if found.item.id == item_id:
                return found
    raise AssertionError(f"no item {item_id}")


def point(
    statements: financials.Statements,
    item_id: str,
    period: financials.Period,
    label: str,
) -> financials.Point:
    for found in series(statements, item_id).points(period):
        if found.label == label:
            return found
    raise AssertionError(f"no {label} for {item_id}")


@pytest.mark.parametrize(
    ("item_id", "period", "label", "millions"),
    [
        ("revenue", "annual", "FY2025", 130_497),
        ("net_income", "annual", "FY2025", 72_880),
        ("revenue", "annual", "FY2024", 60_922),
        ("revenue", "annual", "FY2023", 26_974),
        ("revenue", "quarterly", "Q1 FY2025", 26_044),
        ("revenue", "quarterly", "Q2 FY2025", 30_040),
        ("revenue", "quarterly", "Q3 FY2025", 35_082),
    ],
)
def test_nvda_golden_values(nvda, item_id, period, label, millions):
    found = point(nvda, item_id, period, label)
    assert found.value == millions * 1_000_000
    assert found.source.form in {"10-K", "10-Q"}


def test_nvda_fiscal_labels_follow_the_company(nvda):
    fy2025 = point(nvda, "revenue", "annual", "FY2025")
    assert fy2025.start == D("2024-01-29")
    assert fy2025.end == D("2025-01-26")
    assert fy2025.source.form == "10-K"
    assert nvda.fiscal_year_end == 1
    assert nvda.company == "NVIDIA CORP"


def test_q4_is_the_year_minus_nine_months(nvda):
    q4 = point(nvda, "revenue", "quarterly", "Q4 FY2025")
    assert q4.derived
    assert q4.note == "fiscal year minus the nine-month year-to-date"
    assert q4.value == (130_497 - 26_044 - 30_040 - 35_082) * 1_000_000
    assert q4.start == D("2024-10-28")
    assert q4.end == D("2025-01-26")


def test_cash_flow_quarters_are_de_accumulated(nvda):
    q2 = point(nvda, "ocf", "quarterly", "Q2 FY2025")
    assert q2.derived
    assert q2.note == "year-to-date difference"
    q1 = point(nvda, "ocf", "quarterly", "Q1 FY2025")
    assert not q1.derived
    year = point(nvda, "ocf", "annual", "FY2025").value
    quarters = [
        point(nvda, "ocf", "quarterly", f"Q{n} FY2025").value
        for n in range(1, 5)
    ]
    assert sum(quarters) == pytest.approx(year)


def test_free_cash_flow_is_ocf_minus_capex(nvda):
    ocf = point(nvda, "ocf", "annual", "FY2025").value
    capex = point(nvda, "capex", "annual", "FY2025").value
    fcf = point(nvda, "fcf", "annual", "FY2025")
    assert capex < 0
    assert fcf.derived
    assert fcf.value == ocf + capex


def test_eps_is_split_adjusted(nvda):
    assert [(s.date.year, s.ratio) for s in nvda.splits] == [
        (2021, 4.0),
        (2024, 10.0),
    ]
    # FY2022 diluted EPS was $3.85 in the 10-K for fiscal 2024, filed
    # before the 10-for-1 split of June 2024.
    eps = point(nvda, "eps_diluted", "annual", "FY2022")
    assert eps.value == pytest.approx(0.385, abs=1e-6)
    assert eps.note == "split-adjusted"
    later = point(nvda, "eps_diluted", "annual", "FY2025")
    assert later.value == pytest.approx(2.94)
    assert later.note is None


def test_balance_points_are_instants(nvda):
    assets = point(nvda, "total_assets", "annual", "FY2025")
    assert assets.start is None
    assert assets.end == D("2025-01-26")


def row(
    start: str | None,
    end: str,
    val: float,
    filed: str,
    form: str = "10-Q",
    accn: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "end": end,
        "val": val,
        "accn": accn or f"0000000000-{filed[2:4]}-{filed[5:7]}{filed[8:]}00",
        "fy": int(end[:4]),
        "fp": "FY" if form == "10-K" else "Q1",
        "form": form,
        "filed": filed,
    }
    if start is not None:
        out["start"] = start
    return out


def document(concepts: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    gaap: dict[str, Any] = {}
    for name, rows in concepts.items():
        local, _, unit = name.partition("|")
        gaap.setdefault(local, {"units": {}})["units"][unit or "USD"] = rows
    return {"entityName": "TEST CO", "facts": {"us-gaap": gaap}}


# A calendar year company: FY2024 with 3 quarters filed as quarters.
REVENUE = [
    row("2024-01-01", "2024-12-31", 1000, "2025-02-10", "10-K"),
    row("2024-01-01", "2024-03-31", 200, "2024-05-01"),
    row("2024-04-01", "2024-06-30", 250, "2024-08-01"),
    row("2024-07-01", "2024-09-30", 260, "2024-11-01"),
]


def test_q4_from_the_year_minus_three_quarters(statements_config):
    built = financials.extract(
        document({"Revenues": REVENUE}), statements_config
    )
    q4 = point(built, "revenue", "quarterly", "Q4 FY2024")
    assert q4.derived
    assert q4.note == "fiscal year minus Q1 to Q3"
    assert q4.value == 290
    assert q4.start == D("2024-10-01")


def test_ytd_cash_flow_and_the_capex_fallback(statements_config):
    # Capex is tagged PaymentsToAcquirePropertyPlantAndEquipment until
    # the 10-K and PaymentsToAcquireProductiveAssets after it.
    ppe = [
        row("2024-01-01", "2024-03-31", 10, "2024-05-01"),
        row("2024-01-01", "2024-06-30", 25, "2024-08-01"),
        row("2024-01-01", "2024-09-30", 45, "2024-11-01"),
    ]
    productive = [
        row("2024-01-01", "2024-12-31", 70, "2025-02-10", "10-K"),
    ]
    ocf = [
        row("2024-01-01", "2024-03-31", 100, "2024-05-01"),
        row("2024-01-01", "2024-06-30", 220, "2024-08-01"),
        row("2024-01-01", "2024-09-30", 330, "2024-11-01"),
        row("2024-01-01", "2024-12-31", 500, "2025-02-10", "10-K"),
    ]
    built = financials.extract(
        document(
            {
                "Revenues": REVENUE,
                "PaymentsToAcquirePropertyPlantAndEquipment": ppe,
                "PaymentsToAcquireProductiveAssets": productive,
                "NetCashProvidedByUsedInOperatingActivities": ocf,
            }
        ),
        statements_config,
    )
    capex = series(built, "capex")
    assert [p.value for p in capex.quarterly] == [-10, -15, -20, -25]
    assert [p.derived for p in capex.quarterly] == [False, True, True, True]
    assert [p.value for p in capex.annual] == [-70]
    assert capex.annual[0].source.form == "10-K"
    ocf_q = [p.value for p in series(built, "ocf").quarterly]
    assert ocf_q == [100, 120, 110, 170]
    fcf = series(built, "fcf")
    assert [p.value for p in fcf.quarterly] == [90, 105, 90, 145]
    assert all(p.derived for p in fcf.quarterly)


def test_liabilities_fall_back_to_l_and_e_minus_equity(statements_config):
    built = financials.extract(
        document(
            {
                "Revenues": REVENUE,
                "LiabilitiesAndStockholdersEquity": [
                    row(None, "2024-12-31", 900, "2025-02-10", "10-K")
                ],
                "StockholdersEquity": [
                    row(None, "2024-12-31", 300, "2025-02-10", "10-K")
                ],
            }
        ),
        statements_config,
    )
    liabilities = point(built, "total_liabilities", "annual", "FY2024")
    assert liabilities.value == 600
    assert liabilities.derived
    assert series(built, "liabilities_and_equity").item.hidden


def test_latest_filing_wins_and_priority_holds(statements_config):
    revenue = [
        *REVENUE,
        row("2024-01-01", "2024-12-31", 1010, "2025-06-01", "10-K/A"),
    ]
    contract = [
        row("2023-01-01", "2023-12-31", 800, "2024-02-10", "10-K"),
        row("2024-01-01", "2024-12-31", 5, "2025-02-10", "10-K"),
    ]
    built = financials.extract(
        document(
            {
                "Revenues": revenue,
                "RevenueFromContractWithCustomerExcludingAssessedTax": contract,
            }
        ),
        statements_config,
    )
    annual = series(built, "revenue").annual
    assert [(p.label, p.value) for p in annual] == [
        ("FY2023", 800),
        ("FY2024", 1010),
    ]
    assert annual[1].source.form == "10-K/A"


def test_rows_of_other_forms_and_bad_rows_are_skipped(statements_config):
    bad = [
        row("2024-01-01", "2024-12-31", 999, "2025-02-10", "8-K"),
        {"end": "not a date", "val": 1, "fy": 2024, "form": "10-K"},
        "not a row",
    ]
    built = financials.extract(
        document({"Revenues": [*REVENUE, *bad]}), statements_config
    )
    assert [p.value for p in series(built, "revenue").annual] == [1000]


def test_detect_splits_needs_two_agreeing_pairs():
    eps = [
        row("2023-01-01", "2023-12-31", 8.0, "2024-02-10", "10-K"),
        row("2023-01-01", "2023-12-31", 2.0, "2025-02-10", "10-K"),
        row("2022-01-01", "2022-12-31", 6.0, "2023-02-10", "10-K"),
        row("2022-01-01", "2022-12-31", 1.5, "2025-02-10", "10-K"),
    ]
    facts = document({"EarningsPerShareDiluted|USD/shares": eps})["facts"]
    names = {"USD/shares": ["us-gaap:EarningsPerShareDiluted"]}
    assert financials.detect_splits(facts, names) == (
        financials.Split(D("2025-02-10"), 4.0),
    )
    single = {"USD/shares": ["us-gaap:EarningsPerShareDiluted"]}
    one = document({"EarningsPerShareDiluted|USD/shares": eps[:2]})
    assert financials.detect_splits(one["facts"], single) == ()


def test_detect_splits_reads_share_counts_and_reverse_splits():
    shares = [
        row("2023-01-01", "2023-12-31", 800, "2024-02-10", "10-K"),
        row("2023-01-01", "2023-12-31", 100, "2025-02-10", "10-K"),
        row("2023-04-01", "2023-06-30", 808, "2023-08-01"),
        row("2023-04-01", "2023-06-30", 101, "2025-02-10", "10-K"),
        # A restatement of 3 percent is no split.
        row("2022-01-01", "2022-12-31", 100, "2023-02-10", "10-K"),
        row("2022-01-01", "2022-12-31", 103, "2024-02-10", "10-K"),
    ]
    name = "WeightedAverageNumberOfDilutedSharesOutstanding"
    facts = document({f"{name}|shares": shares})["facts"]
    found = financials.detect_splits(facts, {"shares": [f"us-gaap:{name}"]})
    assert found == (financials.Split(D("2025-02-10"), 0.125),)


def test_split_table_of_the_config_replaces_detection(statements_config):
    table = statements_config.model_copy(
        update={
            "splits": {
                "0000000001": (
                    financials.SplitConfig(date=D("2025-01-01"), ratio=2.0),
                )
            }
        }
    )
    eps = [row("2024-01-01", "2024-12-31", 4.0, "2024-12-15", "10-K")]
    built = financials.extract(
        document(
            {"Revenues": REVENUE, "EarningsPerShareDiluted|USD/shares": eps}
        ),
        table,
        "0000000001",
    )
    assert built.splits == (financials.Split(D("2025-01-01"), 2.0),)
    assert point(built, "eps_diluted", "annual", "FY2024").value == 2.0


def test_fiscal_year_numbering_comes_from_the_10k():
    # A 52/53-week year that ends on 2022-01-01 is the company's FY2021.
    concept = edgar.FactConcept(
        key="c", label="c", unit="USD", names=("us-gaap:Revenues",)
    )
    doc = document(
        {
            "Revenues": [
                row("2021-01-03", "2022-01-01", 10, "2022-02-20", "10-K"),
            ]
        }
    )
    doc["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["fy"] = 2021
    labels = edgar.fiscal_labels(doc, concept)
    assert labels[("annual", D("2022-01-01"))] == (2021, "FY")
    config = financials.load_financials_config(CONFIG)
    built = financials.extract(doc, config)
    assert [p.label for p in series(built, "revenue").annual] == ["FY2021"]


def test_no_facts_gives_empty_series(statements_config):
    built = financials.extract({"entityName": "EMPTY"}, statements_config)
    assert built.fiscal_year_end is None
    assert all(
        not s.annual and not s.quarterly
        for statement in built.statements
        for s in statement.series
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "calendar: [[us-gaap:Revenues]]\nstatements:\n- id: a\n"
            "  label: A\n  kind: duration\n  items:\n  - id: x\n"
            "    label: X\n    parent: y\n    names: [us-gaap:X]\n",
            "parent",
        ),
        (
            "calendar: [[us-gaap:Revenues]]\nstatements:\n- id: a\n"
            "  label: A\n  kind: duration\n  items:\n  - id: x\n"
            "    label: X\n",
            "no names",
        ),
        (
            "calendar: [[us-gaap:Revenues]]\nstatements:\n- id: a\n"
            "  label: A\n  kind: duration\n  defaults: [z]\n  items:\n"
            "  - id: x\n    label: X\n    names: [us-gaap:X]\n",
            "unknown default",
        ),
        (
            "calendar: [[us-gaap:Revenues]]\nstatements:\n- id: a\n"
            "  label: A\n  kind: duration\n  items:\n  - id: x\n"
            "    label: X\n    names: [NoTaxonomy]\n",
            "taxonomy:Name",
        ),
        (
            "calendar: [[us-gaap:Revenues]]\nstatements:\n- id: a\n"
            "  label: A\n  kind: duration\n  items:\n  - id: x\n"
            "    label: X\n    derive: {op: add, left: x, right: q, "
            "note: n}\n",
            "unknown",
        ),
        (
            "calendar: [[us-gaap:Revenues]]\nstatements:\n- id: a\n"
            "  label: A\n  kind: duration\n  items:\n  - id: x\n"
            "    label: X\n    names: [us-gaap:X]\n  - id: x\n"
            "    label: X\n    names: [us-gaap:X]\n",
            "duplicate",
        ),
    ],
)
def test_config_validation(tmp_path: pathlib.Path, text, message):
    path = tmp_path / "financials.yaml"
    path.write_text(text)
    with pytest.raises(errors.ConfigError, match=message):
        financials.load_financials_config(path)


def test_repository_config_loads(statements_config):
    ids = [s.id for s in statements_config.statements]
    assert ids == ["income", "balance", "cash"]
