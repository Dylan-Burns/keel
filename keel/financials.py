"""Financial statements from the SEC company facts (the financials page).

From the XBRL company facts document of 1 company (`EdgarClient.
company_facts`) and the line items of `config/financials.yaml`, this module
builds the annual and quarterly series of 3 statements: the income
statement, the balance sheet, and the cash flow. It is pure
code over a cached document: no model request (decision D-02) and no
network request.

The rules follow the filings, not a vendor feed:

- Only 10-K and 10-Q rows count (`edgar.FACT_FORMS`). A duration of 350 to
  380 days is a fiscal year, 84 to 98 days a quarter (`edgar._kind`). The
  `fy` and `fp` of a row belong to the filing, not to the period, so the
  fiscal label comes from the period end and the company's own fiscal
  year numbering (`edgar.fiscal_labels`).
- For each period the first XBRL name of the item with a value wins, and
  among its rows the latest filing wins (a restatement replaces the value).
- Recent fourth quarters are not filed as quarters: Q4 is the fiscal year
  minus the 9-month year-to-date value. 10-Q cash flows are year-to-date:
  Q2 and Q3 are the differences of 2 year-to-date values. Such points carry
  the flag `derived` and a note.
- A per-share value or a share count filed before a stock split, and never
  restated by a later filing, is adjusted by the split ratio. The splits
  come from the filings themselves (`detect_splits`: the same period
  reported before and after a split differs by the split ratio), or from
  the per-company table of the config.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import datetime
import itertools
import logging
import pathlib
from typing import Any
from typing import Literal

import pydantic

from keel import config
from keel import edgar
from keel import errors

logger = logging.getLogger(__name__)

ANNUAL_DAYS = edgar.ANNUAL_DAYS
QUARTER_DAYS = edgar.QUARTER_DAYS
# 2 period ends less than this many days apart are the same end mistagged
# by a day or two (2010-07-31 and 2010-08-01).
SAME_END_DAYS = 7
# A quarter that starts within this many days of the expected start is the
# expected quarter (a 52/53-week calendar moves the start by a day or two).
START_SLACK_DAYS = 3
# Split ratios the detection accepts, and the reverse splits as 1/n.
SPLIT_RATIOS = (
    1.5,
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    7.0,
    8.0,
    10.0,
    15.0,
    20.0,
    25.0,
    30.0,
    40.0,
    50.0,
    100.0,
)
SPLIT_TOLERANCE = 0.02
# A per-share value under this size is too rounded to measure a ratio.
MIN_SPLIT_EPS = 0.5
# Pairs of filings that must agree before a split counts.
MIN_SPLIT_EVIDENCE = 2
SPLIT_UNITS = ("USD/shares", "shares")

Period = Literal["annual", "quarterly"]
StatementKind = Literal["duration", "instant"]


# --- Config (config/financials.yaml) ------------------------------------------


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class Derivation(_Model):
    """A line item computed from 2 other items of the same statement.

    Attributes:
        op: `add` or `subtract`, on the signed values.
        left: The first item; its point gives the source of the result.
        right: The second item.
        mode: `replace` computes every point; `gaps` fills only the
            periods that the filings leave empty.
        note: How the value was computed, for the tooltip.
    """

    op: Literal["add", "subtract"]
    left: str
    right: str
    mode: Literal["replace", "gaps"] = "gaps"
    note: str


class LineItemConfig(_Model):
    """1 line item of a statement.

    Attributes:
        id: The item ID, unique across the statements.
        label: The row label.
        parent: The ID of an earlier item of the same statement, or None.
        names: The XBRL names (taxonomy:Name) in priority order.
        unit: The XBRL unit: `USD`, `USD/shares`, or `shares`.
        sign: -1 shows the value negated (an outflow).
        hidden: The item only feeds a derivation and never shows.
        derive: The derivation, or None.
    """

    id: str = pydantic.Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    label: str
    parent: str | None = None
    names: tuple[str, ...] = ()
    unit: Literal["USD", "USD/shares", "shares"] = "USD"
    sign: Literal[1, -1] = 1
    hidden: bool = False
    derive: Derivation | None = None

    @pydantic.field_validator("names")
    @classmethod
    def _check_names(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        for name in names:
            taxonomy, _, local = name.partition(":")
            if not taxonomy or not local:
                raise ValueError(f"{name!r} is not taxonomy:Name")
        return names


class StatementConfig(_Model):
    """1 statement: a tab of the page.

    Attributes:
        id: The statement ID, such as `income`.
        label: The tab label.
        kind: `duration` (flows) or `instant` (balances).
        defaults: The items charted when the tab opens.
        items: The line items in row order.
    """

    id: str = pydantic.Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    label: str
    kind: StatementKind
    defaults: tuple[str, ...] = ()
    items: tuple[LineItemConfig, ...] = pydantic.Field(min_length=1)


class SplitConfig(_Model):
    """1 stock split of the per-company table.

    Attributes:
        date: The first filing date with split-adjusted values.
        ratio: New shares per old share (10 for a 10-for-1 split).
    """

    date: datetime.date
    ratio: float = pydantic.Field(gt=0)


class FinancialsConfig(_Model):
    """The statements of `config/financials.yaml`.

    Attributes:
        calendar: Lists of XBRL names, in priority order, whose periods
            define the fiscal years and the quarter ends.
        split_evidence: The share count names `detect_splits` reads
            besides the per-share items.
        splits: Per-company split tables (CIK of 10 digits to splits); an
            entry replaces the detection for that company.
        statements: The statements in tab order.
    """

    calendar: tuple[tuple[str, ...], ...] = pydantic.Field(min_length=1)
    split_evidence: tuple[str, ...] = ()
    splits: dict[str, tuple[SplitConfig, ...]] = pydantic.Field(
        default_factory=dict
    )
    statements: tuple[StatementConfig, ...] = pydantic.Field(min_length=1)

    @pydantic.model_validator(mode="after")
    def _check_tree(self) -> FinancialsConfig:
        seen: set[str] = set()
        for statement in self.statements:
            local: set[str] = set()
            for item in statement.items:
                if item.id in seen:
                    raise ValueError(f"duplicate line item {item.id!r}")
                if item.parent is not None and item.parent not in local:
                    raise ValueError(
                        f"{item.id}: parent {item.parent!r} is not an earlier "
                        f"item of {statement.id}"
                    )
                if not item.names and item.derive is None:
                    raise ValueError(f"{item.id}: no names and no derive")
                seen.add(item.id)
                local.add(item.id)
            ids = {item.id for item in statement.items}
            for item in statement.items:
                if item.derive is not None:
                    for ref in (item.derive.left, item.derive.right):
                        if ref not in ids:
                            raise ValueError(
                                f"{item.id}: derive names unknown {ref!r}"
                            )
            for default in statement.defaults:
                if default not in ids:
                    raise ValueError(
                        f"{statement.id}: unknown default {default!r}"
                    )
        return self


def load_financials_config(path: pathlib.Path) -> FinancialsConfig:
    """Load `config/financials.yaml`.

    Args:
        path: The YAML file.

    Returns:
        The validated config.

    Raises:
        ConfigError: The file is unreadable or fails validation.
    """
    data = config.read_yaml(path)
    try:
        return FinancialsConfig.model_validate(data)
    except pydantic.ValidationError as error:
        raise errors.ConfigError(f"invalid {path}: {error}") from error


# --- Results ------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Source:
    """The filing behind a value.

    Attributes:
        form: The form, such as `10-K`.
        accession: The accession number.
        filed: The filing date.
    """

    form: str
    accession: str
    filed: datetime.date


@dataclasses.dataclass(frozen=True)
class Point:
    """1 value of a line item for 1 fiscal period.

    Attributes:
        label: `FY2025` or `Q3 FY2025`.
        start: The first day of a duration, None for an instant.
        end: The last day of the period, or the instant.
        value: The value in the XBRL unit, signed for display.
        source: The filing of the value (of the left item when derived).
        derived: True when no filing reports the value as is.
        note: How the value was computed or adjusted, or None.
    """

    label: str
    start: datetime.date | None
    end: datetime.date
    value: float
    source: Source
    derived: bool = False
    note: str | None = None


@dataclasses.dataclass(frozen=True)
class Series:
    """The points of 1 line item.

    Attributes:
        item: The config of the item.
        annual: The fiscal years, oldest first.
        quarterly: The fiscal quarters, oldest first.
    """

    item: LineItemConfig
    annual: tuple[Point, ...]
    quarterly: tuple[Point, ...]

    def points(self, period: Period) -> tuple[Point, ...]:
        """The points of 1 period kind.

        Args:
            period: `annual` or `quarterly`.

        Returns:
            The points, oldest first.
        """
        return self.annual if period == "annual" else self.quarterly


@dataclasses.dataclass(frozen=True)
class Split:
    """1 stock split.

    Attributes:
        date: The first filing date with split-adjusted values.
        ratio: New shares per old share.
    """

    date: datetime.date
    ratio: float


@dataclasses.dataclass(frozen=True)
class StatementSeries:
    """The series of 1 statement.

    Attributes:
        config: The statement config.
        series: The series of its items, in row order.
    """

    config: StatementConfig
    series: tuple[Series, ...]


@dataclasses.dataclass(frozen=True)
class Statements:
    """The statements of 1 company.

    Attributes:
        company: The entity name of the facts document.
        fiscal_year_end: The month of the latest fiscal year end (1 to 12),
            or None when no fiscal year is known.
        splits: The stock splits applied.
        statements: The statements in tab order.
    """

    company: str
    fiscal_year_end: int | None
    splits: tuple[Split, ...]
    statements: tuple[StatementSeries, ...]


# --- Rows ---------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Row:
    """1 usable row of the company facts: a value of 1 XBRL name."""

    priority: int
    name: str
    start: datetime.date | None
    end: datetime.date
    value: float
    form: str
    accession: str
    filed: datetime.date

    @property
    def source(self) -> Source:
        return Source(self.form, self.accession, self.filed)


@dataclasses.dataclass(frozen=True)
class _Value:
    """The winning value of 1 period, split-adjusted."""

    value: float
    source: Source
    adjusted: bool


PeriodKey = tuple[datetime.date | None, datetime.date]


def _days(start: datetime.date, end: datetime.date) -> int:
    return (end - start).days + 1


def _rows(
    facts: Mapping[str, Any], names: Sequence[str], unit: str
) -> list[_Row]:
    """Read every 10-K and 10-Q row of the names, any duration."""
    rows: list[_Row] = []
    for priority, name in enumerate(names):
        taxonomy, _, local = name.partition(":")
        group = facts.get(taxonomy)
        item = group.get(local) if isinstance(group, Mapping) else None
        units = item.get("units") if isinstance(item, Mapping) else None
        raw = units.get(unit) if isinstance(units, Mapping) else None
        for row in raw if isinstance(raw, list) else []:
            parsed = _row(priority, local, row)
            if parsed is not None:
                rows.append(parsed)
    return rows


def _row(priority: int, name: str, row: object) -> _Row | None:
    """Parse 1 row, or None for a row of another form or a bad row."""
    if not isinstance(row, Mapping):
        return None
    if row.get("form") not in edgar.FACT_FORMS or row.get("fy") is None:
        return None
    try:
        start = (
            datetime.date.fromisoformat(row["start"])
            if "start" in row
            else None
        )
        return _Row(
            priority=priority,
            name=name,
            start=start,
            end=datetime.date.fromisoformat(row["end"]),
            value=float(row["val"]),
            form=str(row["form"]),
            accession=str(row["accn"]),
            filed=datetime.date.fromisoformat(row["filed"]),
        )
    except (KeyError, TypeError, ValueError):
        logger.warning("skipping a bad %s row: %r", name, row)
        return None


def _factor(filed: datetime.date, unit: str, splits: Sequence[Split]) -> float:
    """The split factor of a value filed on a date, in its unit."""
    if unit not in SPLIT_UNITS:
        return 1.0
    factor = 1.0
    for split in splits:
        if filed < split.date:
            factor *= split.ratio
    return factor if unit == "shares" else 1.0 / factor


def _best(
    rows: Iterable[_Row], unit: str, splits: Sequence[Split]
) -> dict[PeriodKey, _Value]:
    """Per period: the first name with a value, its latest filing."""
    best: dict[PeriodKey, _Row] = {}
    for row in rows:
        key = (row.start, row.end)
        current = best.get(key)
        rank = (-row.priority, row.filed, row.accession)
        if current is None or rank > (
            -current.priority,
            current.filed,
            current.accession,
        ):
            best[key] = row
    out: dict[PeriodKey, _Value] = {}
    for key, row in best.items():
        factor = _factor(row.filed, unit, splits)
        out[key] = _Value(row.value * factor, row.source, factor != 1.0)
    return out


# --- Stock splits -------------------------------------------------------------


def _split_ratio(ratio: float) -> float | None:
    """The split ratio a value ratio matches, or None."""
    for candidate in SPLIT_RATIOS:
        for value in (candidate, 1.0 / candidate):
            if abs(ratio / value - 1.0) <= SPLIT_TOLERANCE:
                return value
    return None


def detect_splits(
    facts: Mapping[str, Any], names: Mapping[str, Sequence[str]]
) -> tuple[Split, ...]:
    """Find the stock splits in the filings themselves.

    After a split, a filing restates the per-share values and the share
    counts of earlier periods. The same period reported by 2 consecutive
    filings then differs by the split ratio: a per-share value divides by
    it, a share count multiplies by it. Each such pair brackets the split
    between its 2 filing dates; pairs with the same ratio and overlapping
    brackets are 1 split, dated at the first filing with the new values.
    A split needs 2 agreeing pairs.

    Args:
        facts: The `facts` mapping of a company facts document.
        names: The unit (`USD/shares` or `shares`) to the XBRL names read.

    Returns:
        The splits, oldest first.
    """
    pairs: list[tuple[float, datetime.date, datetime.date]] = []
    for unit, unit_names in names.items():
        if unit not in SPLIT_UNITS:
            continue
        by_period: dict[tuple[str, PeriodKey], list[_Row]] = (
            collections.defaultdict(list)
        )
        for row in _rows(facts, unit_names, unit):
            by_period[(row.name, (row.start, row.end))].append(row)
        for rows in by_period.values():
            rows.sort(key=lambda row: (row.filed, row.accession))
            for old, new in itertools.pairwise(rows):
                if new.filed <= old.filed or old.value * new.value <= 0:
                    continue
                if (
                    unit == "USD/shares"
                    and min(abs(old.value), abs(new.value)) < MIN_SPLIT_EPS
                ):
                    continue
                raw = (
                    old.value / new.value
                    if unit == "USD/shares"
                    else new.value / old.value
                )
                ratio = _split_ratio(raw)
                if ratio is not None:
                    pairs.append((ratio, old.filed, new.filed))
    splits: list[Split] = []
    for ratio in sorted({pair[0] for pair in pairs}):
        brackets = sorted((lo, hi) for r, lo, hi in pairs if r == ratio)
        groups: list[list[datetime.date]] = []  # [lo, hi]
        counts: list[int] = []
        for lo, hi in sorted(brackets, key=lambda b: b[1]):
            if groups and lo < groups[-1][1] and hi > groups[-1][0]:
                groups[-1] = [max(groups[-1][0], lo), min(groups[-1][1], hi)]
                counts[-1] += 1
            else:
                groups.append([lo, hi])
                counts.append(1)
        splits.extend(
            Split(date=group[1], ratio=ratio)
            for group, count in zip(groups, counts, strict=True)
            if count >= MIN_SPLIT_EVIDENCE
        )
    return tuple(sorted(splits, key=lambda split: split.date))


# --- Fiscal calendar ----------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Year:
    """1 fiscal year: its bounds, its label, and its quarter ends."""

    start: datetime.date
    end: datetime.date
    label: str
    quarter_ends: tuple[datetime.date, ...]
    closed: bool


def _label_year(end: datetime.date) -> int:
    """The calendar year a fiscal year end names before the offset."""
    # A 52/53-week year that ends in the first days of January is the
    # previous year's (a year ending 2022-01-01 is fiscal 2021).
    return (end - datetime.timedelta(days=14)).year


def _year_offset(
    document: Mapping[str, Any],
    names: Sequence[str],
    ends: Iterable[datetime.date],
) -> int:
    """The company's fiscal year numbering against `_label_year`.

    The 10-K of a fiscal year labels its current annual period with the
    company's fiscal year (`edgar.fiscal_labels`). The most common
    difference to `_label_year` of the period end is the offset; 0 when
    no 10-K says.
    """
    concept = edgar.FactConcept(
        key="calendar", label="calendar", unit="USD", names=tuple(names)
    )
    labels = edgar.fiscal_labels(document, concept)
    votes = collections.Counter(
        labels[("annual", end)][0] - _label_year(end)
        for end in ends
        if ("annual", end) in labels
    )
    return votes.most_common(1)[0][0] if votes else 0


def _cluster(
    ends: Iterable[datetime.date], counts: Mapping[datetime.date, int]
) -> list[datetime.date]:
    """Merge ends less than a week apart; the most reported end wins."""
    picked: list[datetime.date] = []
    for end in sorted(set(ends)):
        if picked and (end - picked[-1]).days < SAME_END_DAYS:
            if counts.get(end, 0) > counts.get(picked[-1], 0):
                picked[-1] = end
            continue
        picked.append(end)
    return picked


def _calendar(
    document: Mapping[str, Any], calendar: Sequence[Sequence[str]]
) -> tuple[list[_Year], list[_Row]]:
    """The fiscal years of a company with their labels and quarter ends.

    The fiscal years are the annual periods of the first calendar concept
    with any, plus the open year after the last one. The quarter ends of a
    year are the ends of its quarters and of its year-to-date values,
    each a quarter after the previous end.

    Returns:
        The years, oldest first, and the rows of the calendar concept.
    """
    facts = document.get("facts")
    if not isinstance(facts, Mapping):
        return [], []
    rows: list[_Row] = []
    names: Sequence[str] = ()
    for names in calendar:
        rows = _rows(facts, names, "USD")
        if any(
            row.start is not None and _days(row.start, row.end) in ANNUAL_DAYS
            for row in rows
        ):
            break
    counts = collections.Counter(row.end for row in rows)
    annual = [
        (row.start, row.end)
        for row in rows
        if row.start is not None and _days(row.start, row.end) in ANNUAL_DAYS
    ]
    if not annual:
        return [], rows
    ends = _cluster((end for _, end in annual), counts)
    starts: dict[datetime.date, datetime.date] = {}
    for start, end in sorted(annual):
        if end in ends:
            starts[end] = start
    bounds = [(starts[end], end) for end in ends]
    # Drop a year that overlaps the previous one (a changed fiscal year).
    clean: list[tuple[datetime.date, datetime.date]] = []
    for first, end in bounds:
        start = first
        if clean and start <= clean[-1][1]:
            start = clean[-1][1] + datetime.timedelta(days=1)
            if _days(start, end) not in ANNUAL_DAYS:
                continue
        clean.append((start, end))
    last_end = clean[-1][1]
    open_year = (
        last_end + datetime.timedelta(days=1),
        last_end + datetime.timedelta(days=371),
    )
    offset = _year_offset(document, names, (end for _, end in clean))
    years: list[_Year] = []
    for (start, end), closed in [
        *((b, True) for b in clean),
        (open_year, False),
    ]:
        inside = [
            row
            for row in rows
            if row.start is not None and start <= row.start and row.end <= end
        ]
        candidates = {
            row.end
            for row in inside
            if row.start is not None
            and (
                _days(row.start, row.end) in QUARTER_DAYS
                or abs((row.start - start).days) <= START_SLACK_DAYS
            )
        }
        quarter_ends: list[datetime.date] = []
        previous = start - datetime.timedelta(days=1)
        for candidate in _cluster(candidates, counts):
            if _days(previous + datetime.timedelta(days=1), candidate) in (
                QUARTER_DAYS
            ):
                quarter_ends.append(candidate)
                previous = candidate
        label_end = end if closed else start + datetime.timedelta(days=364)
        years.append(
            _Year(
                start=start,
                end=end,
                label=f"FY{_label_year(label_end) + offset}",
                quarter_ends=tuple(quarter_ends[:4]),
                closed=closed,
            )
        )
    return years, rows


# --- Series -------------------------------------------------------------------


def _point(
    label: str,
    start: datetime.date | None,
    end: datetime.date,
    value: _Value,
    sign: int,
) -> Point:
    return Point(
        label=label,
        start=start,
        end=end,
        value=_tidy(value.value * sign),
        source=value.source,
        note="split-adjusted" if value.adjusted else None,
    )


def _derived(
    label: str,
    start: datetime.date,
    end: datetime.date,
    *,
    raw: float,
    source: _Value,
    how: str,
) -> Point:
    note = how + ("; split-adjusted" if source.adjusted else "")
    return Point(
        label=label,
        start=start,
        end=end,
        value=_tidy(raw),
        source=source.source,
        derived=True,
        note=note,
    )


def _tidy(value: float) -> float:
    """Round away the float noise of a difference."""
    return round(value, 6) if abs(value) < 1000 else float(round(value))


def _quarter_value(
    per: Mapping[PeriodKey, _Value], start: datetime.date, end: datetime.date
) -> _Value | None:
    """The value filed for a quarter, allowing a start a few days off."""
    direct = per.get((start, end))
    if direct is not None:
        return direct
    for (other_start, other_end), value in per.items():
        if (
            other_start is not None
            and other_end == end
            and abs((other_start - start).days) <= START_SLACK_DAYS
            and _days(other_start, other_end) in QUARTER_DAYS
        ):
            return value
    return None


def _flow_series(
    item: LineItemConfig,
    per: Mapping[PeriodKey, _Value],
    years: Sequence[_Year],
) -> tuple[list[Point], list[Point]]:
    """The fiscal years and quarters of a duration item.

    A quarter is the filed quarter; else the difference of 2 year-to-date
    values (a 10-Q cash flow, or Q4 as the year minus 9 months); else, for
    Q4, the fiscal year minus the 3 quarters before it.
    """
    sign = item.sign
    annual: list[Point] = []
    quarterly: list[Point] = []
    for year in years:
        filed_year = per.get((year.start, year.end)) if year.closed else None
        if filed_year is not None:
            annual.append(
                _point(year.label, year.start, year.end, filed_year, 1)
            )
        previous_end: datetime.date | None = None
        previous_raw: list[float | None] = []
        for index, end in enumerate(year.quarter_ends):
            start = (
                year.start
                if previous_end is None
                else previous_end + datetime.timedelta(days=1)
            )
            label = f"Q{index + 1} {year.label}"
            point: Point | None = None
            raw: float | None = None
            direct = _quarter_value(per, start, end)
            cumulative = per.get((year.start, end))
            before = (
                per.get((year.start, previous_end))
                if previous_end is not None
                else None
            )
            if direct is not None:
                point = _point(label, start, end, direct, 1)
                raw = direct.value
            elif cumulative is not None and before is not None:
                raw = cumulative.value - before.value
                how = (
                    "fiscal year minus the nine-month year-to-date"
                    if end == year.end
                    else "year-to-date difference"
                )
                point = _derived(
                    label, start, end, raw=raw, source=cumulative, how=how
                )
            elif cumulative is not None and previous_end is None:
                point = _point(label, start, end, cumulative, 1)
                raw = cumulative.value
            elif (
                end == year.end
                and filed_year is not None
                and len(previous_raw) == index == 3
                and all(value is not None for value in previous_raw)
            ):
                raw = filed_year.value - sum(
                    value for value in previous_raw if value is not None
                )
                point = _derived(
                    label,
                    start,
                    end,
                    raw=raw,
                    source=filed_year,
                    how="fiscal year minus Q1 to Q3",
                )
            previous_raw.append(raw)
            if point is not None:
                quarterly.append(point)
            previous_end = end
    return _signed(annual, sign), _signed(quarterly, sign)


def _signed(points: list[Point], sign: int) -> list[Point]:
    if sign == 1:
        return points
    return [
        dataclasses.replace(point, value=_tidy(point.value * sign))
        for point in points
    ]


def _instant_series(
    item: LineItemConfig,
    per: Mapping[PeriodKey, _Value],
    years: Sequence[_Year],
) -> tuple[list[Point], list[Point]]:
    """The fiscal year ends and quarter ends of a balance item."""
    by_end = {
        end: value for (start, end), value in per.items() if start is None
    }
    annual: list[Point] = []
    quarterly: list[Point] = []
    for year in years:
        if year.closed and year.end in by_end:
            annual.append(
                _point(year.label, None, year.end, by_end[year.end], item.sign)
            )
        for index, end in enumerate(year.quarter_ends):
            if end in by_end:
                quarterly.append(
                    _point(
                        f"Q{index + 1} {year.label}",
                        None,
                        end,
                        by_end[end],
                        item.sign,
                    )
                )
    return annual, quarterly


def _combine(
    left: Sequence[Point],
    right: Sequence[Point],
    rule: Derivation,
) -> list[Point]:
    """Point-wise derivation of 2 series with the same period labels."""
    by_label = {point.label: point for point in right}
    out: list[Point] = []
    for point in left:
        other = by_label.get(point.label)
        if other is None:
            continue
        value = (
            point.value + other.value
            if rule.op == "add"
            else point.value - other.value
        )
        note = rule.note if point.note is None else f"{rule.note}; {point.note}"
        out.append(
            dataclasses.replace(
                point, value=_tidy(value), derived=True, note=note
            )
        )
    return out


def _apply(
    target: Sequence[Point], computed: Sequence[Point], mode: str
) -> tuple[Point, ...]:
    if mode == "replace":
        merged = list(computed)
    else:
        have = {point.label for point in target}
        merged = [*target, *(p for p in computed if p.label not in have)]
    return tuple(sorted(merged, key=lambda point: point.end))


def _splits_of(
    document: Mapping[str, Any], settings: FinancialsConfig, cik: str | None
) -> tuple[Split, ...]:
    if cik is not None and cik in settings.splits:
        return tuple(
            Split(entry.date, entry.ratio) for entry in settings.splits[cik]
        )
    facts = document.get("facts")
    if not isinstance(facts, Mapping):
        return ()
    names: dict[str, list[str]] = collections.defaultdict(list)
    for statement in settings.statements:
        for item in statement.items:
            if item.unit in SPLIT_UNITS:
                names[item.unit].extend(
                    n for n in item.names if n not in names[item.unit]
                )
    names["shares"].extend(settings.split_evidence)
    return detect_splits(facts, names)


def extract(
    document: Mapping[str, Any],
    settings: FinancialsConfig,
    cik: str | None = None,
) -> Statements:
    """Build the statements of 1 company from its company facts.

    Args:
        document: The company facts body (`CachedDocument.data`).
        settings: The statements config.
        cik: The 10-digit CIK, for the per-company split table.

    Returns:
        The statements; an item with no value has empty series.
    """
    facts = document.get("facts")
    facts = facts if isinstance(facts, Mapping) else {}
    years, _ = _calendar(document, settings.calendar)
    splits = _splits_of(document, settings, cik)
    out: list[StatementSeries] = []
    for statement in settings.statements:
        built: dict[str, Series] = {}
        for item in statement.items:
            if not item.names:
                built[item.id] = Series(item, (), ())
                continue
            per = _best(_rows(facts, item.names, item.unit), item.unit, splits)
            if statement.kind == "duration":
                annual, quarterly = _flow_series(item, per, years)
            else:
                annual, quarterly = _instant_series(item, per, years)
            built[item.id] = Series(item, tuple(annual), tuple(quarterly))
        for item in statement.items:
            rule = item.derive
            if rule is None:
                continue
            left, right = built[rule.left], built[rule.right]
            current = built[item.id]
            built[item.id] = Series(
                item,
                _apply(
                    current.annual,
                    _combine(left.annual, right.annual, rule),
                    rule.mode,
                ),
                _apply(
                    current.quarterly,
                    _combine(left.quarterly, right.quarterly, rule),
                    rule.mode,
                ),
            )
        out.append(
            StatementSeries(
                statement,
                tuple(built[item.id] for item in statement.items),
            )
        )
    closed = [year for year in years if year.closed]
    return Statements(
        company=str(document.get("entityName") or ""),
        fiscal_year_end=closed[-1].end.month if closed else None,
        splits=splits,
        statements=tuple(out),
    )
