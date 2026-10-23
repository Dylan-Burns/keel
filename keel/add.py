"""`keel add TICKER`: 1 company from EDGAR into the index (chapter 26.2).

The steps follow chapter 26.2 and the procedure of chapter 17.4:

1. Resolve the ticker to a CIK through the cached ticker map.
2. Read the submissions and pick the latest 10-K and the latest 10-Q.
3. Download each primary document through the EDGAR client (cached).
4. Convert the HTML to the corpus text format and write the file into the
   corpus directory under the corpus file name pattern.
5. Record each file in the corpus manifest, with `source: edgar` under
   `added`, and add the company to `config/companies.yaml` when absent.
6. Parse the company's files with the unchanged parser of chapter 7 (the
   report), then run the incremental build of chapter 9, which embeds only
   the new or changed filings.

All fetches happen here, before any question; no model request is made
(decisions D-01 and D-02).
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import datetime
import json
import logging
import pathlib
import re

import pydantic

from keel import config
from keel import edgar
from keel import errors
from keel import html_text
from keel import indexer
from keel import inventory
from keel import steps
from keel.parsers import base
from keel.parsers import corpus as parser_corpus
from keel.stores import chunk_store

logger = logging.getLogger(__name__)

MANIFEST = "manifest.json"
FORM_CODES = {"10-K": "10K", "10-Q": "10Q"}
# The steps of `add_ticker` before the build steps of `indexer.STEPS`.
FETCH_STEPS = (
    steps.StepDef("resolve", "Resolve the ticker"),
    steps.StepDef("filings", "Fetch the filing list from EDGAR"),
    *(
        steps.StepDef(f"download_{code.lower()}", f"Download the {form}")
        for form, code in FORM_CODES.items()
    ),
    steps.StepDef("convert", "Convert to text"),
)
STEPS = FETCH_STEPS + indexer.STEPS
# The ticker part of a corpus file name (inventory.FILENAME_* patterns).
CORPUS_TICKER = re.compile(r"^[A-Z][A-Z.]{0,9}$")
_NAME_TOKEN = re.compile(r"[^\w&'.-]+")


class FilingReport(pydantic.BaseModel):
    """What `keel add` did with 1 filing.

    Attributes:
        form: `10-K` or `10-Q`.
        accession: The accession number.
        filing_date: The filing date.
        report_date: The period end date the submissions state.
        url: The archive URL of the primary document.
        file_name: The corpus file written.
        changed: True when the file is new or its text changed.
        filing_id: The filing ID from the parse, or None.
        period_end_date: The period end date from the cover page.
        fiscal_year: The fiscal year from the parser.
        fiscal_period: `FY`, `Q1` to `Q3`, or `unknown`.
        quarantine: The quarantine reason, or None.
        warnings: The parser warning codes.
        chunks: The chunks of the filing in the published index.
    """

    form: str
    accession: str
    filing_date: datetime.date
    report_date: datetime.date
    url: str
    file_name: str
    changed: bool
    filing_id: str | None = None
    period_end_date: datetime.date | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    quarantine: str | None = None
    warnings: tuple[str, ...] = ()
    chunks: int = 0


class AddReport(pydantic.BaseModel):
    """The result of `keel add TICKER`.

    Attributes:
        ticker: The ticker as the corpus spells it.
        cik: The CIK, 10 digits.
        company: The company name from the submissions.
        filings: 1 report per filing picked.
        dictionary_added: True when the company joined the dictionary.
        index_built: True when a new index build was published.
        index_version: The index version behind `current` afterwards.
        embedded_filings: The filings the build sent to the model.
        embedded_chunks: The chunks the build sent to the model.
        requests: The EDGAR requests of this run.
    """

    ticker: str
    cik: str
    company: str
    filings: list[FilingReport]
    dictionary_added: bool
    index_built: bool
    index_version: str
    embedded_filings: int = 0
    embedded_chunks: int = 0
    requests: int = 0


def corpus_ticker(ticker: str) -> str:
    """Spell a ticker the way the corpus file names do (`BRK.B`).

    Args:
        ticker: The ticker as typed.

    Returns:
        The ticker, upper case, with `.` for a share class.

    Raises:
        EdgarError: The ticker cannot name a corpus file.
    """
    spelled = edgar.normalize_ticker(ticker).replace("-", ".")
    if not CORPUS_TICKER.match(spelled):
        raise errors.EdgarError(f"ticker {ticker!r} cannot name a corpus file")
    return spelled


def file_name(ticker: str, ref: edgar.FilingRef) -> str:
    """Name the corpus file of a filing (the inventory patterns).

    A 10-K has no period code, as in the corpus; a 10-Q carries the
    calendar quarter of its report date.

    Args:
        ticker: The corpus ticker.
        ref: The filing.

    Returns:
        A name such as `ZTS_10Q_2026Q2_2026-08-06_full.txt`.
    """
    code = FORM_CODES[ref.form]
    filed = ref.filing_date.isoformat()
    if ref.form == "10-K":
        return f"{ticker}_{code}_{filed}_full.txt"
    period = base.calendar_quarter(ref.report_date)
    return f"{ticker}_{code}_{period}_{filed}_full.txt"


def write_if_changed(path: pathlib.Path, text: str) -> bool:
    """Write a text file unless it already holds the same text.

    Args:
        path: The file.
        text: The text.

    Returns:
        True when the file was written.

    Raises:
        EdgarError: The file cannot be written.
    """
    data = text.encode("utf-8")
    try:
        if path.is_file() and path.read_bytes() == data:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
    except OSError as error:
        raise errors.EdgarError(f"cannot write {path}: {error}") from error
    return True


def record_in_manifest(
    path: pathlib.Path,
    entries: dict[str, dict[str, str]],
) -> bool:
    """Add files to the corpus manifest with their source (26.2, step 6).

    The new file names join `files`, `file_count` and `filing_types` grow
    by them, and each file gets an entry under `added` with `source:
    edgar`, the form, the accession number, and the URL. Unknown keys are
    kept.

    Args:
        path: The manifest JSON file.
        entries: The `added` entry per file name.

    Returns:
        True when the manifest changed.

    Raises:
        ManifestMissingError: The manifest is absent or not JSON.
        EdgarError: The manifest cannot be written.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise errors.ManifestMissingError(
            f"manifest unusable at {path}: {error}"
        ) from error
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise errors.ManifestMissingError(f"{path} has no files list")
    before = json.dumps(data, sort_keys=True)
    new = sorted(set(entries) - set(data["files"]))
    added = data.get("added")
    added = dict(added) if isinstance(added, dict) else {}
    added.update(entries)
    data["files"] = sorted([*data["files"], *new])
    # The claims of the zip manifest grow by the new files only, so a
    # discrepancy that `keel inventory` reports stays visible.
    if isinstance(data.get("file_count"), int):
        data["file_count"] += len(new)
    forms = data.get("filing_types")
    forms = dict(forms) if isinstance(forms, dict) else {}
    for name in new:
        parsed = inventory.parse_filename(name)
        if parsed is not None:
            forms[parsed.form] = int(forms.get(parsed.form, 0)) + 1
    data["filing_types"] = dict(sorted(forms.items()))
    data["added"] = dict(sorted(added.items()))
    if json.dumps(data, sort_keys=True) == before:
        return False
    write_if_changed(path, json.dumps(data, indent=2) + "\n")
    return True


def aliases(ticker: str, company: str) -> list[str]:
    """Build the dictionary aliases of a company: its short name and ticker.

    Args:
        ticker: The corpus ticker.
        company: The company name, such as `Workday, Inc.`.

    Returns:
        The lower-case aliases, such as `["workday", "wday"]`.
    """
    tokens = [t.strip(".") for t in _NAME_TOKEN.split(company) if t]
    while tokens and (
        tokens[-1].upper() in base.NAME_STOP_TOKENS
        or not any(char.isalnum() for char in tokens[-1])
    ):
        tokens.pop()
    found = [" ".join(tokens).lower(), ticker.lower()]
    return [alias for i, alias in enumerate(found) if alias not in found[:i]]


def ensure_company(path: pathlib.Path, ticker: str, company: str) -> bool:
    """Add a company to `config/companies.yaml` when absent (17.4).

    The entry is appended as text, so the comments of the file stay. It
    holds the name, the aliases, and no group.

    Args:
        path: The dictionary file.
        ticker: The corpus ticker.
        company: The company name.

    Returns:
        True when the entry was added.

    Raises:
        ConfigError: The dictionary is unreadable or unwritable, or
            invalid after the append (the file is then restored).
    """
    if ticker in config.read_yaml(path):
        return False
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as error:
        raise errors.ConfigError(f"cannot read {path}: {error}") from error
    # A quoted key: YAML reads a bare `ON` or `NO` as a boolean.
    entry = (
        f"{json.dumps(ticker)}:\n"
        f"  company: {json.dumps(company)}\n"
        f"  aliases: {json.dumps(aliases(ticker, company))}\n"
        "  groups: []\n"
    )
    separator = "" if original.endswith("\n") else "\n"
    _replace_text(path, original + separator + entry)
    try:
        loaded = config.read_yaml(path).get(ticker)
    except errors.ConfigError:
        _replace_text(path, original)
        raise
    if not isinstance(loaded, dict) or loaded.get("company") != company:
        _replace_text(path, original)
        raise errors.ConfigError(f"cannot add {ticker} to {path}")
    return True


def _replace_text(path: pathlib.Path, text: str) -> None:
    """Write a config file through a temporary file."""
    try:
        write_if_changed(path, text)
    except errors.EdgarError as error:
        raise errors.ConfigError(str(error)) from error


def _parse_ticker(
    settings: config.Settings, corpus_dir: pathlib.Path, ticker: str
) -> dict[str, base.ParsedFiling]:
    """Parse the files of 1 ticker with the unchanged parser."""
    manifest = inventory.load_manifest(corpus_dir / MANIFEST)
    context = base.ParseContext.from_settings(settings, manifest.files)
    paths = sorted(corpus_dir.glob(f"{ticker}_*_full.txt"))
    parsed = parser_corpus.finish_corpus(
        parser_corpus.parse_files(paths, context), context
    )
    return {f.metadata.file_name: f for f in parsed.filings}


def _chunk_counts(build_dir: pathlib.Path) -> dict[str, int]:
    """Count the chunks per filing ID in a published build."""
    conn = chunk_store.open_read_only(build_dir / chunk_store.FILE_NAME)
    try:
        rows = conn.execute(
            "SELECT filing_id, COUNT(*) FROM chunks GROUP BY filing_id"
        ).fetchall()
    finally:
        conn.close()
    return {str(filing_id): int(count) for filing_id, count in rows}


def _report(
    ref: edgar.FilingRef,
    name: str,
    changed: bool,
    filing: base.ParsedFiling | None,
    counts: dict[str, int],
) -> FilingReport:
    report = FilingReport(
        form=ref.form,
        accession=ref.accession,
        filing_date=ref.filing_date,
        report_date=ref.report_date,
        url=ref.url,
        file_name=name,
        changed=changed,
    )
    if filing is None:
        return report
    meta = filing.metadata
    return report.model_copy(
        update={
            "filing_id": filing.filing_id,
            "period_end_date": meta.period_end_date,
            "fiscal_year": meta.fiscal_year,
            "fiscal_period": meta.fiscal_period,
            "quarantine": filing.quarantine.reason
            if filing.quarantine
            else None,
            "warnings": filing.warnings,
            "chunks": counts.get(filing.filing_id or "", 0),
        }
    )


def _download(
    client: edgar.EdgarClient,
    refs: Sequence[edgar.FilingRef],
    reporter: steps.Reporter,
) -> list[tuple[edgar.FilingRef, bytes]]:
    """Download the primary document of each picked filing.

    Each form has its own step; a form without a picked filing is
    skipped.
    """
    documents: list[tuple[edgar.FilingRef, bytes]] = []
    by_form = {ref.form: ref for ref in refs}
    for form, code in FORM_CODES.items():
        key = f"download_{code.lower()}"
        ref = by_form.get(form)
        if ref is None:
            reporter.skip(key, f"no {form} picked")
            continue
        reporter.step(key)
        before = client.requests
        document = client.filing_document(ref)
        origin = "EDGAR" if client.requests > before else "the EDGAR cache"
        reporter.log(
            f"{ref.form} filed {ref.filing_date}: {len(document):,} bytes "
            f"from {origin}"
        )
        documents.append((ref, document))
    # The files are converted and reported in the order of the pick.
    return sorted(documents, key=lambda pair: refs.index(pair[0]))


@dataclasses.dataclass(frozen=True)
class _Origin:
    """The company of the converted files."""

    company: str
    ticker: str
    cik: str


def _convert(
    documents: Sequence[tuple[edgar.FilingRef, bytes]],
    origin: _Origin,
    corpus_dir: pathlib.Path,
    reporter: steps.Reporter,
) -> tuple[list[tuple[edgar.FilingRef, str, bool]], dict[str, dict[str, str]]]:
    """Write each document as a corpus file; list the manifest entries."""
    written: list[tuple[edgar.FilingRef, str, bool]] = []
    entries: dict[str, dict[str, str]] = {}
    for ref, document in documents:
        header = html_text.FilingHeader(
            company=origin.company,
            ticker=origin.ticker,
            form=ref.form,
            filing_date=ref.filing_date,
            cik=origin.cik,
            url=ref.url,
        )
        text = html_text.to_corpus_text(document, header)
        name = file_name(origin.ticker, ref)
        changed = write_if_changed(corpus_dir / name, text)
        logger.info(
            "%s %s: %s (%d characters)",
            "wrote" if changed else "unchanged",
            ref.form,
            name,
            len(text),
        )
        verb = "wrote" if changed else "unchanged"
        reporter.log(f"{verb} {name} ({len(text):,} characters)")
        written.append((ref, name, changed))
        entries[name] = {
            "source": html_text.SOURCE,
            "ticker": origin.ticker,
            "form": ref.form,
            "accession": ref.accession,
            "url": ref.url,
        }
    return written, entries


def add_ticker(  # pylint: disable=too-many-locals
    settings: config.Settings,
    ticker: str,
    *,
    client: edgar.EdgarClient,
    corpus_dir: pathlib.Path,
    index_dir: pathlib.Path,
    embedder_factory: indexer.EmbedderFactory,
    forms: Sequence[str] = edgar.ADD_FORMS,
    reporter: steps.Reporter = steps.NULL,
) -> AddReport:
    """Add the latest 10-K and 10-Q of 1 company (chapter 26.2).

    Args:
        settings: The loaded settings.
        ticker: The ticker.
        client: The EDGAR client (offline for a cache-only run).
        corpus_dir: The corpus directory with `manifest.json`.
        index_dir: The index directory with `current`.
        embedder_factory: Loads the embedder for the new filings.
        forms: The forms to pick.
        reporter: Receives the steps of `STEPS` and their log lines.

    Returns:
        The report.

    Raises:
        UnknownTickerError: The SEC ticker map has no such ticker.
        EdgarError: A form is not 10-K or 10-Q, or a fetch, the cache,
            or the conversion fails.
        ConfigError: The dictionary cannot take the company.
        IndexMissingError: The index directory has no current build.
        ManifestMissingError: The corpus has no usable manifest.
    """
    unknown = [form for form in forms if form not in FORM_CODES]
    if unknown:
        raise errors.EdgarError("keel add reads no " + ", ".join(unknown))
    current = indexer.current_build(index_dir)
    if current is None:
        raise errors.IndexMissingError(
            f"no current build in {index_dir}: run `keel index` first"
        )
    spelled = corpus_ticker(ticker)
    reporter.step("resolve")
    cik = client.cik(ticker)
    reporter.log(f"{spelled} is CIK {cik}")
    reporter.step("filings")
    submissions = client.submissions(cik).data
    company = str(
        submissions.get("name") or client.ticker_map().lookup(ticker).title
    )
    refs = edgar.pick_latest(submissions, forms)
    reporter.log(f"{company}: {len(refs)} filings picked")
    for ref in refs:
        reporter.log(
            f"latest {ref.form} filed {ref.filing_date}, accession "
            f"{ref.accession}"
        )
    dictionary_added = ensure_company(
        settings.dictionaries.companies, spelled, company
    )
    if dictionary_added:
        reporter.log(f"added {company} to the company dictionary")
    documents = _download(client, refs, reporter)
    reporter.step("convert")
    written, entries = _convert(
        documents,
        _Origin(company=company, ticker=spelled, cik=cik),
        corpus_dir,
        reporter,
    )
    manifest_changed = record_in_manifest(corpus_dir / MANIFEST, entries)
    reporter.step("parse")
    parsed = _parse_ticker(settings, corpus_dir, spelled)
    for name, filing in parsed.items():
        if name not in entries:
            continue
        if filing.quarantine is not None:
            logger.warning(
                "%s quarantined: %s (%s)",
                name,
                filing.quarantine.reason,
                filing.quarantine.detail,
            )
            reporter.log(f"{name}: quarantined: {filing.quarantine.reason}")
        else:
            meta = filing.metadata
            reporter.log(
                f"{name}: fiscal {meta.fiscal_period} {meta.fiscal_year}, "
                f"period end {meta.period_end_date}"
            )
    # A file written by an earlier run whose build failed is not indexed
    # yet; an indexable picked filing missing from `current` builds too.
    indexed = _chunk_counts(current)
    missing = [
        name
        for name, picked in parsed.items()
        if name in entries
        and picked.quarantine is None
        and (picked.filing_id or "") not in indexed
    ]
    needs_build = (
        manifest_changed or any(c for _, _, c in written) or bool(missing)
    )
    embedded = (0, 0)
    if needs_build:
        result = indexer.build_index(
            settings,
            corpus_dir,
            index_dir,
            embedder_factory,
            incremental=True,
            reporter=reporter,
        )
        build_dir = result.build_dir
        embedded = (
            result.manifest.build.embedded_filings,
            result.manifest.build.embedded_chunks,
        )
    else:
        logger.info("no new or changed filing: the index stays as it is")
        reporter.log("no new or changed filing: the index stays as it is")
        build_dir = current
    counts = _chunk_counts(build_dir)
    return AddReport(
        ticker=spelled,
        cik=cik,
        company=company,
        filings=[
            _report(ref, name, changed, parsed.get(name), counts)
            for ref, name, changed in written
        ],
        dictionary_added=dictionary_added,
        index_built=needs_build,
        index_version=indexer.load_manifest(build_dir).index_version,
        embedded_filings=embedded[0],
        embedded_chunks=embedded[1],
        requests=client.requests,
    )
