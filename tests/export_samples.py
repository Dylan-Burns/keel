"""A stored answer record for the memo export tests (chapter 27.2)."""

AAPL = "AAPL_10K_2025-09-27__risk_factors__0003"
AAPL_MDNA = "AAPL_10K_2025-09-27__mdna__0011"
MSFT = "MSFT_10K_2025-06-30__risk_factors__0007"
UNCITED = "MSFT_10K_2025-06-30__mdna__0002"
AAPL_URL = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20250927.htm"
MSFT_URL = "https://www.sec.gov/Archives/edgar/data/789019/msft-20250630.htm"
EVIL_URL = "https://evil.example/filing.htm"
QUESTION = "How do Apple and Microsoft describe supply chain risk?"


def resolved(chunk_id, url, *, quote="net sales of $416,161 million"):
    ticker = chunk_id.split("_")[0]
    company = {"AAPL": "Apple Inc.", "MSFT": "Microsoft Corp"}[ticker]
    label = "FY2025"
    period_end = chunk_id.split("_")[2]
    return {
        "chunk_id": chunk_id,
        "claim": "a claim",
        "quote": quote,
        "ticker": ticker,
        "filing_name": f"{company} 10-K {label}",
        "section_title": "Risk Factors",
        "fiscal_label": label,
        "period_end": period_end,
        "filing_date": "2025-10-31",
        "sec_url": url,
        "truncated": False,
        "quote_mismatch": False,
        "valid": True,
    }


def make_record(request_id="req-1", msft_url=MSFT_URL):
    return {
        "request_id": request_id,
        "question": QUESTION,
        "outcome": "answered",
        "answer": {
            "direct_answer": (
                "Apple reported net sales of $416,161 million in FY2025 "
                f"(period ended 2025-09-27) [{AAPL}]. Microsoft names "
                f"supplier concentration [{MSFT}, {AAPL}]. See [note] "
                "for scope."
            ),
            "company_findings": [
                {
                    "ticker": "AAPL",
                    "company": "Apple Inc.",
                    "findings": [
                        {
                            "point": "Single-source suppliers in Asia.",
                            "citations": [AAPL_MDNA],
                            "unverified": False,
                        },
                        {
                            "point": "A claim with no valid citation.",
                            "citations": [],
                            "unverified": True,
                        },
                    ],
                },
                {
                    "ticker": "MSFT",
                    "company": "Microsoft Corp",
                    "findings": [
                        {
                            "point": f"Datacenter parts [{MSFT}].",
                            "citations": [MSFT],
                            "unverified": False,
                        }
                    ],
                },
            ],
            "comparison_table": {
                "columns": ["Company", "Risk | theme"],
                "rows": [
                    ["Apple Inc.", f"Suppliers <b>Asia</b> [{AAPL}]"],
                    ["Microsoft Corp"],
                ],
            },
            "citations": [],
            "coverage": {
                "companies_used": [
                    {
                        "ticker": "AAPL",
                        "forms": ["10-K"],
                        "fiscal_periods": ["FY2025"],
                    }
                ],
                "companies_missing": ["NVDA"],
                "data_as_of": "2025-10-31",
            },
            "gaps": ["No 10-Q after Q3 FY2025."],
            "confidence": "medium",
            "confidence_reason": "2 of 3 companies covered",
            "next_questions": [],
            "refusal": None,
        },
        "citations_resolved": [
            resolved(MSFT, msft_url),
            resolved(AAPL, AAPL_URL),
            resolved(AAPL, AAPL_URL, quote="second quote"),
            resolved(UNCITED, None),
        ],
        "retrieval": {
            "chunks": [
                {
                    "chunk_id": AAPL_MDNA,
                    "ticker": "AAPL",
                    "form": "10-K",
                    "fiscal_label": "FY2025",
                    "period_end": "2025-09-27",
                    "section": "mdna",
                    "filing_name": "Apple Inc. 10-K FY2025",
                    "sec_url": AAPL_URL,
                }
            ]
        },
        "meta": {
            "model": "claude-sonnet-5-5",
            "prompt_version": "1.3.0",
            "index_version": "1.0.0",
        },
    }


def audit_line(request_id: str, model: str = "claude-sonnet-5-5") -> dict:
    return {
        "request_id": request_id,
        "question": QUESTION,
        "index_version": "1.0.0",
        "prompt_version": "1.3.0",
        "model": model,
    }
