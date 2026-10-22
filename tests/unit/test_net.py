"""Tests for the shared S-11 request guards."""

import logging

import httpx
import pytest

import conftest
from keel import errors
from keel import net

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:4700::1111", True),
        ("10.1.2.3", False),
        ("192.168.0.1", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("::1", False),
        ("fe80::1%en0", False),
        ("224.0.0.1", False),
        ("not an address", False),
    ],
)
def test_is_public_address(address: str, public: bool) -> None:
    assert net.is_public_address(address) is public


def test_check_addresses() -> None:
    net.check_addresses("h", ["93.184.216.34"])
    with pytest.raises(errors.HostNotAllowedError, match="no address"):
        net.check_addresses("h", [])
    with pytest.raises(errors.HostNotAllowedError, match="non-public"):
        net.check_addresses("h", ["93.184.216.34", "10.0.0.1"])


class StringPeer:
    def __init__(self, value: object) -> None:
        self.value = value

    def get_extra_info(self, info: str) -> object:
        return self.value


def test_peer_address_shapes() -> None:
    assert net.peer_address(httpx.Response(200)) is None
    assert net.peer_address(conftest.with_peer(httpx.Response(200))) == (
        conftest.PUBLIC_IP
    )
    response = httpx.Response(200)
    response.extensions["network_stream"] = StringPeer("8.8.8.8")
    assert net.peer_address(response) == "8.8.8.8"
    response.extensions["network_stream"] = StringPeer(None)
    assert net.peer_address(response) is None


def test_check_peer() -> None:
    ok = conftest.with_peer(httpx.Response(200))
    assert net.check_peer(ok, "h") == conftest.PUBLIC_IP
    bad = conftest.with_peer(httpx.Response(200), "192.168.1.1")
    with pytest.raises(errors.HostNotAllowedError, match="non-public"):
        net.check_peer(bad, "h")


def test_redact_url() -> None:
    url = "https://user:pw@b.example.com:8443/a/c.zip?X-Sig=abc#frag"
    assert net.redact_url(url) == "https://b.example.com:8443/a/c.zip"
    assert net.redact_url(httpx.URL("https://b.example.com/c?s=1")) == (
        "https://b.example.com/c"
    )


def test_quiet_http_logs_restores_levels() -> None:
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.DEBUG)
    try:
        with net.quiet_http_logs():
            assert httpx_logger.level == logging.WARNING
            assert logging.getLogger("httpcore").level == logging.WARNING
        assert httpx_logger.level == logging.DEBUG
    finally:
        httpx_logger.setLevel(logging.NOTSET)
