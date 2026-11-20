"""The single-job extractor drives a headless browser on the API server, so a
user-typed URL must never reach the server's own network or filesystem."""
from __future__ import annotations

import socket

import pytest

from src.url_safety import UnsafeURL, assert_public_url, is_public_url


def _resolves_to(monkeypatch, *addresses: str) -> None:
    def fake(host, port, *a, **kw):  # noqa: ANN001
        return [(socket.AF_INET6 if ":" in a_ else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a_, port))
                for a_ in addresses]
    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.mark.parametrize("url", [
    "file:///proc/self/environ",
    "ftp://example.com/job",
    "javascript:alert(1)",
    "http://user:pass@example.com/job",
    "https:///nohost",
    "",
])
def test_non_web_urls_are_refused(url):
    with pytest.raises(UnsafeURL):
        assert_public_url(url)


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.10", "169.254.169.254",
    "0.0.0.0", "100.64.0.1", "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1",
])
def test_private_addresses_are_refused(monkeypatch, address):
    _resolves_to(monkeypatch, address)
    assert not is_public_url("https://jobs.example.com/123")


def test_a_host_with_any_private_address_is_refused(monkeypatch):
    _resolves_to(monkeypatch, "93.184.216.34", "10.0.0.1")
    assert not is_public_url("https://jobs.example.com/123")


def test_public_addresses_are_allowed(monkeypatch):
    _resolves_to(monkeypatch, "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")
    assert_public_url("https://boards.greenhouse.io/acme/jobs/1")


def test_the_escape_hatch_allows_private_hosts(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_URL_FETCH", "1")
    _resolves_to(monkeypatch, "127.0.0.1")
    assert_public_url("http://localhost:8080/job")
    with pytest.raises(UnsafeURL):
        assert_public_url("file:///etc/passwd")


def test_extract_endpoint_rejects_internal_urls(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server.db as db
    from .conftest import make_engine, register

    monkeypatch.setattr(db, "engine", make_engine(tmp_path))
    from server.app import app

    with TestClient(app) as client:
        register(client, "user@example.com")
        for url in ("http://127.0.0.1:8000/api/secrets", "file:///proc/self/environ",
                    "http://169.254.169.254/latest/meta-data/"):
            res = client.post("/api/single-job/extract", json={"url": url})
            assert res.status_code == 400, (url, res.text)
