import socket

import pytest

from xiaomei_brain.tools.provider.webget import _is_private_url


def _dns_result(*addresses: str):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))
        for address in addresses
    ]


def test_domain_resolving_to_proxy_fake_ip_is_allowed(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_result("198.18.0.43"),
    )

    assert _is_private_url("https://arxiv.org/abs/2210.03629") is False


@pytest.mark.parametrize(
    "url",
    [
        "http://198.18.0.43/",
        "http://198.19.255.255/",
    ],
)
def test_literal_proxy_fake_ip_remains_blocked(url):
    assert _is_private_url(url) is True


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "172.16.0.8",
        "192.168.1.8",
        "169.254.169.254",
    ],
)
def test_domain_resolving_to_internal_address_remains_blocked(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_result(address),
    )

    assert _is_private_url("https://example.invalid/path") is True


def test_mixed_fake_ip_and_private_result_remains_blocked(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_result("198.18.0.43", "192.168.1.8"),
    )

    assert _is_private_url("https://example.invalid/path") is True


def test_public_domain_result_is_allowed(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_result("93.184.216.34"),
    )

    assert _is_private_url("https://example.com/") is False
