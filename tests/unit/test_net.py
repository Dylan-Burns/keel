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


def test_nat64_and_mapped_addresses_use_the_ipv4_part() -> None:
    assert not net.is_public_address("64:ff9b::a00:1")
    assert not net.is_public_address("::ffff:10.0.0.1")
    assert net.is_public_address("64:ff9b::5db8:d822")


def test_redact_text() -> None:
    text = 'HTTP Request: GET https://b.example.com/c.zip?X-Sig=abc "200"'
    assert net.redact_text(text) == (
        'HTTP Request: GET https://b.example.com/c.zip "200"'
    )
    assert net.redact_text("no url here") == "no url here"


def test_install_log_redaction(caplog: pytest.LogCaptureFixture) -> None:
    net.install_log_redaction()
    net.install_log_redaction()
    httpx_logger = logging.getLogger("httpx")
    filters = [
        f for f in httpx_logger.filters if isinstance(f, net.RedactQueryFilter)
    ]
    assert len(filters) == 1
    with caplog.at_level(logging.INFO):
        httpx_logger.info("GET %s", "https://b.example.com/c?sig=secret9")
        httpx_logger.info("plain %s", "line")
    assert "secret9" not in caplog.text
    assert "https://b.example.com/c" in caplog.text
    assert "plain line" in caplog.text
