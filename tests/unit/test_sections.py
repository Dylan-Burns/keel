"""Section detection tests (chapter 8.7) on short texts in the filing shapes.

Each text copies the layout the corpus uses after the chapter 7 parse:
table-of-contents rows with a page cell, labels at the start of a line,
cross-references split onto a line by rule R4, and fused headings.
"""

import pytest

from keel import sections

FILLER = (
    "The company designs and sells products in several markets and reports "
    "its results in two segments. Demand varies by quarter and by region. "
)


def body(chars: int = 900) -> str:
    """Return prose of at least `chars` characters."""
    return (FILLER * (chars // len(FILLER) + 1))[:chars].rstrip() + "."


TOC = (
    "TABLE OF CONTENTS\n| Page\nPart I\n"
    "Item 1. | Business | 4\nItem 1A. | Risk Factors | 13\n"
    "Item 2. | Properties | 33\nItem 3. | Legal Proceedings | 33\n"
    "Item 7. | Management's Discussion and Analysis of Financial Condition "
    "and Results of Operations | 36\n"
    "Item 8. | Financial Statements and Supplementary Data | 46\n"
    "Item 15. | Exhibits and Financial Statement Schedules | 49\n"
)


def ten_k() -> str:
    """A 10-K with a TOC, a cross-reference, and the main items."""
    return (
        "Cover page text of the registrant.\n"
        + TOC
        + "Part I\nItem 1. Business\n"
        + body()
        + " Refer to\nItem 1A. Risk Factors for a discussion of risks.\n"
        + body()
        + "\nItem 1A. Risk Factors\n"
        + body(3_000)
        + "\nItem 2. Properties\n"
        + body(600)
        + "\nItem 3. Legal Proceedings\nNone.\n"
        + "Item 7. Management's Discussion and Analysis of Financial "
        "Condition and Results of Operations\n"
        + body(2_000)
        + "\nItem 8. Financial Statements and Supplementary Data\n"
        + body(2_000)
        + "\nPart IV\nItem 15. Exhibits and Financial Statement Schedules\n"
        + "| 3.1 | Restated Certificate of Incorporation |\n"
        + "SIGNATURES\nPursuant to the requirements of the Act.\n"
    )


def ten_q() -> str:
    """A 10-Q with both Parts and short Part II items."""
    return (
        "PART I. FINANCIAL INFORMATION\nItem 1. Financial Statements\n"
        + body(1_500)
        + "\nItem 2. Management's Discussion and Analysis of Financial "
        "Condition and Results of Operations\n"
        + body(1_500)
        + "\nItem 4. Controls and Procedures\n"
        + body(600)
        + "\nPART II. OTHER INFORMATION\nItem 1A. Risk Factors\n"
        + body(800)
        + "\nItem 3. Defaults Upon Senior Securities\nNone.\n"
        + "Item 4. Mine Safety Disclosures\nNot applicable.\n"
        + "Item 6. Exhibits\n| 31.1 | Certification |\n"
    )


def kinds(text: str, form: str, item: str) -> list[str]:
    return [c.kind for c in sections.classify(text, form) if c.item == item]


def test_toc_rows_rejected() -> None:
    result = sections.classify(TOC, "10-K")
    row = next(c for c in result if c.item == "1A")
    assert row.kind == "toc"
    assert row.reason == "has_page_cell"
    assert all(c.kind == "toc" for c in result)


def test_cross_reference_rejected() -> None:
    text = (
        "Our operating results may vary. Refer to\nItem 1A. Risk Factors "
        "for a discussion.\n" + body()
    )
    (candidate,) = sections.classify(text, "10-K")
    assert candidate.kind == "cross_reference"
    assert candidate.reason == "reference_cue"


def test_trailing_cue_and_unknown_item() -> None:
    text = "Item 1A. Risk Factors of this report.\nItem 99. Other\n" + body()
    found = sections.classify(text, "10-K")
    assert [c.reason for c in found] == ["trailing_cue", "unknown_item"]


def test_short_items() -> None:
    text = (
        "PART II. OTHER INFORMATION\nItem 3. Defaults Upon Senior "
        "Securities\nNone.\nItem 5. Other Information\n" + body()
    )
    found = sections.classify(text, "10-Q")
    defaults = next(c for c in found if c.item == "3")
    assert defaults.part == "II"
    assert defaults.kind == "heading"
    assert defaults.body_chars < sections.BODY_MIN


def test_body_too_short_rejected() -> None:
    text = "Item 1A. Risk Factors\nSee below.\nItem 2. Properties\n" + body()
    assert kinds(text, "10-K", "1A") == ["rejected"]


def test_toc_zone_and_cluster() -> None:
    zone = "INDEX\nItem 1. Business\nItem 2. Properties\n" + body()
    assert kinds(zone, "10-K", "1") == ["toc"]
    rows = "".join(f"Item {n}. Title {n}\n" for n in range(1, 7))
    found = sections.classify(rows + body(), "10-K")
    assert [c.reason for c in found][:5] == ["in_cluster"] * 5


def test_10k_detect_spans() -> None:
    result = sections.detect(ten_k(), "10-K")
    names = [s.section for s in result.sections]
    assert names[0] == "unknown"
    assert (
        result.of("risk_factors")[0].end - result.of("risk_factors")[0].start
        > 3_000
    )
    assert len(result.of("risk_factors")) == 1
    assert "sections_incomplete" not in result.warnings
    assert result.of("legal_proceedings")[0].item_label == "Item 3"
    assert result.of("other")[0].item_label == "Item 2"
    assert result.of("other")[0].title == "Properties"


def test_exhibits_excluded() -> None:
    text = ten_k()
    result = sections.detect(text, "10-K")
    (excluded,) = result.of("excluded")
    assert excluded.item_label == "Item 15"
    assert excluded.end == len(text)
    assert text.index("SIGNATURES") > excluded.start
    assert result.sections[-1].excluded


def test_signatures_excluded_without_exhibits_item() -> None:
    text = ten_k().replace("Item 15.", "Exhibits list.")
    result = sections.detect(text, "10-K")
    (excluded,) = result.of("excluded")
    assert excluded.item_label == "Signatures"
    assert excluded.start == text.index("SIGNATURES")


def test_10q_parts_and_delta() -> None:
    result = sections.detect(ten_q(), "10-Q")
    assert result.of("financial_statements")[0].item_label == "Part I Item 1"
    assert result.of("mdna")[0].item_label == "Part I Item 2"
    (risk,) = result.of("risk_factors")
    assert risk.item_label == "Part II Item 1A"
    assert risk.delta_only
    assert result.of("excluded")[0].item_label == "Part II Item 6"
    assert not result.warnings


def test_10q_without_part_ii() -> None:
    text = ten_q().replace("PART II. OTHER INFORMATION\n", "")
    result = sections.detect(text, "10-Q")
    assert "no_part_ii" in result.warnings
    (risk,) = result.of("risk_factors")
    assert risk.confidence == sections.NO_PART_CONFIDENCE


def test_unknown_fallback() -> None:
    text = body(45_000)
    result = sections.detect(text, "10-K")
    assert {s.section for s in result.sections} == {"unknown"}
    assert len(result.sections) == 3
    assert max(s.end - s.start for s in result.sections) <= 20_000
    assert "sections_incomplete" in result.warnings


def test_forward_looking_flag() -> None:
    text = (
        "Item 7. Management's Discussion and Analysis of Financial Condition "
        "and Results of Operations\n"
        "Cautionary Note Regarding Forward-Looking Statements\n"
        + body(800)
        + "\nOverview\n"
        + body(1_500)
    )
    result = sections.detect(text, "10-K")
    flagged = [s for s in result.sections if s.boilerplate_flag]
    (span,) = flagged
    assert span.section == "mdna"
    assert span.boilerplate_flag == "forward_looking"
    assert text[span.start :].startswith("Cautionary Note")
    assert text[span.end :].startswith("Overview")


def test_relocated_mdna_and_statements() -> None:
    text = (
        "Item 1A. Risk Factors\n"
        + body(2_000)
        + "\nItem 7. Management's Discussion and Analysis of Financial "
        "Condition and Results of Operations\nReference is made to the "
        "Financial Section of this report.\n"
        "Item 8. Financial Statements and Supplementary Data\nSee the "
        "Financial Section.\n"
        "Item 15. Exhibits and Financial Statement Schedules\n"
        "(a) Financial Statements: see the Financial Section.\n"
        "50MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION\n"
        + body(2_000)
        + "\nReport of Independent Registered Public Accounting Firm\n"
        + body(2_000)
        + "\nINDEX TO EXHIBITS\n| 3.1 | Charter |\n"
    )
    result = sections.detect(text, "10-K")
    assert "sections_incomplete" not in result.warnings
    mdna = max(result.of("mdna"), key=lambda s: s.end - s.start)
    assert text[mdna.start :].startswith("50MANAGEMENT")
    statements = result.of("financial_statements")[-1]
    assert text[statements.start :].startswith("Report of Independent")
    assert text[statements.end :].startswith("INDEX TO EXHIBITS")
    assert result.sections[-1].excluded


def test_relocated_risk_factors() -> None:
    text = (
        "Item 7. Management's Discussion and Analysis\n"
        + body(1_000)
        + "\nRisk Factors\n"
        + body(1_500)
        + "\nProperties\n"
        + body(800)
        + "\nItem 8. Financial Statements and Supplementary Data\n"
        + body(800)
    )
    result = sections.detect(text, "10-K")
    (risk,) = result.of("risk_factors")
    assert text[risk.start :].startswith("Risk Factors")
    assert text[risk.end :].startswith("Properties")


def test_carve_trims_overlaps() -> None:
    spans = [
        sections.Section(
            section="other", item_label="Item 2", start=0, end=100, confidence=1
        )
    ]
    new = sections.Section(
        section="mdna", item_label="Item 7", start=0, end=0, confidence=1
    )
    carved = sections.carve(spans, 40, 60, new)
    assert [(s.section, s.start, s.end) for s in carved] == [
        ("other", 0, 40),
        ("mdna", 40, 60),
        ("other", 60, 100),
    ]


def test_title_score_fused_and_variants() -> None:
    expected = ("Quantitative and Qualitative Disclosures About Market Risk",)
    fused = "Quantitative and Qualitative Disclosures about Market RiskWe are"
    assert sections.title_score(expected, fused, fused) == pytest.approx(1.0)
    short = ("Management's Discussion and Analysis of Financial Condition",)
    assert sections.title_score(short, "MD&A", "MD&A") < sections.TITLE_MIN


def test_section_tie_warning() -> None:
    risk = "Item 1A. Risk Factors\n" + body(2_000) + "\n"
    result = sections.detect(risk + risk, "10-K")
    assert "section_tie" in result.warnings


def test_canonical_collisions() -> None:
    assert sections.canonical("10-K", "", "2") == "other"
    assert sections.canonical("10-Q", "I", "2") == "mdna"
    assert sections.canonical("10-Q", "II", "1A") == "risk_factors"
    assert sections.canonical("10-K", "", "15") == "excluded"


def test_coverage_report() -> None:
    report = sections.coverage_report(
        [
            ("A_10K.txt", "10-K", sections.detect(ten_k(), "10-K")),
            ("B_10K.txt", "10-K", sections.detect(body(), "10-K")),
            ("C_10Q.txt", "10-Q", sections.detect(ten_q(), "10-Q")),
        ]
    )
    assert report.filings == {"10-K": 2, "10-Q": 1}
    assert report.core_complete == {"10-K": 1, "10-Q": 1}
    assert report.core_share["10-K"] == 0.5
    assert report.incomplete == [
        ("B_10K.txt", ["risk_factors", "mdna", "financial_statements"])
    ]
    assert report.present["10-Q"]["risk_factors"] == 1
    assert report.warnings == {"sections_incomplete": 1}
