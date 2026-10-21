"""Shared parser types: the parsed filing, checks, IDs, and fiscal math.

Every filing parser returns a `ParsedFiling`. The types here are the module
boundary of the parser (chapter 6.5): the section detector and the chunker
read them. The helpers hold the rules that do not depend on the form: the
decode and normalization stages, the name normalization of check CK-06, the
deterministic IDs of chapter 7.11, and the fiscal math of chapter 7.9.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
import dataclasses
import datetime
import hashlib
import pathlib
import re
from typing import Literal
from typing import Protocol
import unicodedata

import pydantic

from keel import config
from keel import errors
from keel import tables

FORM_CODES = {"10-K": "10K", "10-Q": "10Q"}
CHECK_IDS = tuple(f"CK-{number:02d}" for number in range(1, 12))

# Character mapping of the normalization stage (chapter 7.7). NFKC already
# maps most spaces; the table makes the rule explicit and covers the rest.
_CHAR_MAP = str.maketrans(
    {
        0x00A0: " ",  # no-break space
        0x202F: " ",  # narrow no-break space
        0x2018: "'",  # left single quotation mark
        0x2019: "'",  # right single quotation mark
        0x201C: '"',  # left double quotation mark
        0x201D: '"',  # right double quotation mark
        0x200B: None,  # zero-width space
        0xFEFF: None,  # byte order mark
    }
)
BOM = chr(0xFEFF)
# CK-06 name normalization (chapter 7.10).
NAME_STOP_TOKENS = frozenset(
    {
        "THE",
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "LTD",
        "LIMITED",
        "PLC",
        "LLC",
        "AND",
    }
)
_PUNCTUATION = re.compile(r"[^\w\s]")
# A day of 4 or less belongs to the previous month (52-53 week calendars).
NOMINAL_DAY_LIMIT = 4
# 10-Q offset in months from the quarter end to the fiscal year end.
QUARTER_BY_OFFSET = {9: "Q1", 6: "Q2", 3: "Q3"}
DECEMBER = 12

# The field `ParsedFiling.tables` shadows the module inside the class body.
TableType = tables.Table
Status = Literal["pass", "warning", "quarantine", "fallback", "skipped"]
PeriodSource = Literal["cover", "filename", "override"]


class CheckResult(pydantic.BaseModel):
    """The result of 1 metadata check of chapter 7.10.

    Attributes:
        check: The check id, `CK-01` to `CK-11`.
        status: `pass`, `warning`, `quarantine`, `fallback`, or `skipped`.
        detail: What the check saw, empty on a pass.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    check: str
    status: Status
    detail: str = ""


class QuarantineRecord(pydantic.BaseModel):
    """Why a file stays out of the index.

    Attributes:
        file_name: The quarantined file.
        reason: The reason code, such as `registrant_mismatch`.
        detail: 1 sentence on the conflict.
        evidence: The values that show the conflict (URL, dates, names).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    file_name: str
    reason: str
    detail: str
    evidence: dict[str, str] = pydantic.Field(default_factory=dict)


class FilingMetadata(pydantic.BaseModel):
    """The validated metadata of 1 filing.

    A field is None when the parser could not read it (a quarantined file).

    Attributes:
        file_name: The corpus file name.
        file_sha256: The sha256 of the raw bytes.
        parser_version: The `parser.version` of the config.
        ticker: The header ticker.
        company: The header company name.
        cik: The header CIK.
        form: `10-K` or `10-Q` from the header.
        filing_date: The header filing date.
        url: The header source URL.
        url_trusted: True when the URL is https on `www.sec.gov`.
        header_report_period: The `Report Period` key of the 9-key header.
        header_quarter: The `Quarter` key of the 9-key header.
        period_code: The calendar quarter code in the file name.
        cover_form_phrase: `fiscal year` or `quarterly period`.
        registrant: The registrant name on the cover page.
        period_end_date: The period end date.
        period_source: `cover`, `filename`, or `override`.
        fiscal_year_end_month: The month the fiscal year ends (1 to 12).
        fiscal_year: The fiscal year.
        fiscal_period: `FY`, `Q1`, `Q2`, `Q3`, or `unknown`.
        xbrl_block_chars: The characters removed as the XBRL block.
        xbrl_present: False when the body holds no XBRL block.
        artifact_removals: Page-number and contents artifacts removed.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    file_name: str
    file_sha256: str
    parser_version: str
    ticker: str | None = None
    company: str | None = None
    cik: str | None = None
    form: str | None = None
    filing_date: datetime.date | None = None
    url: str | None = None
    url_trusted: bool = False
    header_report_period: str | None = None
    header_quarter: str | None = None
    period_code: str | None = None
    cover_form_phrase: str | None = None
    registrant: str | None = None
    period_end_date: datetime.date | None = None
    period_source: PeriodSource | None = None
    fiscal_year_end_month: int | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    xbrl_block_chars: int = 0
    xbrl_present: bool = False
    artifact_removals: int = 0


class ParsedFiling(pydantic.BaseModel):
    """The parser output for 1 file.

    Attributes:
        metadata: The validated metadata.
        text: The clean text after the XBRL cut, the normalization, the
            artifact removal, and the boundary repair. Empty when the file
            is quarantined before the body.
        tables: The rebuilt tables with offsets into `text`.
        checks: The result of each check that ran, in check order.
        warnings: The warning codes, such as `no_xbrl_block`.
        quarantine: The quarantine record, or None for an indexable file.
        parse_seconds: The wall time of the parse.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    metadata: FilingMetadata
    text: str = ""
    tables: tuple[TableType, ...] = ()
    checks: tuple[CheckResult, ...] = ()
    warnings: tuple[str, ...] = ()
    quarantine: QuarantineRecord | None = None
    parse_seconds: float = 0.0

    @property
    def quarantined(self) -> bool:
        """True when the file stays out of the index."""
        return self.quarantine is not None

    @property
    def filing_id(self) -> str | None:
        """The deterministic filing ID, or None without the metadata."""
        meta = self.metadata
        if meta.ticker is None or meta.form not in FORM_CODES:
            return None
        if meta.period_end_date is None:
            return None
        return filing_id(meta.ticker, meta.form, meta.period_end_date)

    def check(self, check_id: str) -> CheckResult | None:
        """Return the result of 1 check.

        Args:
            check_id: The check id, such as `CK-06`.

        Returns:
            The result, or None when the check did not run.
        """
        return next((c for c in self.checks if c.check == check_id), None)


@dataclasses.dataclass(frozen=True)
class ParseContext:
    """The dictionaries and corpus facts a parse needs.

    Attributes:
        parser_version: The `parser.version` of the config.
        abbreviations: The abbreviations rule R1 protects.
        protected_names: The names rule R3 never splits.
        fiscal_year_ends: The fallback fiscal-year-end month per ticker.
        overrides: The quarantine lifts keyed by file name.
        manifest_files: The manifest file list, or None without a manifest.
    """

    parser_version: str
    abbreviations: frozenset[str]
    protected_names: tuple[str, ...]
    fiscal_year_ends: dict[str, int] = dataclasses.field(default_factory=dict)
    overrides: dict[str, dict[str, str]] = dataclasses.field(
        default_factory=dict
    )
    manifest_files: frozenset[str] | None = None

    @classmethod
    def from_settings(
        cls,
        settings: config.Settings,
        manifest_files: Iterable[str] | None = None,
    ) -> ParseContext:
        """Load the parser dictionaries named in the config.

        Args:
            settings: The loaded settings.
            manifest_files: The manifest file list, or None.

        Returns:
            The context.

        Raises:
            ConfigError: A dictionary file is absent or invalid.
        """
        parser = settings.parser
        year_ends = config.read_yaml(parser.fiscal_year_ends)
        overrides = config.read_yaml(parser.overrides)
        try:
            months = {str(k): int(v) for k, v in year_ends.items()}
            lifts = {
                str(name): {str(k): str(v) for k, v in entry.items()}
                for name, entry in overrides.items()
            }
        except (TypeError, ValueError, AttributeError) as error:
            raise errors.ConfigError(
                f"invalid parser dictionary: {type(error).__name__}"
            ) from error
        if any(not 1 <= month <= DECEMBER for month in months.values()):
            raise errors.ConfigError(
                f"{parser.fiscal_year_ends}: a month is outside 1 to 12"
            )
        return cls(
            parser_version=parser.version,
            abbreviations=frozenset(
                config.read_word_list(parser.abbreviations)
            ),
            protected_names=config.read_word_list(parser.protected_names),
            fiscal_year_ends=months,
            overrides=lifts,
            manifest_files=(
                frozenset(manifest_files)
                if manifest_files is not None
                else None
            ),
        )


class FilingParser(Protocol):
    """The interface of a parser for 1 family of filing forms (chapter 17).

    Attributes:
        forms: The header forms the parser reads, such as `10-K`.
    """

    forms: tuple[str, ...]

    def parse(self, path: pathlib.Path, context: ParseContext) -> ParsedFiling:
        """Parse 1 file. A failed check quarantines; it never raises."""


def sha256_hex(data: bytes) -> str:
    """Hash bytes.

    Args:
        data: The bytes.

    Returns:
        The hex sha256 digest.
    """
    return hashlib.sha256(data).hexdigest()


def decode(data: bytes) -> str:
    """Decode a filing (chapter 7.1, stage 1).

    Args:
        data: The raw bytes.

    Returns:
        The text without a byte order mark, with LF line ends.

    Raises:
        FilingDecodeError: The bytes are not valid UTF-8 (E-D-27).
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise errors.FilingDecodeError(
            f"invalid UTF-8 at byte {error.start}: {error.reason}"
        ) from error
    text = text.removeprefix(BOM)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_text(text: str) -> str:
    """Apply NFKC and the character map of chapter 7.7 (stage 3).

    Args:
        text: The decoded body.

    Returns:
        The text with plain spaces, straight quotes, and no zero-width
        characters.
    """
    return unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)


def _name_words(name: str) -> list[str]:
    words = _PUNCTUATION.sub("", name.upper()).split()
    return [word for word in words if word not in NAME_STOP_TOKENS]


def name_tokens(name: str) -> frozenset[str]:
    """Normalize a company name for check CK-06 (chapter 7.10).

    Args:
        name: A header company name or a cover page registrant.

    Returns:
        The upper-case tokens after the punctuation removal, without the
        stop tokens.
    """
    return frozenset(_name_words(name))


def names_match(header_name: str, cover_name: str) -> bool:
    """Compare 2 company names as check CK-06 does.

    The token sets must be equal. The corpus adds 2 cases: a name whose
    punctuation joins 2 words on 1 side only (`Coca-Cola` in the header,
    `COCA COLA` on the cover), and a cover that fuses `THE` into the next
    word (`THEPROCTER & GAMBLE`). Both match when the tokens, joined in
    order without spaces and without a leading `THE`, are equal.

    Args:
        header_name: The header company name.
        cover_name: The cover page registrant.

    Returns:
        True when the names match.
    """
    header, cover = _name_words(header_name), _name_words(cover_name)
    if set(header) == set(cover):
        return True
    return "".join(header).removeprefix("THE") == "".join(cover).removeprefix(
        "THE"
    )


def filing_id(ticker: str, form: str, period_end: datetime.date) -> str:
    """Build the filing ID of chapter 7.11.

    Args:
        ticker: The ticker.
        form: `10-K` or `10-Q`.
        period_end: The period end date.

    Returns:
        An ID such as `AAPL_10Q_2022-12-31`.
    """
    return f"{ticker}_{FORM_CODES[form]}_{period_end:%Y-%m-%d}"


def chunk_id(filing: str, section: str, sequence: int) -> str:
    """Build the chunk ID of chapter 7.11.

    Args:
        filing: The filing ID.
        section: The canonical section name.
        sequence: The sequence number inside the section, from 0.

    Returns:
        An ID such as `AAPL_10Q_2022-12-31__risk_factors__0007`.
    """
    return f"{filing}__{section}__{sequence:04d}"


def chunk_hash(text: str) -> str:
    """Hash a normalized chunk text (chapter 7.11).

    Args:
        text: The normalized chunk text.

    Returns:
        The first 16 hex characters of the sha256.
    """
    return sha256_hex(text.encode("utf-8"))[:16]


def nominal_month(day: datetime.date) -> tuple[int, int]:
    """Compute the nominal month of a period end date (chapter 7.9).

    Args:
        day: The period end date.

    Returns:
        The (year, month) pair. A day of 4 or less gives the previous month,
        so October 2 gives September.
    """
    if day.day > NOMINAL_DAY_LIMIT:
        return day.year, day.month
    if day.month == 1:
        return day.year - 1, DECEMBER
    return day.year, day.month - 1


def fiscal_period(
    form: str, period_end: datetime.date, year_end_month: int
) -> tuple[int, str]:
    """Compute the fiscal year and the fiscal period (chapter 7.9).

    Args:
        form: `10-K` or `10-Q`.
        period_end: The period end date.
        year_end_month: The fiscal-year-end month of the ticker.

    Returns:
        The (fiscal year, fiscal period) pair. A 10-K takes the year of the
        nominal month, so the JNJ year that ends on January 2, 2022 is
        fiscal 2021 (chapter 7.9 says the calendar year; the data wins).
        The period is `FY` for a 10-K, `Q1` to `Q3` for a 10-Q, or
        `unknown` for a 10-Q whose month offset is not 3, 6, or 9.
    """
    year, month = nominal_month(period_end)
    if form == "10-K":
        return year, "FY"
    offset = (year_end_month - month) % DECEMBER
    end_index = year * DECEMBER + (month - 1) + offset
    return end_index // DECEMBER, QUARTER_BY_OFFSET.get(offset, "unknown")


def quarter_end(period_code: str) -> datetime.date:
    """Return the last day of a calendar quarter code.

    Args:
        period_code: A code such as `2022Q4`.

    Returns:
        The last calendar day of that quarter.
    """
    year, quarter = int(period_code[:4]), int(period_code[5])
    month = quarter * 3
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


def calendar_quarter(day: datetime.date) -> str:
    """Return the calendar quarter code of a date.

    Args:
        day: A date.

    Returns:
        A code such as `2022Q4`.
    """
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"
