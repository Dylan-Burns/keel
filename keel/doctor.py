"""Environment checks for `keel doctor` (chapter 21 pre-flight, GOTCHAS).

Each check returns a `CheckResult` with the status `ok`, `warn`, or `fail`.
A `fail` makes the command exit with 1. A check never prints a secret: the
key checks report only whether the variable is set.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import datetime
import logging
import os
import pathlib
import shutil
import socket
import sqlite3
import sys
import time
import zipfile

import pydantic

from keel import config
from keel import errors
from keel import inventory

logger = logging.getLogger(__name__)

OK = "ok"
WARN = "warn"
FAIL = "fail"
REQUIRED_PYTHON = (3, 12)
MIN_FREE_BYTES = 2 * 1024**3
CLOCK_MAX_LAG_DAYS = 730
PORT_SEARCH_SPAN = 10


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """The outcome of 1 doctor check.

    Attributes:
        name: The check name.
        status: `ok`, `warn`, or `fail`.
        detail: 1 line for the person at the terminal. Never a secret.
    """

    name: str
    status: str
    detail: str


def check_python(version: tuple[int, int, int]) -> CheckResult:
    """Check that the interpreter is Python 3.12.

    Args:
        version: The major, minor, and micro version.

    Returns:
        `ok` on 3.12, else `fail`.
    """
    text = ".".join(str(part) for part in version)
    if version[:2] == REQUIRED_PYTHON:
        return CheckResult("python", OK, text)
    return CheckResult("python", FAIL, f"{text}, Keel needs 3.12")


def check_fts5() -> CheckResult:
    """Check that SQLite has the FTS5 extension.

    Returns:
        `ok` when `ENABLE_FTS5` is a compile option and an FTS5 table
        builds, else `fail`.
    """
    connection = sqlite3.connect(":memory:")
    try:
        options = {
            row[0] for row in connection.execute("PRAGMA compile_options")
        }
        if "ENABLE_FTS5" not in options:
            return CheckResult(
                "sqlite fts5", FAIL, "ENABLE_FTS5 is not a compile option"
            )
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
    except sqlite3.OperationalError as error:
        return CheckResult("sqlite fts5", FAIL, str(error))
    finally:
        connection.close()
    return CheckResult("sqlite fts5", OK, f"SQLite {sqlite3.sqlite_version}")


def check_secret(variable: str, is_set: bool, effect: str) -> CheckResult:
    """Report whether a secret is set, without its value.

    Args:
        variable: The environment variable name.
        is_set: Whether the variable holds a value.
        effect: What happens without it.

    Returns:
        `ok` when set, else `warn` with the effect.
    """
    if is_set:
        return CheckResult(variable, OK, "set")
    return CheckResult(variable, WARN, f"absent: {effect}")


def check_clock(
    today: datetime.date,
    last_filing: datetime.date | None,
    time_zone: str,
    max_lag_days: int = CLOCK_MAX_LAG_DAYS,
) -> CheckResult:
    """Compare the clock with the newest corpus filing date (E-F-12).

    A wrong clock is a warning only, because time scopes anchor on the
    corpus dates, not the clock (decision D-33).

    Args:
        today: The local date of the clock.
        last_filing: The newest filing date in the corpus, or None.
        time_zone: The local time zone name, for the message.
        max_lag_days: The largest plausible gap after the newest filing.

    Returns:
        `ok` when the clock is after the newest filing and within the lag,
        else `warn`.
    """
    if last_filing is None:
        return CheckResult(
            "clock", WARN, f"{today} {time_zone}: no corpus dates to compare"
        )
    lag = (today - last_filing).days
    if lag < 0:
        return CheckResult(
            "clock",
            WARN,
            f"{today} {time_zone} is before the newest filing "
            f"{last_filing}: check the clock and the time zone",
        )
    if lag > max_lag_days:
        return CheckResult(
            "clock",
            WARN,
            f"{today} {time_zone} is {lag} days after the newest filing "
            f"{last_filing}: check the clock",
        )
    return CheckResult(
        "clock",
        OK,
        f"{today} {time_zone}, newest filing {last_filing} ({lag} days)",
    )


def corpus_last_filing(settings: config.Settings) -> datetime.date | None:
    """Find the newest filing date from the corpus file names.

    Reads the extracted directory, or the zip listing when the directory is
    absent. Nothing is extracted.

    Args:
        settings: The loaded settings.

    Returns:
        The newest filing date, or None when no corpus is present.
    """
    names: list[str] = []
    if settings.corpus.dir.is_dir():
        names = [path.name for path in settings.corpus.dir.glob("*.txt")]
    elif settings.corpus.zip.is_file():
        try:
            with zipfile.ZipFile(settings.corpus.zip) as archive:
                names = [pathlib.PurePath(n).name for n in archive.namelist()]
        except zipfile.BadZipFile:
            return None
    dates = [
        item.filing_date
        for item in map(inventory.parse_filename, names)
        if item is not None
    ]
    return max(dates, default=None)


def check_disk(
    path: pathlib.Path, min_free: int = MIN_FREE_BYTES
) -> CheckResult:
    """Check the free disk space under a path.

    Args:
        path: A path on the disk to check. Its nearest existing parent is
            measured.
        min_free: The free bytes needed.

    Returns:
        `ok` at or above the minimum, else `warn`.
    """
    probe = path.resolve()
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    detail = f"{free / 1024**3:.1f} GB free at {probe}"
    if free >= min_free:
        return CheckResult("disk", OK, detail)
    return CheckResult(
        "disk", WARN, f"{detail}, below {min_free / 1024**3:.0f} GB"
    )


def port_free(host: str, port: int) -> bool:
    """Tell whether a TCP port can be bound.

    Args:
        host: The bind address.
        port: The port.

    Returns:
        True when the bind succeeds.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def check_port(
    host: str,
    port: int,
    is_free: collections.abc.Callable[[str, int], bool] = port_free,
) -> CheckResult:
    """Check the server port and name the next free one (E-F-08).

    Args:
        host: The bind address.
        port: The configured port.
        is_free: The probe, replaceable in tests.

    Returns:
        `ok` when the port is free, else `warn` with the next free port.
    """
    if is_free(host, port):
        return CheckResult("port", OK, f"{host}:{port} is free")
    for candidate in range(port + 1, port + PORT_SEARCH_SPAN + 1):
        if is_free(host, candidate):
            return CheckResult(
                "port", WARN, f"{host}:{port} is in use, {candidate} is free"
            )
    return CheckResult(
        "port",
        WARN,
        f"{host}:{port} to {port + PORT_SEARCH_SPAN} are all in use",
    )


def check_prices(settings: config.Settings) -> CheckResult:
    """Check that every configured model has a price entry.

    Args:
        settings: The loaded settings.

    Returns:
        `ok` with the check date, or `fail` with the missing model ids.
    """
    try:
        prices = config.load_prices(settings.llm.prices)
    except errors.ConfigError as error:
        return CheckResult("prices", FAIL, str(error))
    missing = config.models_without_prices(settings, prices)
    if missing:
        return CheckResult("prices", FAIL, "no price for " + ", ".join(missing))
    return CheckResult(
        "prices", OK, f"checked on {prices.checked_on.isoformat()}"
    )


def hf_cache_dir(environ: collections.abc.Mapping[str, str]) -> pathlib.Path:
    """Return the Hugging Face hub cache directory.

    Args:
        environ: The environment variables.

    Returns:
        `HF_HUB_CACHE`, else `HF_HOME/hub`, else the XDG or home default.
    """
    if environ.get("HF_HUB_CACHE"):
        return pathlib.Path(environ["HF_HUB_CACHE"]).expanduser()
    if environ.get("HF_HOME"):
        return pathlib.Path(environ["HF_HOME"]).expanduser() / "hub"
    base = environ.get("XDG_CACHE_HOME") or str(pathlib.Path.home() / ".cache")
    return pathlib.Path(base).expanduser() / "huggingface" / "hub"


def model_snapshot(
    cache_dir: pathlib.Path, model: str, revision: str
) -> pathlib.Path:
    """Return the cache path of a pinned model snapshot.

    Args:
        cache_dir: The hub cache directory.
        model: The repository id such as `BAAI/bge-small-en-v1.5`.
        revision: The pinned commit hash.

    Returns:
        The snapshot directory, which may not exist.
    """
    folder = "models--" + model.replace("/", "--")
    return cache_dir / folder / "snapshots" / revision


def check_models(
    settings: config.Settings, cache_dir: pathlib.Path
) -> list[CheckResult]:
    """Check that both pinned models are in the local cache.

    Args:
        settings: The loaded settings.
        cache_dir: The hub cache directory.

    Returns:
        1 result per model: `ok` when the snapshot holds files, else `warn`
        with the download command (E-F-11).
    """
    results = []
    for model, revision in _pinned_models(settings):
        snapshot = model_snapshot(cache_dir, model, revision)
        if snapshot.is_dir() and any(snapshot.iterdir()):
            results.append(CheckResult(model, OK, f"cached at {revision[:12]}"))
        else:
            results.append(
                CheckResult(
                    model,
                    WARN,
                    f"revision {revision[:12]} not cached: "
                    "run keel doctor --download-models",
                )
            )
    return results


def _pinned_models(settings: config.Settings) -> list[tuple[str, str]]:
    return [
        (settings.embedding.model, settings.embedding.revision),
        (settings.reranker.model, settings.reranker.revision),
    ]


def download_models(settings: config.Settings) -> list[CheckResult]:
    """Download and load both pinned models into the local cache.

    Uses only the constructors that sentence-transformers 3.4 and 6 share,
    `SentenceTransformer(name, revision=...)` and
    `CrossEncoder(name, revision=...)`. Needs network access.

    Args:
        settings: The loaded settings.

    Returns:
        1 result per model with the load time, `fail` on an error.
    """
    # Heavy (torch), so imported only when a download is asked for.
    import sentence_transformers  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    loaders = [
        sentence_transformers.SentenceTransformer,
        sentence_transformers.CrossEncoder,
    ]
    results = []
    for loader, (model, revision) in zip(
        loaders, _pinned_models(settings), strict=True
    ):
        logger.info("loading %s at revision %s", model, revision)
        started = time.perf_counter()
        try:
            loader(model, revision=revision)
        except (OSError, ValueError, RuntimeError) as error:
            results.append(
                CheckResult(f"download {model}", FAIL, f"failed: {error}")
            )
            continue
        seconds = time.perf_counter() - started
        results.append(
            CheckResult(f"download {model}", OK, f"loaded in {seconds:.1f} s")
        )
    return results


def check_index(index_dir: pathlib.Path) -> CheckResult:
    """Check that an index build exists.

    Args:
        index_dir: The configured index directory.

    Returns:
        `ok` when `current` exists, else `warn` with the build command.
    """
    current = index_dir / "current"
    if current.exists():
        return CheckResult("index", OK, f"{current} present")
    return CheckResult("index", WARN, f"{current} absent: run keel index")


def _has_value(secret: pydantic.SecretStr | None) -> bool:
    return secret is not None and bool(secret.get_secret_value().strip())


def run_doctor(
    settings: config.Settings,
    now: datetime.datetime | None = None,
    download: bool = False,
    environ: collections.abc.Mapping[str, str] | None = None,
) -> list[CheckResult]:
    """Run every check.

    Args:
        settings: The loaded settings.
        now: The local time to check, or None for the clock.
        download: Download the pinned models before the model check.
        environ: The environment, or None for `os.environ`.

    Returns:
        The results in a stable order.
    """
    environ = os.environ if environ is None else environ
    local = now or datetime.datetime.now().astimezone()
    results = [
        check_python(
            (sys.version_info[0], sys.version_info[1], sys.version_info[2])
        ),
        check_fts5(),
        check_prices(settings),
        check_secret(
            "ANTHROPIC_API_KEY",
            _has_value(settings.anthropic_api_key),
            "the service starts in degraded mode (E-F-07)",
        ),
        check_secret(
            "KEEL_API_TOKEN",
            _has_value(settings.api_token),
            "the API refuses every request",
        ),
        check_clock(
            local.date(), corpus_last_filing(settings), local.tzname() or "?"
        ),
        check_disk(settings.index.dir),
        check_port(settings.server.host, settings.server.port),
        check_index(settings.index.dir),
    ]
    if download:
        results.extend(download_models(settings))
    results.extend(check_models(settings, hf_cache_dir(environ)))
    return results
