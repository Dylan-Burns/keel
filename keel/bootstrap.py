"""The first-start bootstrap: corpus download, extraction, index build.

`keel bootstrap` and `keel serve --bootstrap` run the same routine (chapter
29.9 step 6). It is idempotent: a corpus directory that holds filings skips
the download and the extraction, and an index with a `current` pointer
skips the build, so later starts cost a directory listing.

The zip comes from, in order: the local `corpus.zip`, a zip downloaded by an
earlier run, `gh release download` of the `corpus.release_tag` asset when
`GH_TOKEN` is set and `gh` is installed (chapter 29.11), or an https GET of
`corpus.url`. The GET follows control S-11: https only, a host on the allow
list (the host of `corpus.url` and the GitHub release asset hosts), every
resolved address public, the address of the opened socket public too (DNS
rebinding), and each redirect target checked again. The URL can carry a
signature in its query, so logs and errors never hold the query string, and
the httpx and httpcore loggers stay at WARNING during the download.

The routine reports its phase and progress through a `BootstrapState`, so
the server can run it in a background thread and `/api/ready` can read the
state without waiting for it.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
import contextlib
import dataclasses
import datetime
import enum
import logging
import os
import pathlib
import shutil
import socket
import subprocess
import tempfile
import threading
from urllib import parse

import httpx
import pydantic

from keel import config
from keel import errors
from keel import extractor
from keel import indexer
from keel import net
from keel.stores import numpy_dense

logger = logging.getLogger(__name__)

# GitHub serves a release asset from github.com with a redirect to one of
# these hosts. They join the allow list next to the host of `corpus.url`.
GITHUB_RELEASE_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
MAX_REDIRECTS = 5
MAX_DOWNLOAD_BYTES = extractor.MAX_TOTAL_BYTES
GH_TIMEOUT_SECONDS = 1800
_STREAM_CHUNK_BYTES = 1024 * 1024

Resolver = Callable[[str], Sequence[str]]
CommandRunner = Callable[[Sequence[str]], None]


class Phase(enum.StrEnum):
    """The phases of a bootstrap, in the order they run."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


ACTIVE_PHASES = frozenset({Phase.DOWNLOADING, Phase.EXTRACTING, Phase.INDEXING})


class BootstrapStatus(pydantic.BaseModel):
    """A snapshot of the bootstrap for `/api/ready` and the CLI.

    Attributes:
        phase: The current phase.
        detail: 1 line on what the phase does, without secrets.
        done: The units done in the phase: bytes while downloading, shards
            while indexing.
        total: The units in all, or None when unknown.
        corpus: `present`, `extracted`, or `downloaded`, once known.
        index: `present` or `built`, once known.
        error: The error class and message after a failure.
        started_at: The UTC start time, or None before the start.
        finished_at: The UTC end time, or None while it runs.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    phase: Phase = Phase.PENDING
    detail: str = ""
    done: int = 0
    total: int | None = None
    corpus: str | None = None
    index: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def running(self) -> bool:
        """True while a phase does work."""
        return self.phase in ACTIVE_PHASES


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class BootstrapState:
    """The thread-safe holder of the bootstrap status.

    The bootstrap thread writes it; request handlers read `snapshot()`.
    """

    def __init__(self) -> None:
        """Start in the `pending` phase."""
        self._lock = threading.Lock()
        self._status = BootstrapStatus()

    def snapshot(self) -> BootstrapStatus:
        """Return the current status.

        Returns:
            An immutable copy of the status.
        """
        with self._lock:
            return self._status

    def begin(self) -> bool:
        """Claim the state for a run.

        Returns:
            False when a run is already active, else True.
        """
        with self._lock:
            if self._status.running:
                return False
            self._status = BootstrapStatus(
                phase=Phase.PENDING, detail="starting", started_at=_now()
            )
            return True

    def update(self, **changes: object) -> None:
        """Change fields of the status.

        Args:
            **changes: The fields of `BootstrapStatus` to set.
        """
        with self._lock:
            self._status = self._status.model_copy(update=changes)

    def enter(
        self, phase: Phase, detail: str, total: int | None = None
    ) -> None:
        """Move to a phase and reset the progress.

        Args:
            phase: The new phase.
            detail: What the phase does.
            total: The units of the phase, or None when unknown.
        """
        logger.info("bootstrap %s: %s", phase, detail)
        self.update(phase=phase, detail=detail, done=0, total=total)

    def advance(self, done: int, total: int | None) -> None:
        """Record the progress inside the phase.

        Args:
            done: The units done.
            total: The units in all, or None when unknown.
        """
        self.update(done=done, total=total)


def resolve_host(host: str) -> list[str]:
    """Resolve a host name to its IP addresses.

    Args:
        host: The host name.

    Returns:
        The addresses, without duplicates.

    Raises:
        HostNotAllowedError: The name does not resolve.
    """
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise errors.HostNotAllowedError(
            f"cannot resolve {host}: {error}"
        ) from error
    return sorted({str(info[4][0]) for info in infos})


def allowed_hosts(url: str | None) -> frozenset[str]:
    """Return the outbound allow list of the bootstrap download.

    Args:
        url: The configured `corpus.url`, or None.

    Returns:
        The host of the URL and the GitHub release asset hosts.
    """
    hosts = set(GITHUB_RELEASE_HOSTS)
    if url:
        host = parse.urlsplit(url).hostname
        if host:
            hosts.add(host.lower())
    return frozenset(hosts)


def check_url(url: str, allowed: frozenset[str], resolver: Resolver) -> str:
    """Check 1 URL against control S-11 before a request.

    Args:
        url: The URL to fetch.
        allowed: The allowed host names.
        resolver: Resolves a host name to IP addresses.

    Returns:
        The host name of the URL.

    Raises:
        HostNotAllowedError: The URL is not https, names a host outside the
            allow list, carries credentials or a port other than 443, or
            resolves to a private, loopback, link-local, or reserved address.
    """
    parts = parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        scheme = parts.scheme or "no scheme"
        raise errors.HostNotAllowedError(
            f"only https downloads are allowed, not {scheme}"
        )
    if host not in allowed:
        shown = host or "no host"
        raise errors.HostNotAllowedError(f"{shown} is not allowed")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise errors.HostNotAllowedError(
            f"credentials or a port in the URL of {host}"
        )
    net.check_addresses(host, resolver(host))
    return host


def download(
    url: str,
    destination: pathlib.Path,
    *,
    allowed: frozenset[str],
    resolver: Resolver = resolve_host,
    transport: httpx.BaseTransport | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> int:
    """Download a URL to a file under control S-11.

    Redirects are followed by hand, at most `MAX_REDIRECTS`, and each target
    passes `check_url` again. The body goes to `<destination>.part`, which is
    renamed into place only when it is complete.

    Args:
        url: The https URL.
        destination: The file to write.
        allowed: The allowed host names.
        resolver: Resolves a host name to IP addresses.
        transport: The httpx transport; None uses the network.
        progress: Called with the bytes done and the bytes in all.
        max_bytes: The largest body accepted.

    Returns:
        The number of bytes written.

    Raises:
        HostNotAllowedError: The URL or a redirect target fails S-11.
        CorpusDownloadError: An HTTP error, too many redirects, a body over
            the limit, or a network or write failure.
    """
    part = destination.with_name(destination.name + ".part")
    timeout = httpx.Timeout(60.0, connect=10.0)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (
            net.quiet_http_logs(),
            httpx.Client(
                transport=transport, follow_redirects=False, timeout=timeout
            ) as client,
        ):
            for _ in range(MAX_REDIRECTS + 1):
                host = check_url(url, allowed, resolver)
                logger.info("bootstrap: GET %s", net.redact_url(url))
                with client.stream("GET", url) as response:
                    # DNS rebinding: the connect may resolve again.
                    net.check_peer(response, host)
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        url = parse.urljoin(url, location)
                        continue
                    if response.status_code != httpx.codes.OK:
                        raise errors.CorpusDownloadError(
                            f"{host} answered HTTP {response.status_code}"
                        )
                    written = _stream_body(
                        response, part, host, progress, max_bytes
                    )
                os.replace(part, destination)
                return written
    except httpx.HTTPError as error:
        _discard(part)
        raise errors.CorpusDownloadError(
            f"download failed: {type(error).__name__}"
        ) from error
    except OSError as error:
        _discard(part)
        raise errors.CorpusDownloadError(
            f"cannot write {destination}: {error}"
        ) from error
    except errors.KeelError:
        _discard(part)
        raise
    raise errors.CorpusDownloadError(f"more than {MAX_REDIRECTS} redirects")


def _discard(part: pathlib.Path) -> None:
    """Remove a partial download; a missing parent is not an error."""
    with contextlib.suppress(OSError):
        part.unlink(missing_ok=True)


def _stream_body(
    response: httpx.Response,
    part: pathlib.Path,
    host: str,
    progress: Callable[[int, int | None], None] | None,
    max_bytes: int,
) -> int:
    """Write the response body to the part file within the byte limit."""
    length = response.headers.get("content-length")
    total = int(length) if length and length.isdigit() else None
    if total is not None and total > max_bytes:
        raise errors.CorpusDownloadError(
            f"{host} sends {total} bytes, the limit is {max_bytes}"
        )
    written = 0
    with part.open("wb") as sink:
        for chunk in response.iter_bytes(_STREAM_CHUNK_BYTES):
            written += len(chunk)
            if written > max_bytes:
                raise errors.CorpusDownloadError(
                    f"{host} sends more than {max_bytes} bytes"
                )
            sink.write(chunk)
            if progress is not None:
                progress(written, total)
    return written


def _run_command(command: Sequence[str]) -> None:
    """Run a command; the token stays in the inherited environment."""
    try:
        # A fixed argument list with no shell; the executable path comes
        # from shutil.which and the arguments from the config.
        subprocess.run(  # noqa: S603
            list(command),
            check=True,
            capture_output=True,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.CalledProcessError as error:
        raise errors.CorpusDownloadError(
            f"{pathlib.Path(command[0]).name} exited with {error.returncode}"
        ) from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise errors.CorpusDownloadError(
            f"{pathlib.Path(command[0]).name} failed: {type(error).__name__}"
        ) from error


def gh_download(
    gh: str,
    repo: str,
    tag: str,
    destination: pathlib.Path,
    run_command: CommandRunner = _run_command,
) -> None:
    """Download a release asset with `gh release download`.

    Args:
        gh: The path of the `gh` executable.
        repo: The repository, `owner/name`.
        tag: The release tag.
        destination: The file to write; its name is the asset name.
        run_command: Runs the command.

    Raises:
        CorpusDownloadError: `gh` fails or writes no file.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(
        tempfile.mkdtemp(prefix=".gh-", dir=destination.parent)
    )
    try:
        run_command(
            [
                gh,
                "release",
                "download",
                tag,
                "--repo",
                repo,
                "--pattern",
                destination.name,
                "--dir",
                str(staging),
            ]
        )
        fetched = staging / destination.name
        if not fetched.is_file():
            raise errors.CorpusDownloadError(
                f"gh wrote no {destination.name} for release {tag}"
            )
        os.replace(fetched, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@dataclasses.dataclass(frozen=True)
class Dependencies:
    """The outside world of the bootstrap, replaceable in tests.

    Attributes:
        embedder_factory: Loads the embedder; None loads the pinned model.
        transport: The httpx transport; None uses the network.
        resolver: Resolves a host name to IP addresses.
        run_command: Runs `gh`.
        environ: The environment to read `GH_TOKEN` from; None reads
            `os.environ`.
        which: Finds an executable on the PATH.
    """

    embedder_factory: indexer.EmbedderFactory | None = None
    transport: httpx.BaseTransport | None = None
    resolver: Resolver = resolve_host
    run_command: CommandRunner = _run_command
    environ: Mapping[str, str] | None = None
    which: Callable[[str], str | None] = shutil.which


def download_path(settings: config.Settings) -> pathlib.Path:
    """Return where a downloaded zip lands: next to the corpus directory.

    The image is read-only outside the volume, so the zip goes beside
    `corpus.dir` (`/data/corpus` on Railway), not to `corpus.zip`.

    Args:
        settings: The loaded settings.

    Returns:
        The path of the downloaded zip.
    """
    return settings.corpus.dir.parent / settings.corpus.zip.name


def corpus_present(corpus_dir: pathlib.Path) -> bool:
    """Tell whether the corpus directory holds filings.

    Args:
        corpus_dir: The corpus directory.

    Returns:
        True when it holds at least 1 `*.txt` file.
    """
    return corpus_dir.is_dir() and any(corpus_dir.glob("*.txt"))


def _fetch_zip(
    settings: config.Settings, state: BootstrapState, deps: Dependencies
) -> tuple[pathlib.Path, str]:
    """Find or download the corpus zip; return it and how it came."""
    if settings.corpus.zip.is_file():
        return settings.corpus.zip, "extracted"
    target = download_path(settings)
    if target.is_file():
        return target, "extracted"
    environ = os.environ if deps.environ is None else deps.environ
    repo = settings.corpus.release_repo
    gh = deps.which("gh")
    if environ.get("GH_TOKEN") and repo and gh:
        state.enter(
            Phase.DOWNLOADING,
            f"gh release download {settings.corpus.release_tag} from {repo}",
        )
        gh_download(
            gh, repo, settings.corpus.release_tag, target, deps.run_command
        )
        return target, "downloaded"
    url = settings.corpus.url
    if not url:
        raise errors.CorpusMissingError(
            f"no filings in {settings.corpus.dir}, no zip at "
            f"{settings.corpus.zip}, no GH_TOKEN with gh, and no corpus.url"
        )
    allowed = allowed_hosts(url)
    host = parse.urlsplit(url).hostname or ""
    state.enter(Phase.DOWNLOADING, f"downloading the corpus zip from {host}")
    download(
        url,
        target,
        allowed=allowed,
        resolver=deps.resolver,
        transport=deps.transport,
        progress=state.advance,
    )
    return target, "downloaded"


def _ensure_corpus(
    settings: config.Settings, state: BootstrapState, deps: Dependencies
) -> str:
    """Fill the corpus directory when it holds no filings."""
    corpus_dir = settings.corpus.dir
    if corpus_present(corpus_dir):
        logger.info("bootstrap: filings present in %s", corpus_dir)
        return "present"
    zip_path, action = _fetch_zip(settings, state, deps)
    state.enter(Phase.EXTRACTING, f"extracting {zip_path.name}")
    result = extractor.extract_zip(zip_path, corpus_dir)
    state.advance(result.file_count, result.file_count)
    return action


def _ensure_index(
    settings: config.Settings, state: BootstrapState, deps: Dependencies
) -> str:
    """Build the index when no `current` pointer exists."""
    index_dir = settings.index.dir
    if indexer.current_build(index_dir) is not None:
        logger.info("bootstrap: index present in %s", index_dir)
        return "present"
    factory = deps.embedder_factory or (
        lambda: numpy_dense.SentenceEmbedder.from_settings(settings)
    )
    state.enter(Phase.INDEXING, f"building the index in {index_dir}")
    indexer.build_index(
        settings,
        settings.corpus.dir,
        index_dir,
        factory,
        progress=state.advance,
    )
    return "built"


def run_bootstrap(
    settings: config.Settings,
    state: BootstrapState | None = None,
    deps: Dependencies | None = None,
) -> BootstrapStatus:
    """Make sure the corpus and the index exist; skip what is present.

    The routine never raises a Keel error: a failure moves the state to
    `failed` with the error, so a background thread cannot die silently.

    Args:
        settings: The loaded settings.
        state: The state to report to; None creates one.
        deps: The outside world; None uses the real one.

    Returns:
        The final status: `ready`, `failed`, or the status of a run that
        was already active on this state.
    """
    state = state or BootstrapState()
    deps = deps or Dependencies()
    if not state.begin():
        logger.info("bootstrap already running")
        return state.snapshot()
    try:
        state.update(corpus=_ensure_corpus(settings, state, deps))
        state.update(index=_ensure_index(settings, state, deps))
    except errors.KeelError as error:
        logger.error("bootstrap failed: %s: %s", type(error).__name__, error)
        state.update(
            phase=Phase.FAILED,
            detail="bootstrap failed",
            error=f"{type(error).__name__}: {error}",
            finished_at=_now(),
        )
        return state.snapshot()
    except BaseException as error:
        state.update(
            phase=Phase.FAILED,
            detail="bootstrap failed",
            error=type(error).__name__,
            finished_at=_now(),
        )
        raise
    state.update(
        phase=Phase.READY,
        detail="corpus and index ready",
        finished_at=_now(),
    )
    return state.snapshot()


def start_background(
    settings: config.Settings,
    state: BootstrapState,
    deps: Dependencies | None = None,
) -> threading.Thread:
    """Run the bootstrap in a daemon thread, for `keel serve --bootstrap`.

    The server starts first and answers `/api/health` at once; `/api/ready`
    reads `state.snapshot()` while the thread works.

    Args:
        settings: The loaded settings.
        state: The state the thread reports to.
        deps: The outside world; None uses the real one.

    Returns:
        The started thread.
    """
    thread = threading.Thread(
        target=run_bootstrap,
        args=(settings, state, deps),
        name="keel-bootstrap",
        daemon=True,
    )
    thread.start()
    return thread
