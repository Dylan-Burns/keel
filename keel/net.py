"""Outbound request guards of control S-11, shared by every fetch.

`check_addresses` rejects a host that resolves to a private, loopback,
link-local, reserved, or multicast address before a request. A host can
answer the first lookup with a public address and the connect with a
private one (DNS rebinding), so `check_peer` reads the address of the
socket that httpx really opened and rejects the response before any body
byte is read. `redact_url` and `quiet_http_logs` keep the query string of a
signed URL out of the logs, and `install_log_redaction` strips the query
from the URLs httpx and httpcore log. The bootstrap download uses them; the
EDGAR client of chapter 26 can adopt the same calls.
"""

from __future__ import annotations

from collections.abc import Sequence
import ipaddress
import logging
import re
import threading
from urllib import parse

import httpx

from keel import errors

# The loggers of httpx and httpcore print the full request URL at INFO.
HTTP_LOGGERS = ("httpx", "httpcore")
# NAT64 maps an IPv4 address into IPv6; the embedded address decides.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def is_public_address(address: str) -> bool:
    """Tell whether an IP address is public.

    Args:
        address: An IPv4 or IPv6 address.

    Returns:
        True for a global unicast address; False for a private, loopback,
        link-local, reserved, multicast, or unparsable one.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


def check_addresses(host: str, addresses: Sequence[str]) -> None:
    """Reject a host unless every resolved address is public.

    Args:
        host: The host name, for the message.
        addresses: Its resolved addresses.

    Raises:
        HostNotAllowedError: No address, or 1 address that is not public.
    """
    if not addresses:
        raise errors.HostNotAllowedError(f"{host} resolves to no address")
    for address in addresses:
        if not is_public_address(address):
            raise errors.HostNotAllowedError(
                f"{host} resolves to a non-public address {address}"
            )


def peer_address(response: httpx.Response) -> str | None:
    """Return the IP address of the server socket behind a response.

    Args:
        response: A response whose headers have arrived.

    Returns:
        The peer address from httpcore's `network_stream`, or None when
        the transport exposes none.
    """
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    peer = stream.get_extra_info("server_addr")
    if isinstance(peer, tuple) and peer:
        return str(peer[0])
    if isinstance(peer, str):
        return peer
    return None


def check_peer(response: httpx.Response, host: str) -> str:
    """Reject a response unless its socket peer is a public address.

    Call it after the headers arrive and before reading the body. Only the
    request line and headers reached the peer by then.

    Args:
        response: The streamed response.
        host: The host name, for the message.

    Returns:
        The peer address.

    Raises:
        HostNotAllowedError: The peer address is unknown or not public.
    """
    address = peer_address(response)
    if address is None:
        raise errors.HostNotAllowedError(
            f"the connection to {host} exposes no peer address"
        )
    if not is_public_address(address):
        raise errors.HostNotAllowedError(
            f"{host} connected to a non-public address {address}"
        )
    return address


def redact_url(url: str | httpx.URL) -> str:
    """Return a URL without its query, fragment, and credentials.

    Args:
        url: The URL.

    Returns:
        `scheme://host[:port]/path`.
    """
    parts = parse.urlsplit(str(url))
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return f"{parts.scheme}://{host}{parts.path}"


_URL_QUERY = re.compile(r"(\bhttps?://[^\s?#\"'<>]*)[?#][^\s\"'<>]*")
_install_lock = threading.Lock()


def redact_text(text: str) -> str:
    """Remove the query and fragment of every URL in a text.

    Args:
        text: A log message.

    Returns:
        The text with each `?query` or `#fragment` of a URL cut off.
    """
    return _URL_QUERY.sub(r"\1", text)


class RedactQueryFilter(logging.Filter):
    """Strips URL queries from a log record before any handler sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the record message without URL queries.

        Args:
            record: The log record.

        Returns:
            True: the record is kept, redacted.
        """
        message = record.getMessage()
        redacted = redact_text(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def install_log_redaction() -> None:
    """Add 1 `RedactQueryFilter` to the httpx and httpcore loggers, once.

    Their lines carry the full request URL, query included. A filter, not
    a level change, so other clients keep their logs and threads cannot
    restore a level out of order.
    """
    with _install_lock:
        for name in HTTP_LOGGERS:
            target = logging.getLogger(name)
            if not any(
                isinstance(item, RedactQueryFilter) for item in target.filters
            ):
                target.addFilter(RedactQueryFilter())
