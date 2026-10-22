"""Question understanding without an LLM call (chapter 10).

The step turns the raw question into a `QuestionAnalysis`: the resolved
tickers, the groups, the time scope with a period window per company, the
question types, the topic terms with their section weights, and the flags.
Every rule is a dictionary entry in `config/` or a regular expression in
this module. No model request happens here (decisions D-01 and D-02).

The corpus facts (the filings per ticker, their period end dates, and the
quarantined files) come in as a `Catalog`, so the rules run the same way on
the parse of the corpus, on the index, or on a test fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import datetime
import json
import logging
import pathlib
import re
import sqlite3
import time
from typing import Literal
import unicodedata

import pydantic
from rapidfuzz import fuzz
from rapidfuzz import process

from keel import config
from keel import errors
from keel.parsers import base as parser_base
from keel.parsers import corpus as parser_corpus
from keel.stores import pilot

logger = logging.getLogger(__name__)


def _words(text: str) -> frozenset[str]:
    """Split a space-separated word list into a set."""
    return frozenset(text.split())


# Rule 3 of chapter 10.2: tickers of 1 or 2 letters resolve only in upper
# case, and never in a position where the token is an ordinary word.
SHORT_TICKERS = _words("T V MA KO GE GS DE HD PG BA MS")
# The words before a token that make a short ticker a label (Part V,
# Item T) and the characters after it that make it a word (Ms., T-Mobile).
SHORT_TICKER_LABELS = _words(
    "part item section schedule exhibit form article chapter title note "
    "letter a"
)
SHORT_TICKER_NEXT = re.compile(r"^(?:[-'&/]|\.\w)")
# Rule 4: capitalized common words resolve only when capitalized in the
# original text and not followed by 1 of the words below.
GUARDED_WORDS = _words("apple target chase meta visa oracle caterpillar deere")
GUARDED_NEXT = _words("company companies price market")
# Lower-case aliases that are English words; these tickers resolve only in
# upper case through rules 2 and 3.
WORD_TICKERS = _words("t v ma ko ge gs de hd pg ba ms cost cat dis ups pep")
# Rule 5: the fuzzy match threshold (a rapidfuzz ratio of 0 to 100).
FUZZY_MIN_LENGTH = 5
FUZZY_THRESHOLD = 88.0
# A question with this share of upper-case letters or more is shouting,
# so its upper-case tokens are not read as tickers.
UPPER_SHARE_LIMIT = 0.6

TOKEN = re.compile(r"[A-Za-z]+(?:[.&][A-Za-z]+)*")
WORD = re.compile(r"[A-Za-z]+")
DOLLAR_TICKER = re.compile(r"\$([A-Z]{1,5})\b")
NAMED_TICKER = re.compile(r"\bticker\s+([A-Z]{1,5})\b")
POSSESSIVE = re.compile(r"(?<=\w)'s?\b")
COMPANY_SUFFIX = re.compile(
    r"((?:[A-Z][\w&'.-]*\s+){1,3})"
    r"(?:Inc|Corp|Corporation|Co|Ltd|plc|PLC|Group|Holdings)\b\.?"
)
LEADING_FILLER = _words(
    "what how which who why when where does do did is are was were the "
    "compare and between for of about tell show list describe explain give"
)


# Chapter 10.7: the input checks.
ASCII_LETTER_SHARE = 0.7
ENGLISH_WORDS = _words(
    "the a an what which who how why when where is are was were do does did "
    "of and or to in on for with from by about has have had its their they "
    "this that these those be been will would can could should over between "
    "it me my our your"
)
# The optional language detector of chapter 10.7, as function words of the
# languages a reviewer is most likely to try. A question with 2 or more of
# them and more of them than English function words is not English.
FOREIGN_WORDS = _words(
    "le la les des du une est sont quels quelles quel quelle dans pour avec "
    "qui leur leurs comment aux au sur ses ces cette entre el los las del "
    "una que para con por cuales como cual sus esta estos der die das und "
    "ist sind welche wie nicht mit fur den dem ein eine gli sono quali "
    "della delle che come nel degli os sao quais nao uma com pelo pela"
)
INJECTION = re.compile(
    r"(?i)\bignore\b[^.?!]{0,40}\b(?:instructions?|rules|prompt|above)\b"
    r"|\bsystem\s+prompt\b|\byou\s+are\s+now\b|\bdisregard\b"
)

# Chapter 10.5 and E-Q-09: the parts no filing answers.
OUT_OF_SCOPE = re.compile(
    r"(?i)\b(?:(?:current\s+|today'?s\s+)?(?:stock|share)\s+prices?"
    r"(?:\s+(?:today|now|right\s+now))?"
    r"|market\s+(?:cap|capitali[sz]ation|value)"
    r"|price\s+target|trading\s+at|should\s+i\s+(?:buy|sell|invest|short)"
    r"|buy\s+or\s+sell|good\s+investment|worth\s+(?:buying|investing)"
    r"|should\s+i\s+invest\s+in|recommend\s+(?:buying|selling)|rumou?rs?"
    r"|tomorrow)\b"
)
YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")

# Chapter 10.5: the type rules.
COMPARISON = re.compile(
    r"(?i)\b(?:compar(?:e|es|ed|ing|ison)|versus|vs\.?|differ(?:s|ent|ence|"
    r"ences)?|how\s+do|both|each|which)\b"
)
TREND = re.compile(
    r"(?i)\b(?:chang(?:e|es|ed|ing)|over\s+time|trends?|over\s+the\s+"
    r"(?:last|past)|past\s+\d+|since|growth|trajectory|outlook)\b"
)
NUMERIC = re.compile(
    r"(?i)(?:\b(?:revenues?|net\s+sales|margins?|income|"
    r"earnings\s+per\s+share|how\s+much|what\s+was\s+the|total|"
    r"percent(?:age)?)\b|[%$\u20ac\u00a3])"
)
NUMERIC_TABLE_WEIGHT = 1.3

QuestionType = Literal[
    "out_of_scope",
    "sector",
    "comparison",
    "trend",
    "numeric",
    "single_company",
    "generic",
]
TYPE_PRIORITY: tuple[QuestionType, ...] = (
    "out_of_scope",
    "sector",
    "comparison",
    "trend",
    "numeric",
    "single_company",
    "generic",
)


@dataclasses.dataclass(frozen=True)
class TopicProfile:
    """A topic with its trigger words and its section weights.

    Attributes:
        name: The topic name.
        pattern: The trigger words.
        section_weights: The weight per canonical section (chapter 11.1).
        unless: Words that keep this profile from setting the weights, or
            None.
    """

    name: str
    pattern: re.Pattern[str]
    section_weights: Mapping[str, float]
    unless: re.Pattern[str] | None = None


# The first profile that matches sets the section weights; every match adds
# its words to the topic terms. The weights follow the worked examples of
# chapters 11.7 to 11.9.
TOPIC_PROFILES = (
    TopicProfile(
        "regulatory",
        re.compile(
            r"(?i)\b(?:regulat\w*|fda|compliance|legislation|antitrust|"
            r"government\s+policy|sanctions|export\s+controls?)\b"
        ),
        {
            "risk_factors": 1.5,
            "legal_proceedings": 1.2,
            "business": 1.0,
            "mdna": 0.8,
        },
    ),
    TopicProfile(
        "legal",
        re.compile(
            r"(?i)\b(?:litigation|lawsuits?|legal\s+proceedings|"
            r"settlements?|investigations?)\b"
        ),
        {
            "legal_proceedings": 1.5,
            "risk_factors": 1.1,
            "mdna": 0.8,
            "business": 0.8,
            "financial_statements": 1.2,
        },
    ),
    TopicProfile(
        "risk",
        re.compile(
            r"(?i)\b(?:risk\s+factors|risks?|threats?|uncertaint(?:y|ies)|"
            r"exposures?|cybersecurity|headwinds)\b"
        ),
        {
            "risk_factors": 1.5,
            "legal_proceedings": 1.1,
            "mdna": 1.0,
            "business": 0.8,
        },
    ),
    # How a company is organized (its business or reportable segments) is
    # described in Item 1; a question that asks for a segment figure (a
    # measure word such as revenue or net sales) stays with "financial".
    TopicProfile(
        "structure",
        re.compile(
            r"(?i)\b(?:(?:business|operating|reportable)\s+segments?|"
            r"segment\s+structure|lines?\s+of\s+business|"
            r"business\s+model|organizational\s+structure)\b"
        ),
        {"business": 1.5, "mdna": 1.0, "financial_statements": 0.8},
        re.compile(
            r"(?i)\b(?:revenues?|sales|income|margins?|earnings|profits?|"
            r"how\s+much|total)\b|\$"
        ),
    ),
    TopicProfile(
        "financial",
        re.compile(
            r"(?i)\b(?:revenues?|net\s+sales|sales|growth|outlook|guidance|"
            r"margins?|income|earnings|profits?|profitability|cash\s+flows?|"
            r"liquidity|debt|capital|expenses?|costs?|dividends?|"
            r"buybacks?|repurchases?|segments?|results|performance|"
            r"financials?|eps|interest)\b"
        ),
        {
            "mdna": 1.5,
            "financial_statements": 1.2,
            "business": 0.8,
            "risk_factors": 0.6,
        },
    ),
    TopicProfile(
        "business",
        re.compile(
            r"(?i)\b(?:strateg\w*|business|products?|services|customers?|"
            r"competition|competitors?|employees|workforce|operations|"
            r"supply\s+chain|acquisitions?|mergers?|investments?|"
            r"markets?|ai|artificial\s+intelligence|data\s+centers?|"
            r"esg|climate|sustainability|executives?|compensation|"
            r"governance|filings?|10-k|10-q|annual\s+report|"
            r"quarterly\s+report|disclos\w*)\b"
        ),
        {"business": 1.5, "mdna": 1.0, "risk_factors": 0.8},
    ),
)
DEFAULT_SECTION_WEIGHTS: Mapping[str, float] = {
    "mdna": 1.0,
    "business": 1.0,
    "risk_factors": 1.0,
}

NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "the": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "few": 3,
    "several": 3,
}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_COUNT = r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")"

ScopeKind = Literal[
    "fiscal_year",
    "fiscal_quarter",
    "calendar_year",
    "range",
    "since",
    "relative_years",
    "relative_quarters",
    "last_quarter",
    "latest",
]

# Chapter 10.4: the scope patterns in the order they claim the text, so a
# phrase such as "in fiscal 2024" is a fiscal year and not a calendar year.
SCOPE_PATTERNS: tuple[tuple[ScopeKind, re.Pattern[str]], ...] = (
    (
        "fiscal_quarter",
        re.compile(
            r"(?i)\bQ([1-4])\s*(?:of\s+)?(?:fiscal\s+(?:year\s+)?|FY\s?)?"
            r"'?(\d{4}|\d{2})(?![-\w])"
        ),
    ),
    (
        "fiscal_quarter",
        re.compile(
            r"(?i)\b(first|second|third|fourth)\s+(?:fiscal\s+)?quarter\s+"
            r"(?:of\s+)?(?:fiscal\s+(?:year\s+)?|FY\s?)?(\d{4})\b"
        ),
    ),
    (
        "fiscal_year",
        re.compile(
            r"(?i)\b(?:fiscal\s+(?:year\s+)?'?|FY\s?'?)(\d{4}|\d{2})(?![-\w])"
        ),
    ),
    (
        "range",
        re.compile(
            r"(?i)\b(?:between\s+(\d{4})\s+and|from\s+(\d{4})\s+(?:to|"
            r"through|until)|(\d{4})\s*(?:to|through|-)\s*)\s*(\d{4})\b"
        ),
    ),
    ("since", re.compile(r"(?i)\bsince\s+(\d{4})\b")),
    (
        "relative_years",
        re.compile(
            rf"(?i)\b(?:last|past|previous|prior|recent)\s+(?:{_COUNT}\s+)?"
            r"(?:fiscal\s+)?years?\b"
        ),
    ),
    (
        "relative_quarters",
        re.compile(
            rf"(?i)\b(?:last|past|previous|prior|recent)\s+{_COUNT}\s+"
            r"quarters\b"
        ),
    ),
    (
        "last_quarter",
        re.compile(
            r"(?i)\b(?:last|latest|most\s+recent|previous|prior|recent)\s+"
            r"(?:fiscal\s+)?quarter\b"
        ),
    ),
    (
        "latest",
        re.compile(
            r"(?i)\b(?:latest|most\s+recent|current\s+(?:fiscal\s+)?"
            r"(?:year|quarter|filings?|10-K|10-Q|annual\s+report))\b"
        ),
    ),
    (
        "calendar_year",
        re.compile(
            r"(?i)\b(?:in|during|for|of|calendar(?:\s+year)?)\s+"
            r"(\d{4})\b"
        ),
    ),
)
NOMINAL_START_DAY = parser_base.NOMINAL_DAY_LIMIT + 1


# --- Inputs: the dictionaries and the corpus catalog -------------------------


@dataclasses.dataclass(frozen=True)
class Company:
    """1 entry of `config/companies.yaml`.

    Attributes:
        ticker: The ticker.
        name: The legal name.
        aliases: The lower-case aliases.
        groups: The group names.
    """

    ticker: str
    name: str
    aliases: tuple[str, ...]
    groups: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Group:
    """1 entry of `config/groups.yaml`.

    Attributes:
        name: The group name.
        triggers: The trigger phrases, lower case.
        tickers: The member tickers; empty for `all`.
    """

    name: str
    triggers: tuple[str, ...]
    tickers: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Dictionaries:
    """The dictionaries of question understanding.

    Attributes:
        companies: The companies keyed by ticker, in file order.
        groups: The groups keyed by name, in file order.
        known_external: The sector tag per company outside the corpus.
    """

    companies: Mapping[str, Company]
    groups: Mapping[str, Group]
    known_external: Mapping[str, str]

    @classmethod
    def from_settings(cls, settings: config.Settings) -> Dictionaries:
        """Load the dictionaries named in the config.

        Args:
            settings: The loaded settings.

        Returns:
            The dictionaries.

        Raises:
            ConfigError: A dictionary file is absent or invalid.
        """
        paths = settings.dictionaries
        return cls.from_mappings(
            config.read_yaml(paths.companies),
            config.read_yaml(paths.groups),
            config.read_yaml(paths.known_external),
        )

    @classmethod
    def from_mappings(
        cls,
        companies: Mapping[str, object],
        groups: Mapping[str, object],
        known_external: Mapping[str, object],
    ) -> Dictionaries:
        """Build the dictionaries from the parsed YAML mappings.

        Args:
            companies: The mapping of `config/companies.yaml`.
            groups: The mapping of `config/groups.yaml`.
            known_external: The mapping of `config/known_external.yaml`.

        Returns:
            The dictionaries.

        Raises:
            ConfigError: An entry does not have the expected shape.
        """
        try:
            company_map = {
                str(ticker): Company(
                    ticker=str(ticker),
                    name=str(_field(entry, "company")),
                    aliases=tuple(
                        str(a).lower() for a in _list(entry, "aliases")
                    ),
                    groups=tuple(str(g) for g in _list(entry, "groups")),
                )
                for ticker, entry in companies.items()
            }
            group_map = {
                str(name): Group(
                    name=str(name),
                    triggers=tuple(
                        str(t).lower() for t in _list(entry, "triggers")
                    ),
                    tickers=tuple(str(t) for t in _list(entry, "tickers")),
                )
                for name, entry in groups.items()
            }
        except (TypeError, KeyError) as error:
            raise errors.ConfigError(
                f"invalid understanding dictionary: {error}"
            ) from error
        external = {str(k): str(v) for k, v in known_external.items()}
        return cls(company_map, group_map, external)


def _field(entry: object, key: str) -> object:
    if not isinstance(entry, Mapping):
        raise TypeError(f"entry is not a mapping: {entry!r}")
    return entry[key]


def _list(entry: object, key: str) -> list[object]:
    value = _field(entry, key)
    if not isinstance(value, list):
        raise TypeError(f"{key} is not a list")
    return value


@dataclasses.dataclass(frozen=True)
class FilingRef:
    """The period facts of 1 indexed filing.

    Attributes:
        ticker: The ticker.
        form: `10-K` or `10-Q`.
        period_end_date: The period end date from the cover page.
        fiscal_year: The fiscal year.
        fiscal_period: `FY`, `Q1`, `Q2`, `Q3`, or `unknown`.
        filing_date: The filing date.
        filing_id: The filing ID, or None when unknown.
    """

    ticker: str
    form: str
    period_end_date: datetime.date
    fiscal_year: int
    fiscal_period: str
    filing_date: datetime.date
    filing_id: str | None = None

    @property
    def label(self) -> str:
        """The fiscal label, such as `fiscal 2025 10-K (ended 2025-01-26)`."""
        ended = self.period_end_date.isoformat()
        if self.fiscal_period == "FY":
            return f"fiscal {self.fiscal_year} {self.form} (ended {ended})"
        return (
            f"{self.fiscal_period} fiscal {self.fiscal_year} {self.form} "
            f"(ended {ended})"
        )


@dataclasses.dataclass(frozen=True)
class QuarantineNote:
    """A quarantined file of a ticker.

    Attributes:
        ticker: The ticker, from the header or the file name.
        file_name: The file name.
        reason: The quarantine reason, such as `registrant_mismatch`.
        detail: The evidence in 1 sentence.
    """

    ticker: str
    file_name: str
    reason: str
    detail: str


@dataclasses.dataclass(frozen=True)
class Catalog:
    """The corpus facts the time scope and the not-indexed rule need.

    Attributes:
        filings: The indexed filings.
        quarantined: The quarantined files.
        year_end_months: The fiscal-year-end month per ticker.
    """

    filings: tuple[FilingRef, ...]
    quarantined: tuple[QuarantineNote, ...] = ()
    year_end_months: Mapping[str, int] = dataclasses.field(default_factory=dict)

    def for_ticker(self, ticker: str) -> list[FilingRef]:
        """List the indexed filings of a ticker by period end date.

        Args:
            ticker: The ticker.

        Returns:
            The filings, earliest first.
        """
        return sorted(
            (f for f in self.filings if f.ticker == ticker),
            key=lambda f: (f.period_end_date, f.form),
        )

    @property
    def indexed_tickers(self) -> list[str]:
        """The tickers with at least 1 indexed filing, sorted."""
        return sorted({f.ticker for f in self.filings})

    @property
    def last_filing_date(self) -> datetime.date | None:
        """The newest filing date of the corpus."""
        return max((f.filing_date for f in self.filings), default=None)

    def year_end_month(self, ticker: str) -> int:
        """Return the fiscal-year-end month of a ticker.

        Args:
            ticker: The ticker.

        Returns:
            The month (1 to 12); December when unknown.
        """
        return self.year_end_months.get(ticker, parser_base.DECEMBER)

    @classmethod
    def from_parse(cls, result: parser_corpus.CorpusParse) -> Catalog:
        """Build the catalog from the parse of the corpus.

        Args:
            result: The corpus parse.

        Returns:
            The catalog.
        """
        filings: list[FilingRef] = []
        quarantined: list[QuarantineNote] = []
        for filing in result.filings:
            meta = filing.metadata
            if filing.quarantine is not None:
                ticker = (
                    meta.ticker or filing.quarantine.file_name.split("_")[0]
                )
                quarantined.append(
                    QuarantineNote(
                        ticker=ticker,
                        file_name=filing.quarantine.file_name,
                        reason=filing.quarantine.reason,
                        detail=filing.quarantine.detail,
                    )
                )
                continue
            if (
                meta.ticker is None
                or meta.form is None
                or meta.period_end_date is None
                or meta.fiscal_year is None
                or meta.filing_date is None
            ):
                continue
            filings.append(
                FilingRef(
                    ticker=meta.ticker,
                    form=meta.form,
                    period_end_date=meta.period_end_date,
                    fiscal_year=meta.fiscal_year,
                    fiscal_period=meta.fiscal_period or "unknown",
                    filing_date=meta.filing_date,
                    filing_id=filing.filing_id,
                )
            )
        return cls(
            filings=tuple(filings),
            quarantined=tuple(quarantined),
            year_end_months=dict(result.year_end_months),
        )

    @classmethod
    def from_store(cls, conn: sqlite3.Connection) -> Catalog:
        """Build the catalog from the `filings` and `quarantine` tables.

        The index holds the same facts as the parse, so a command with an
        index reads them in milliseconds instead of parsing the corpus.

        Args:
            conn: An open chunk store.

        Returns:
            The catalog.
        """
        filings: list[FilingRef] = []
        months: dict[str, int] = {}
        rows = conn.execute(
            "SELECT filing_id, ticker, form, period_end_date, fiscal_year, "
            "fiscal_period, filing_date, fiscal_year_end_month FROM filings "
            "ORDER BY filing_id"
        )
        for filing_id, ticker, form, period, year, fiscal, filed, month in rows:
            try:
                ref = FilingRef(
                    ticker=ticker,
                    form=form,
                    period_end_date=datetime.date.fromisoformat(period),
                    fiscal_year=int(year),
                    fiscal_period=fiscal or "unknown",
                    filing_date=datetime.date.fromisoformat(filed),
                    filing_id=filing_id,
                )
            except (TypeError, ValueError):
                logger.warning(
                    "skipping filing %s: bad period facts", filing_id
                )
                continue
            filings.append(ref)
            if month is not None:
                months[ticker] = int(month)
        quarantined = [
            QuarantineNote(
                ticker=file_name.split("_")[0],
                file_name=file_name,
                reason=reason,
                detail=_quarantine_detail(reason, evidence),
            )
            for file_name, reason, evidence in conn.execute(
                "SELECT file_name, reason, evidence FROM quarantine "
                "ORDER BY file_name"
            )
        ]
        return cls(
            filings=tuple(filings),
            quarantined=tuple(quarantined),
            year_end_months=months,
        )


def _quarantine_detail(reason: str, evidence: str | None) -> str:
    """Rebuild the 1-sentence detail from the stored evidence.

    The store keeps the evidence, not the sentence; the CK-06 sentence is
    rebuilt word for word, any other reason lists its evidence.
    """
    try:
        values = json.loads(evidence or "{}")
    except json.JSONDecodeError:
        values = {}
    if not isinstance(values, dict):
        values = {}
    if reason == "registrant_mismatch":
        cover = values.get("cover_registrant")
        header = values.get("header_company")
        return f"cover registrant {cover!r}, header company {header!r}"
    shown = ", ".join(f"{k} {v}" for k, v in sorted(values.items()))
    return f"{reason}: {shown}" if shown else reason


# --- Output: the QuestionAnalysis (chapter 10.8) -----------------------------


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)


class Entity(_Model):
    """1 resolved company mention.

    Attributes:
        ticker: The ticker.
        company: The legal name the front-end shows.
        text: The text of the question that resolved.
        rule: `alias`, `ticker`, `short_ticker`, `capitalized`, `fuzzy`, or
            `group:<name>`.
        fuzzy: True for a fuzzy match.
        score: The fuzzy ratio (0 to 100), or None.
    """

    ticker: str
    company: str
    text: str
    rule: str
    fuzzy: bool = False
    score: float | None = None


class NotIndexed(_Model):
    """A company of the corpus without an indexed filing.

    Attributes:
        ticker: The ticker.
        company: The legal name.
        status: `in_manifest_not_indexed` or `no_filings`.
        reason: The quarantine reason, or None.
        detail: The quarantine evidence, or None.
        file_name: The quarantined file, or None.
    """

    ticker: str
    company: str
    status: str
    reason: str | None = None
    detail: str | None = None
    file_name: str | None = None


class CompSetUse(_Model):
    """1 comp set that the question names (chapter 27.2).

    Attributes:
        name: The comp set name.
        text: The text of the question that named it.
        tickers: Every ticker of the set, in the saved order.
        missing: The tickers of the set without an indexed filing.
    """

    name: str
    text: str
    tickers: tuple[str, ...]
    missing: tuple[str, ...] = ()


class Scope(_Model):
    """1 time scope phrase of the question.

    Attributes:
        kind: The pattern that matched.
        text: The matched text.
        fiscal_year: The fiscal year of a fiscal year or quarter scope.
        fiscal_period: `Q1` to `Q4` of a quarter scope.
        calendar_year: The year of a calendar year scope.
        start_year: The first year of a range or since scope.
        end_year: The last year of a range scope.
        count: The N of a relative scope.
    """

    kind: ScopeKind
    text: str
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    calendar_year: int | None = None
    start_year: int | None = None
    end_year: int | None = None
    count: int | None = None


class TimeScope(_Model):
    """The time scope of the question.

    Attributes:
        kind: `none`, the kind of the single scope, or `multiple` (E-Q-17).
        scopes: Every scope phrase, in question order.
        fiscal_year: The fiscal year when exactly 1 scope sets it.
        fiscal_period: The fiscal period when exactly 1 scope sets it.
    """

    kind: str = "none"
    scopes: tuple[Scope, ...] = ()
    fiscal_year: int | None = None
    fiscal_period: str | None = None


class Window(_Model):
    """The period window of 1 company on `period_end_date`.

    Attributes:
        start: The first period end date, inclusive.
        end: The last period end date, inclusive.
        anchor: The latest period end date of the company (D-33).
        filings: The fiscal labels of the indexed filings in the window.
    """

    start: datetime.date
    end: datetime.date
    anchor: datetime.date | None
    filings: tuple[str, ...] = ()


class Flags(_Model):
    """The flags of chapter 10.8.

    Attributes:
        fuzzy: A company resolved through the fuzzy match.
        injection_suspect: The text matches an injection pattern.
        has_out_of_scope_part: A part of the question is out of scope.
    """

    fuzzy: bool = False
    injection_suspect: bool = False
    has_out_of_scope_part: bool = False


class QuestionAnalysis(_Model):
    """The result of question understanding (chapter 10.8).

    Attributes:
        question: The question as asked, trimmed.
        tickers: The indexed tickers in question order, groups expanded.
        entities: How each company resolved.
        groups: The resolved groups.
        comp_sets: The saved comp sets the question names, expanded into
            `tickers` after the companies it names itself.
        unknown_entities: Company mentions outside the corpus.
        not_indexed: Companies of the corpus without an indexed filing.
        time_scope: The time scope.
        windows: The window per ticker, or None without a scope.
        primary_type: The type that decides the retrieval plan.
        types: Every type that applies, in priority order.
        topic_terms: The topic words of the question.
        section_weights: The weight per canonical section.
        table_weight: The weight of table chunks (1.3 for numeric).
        flags: The flags.
        out_of_scope_parts: The parts no filing answers, for the gaps.
        out_of_scope_reason: Why the question is out of scope, or None.
        suggested_tickers: Covered companies in the sector of an unknown
            company, for the out-of-scope response.
        elapsed_ms: The time the analysis took.
    """

    question: str
    tickers: tuple[str, ...]
    entities: tuple[Entity, ...]
    groups: tuple[str, ...]
    unknown_entities: tuple[str, ...]
    not_indexed: tuple[NotIndexed, ...]
    time_scope: TimeScope
    windows: dict[str, Window | None]
    primary_type: QuestionType
    types: tuple[QuestionType, ...]
    topic_terms: tuple[str, ...]
    section_weights: dict[str, float]
    table_weight: float
    flags: Flags
    out_of_scope_parts: tuple[str, ...]
    out_of_scope_reason: str | None
    suggested_tickers: tuple[str, ...]
    elapsed_ms: float
    comp_sets: tuple[CompSetUse, ...] = ()

    @property
    def out_of_scope(self) -> bool:
        """True when nothing in the question is in scope (no model call)."""
        return self.primary_type == "out_of_scope"


# --- Step 1 and 2: input checks and normalization ----------------------------

_QUOTES = str.maketrans(
    {chr(code): "'" for code in (0x2018, 0x2019, 0x201B, 0x2032)}
    | {chr(code): '"' for code in (0x201C, 0x201D, 0x201F, 0x2033)}
)


def normalize(question: str) -> str:
    """Normalize a question: NFKC, straight quotes, single spaces.

    Args:
        question: The raw question.

    Returns:
        The normalized text.
    """
    text = unicodedata.normalize("NFKC", question).translate(_QUOTES)
    return " ".join(text.split())


def check_input(question: str, min_chars: int, max_chars: int) -> str:
    """Run the length and language checks of chapter 10.7.

    Args:
        question: The raw question.
        min_chars: The shortest trimmed question allowed.
        max_chars: The longest question allowed.

    Returns:
        The normalized question.

    Raises:
        EmptyQuestionError: The trimmed text is too short (HTTP 400).
        QuestionTooLongError: The text is too long (HTTP 413).
        NonEnglishQuestionError: The text is not English (HTTP 400).
    """
    stripped = question.strip()
    if len(stripped) < min_chars:
        raise errors.EmptyQuestionError(
            f"the question needs at least {min_chars} characters"
        )
    if len(stripped) > max_chars:
        raise errors.QuestionTooLongError(
            f"the question has {len(stripped)} characters; the limit is "
            f"{max_chars}"
        )
    text = normalize(stripped)
    if not is_english(text):
        raise errors.NonEnglishQuestionError(
            "Keel answers questions in English; please ask in English"
        )
    return text


def is_english(text: str) -> bool:
    """Tell whether a question reads as English.

    Args:
        text: The normalized question.

    Returns:
        False when fewer than 70% of the letters are ASCII letters, or when
        the function words are mostly those of another language.
    """
    letters = [c for c in text if c.isalpha()]
    if letters:
        ascii_share = sum(c.isascii() for c in letters) / len(letters)
        if ascii_share < ASCII_LETTER_SHARE:
            return False
    folded = unicodedata.normalize("NFKD", text)
    words = [
        w
        for w in WORD.findall("".join(c for c in folded if c.isascii()))
        if w.islower()
    ]
    english = sum(w in ENGLISH_WORDS for w in words)
    foreign = sum(w in FOREIGN_WORDS for w in words)
    return not (foreign >= 2 and foreign > english)


# --- Step 3: entity resolution (chapter 10.2) --------------------------------


@dataclasses.dataclass(frozen=True)
class _Hit:
    start: int
    end: int
    entity: Entity


class _Text:
    """The question in its 2 aligned copies and the claimed spans."""

    def __init__(self, text: str) -> None:
        # A possessive becomes spaces so the offsets stay aligned.
        self.original = POSSESSIVE.sub(lambda m: " " * len(m.group()), text)
        self.lower = self.original.lower()
        self.claimed: list[tuple[int, int]] = []

    def free(self, start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in self.claimed)

    def claim(self, start: int, end: int) -> None:
        self.claimed.append((start, end))

    def next_word(self, end: int) -> str:
        match = WORD.search(self.lower, end)
        return match.group() if match else ""

    def previous_word(self, start: int) -> str:
        words = WORD.findall(self.lower[:start])
        return words[-1] if words else ""

    def shouting(self) -> bool:
        letters = [c for c in self.original if c.isalpha()]
        if not letters:
            return False
        upper = sum(c.isupper() for c in letters)
        return upper / len(letters) >= UPPER_SHARE_LIMIT


CompSetSource = Callable[[], Mapping[str, Sequence[str]]]
COMP_SET_SUFFIX = r"(?:comps|comp\s+set|comparables|peers|peer\s+set)"


def comp_set_pattern(name: str) -> re.Pattern[str]:
    """The phrase that names a comp set in a lower-case question.

    `my software comps`, `our software comp set`, and `software peers`
    all name the set `software` (chapter 27.2).

    Args:
        name: The comp set name, lower case.

    Returns:
        The pattern; it matches the optional `my`, `our`, or `the`.
    """
    words = r"\s+".join(re.escape(word) for word in name.split())
    return re.compile(
        rf"(?<![\w&])(?:(?:my|our|the)\s+)?{words}\s+{COMP_SET_SUFFIX}"
        r"(?![\w&])"
    )


def _no_comp_sets() -> dict[str, tuple[str, ...]]:
    return {}


def store_comp_sets(path: pathlib.Path) -> CompSetSource:
    """The comp sets of the pilot store, read again on every question.

    Args:
        path: The pilot store file (`pilot.db`).

    Returns:
        A function that returns the tickers per comp set name.
    """
    store = pilot.PilotStore(path)

    def read() -> dict[str, tuple[str, ...]]:
        sets = store.comp_sets()
        return {name: entry.tickers for name, entry in sets.items()}

    return read


def _alias_pattern(alias: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w&]){re.escape(alias)}(?![\w&]|\.\w)")


class Resolver:
    """The entity, group, and unknown-company rules of chapter 10.

    Args:
        dictionaries: The loaded dictionaries.
    """

    def __init__(self, dictionaries: Dictionaries) -> None:
        self.dictionaries = dictionaries
        self.tickers = frozenset(dictionaries.companies)
        aliases: list[tuple[str, str]] = []
        guarded: list[tuple[str, str]] = []
        for company in dictionaries.companies.values():
            for alias in company.aliases:
                if alias in GUARDED_WORDS:
                    guarded.append((alias, company.ticker))
                elif alias in WORD_TICKERS:
                    continue  # an English word resolves through rules 2 and 3
                else:
                    aliases.append((alias, company.ticker))
        aliases.sort(key=lambda pair: (-len(pair[0]), pair[0]))
        self.aliases = [(_alias_pattern(a), a, t) for a, t in aliases]
        self.guarded = [(_alias_pattern(a), a, t) for a, t in guarded]
        self.fuzzy_choices = {
            alias: ticker
            for alias, ticker in aliases + guarded
            if len(alias) >= FUZZY_MIN_LENGTH
        }
        self.exact_words = frozenset(
            word for alias, _ in aliases + guarded for word in alias.split()
        )
        triggers = [
            (trigger, group.name)
            for group in dictionaries.groups.values()
            for trigger in group.triggers
        ]
        triggers.sort(key=lambda pair: (-len(pair[0]), pair[0]))
        self.triggers = [(_alias_pattern(t), g) for t, g in triggers]
        externals = sorted(dictionaries.known_external, key=len, reverse=True)
        self.externals = [
            (re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])"), name)
            for name in externals
        ]

    def _entity(
        self,
        ticker: str,
        text: str,
        rule: str,
        score: float | None = None,
    ) -> Entity:
        return Entity(
            ticker=ticker,
            company=self.dictionaries.companies[ticker].name,
            text=text,
            rule=rule,
            fuzzy=rule == "fuzzy",
            score=score,
        )

    def resolve(
        self, text: str, work: _Text | None = None
    ) -> tuple[list[Entity], _Text]:
        """Resolve the company mentions of a question (rules 1 to 6).

        Args:
            text: The normalized question.
            work: The text with the spans already claimed (the comp set
                names), or None to start from `text`.

        Returns:
            The entities in question order without duplicates, and the
            text with the claimed spans for the later steps.
        """
        if work is None:
            work = _Text(text)
        hits: list[_Hit] = []
        hits += self._aliases(work)
        hits += self._explicit_tickers(work)
        hits += self._tickers(work)
        hits += self._guarded(work)
        hits += self._fuzzy(work)
        hits.sort(key=lambda hit: hit.start)
        seen: set[str] = set()
        entities: list[Entity] = []
        for hit in hits:
            if hit.entity.ticker not in seen:
                seen.add(hit.entity.ticker)
                entities.append(hit.entity)
        return entities, work

    def _aliases(self, work: _Text) -> list[_Hit]:
        hits: list[_Hit] = []
        for pattern, _, ticker in self.aliases:
            for match in pattern.finditer(work.lower):
                if work.free(match.start(), match.end()):
                    work.claim(match.start(), match.end())
                    span = work.original[match.start() : match.end()]
                    hits.append(
                        _Hit(
                            match.start(),
                            match.end(),
                            self._entity(ticker, span, "alias"),
                        )
                    )
        return hits

    def _explicit_tickers(self, work: _Text) -> list[_Hit]:
        hits: list[_Hit] = []
        for pattern in (DOLLAR_TICKER, NAMED_TICKER):
            for match in pattern.finditer(work.original):
                ticker = match.group(1)
                if ticker in self.tickers and work.free(*match.span(1)):
                    work.claim(*match.span(1))
                    hits.append(
                        _Hit(
                            match.start(1),
                            match.end(1),
                            self._entity(ticker, match.group(), "ticker"),
                        )
                    )
        return hits

    def _tickers(self, work: _Text) -> list[_Hit]:
        if work.shouting():
            return []
        hits: list[_Hit] = []
        for match in TOKEN.finditer(work.original):
            token = match.group()
            if token not in self.tickers or not work.free(*match.span()):
                continue
            if token in SHORT_TICKERS:
                if not self._short_ticker_ok(work, match):
                    continue
                rule = "short_ticker"
            elif 2 <= len(token) <= 5:
                rule = "ticker"
            else:
                continue
            work.claim(*match.span())
            hits.append(
                _Hit(
                    match.start(),
                    match.end(),
                    self._entity(token, token, rule),
                )
            )
        return hits

    @staticmethod
    def _short_ticker_ok(work: _Text, match: re.Match[str]) -> bool:
        after = work.original[match.end() :]
        if SHORT_TICKER_NEXT.match(after):
            return False
        return work.previous_word(match.start()) not in SHORT_TICKER_LABELS

    def _guarded(self, work: _Text) -> list[_Hit]:
        hits: list[_Hit] = []
        for pattern, _, ticker in self.guarded:
            for match in pattern.finditer(work.lower):
                span = work.original[match.start() : match.end()]
                if not span[0].isupper() or not work.free(*match.span()):
                    continue
                if work.next_word(match.end()) in GUARDED_NEXT:
                    continue
                work.claim(*match.span())
                hits.append(
                    _Hit(
                        match.start(),
                        match.end(),
                        self._entity(ticker, span, "capitalized"),
                    )
                )
        return hits

    def _fuzzy(self, work: _Text) -> list[_Hit]:
        hits: list[_Hit] = []
        for match in WORD.finditer(work.original):
            token = match.group()
            lower = token.lower()
            if (
                len(token) < FUZZY_MIN_LENGTH
                or not token[0].isupper()
                or lower in self.exact_words
                or not work.free(*match.span())
            ):
                continue
            best = process.extractOne(
                lower,
                self.fuzzy_choices.keys(),
                scorer=fuzz.ratio,
                score_cutoff=FUZZY_THRESHOLD,
            )
            if best is None:
                continue
            alias, score = best[0], float(best[1])
            work.claim(*match.span())
            hits.append(
                _Hit(
                    match.start(),
                    match.end(),
                    self._entity(
                        self.fuzzy_choices[alias], token, "fuzzy", score
                    ),
                )
            )
        return hits

    def groups(self, work: _Text) -> list[str]:
        """Match the group trigger phrases on the unclaimed text.

        Args:
            work: The text after the entity rules.

        Returns:
            The group names in question order.
        """
        found: list[tuple[int, str]] = []
        for pattern, group in self.triggers:
            for match in pattern.finditer(work.lower):
                if work.free(*match.span()):
                    work.claim(*match.span())
                    found.append((match.start(), group))
        names: list[str] = []
        for _, group in sorted(found):
            if group not in names:
                names.append(group)
        return names

    def unknown(self, work: _Text) -> list[str]:
        """Find company mentions outside the corpus (chapter 10.6).

        Args:
            work: The text after the entity and group rules.

        Returns:
            The unknown company names in question order.
        """
        found: list[tuple[int, str]] = []
        for pattern, name in self.externals:
            for match in pattern.finditer(work.original):
                if work.free(*match.span()):
                    work.claim(*match.span())
                    found.append((match.start(), name))
        for match in COMPANY_SUFFIX.finditer(work.original):
            words = match.group().split()
            start = match.start()
            while words and words[0].lower() in LEADING_FILLER:
                start = work.original.index(words[0], start) + len(words[0])
                words = words[1:]
            if len(words) < 2 or not work.free(start, match.end()):
                continue
            work.claim(start, match.end())
            found.append((start, " ".join(words).rstrip(".")))
        names: list[str] = []
        for _, name in sorted(found):
            if name not in names:
                names.append(name)
        return names


# --- Step 5: time scope and windows (chapter 10.4) ---------------------------


def _year(value: str) -> int:
    year = int(value)
    return 2000 + year if year < 100 else year


def _count(value: str | None) -> int:
    if value is None:
        return 1
    if value.isdigit():
        return int(value)
    return NUMBER_WORDS[value.lower()]


def _scope(kind: ScopeKind, match: re.Match[str]) -> Scope:
    groups = match.groups()
    fields: dict[str, object] = {"kind": kind, "text": match.group()}
    if kind == "fiscal_quarter":
        first = groups[0]
        quarter = ORDINALS.get(first.lower()) or int(first)
        fields |= {
            "fiscal_year": _year(groups[1]),
            "fiscal_period": f"Q{quarter}",
        }
    elif kind == "fiscal_year":
        fields["fiscal_year"] = _year(groups[0])
    elif kind == "range":
        first = next(g for g in groups[:3] if g)
        low, high = sorted((int(first), int(groups[3])))
        fields |= {"start_year": low, "end_year": high}
    elif kind == "since":
        fields["start_year"] = int(groups[0])
    elif kind in {"relative_years", "relative_quarters"}:
        fields["count"] = _count(groups[0])
    elif kind == "calendar_year":
        fields["calendar_year"] = int(groups[0])
    return Scope.model_validate(fields)


def parse_time_scope(text: str) -> TimeScope:
    """Find the time scope phrases of a question.

    Args:
        text: The normalized question.

    Returns:
        The time scope; `multiple` when more than 1 phrase matches.
    """
    claimed: list[tuple[int, int]] = []
    found: list[tuple[int, Scope]] = []
    for kind, pattern in SCOPE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < e and end > s for s, e in claimed):
                continue
            claimed.append((start, end))
            found.append((start, _scope(kind, match)))
    scopes = tuple(scope for _, scope in sorted(found, key=lambda p: p[0]))
    if not scopes:
        return TimeScope()
    if len(scopes) == 1:
        only = scopes[0]
        return TimeScope(
            kind=only.kind,
            scopes=scopes,
            fiscal_year=only.fiscal_year,
            fiscal_period=only.fiscal_period,
        )
    years = {s.fiscal_year for s in scopes if s.fiscal_year is not None}
    return TimeScope(
        kind="multiple",
        scopes=scopes,
        fiscal_year=years.pop() if len(years) == 1 else None,
    )


def _month_index(year: int, month: int) -> tuple[int, int]:
    index = year * 12 + month - 1
    return index // 12, index % 12 + 1


def _nominal_window(
    first: tuple[int, int], last: tuple[int, int]
) -> tuple[datetime.date, datetime.date]:
    """Return the period end dates whose nominal month is in a range.

    A period that ends on day 4 or earlier belongs to the previous month
    (chapter 7.9), so the window runs from day 5 of the first month to day
    4 of the month after the last.
    """
    after = _month_index(last[0], last[1] + 1)
    return (
        datetime.date(first[0], first[1], NOMINAL_START_DAY),
        datetime.date(after[0], after[1], parser_base.NOMINAL_DAY_LIMIT),
    )


def _shift_years(day: datetime.date, years: int) -> datetime.date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # February 29
        return day.replace(year=day.year + years, day=28)


def _shift_months(day: datetime.date, months: int) -> datetime.date:
    year, month = _month_index(day.year, day.month + months)
    return datetime.date(year, month, min(day.day, 28))


def _fixed_window(
    scope: Scope, year_end_month: int
) -> tuple[datetime.date, datetime.date] | None:
    """Compute the window of a scope that names its years."""
    if scope.kind == "fiscal_year" and scope.fiscal_year is not None:
        return _nominal_window(
            _month_index(scope.fiscal_year - 1, year_end_month + 1),
            (scope.fiscal_year, year_end_month),
        )
    if scope.kind == "fiscal_quarter" and scope.fiscal_year is not None:
        quarter = int((scope.fiscal_period or "Q4")[1])
        last = _month_index(
            scope.fiscal_year, year_end_month - 3 * (4 - quarter)
        )
        return _nominal_window(last, last)
    if scope.kind == "calendar_year" and scope.calendar_year is not None:
        year = scope.calendar_year
        return datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    if scope.kind == "range" and scope.start_year and scope.end_year:
        return (
            datetime.date(scope.start_year, 1, 1),
            datetime.date(scope.end_year, 12, 31),
        )
    return None


def _anchored_window(
    scope: Scope, filings: Sequence[FilingRef]
) -> tuple[datetime.date, datetime.date] | None:
    """Compute the window of a scope relative to the company anchor (D-33)."""
    if not filings:
        return None
    anchor = filings[-1].period_end_date
    if scope.kind == "since" and scope.start_year:
        return datetime.date(scope.start_year, 1, 1), anchor
    if scope.kind == "relative_years":
        year, month = parser_base.nominal_month(anchor)
        start, _ = _nominal_window(
            _month_index(year - (scope.count or 1), month + 1), (year, month)
        )
        return start, anchor
    if scope.kind == "relative_quarters":
        months = 3 * ((scope.count or 1) - 1)
        start = _shift_months(anchor, -months) - datetime.timedelta(days=10)
        return start, anchor
    if scope.kind == "last_quarter":
        quarters = [f for f in filings if f.form == "10-Q"] or list(filings)
        latest = quarters[-1].period_end_date
        return latest, latest
    newest: dict[str, datetime.date] = {}
    for filing in filings:  # earliest first, so the last one stays
        newest[filing.form] = filing.period_end_date
    return min(newest.values()), max(newest.values())


def scope_window(
    scope: Scope, filings: Sequence[FilingRef], year_end_month: int
) -> tuple[datetime.date, datetime.date] | None:
    """Compute the window of 1 scope for 1 company.

    Args:
        scope: The scope phrase.
        filings: The indexed filings of the company, earliest first.
        year_end_month: The fiscal-year-end month of the company.

    Returns:
        The inclusive (start, end) on `period_end_date`, or None when a
        relative scope has no filing to anchor on.
    """
    if scope.kind in {
        "fiscal_year",
        "fiscal_quarter",
        "calendar_year",
        "range",
    }:
        return _fixed_window(scope, year_end_month)
    return _anchored_window(scope, filings)


def company_window(
    time_scope: TimeScope, filings: Sequence[FilingRef], year_end_month: int
) -> Window | None:
    """Compute the window of 1 company: the widest of its scopes (E-Q-17).

    Args:
        time_scope: The time scope of the question.
        filings: The indexed filings of the company, earliest first.
        year_end_month: The fiscal-year-end month of the company.

    Returns:
        The window, or None without a scope.
    """
    spans = [
        span
        for scope in time_scope.scopes
        if (span := scope_window(scope, filings, year_end_month)) is not None
    ]
    if not spans:
        return None
    start = min(s for s, _ in spans)
    end = max(e for _, e in spans)
    labels = tuple(
        f.label for f in filings if start <= f.period_end_date <= end
    )
    anchor = filings[-1].period_end_date if filings else None
    return Window(start=start, end=end, anchor=anchor, filings=labels)


# --- Steps 6 and 7: types, topics, out-of-scope parts ------------------------


def topics(text: str) -> tuple[list[str], dict[str, float]]:
    """Find the topic terms and the section weights of a question.

    Args:
        text: The question, without the out-of-scope parts.

    Returns:
        The topic terms in question order without duplicates, and the
        section weights of the first topic profile that matches.
    """
    found: list[tuple[int, str]] = []
    weights: Mapping[str, float] | None = None
    for profile in TOPIC_PROFILES:
        matches = list(profile.pattern.finditer(text))
        blocked = profile.unless is not None and profile.unless.search(text)
        if matches and weights is None and not blocked:
            weights = profile.section_weights
        found += [(m.start(), m.group().lower()) for m in matches]
    terms: list[str] = []
    for _, term in sorted(found):
        if term not in terms:
            terms.append(term)
    return terms, dict(weights or DEFAULT_SECTION_WEIGHTS)


def out_of_scope_parts(
    text: str, time_scope: TimeScope, last_filing: datetime.date | None
) -> tuple[list[str], str, bool]:
    """Find the parts of a question that no filing answers (E-Q-09).

    Args:
        text: The normalized question.
        time_scope: The time scope of the question.
        last_filing: The newest filing date of the corpus.

    Returns:
        The parts, the text with the parts removed, and True when every
        scope of the question lies after the corpus.
    """
    parts = [m.group() for m in OUT_OF_SCOPE.finditer(text)]
    rest = OUT_OF_SCOPE.sub(" ", text)
    later = []
    for scope in time_scope.scopes:
        years = [
            y
            for y in (
                scope.fiscal_year,
                scope.calendar_year,
                scope.start_year,
            )
            if y is not None
        ]
        if last_filing is not None and years and min(years) > last_filing.year:
            later.append(scope)
    parts += [f"{scope.text} (after the corpus)" for scope in later]
    every = bool(time_scope.scopes) and len(later) == len(time_scope.scopes)
    return parts, rest, every


def classify(
    *,
    companies: int,
    groups: Sequence[str],
    text: str,
    has_topic: bool,
    out_of_scope_reason: str | None,
) -> list[QuestionType]:
    """Apply the type rules of chapter 10.5.

    Args:
        companies: The count of resolved companies (groups not counted).
        groups: The resolved groups.
        text: The normalized question.
        has_topic: An in-scope topic word remains.
        out_of_scope_reason: The reason when nothing is in scope.

    Returns:
        The types in priority order; the first is the primary type.
    """
    found: set[QuestionType] = set()
    if out_of_scope_reason is not None:
        found.add("out_of_scope")
    if groups:
        found.add("sector")
    if (companies >= 2 or groups) and COMPARISON.search(text):
        found.add("comparison")
    if TREND.search(text):
        found.add("trend")
    if NUMERIC.search(text):
        found.add("numeric")
    if companies == 1 and not groups:
        found.add("single_company")
    if companies == 0 and not groups and has_topic:
        found.add("generic")
    if companies >= 2 and not found:
        # 2 companies without a compare word still need 1 quota each.
        found.add("comparison")
    if not found:
        found.add("out_of_scope")
    return [t for t in TYPE_PRIORITY if t in found]


def with_period_trend(
    types: Sequence[QuestionType], time_scope: TimeScope
) -> list[QuestionType]:
    """Add `trend` to a question that names 2 or more fiscal years.

    Args:
        types: The types of chapter 10.5, in priority order.
        time_scope: The time scope of the question.

    Returns:
        The types in priority order.
    """
    years = {s.fiscal_year for s in time_scope.scopes if s.fiscal_year}
    if "out_of_scope" in types or "trend" in types or len(years) < 2:
        return list(types)
    found = {*types, "trend"}
    return [t for t in TYPE_PRIORITY if t in found]


# --- The pipeline -------------------------------------------------------------


class Understander:
    """Question understanding with fixed dictionaries and corpus facts.

    Args:
        dictionaries: The loaded dictionaries.
        catalog: The corpus facts.
        min_chars: The shortest trimmed question allowed.
        max_chars: The longest question allowed.
        comp_sets: The saved comp sets (chapter 27.2), read on every
            question; None for none.
    """

    def __init__(
        self,
        dictionaries: Dictionaries,
        catalog: Catalog,
        min_chars: int = 3,
        max_chars: int = 1000,
        *,
        comp_sets: CompSetSource | None = None,
    ) -> None:
        self.comp_sets = comp_sets or _no_comp_sets
        self.dictionaries = dictionaries
        self.catalog = catalog
        self.resolver = Resolver(dictionaries)
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.indexed = frozenset(catalog.indexed_tickers)

    @classmethod
    def from_settings(
        cls, settings: config.Settings, catalog: Catalog
    ) -> Understander:
        """Build the step from the config.

        Args:
            settings: The loaded settings.
            catalog: The corpus facts.

        Returns:
            The step.

        Raises:
            ConfigError: A dictionary file is absent or invalid.
        """
        return cls(
            Dictionaries.from_settings(settings),
            catalog,
            settings.limits.question_min_chars,
            settings.limits.question_max_chars,
            comp_sets=store_comp_sets(pilot.db_path(settings)),
        )

    def _read_comp_sets(self) -> list[tuple[str, tuple[str, ...]]]:
        """The saved comp sets, longest name first; none on a store error.

        A broken pilot store must not stop the questions that name no
        comp set, so the error is logged and the sets are skipped.
        """
        try:
            sets = self.comp_sets()
        except errors.PilotStoreError as error:
            logger.warning("comp sets skipped: %s", error)
            return []
        return sorted(
            ((name, tuple(tickers)) for name, tickers in sets.items()),
            key=lambda item: (-len(item[0]), item[0]),
        )

    def names_comp_set(self, question: str) -> bool:
        """True when the question names a saved comp set.

        The answer cache skips these questions: the key holds the
        question, and a comp set can change under the same words.

        Args:
            question: The raw question.

        Returns:
            True when a comp set phrase appears in the question.
        """
        text = normalize(question).lower()
        return any(
            comp_set_pattern(name).search(text)
            for name, _ in self._read_comp_sets()
        )

    def _match_comp_sets(self, work: _Text) -> list[CompSetUse]:
        """Claim the comp set phrases before the entity rules run."""
        found: list[tuple[int, CompSetUse]] = []
        for name, tickers in self._read_comp_sets():
            for match in comp_set_pattern(name).finditer(work.lower):
                if not work.free(*match.span()):
                    continue
                work.claim(*match.span())
                if any(use.name == name for _, use in found):
                    continue
                found.append(
                    (
                        match.start(),
                        CompSetUse(
                            name=name,
                            text=work.original[match.start() : match.end()],
                            tickers=tickers,
                            missing=tuple(
                                t for t in tickers if t not in self.indexed
                            ),
                        ),
                    )
                )
        return [use for _, use in sorted(found, key=lambda pair: pair[0])]

    def _not_indexed(self, ticker: str) -> NotIndexed:
        company = self.dictionaries.companies[ticker].name
        note = next(
            (q for q in self.catalog.quarantined if q.ticker == ticker), None
        )
        if note is None:
            return NotIndexed(
                ticker=ticker, company=company, status="no_filings"
            )
        return NotIndexed(
            ticker=ticker,
            company=company,
            status="in_manifest_not_indexed",
            reason=note.reason,
            detail=note.detail,
            file_name=note.file_name,
        )

    def _group_tickers(self, group: str) -> list[str]:
        members = self.dictionaries.groups[group].tickers
        if not members:  # the `all` group
            return sorted(self.indexed)
        return [t for t in members if t in self.indexed]

    def _suggestions(self, unknown: Iterable[str]) -> list[str]:
        sectors = {
            self.dictionaries.known_external[name]
            for name in unknown
            if name in self.dictionaries.known_external
        }
        found: list[str] = []
        for sector in sorted(sectors):
            members = (
                list(self._group_tickers(sector))
                if (sector in self.dictionaries.groups)
                else []
            )
            members += [
                c.ticker
                for c in self.dictionaries.companies.values()
                if sector in c.groups and c.ticker in self.indexed
            ]
            found += [t for t in members if t not in found]
        return found

    def analyze(self, question: str) -> QuestionAnalysis:
        """Turn a question into a `QuestionAnalysis` (chapter 10.1).

        Args:
            question: The raw question.

        Returns:
            The analysis. `primary_type` is `out_of_scope` when nothing in
            the question is in scope, so no model call follows.

        Raises:
            EmptyQuestionError: The trimmed text is too short (HTTP 400).
            QuestionTooLongError: The text is too long (HTTP 413).
            NonEnglishQuestionError: The text is not English (HTTP 400).
        """
        started = time.perf_counter()
        text = check_input(question, self.min_chars, self.max_chars)
        injection = INJECTION.search(text) is not None
        if injection:
            logger.warning("injection pattern in the question")

        work = _Text(text)
        comp_sets = self._match_comp_sets(work)
        entities, work = self.resolver.resolve(text, work)
        groups = self.resolver.groups(work)
        unknown = self.resolver.unknown(work)

        tickers: list[str] = []
        not_indexed: list[NotIndexed] = []
        for entity in entities:
            if entity.ticker in self.indexed:
                tickers.append(entity.ticker)
            else:
                not_indexed.append(self._not_indexed(entity.ticker))
        outside: list[str] = []
        for use in comp_sets:
            for ticker in use.tickers:
                if ticker in self.indexed:
                    if ticker not in tickers:
                        tickers.append(ticker)
                elif ticker in self.dictionaries.companies:
                    if all(n.ticker != ticker for n in not_indexed):
                        not_indexed.append(self._not_indexed(ticker))
                elif ticker not in outside:
                    outside.append(ticker)
        for group in groups:
            tickers += [
                t for t in self._group_tickers(group) if t not in tickers
            ]

        time_scope = parse_time_scope(text)
        parts, rest, after_corpus = out_of_scope_parts(
            text, time_scope, self.catalog.last_filing_date
        )
        terms, weights = topics(rest)
        reason = self._out_of_scope_reason(
            entities=[*entities, *comp_sets],
            groups=groups,
            tickers=tickers,
            unknown=unknown,
            terms=terms,
            parts=parts,
            after_corpus=after_corpus,
        )
        parts += [f"{name} (not in the corpus)" for name in unknown]
        parts += [f"{t} (comp set, not in the corpus)" for t in outside]
        named = {e.ticker for e in entities}
        named.update(t for use in comp_sets for t in use.tickers)
        types = classify(
            companies=len(named),
            groups=groups,
            text=text,
            has_topic=bool(terms),
            out_of_scope_reason=reason,
        )
        types = with_period_trend(types, time_scope)
        windows = {
            ticker: company_window(
                time_scope,
                self.catalog.for_ticker(ticker),
                self.catalog.year_end_month(ticker),
            )
            for ticker in tickers
        }
        elapsed = (time.perf_counter() - started) * 1000
        return QuestionAnalysis(
            question=question.strip(),
            tickers=tuple(tickers),
            entities=tuple(entities),
            groups=tuple(groups),
            unknown_entities=tuple(unknown),
            not_indexed=tuple(not_indexed),
            time_scope=time_scope,
            windows=windows,
            primary_type=types[0],
            types=tuple(types),
            topic_terms=tuple(terms),
            section_weights=weights,
            table_weight=NUMERIC_TABLE_WEIGHT if "numeric" in types else 1.0,
            flags=Flags(
                fuzzy=any(e.fuzzy for e in entities),
                injection_suspect=injection,
                has_out_of_scope_part=bool(parts) and reason is None,
            ),
            out_of_scope_parts=tuple(parts),
            out_of_scope_reason=reason,
            suggested_tickers=tuple(self._suggestions(unknown)),
            elapsed_ms=round(elapsed, 3),
            comp_sets=tuple(comp_sets),
        )

    @staticmethod
    def _out_of_scope_reason(
        *,
        entities: Sequence[Entity | CompSetUse],
        groups: Sequence[str],
        tickers: Sequence[str],
        unknown: Sequence[str],
        terms: Sequence[str],
        parts: Sequence[str],
        after_corpus: bool,
    ) -> str | None:
        """Decide whether anything in the question is in scope.

        The parts here are the price, advice, and after-corpus requests;
        an unknown company next to a resolved one is no reason (10.6).
        """
        if tickers:
            request = after_corpus or (bool(parts) and not terms)
            return "out_of_scope_request" if request else None
        if entities and not groups:
            return "not_indexed"
        if unknown:
            return "unknown_company"
        if groups:
            return None
        if not terms:
            return "out_of_scope_request" if parts else "off_topic"
        return None
