"""The location of a cited chunk and the text fragment deep link."""

import pathlib
import sqlite3

import pytest
import test_chunk_store

from keel import locations
from keel.stores import chunk_store

pytestmark = pytest.mark.unit

AAPL_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"
    "aapl-20250927.htm"
)

# The vectors that web/src/lib/fragment.test.ts checks with the same rule.
FRAGMENTS = [
    (
        "sales outside the U.S. representing a majority of the Company's "
        "total net sales",
        ":~:text=representing%20a%20majority%20of%20the,total%20net%20sales",
    ),
    (
        "We face strong competition for our products and services from a "
        "growing list of established and new competitors.",
        ":~:text=We%20face%20strong%20competition%20for%20our,"
        "established%20and%20new%20competitors",
    ),
    (
        "subject to complex and changing laws",
        ":~:text=subject%20to%20complex%20and%20changing%20laws",
    ),
    ("Total net sales | 416,161 | 391,035", ":~:text=Total%20net%20sales"),
    (
        "TABLE: **Products** | $ 307,003 | Services and other | 109,158",
        ":~:text=Services%20and%20other",
    ),
    ("$ 416,161 | 391,035", None),
    ("A-1 “B”", None),
]


@pytest.mark.parametrize(("quote", "expected"), FRAGMENTS)
def test_text_fragment_rule(quote: str, expected: str | None) -> None:
    assert locations.text_fragment(quote) == expected


def test_text_fragment_encodes_every_symbol() -> None:
    fragment = locations.text_fragment("x", anchor="Item 7A. R&D, a-b")
    assert fragment == ":~:text=Item%207A"
    assert locations.text_fragment("", anchor="R&D costs, net-of-tax") == (
        ":~:text=costs"
    )
    # Only letters, digits, `%` and the separators ever reach the URL.
    for quote, _ in FRAGMENTS:
        fragment = locations.text_fragment(quote) or ""
        body = fragment.removeprefix(":~:text=")
        assert all(c.isalnum() or c in "%," for c in body)


def test_table_anchor_comes_first() -> None:
    title = "Third Quarter of Fiscal Year 2026 Summary"
    assert locations.text_fragment("Revenue | $ 57,006 | 22 | %", title) == (
        ":~:text=Third%20Quarter%20of%20Fiscal%20Year%202026%20Summary"
    )
    assert locations.text_fragment("Total net sales | 1", "Net Sales") == (
        ":~:text=Net%20Sales"
    )
    assert locations.text_fragment("$ 1 | 2") is None
    assert locations.text_fragment("$ 1", "Segment Results") == (
        ":~:text=Segment%20Results"
    )


def test_table_title() -> None:
    text = (
        "NVIDIA Corp | 10-Q | Q3 FY2026 | MD&A\n"
        'TABLE: Item 1A. Risk Factors" for a discussion. Third Quarter of '
        "Fiscal Year 2026 Summary | columns: Three Months Ended\n"
        "Revenue | $ 57,006"
    )
    assert locations.table_title(text) == (
        "Third Quarter of Fiscal Year 2026 Summary"
    )
    assert locations.table_title("TABLE: $ | columns: a") is None
    assert locations.table_title("no table") is None


def test_deep_link() -> None:
    quote = "The Company has a minority market share in the global market"
    deep = locations.deep_link(AAPL_URL, quote)
    assert deep == (
        f"{AAPL_URL}#:~:text=The%20Company%20has%20a%20minority%20market,"
        "in%20the%20global%20market"
    )
    assert locations.deep_link(f"{AAPL_URL}#old", quote) == deep
    assert locations.deep_link(AAPL_URL, "$ 1") == AAPL_URL
    assert locations.deep_link(None, quote) is None
    assert locations.deep_link("https://evil.example/x", quote) == (
        "https://evil.example/x"
    )


@pytest.mark.parametrize(
    ("form", "item", "heading", "label"),
    [
        ("10-K", "Item 1A", "Risk Factors", "Part I, Item 1A. Risk Factors"),
        ("10-K", "Item 7", "MD&A", "Part II, Item 7. MD&A"),
        ("10-K", "Item 10", "Directors", "Part III, Item 10. Directors"),
        ("10-K", "Item 15", "Exhibits", "Part IV, Item 15. Exhibits"),
        ("10-K", "Item 99", "Odd", "Item 99. Odd"),
        (
            "10-Q",
            "Part II Item 1A",
            "Risk Factors",
            "Part II, Item 1A. Risk Factors",
        ),
        ("10-Q", "Part I Item 2", "MD&A", "Part I, Item 2. MD&A"),
        ("10-Q", "Item 2", "MD&A", "Item 2. MD&A"),
        ("10-K", None, "Unknown section", "Unknown section"),
        ("10-K", "Signatures", "Signatures", "Signatures"),
    ],
)
def test_section_label(
    form: str, item: str | None, heading: str, label: str
) -> None:
    assert locations.section_label(form, item, heading) == label


def test_heading_and_accession() -> None:
    text = "Apple Inc | 10-K | FY2025 | Risk Factors\nItem 1A. Risk Factors"
    assert locations.heading_of(text) == "Risk Factors"
    assert locations.heading_of("no prefix") == "Unknown section"
    assert locations.accession_of(AAPL_URL) == "0000320193-25-000079"
    assert locations.accession_of("https://www.sec.gov/x.htm") is None
    assert locations.accession_of(None) is None


def test_describe() -> None:
    place = {
        "section_label": "Part II, Item 8. Financial Statements",
        "is_table": True,
        "passage": 12,
        "passages": 84,
        "accession": "0000320193-25-000079",
    }
    assert locations.describe(place) == (
        "Part II, Item 8. Financial Statements, table, passage 12 of 84, "
        "accession 0000320193-25-000079"
    )
    assert locations.describe(None) == ""
    assert locations.describe({"section_label": ""}) == ""


@pytest.fixture(name="store")
def fixture_store(tmp_path: pathlib.Path) -> sqlite3.Connection:
    conn = chunk_store.create(tmp_path / chunk_store.FILE_NAME)
    filing = test_chunk_store.make_filing("AAA")
    meta = filing.metadata.model_copy(update={"url": AAPL_URL})
    chunk_store.write_filings(
        conn, [filing.model_copy(update={"metadata": meta})], "1.0.0"
    )
    prefix = "AAA Inc | 10-K | FY2024 | Risk Factors\n"
    chunks = [
        test_chunk_store.make_chunk(
            "AAA_10K_2024-12-31", "risk_factors", n, prefix + "x", "AAA"
        )
        for n in range(3)
    ]
    chunk_store.write_chunks(conn, chunks)
    conn.commit()
    return conn


def test_locate_and_annotate(store: sqlite3.Connection) -> None:
    second = "AAA_10K_2024-12-31__risk_factors__0001"
    found = locations.locate(store, [second, "facts:AAA:Revenues:FY2024"])
    assert list(found) == [second]
    place = found[second]
    assert place.section_label == "Part I, Item 1A. Risk Factors"
    assert (place.passage, place.passages) == (2, 3)
    assert place.is_table is False
    assert place.filing_date == "2025-02-01"
    assert place.accession == "0000320193-25-000079"
    annotated = locations.annotate(
        store,
        [{"chunk_id": second}, {"chunk_id": "facts:AAA:Revenues:FY2024"}],
    )
    assert annotated[0]["location"]["passage"] == 2
    assert annotated[1]["location"] is None
    assert locations.locate(store, []) == {}


def overlapping_store(tmp_path: pathlib.Path) -> sqlite3.Connection:
    conn = chunk_store.create(tmp_path / "overlap.sqlite")
    filing = test_chunk_store.make_filing("AAA")
    chunk_store.write_filings(conn, [filing], "1.0.0")
    prefix = "AAA Inc | 10-K | FY2024 | Risk Factors\n"
    bodies = [
        (0, "Alpha beta gamma. Delta epsilon.", False),
        (18, "Delta epsilon. Zeta eta.", False),
        (43, "TABLE: Totals | columns: A\nNet | 1", True),
    ]
    chunks = []
    for n, (start, body, table) in enumerate(bodies):
        chunk = test_chunk_store.make_chunk(
            "AAA_10K_2024-12-31", "risk_factors", n, prefix + body, "AAA"
        )
        chunks.append(
            chunk.model_copy(
                update={
                    "char_start": start,
                    "char_end": start + len(body),
                    "is_table": table,
                }
            )
        )
    chunk_store.write_chunks(conn, chunks)
    conn.commit()
    return conn


def test_passages_show_the_overlap_once(tmp_path: pathlib.Path) -> None:
    conn = overlapping_store(tmp_path)
    first, second, table = (
        f"AAA_10K_2024-12-31__risk_factors__000{n}" for n in range(3)
    )
    found = locations.passages(conn, second, 5, 5)
    assert found is not None
    assert [p.chunk_id for p in found] == [first, second, table]
    assert [p.text for p in found] == [
        "Alpha beta gamma.",
        "Delta epsilon. Zeta eta.",
        "TABLE: Totals | columns: A\nNet | 1",
    ]
    assert [p.cited for p in found] == [False, True, False]
    assert found[2].is_table
    around_first = locations.passages(conn, first, 0, 1)
    assert around_first is not None
    assert [p.text for p in around_first] == [
        "Alpha beta gamma. Delta epsilon.",
        "Zeta eta.",
    ]
    only = locations.passages(conn, second, 0, 0)
    assert only is not None
    assert [p.chunk_id for p in only] == [second]
    assert locations.passages(conn, "nope", 1, 1) is None


def test_annotate_survives_a_store_error() -> None:
    conn = sqlite3.connect(":memory:")  # no chunks table
    assert locations.annotate(conn, [{"chunk_id": "x"}]) == [
        {"chunk_id": "x", "location": None}
    ]
    conn.close()


_FY24 = (
    "NVIDIA Corporation | 10-K | FY2024 | MD&A\n"
    "TABLE: Fiscal Year 2024 Summary | units: $ in millions | "
    "columns: Jan 28, 2024 | Jan 29, 2023 | Change\n"
    "Revenue | $ 60,922 | $ 26,974 | Up 126%\n"
    "Net income per diluted share | $ 11.93 | $ 1.74 | Up 586%\n"
)
_FY25 = (
    "NVIDIA Corporation | 10-K | FY2025 | MD&A\n"
    "TABLE: Revenue by Reportable Segments | units: $ in millions | "
    "columns: Jan 26, 2025 | Jan 28, 2024 | $Change | %Change\n"
    "Graphics | 14,304 | 13,517 | 787 | 6 | %\n"
    "Total | $ 130,497 | $ 60,922 | $ 69,575 | 114 | %\n"
)


def test_row_fragment_without_a_title_starts_on_a_unique_number() -> None:
    filing = _FY25 + "Revenue was $130,497 million, up from 60,922 and 114."
    row = "Total | $ 130,497 | $ 60,922 | $ 69,575 | 114 | %"
    assert locations.row_fragment(row, filing) == ":~:text=69%2C575,114"


def test_row_fragment_prefers_the_title_range() -> None:
    filing = _FY25 + "Revenue was $130,497 million, up from 60,922 and 114."
    rows = locations.row_fragments(_FY25, filing)
    total = locations.row_key(
        "Total | $ 130,497 | $ 60,922 | $ 69,575 | 114 | %"
    )
    assert rows[total] == (":~:text=Revenue%20by%20Reportable%20Segments,114")


def test_row_fragment_spans_from_the_title_when_no_number_is_unique() -> None:
    filing = _FY24 + "Revenue was $60,922 million vs 26,974, up 126%."
    rows = locations.row_fragments(_FY24, filing)
    revenue = locations.row_key("Revenue | $ 60,922 | $ 26,974 | Up 126%")
    assert rows[revenue] == ":~:text=Fiscal%20Year%202024%20Summary,126"


def test_row_fragment_never_ends_on_a_number_above_the_row() -> None:
    before = "TABLE: Summary\nA | 126 | 7\n"
    fragment = locations.row_fragment(
        "B | 126 | 55", "126 55 126 55", ["Summary"], before
    )
    assert fragment == ":~:text=Summary,55"


def test_row_fragment_for_matches_the_cited_row() -> None:
    rows = {"Total | $ 130,497": ":~:text=130%2C497"}
    assert locations.row_fragment_for("Total |  $ 130,497", rows) == (
        ":~:text=130%2C497"
    )
    assert locations.row_fragment_for("$ 130,497", rows) == (
        ":~:text=130%2C497"
    )
    assert locations.row_fragment_for("Other | 1", rows) is None
    assert locations.row_fragment_for("Total", None) is None


def test_deep_link_prefers_the_row_fragment() -> None:
    url = "https://www.sec.gov/Archives/x.htm"
    rows = {"Total | $ 130,497": ":~:text=130%2C497"}
    assert locations.deep_link(url, "Total | $ 130,497", "Title", rows) == (
        f"{url}#:~:text=130%2C497"
    )
    assert locations.deep_link(url, "Other | $ 2", "Big Title", rows) == (
        f"{url}#:~:text=Big%20Title"
    )


def _filing_store(chunks: list[tuple[str, str]]) -> sqlite3.Connection:
    """An in-memory chunk table of 1 filing: (chunk ID, text) in order."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE chunks (chunk_id TEXT, filing_id TEXT, "
        "sequence INTEGER, text TEXT)"
    )
    conn.executemany(
        "INSERT INTO chunks VALUES (?, 'F', ?, ?)",
        [(cid, seq, text) for seq, (cid, text) in enumerate(chunks)],
    )
    return conn


_SEGMENTS = (
    "NVIDIA Corporation | 10-K | FY2025 | MD&A\n"
    "TABLE: Revenue by Reportable Segments | units: $ in millions\n"
    "($ in millions)\n"
    "Compute & Networking | $ 116,193 | $ 47,405 | $ 68,788 | 145 | %\n"
    "Graphics | 14,304 | 13,517 | 787 | 6 | %\n"
    "Total | $ 130,497 | $ 60,922 | $ 69,575 | 114 | %\n"
)
_EARLIER = (
    "NVIDIA Corporation | 10-K | FY2025 | MD&A\n"
    "TABLE: Fiscal Year 2025 Summary | units: $ in millions\n"
    "Revenue | $ 130,497 | $ 60,922 | Up 114%\n"
    "Total | $ 11 | $ 22 | 33 | %\n"
)


def test_row_range_covers_the_whole_row() -> None:
    conn = _filing_store([("A", _EARLIER), ("B", _SEGMENTS)])
    stream = locations._stream_of(conn, "F")
    rows = locations.row_fragments(_SEGMENTS, "", stream, "B")
    total = locations.row_key(
        "Total | $ 130,497 | $ 60,922 | $ 69,575 | 114 | %"
    )
    graphics = locations.row_key("Graphics | 14,304 | 13,517 | 787 | 6 | %")
    compute = locations.row_key(
        "Compute & Networking | $ 116,193 | $ 47,405 | $ 68,788 | 145 | %"
    )
    # The label starts the range, pinned by the cell before it; the last
    # number ends it, pinned by the cell after it.
    assert rows[total] == ":~:text=%25-,Total,114,-%25"
    assert rows[graphics] == ":~:text=%25-,Graphics,6,-%25"
    # A multi-word label stays 1 term, as it is 1 cell in the page.
    assert rows[compute] == (
        ":~:text=millions%29-,Compute%20%26%20Networking,145,-%25"
    )


def test_row_range_skips_a_label_seen_earlier_with_the_same_neighbour() -> None:
    # Chunk A already has "%" then "Total" before chunk B does, so the
    # browser would start in chunk A: B's Total row takes the title rule.
    late = _SEGMENTS.replace("Graphics | 14,304 | 13,517 | 787 | 6 | %\n", "")
    first = _EARLIER.replace("Up 114%\n", "Up 114% | %\n")
    conn = _filing_store([("A", first), ("B", late)])
    stream = locations._stream_of(conn, "F")
    rows = locations.row_fragments(late, "x", stream, "B")
    total = locations.row_key(
        "Total | $ 130,497 | $ 60,922 | $ 69,575 | 114 | %"
    )
    assert rows[total] == ":~:text=Revenue%20by%20Reportable%20Segments,114"


def test_row_range_never_uses_context_from_another_chunk() -> None:
    conn = _filing_store([("A", _EARLIER), ("B", _SEGMENTS)])
    stream = locations._stream_of(conn, "F")
    rows = locations.row_fragments(_EARLIER, "", stream, "A")
    revenue = locations.row_key("Revenue | $ 130,497 | $ 60,922 | Up 114%")
    # "Revenue" is the first token of chunk A: no prefix in the chunk, so
    # the title rule applies.
    assert rows[revenue] == ":~:text=Fiscal%20Year%202025%20Summary,114"
