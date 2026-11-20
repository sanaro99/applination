"""Refuse to fetch URLs that point back into the server's own network.

The single-job wizard hands a user-typed URL to a headless browser running on
the API server. On a multi-user install, and above all through the public demo
login, that would let anyone make the server visit ``http://127.0.0.1:8000``,
the cloud metadata service at ``169.254.169.254``, a database on the private
network, or ``file:///proc/self/environ`` (which holds
``APPLINATION_SECRET_KEY``), and then read the result back as a "job
description".

:func:`assert_public_url` is the check. It is applied to the URL the user typed
*and* to every request the browser makes afterwards (redirects, frames,
scripts), because a public page can redirect to a private address.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeURL(ValueError):
    """The URL is not an ordinary public http(s) address."""


def private_fetch_allowed() -> bool:
    """Escape hatch for a single-user install on a trusted machine that really
    does need to extract a posting from an intranet page. Off by default."""
    return os.environ.get("ALLOW_PRIVATE_URL_FETCH", "").strip().lower() in {"1", "true", "yes"}


def _is_public_ip(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def assert_public_url(url: str) -> None:
    """Raise :class:`UnsafeURL` unless ``url`` is http(s) to a host whose every
    resolved address is publicly routable."""
    try:
        parts = urlsplit((url or "").strip())
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise UnsafeURL("That is not a valid URL.") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL("Only http and https job links can be fetched.")
    if not hostname:
        raise UnsafeURL("The URL has no host name.")
    if parts.username or parts.password:
        raise UnsafeURL("URLs with embedded credentials are not fetched.")
    if private_fetch_allowed():
        return
    try:
        infos = socket.getaddrinfo(hostname, port or (443 if parts.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeURL(f"Could not resolve {hostname}.") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_is_public_ip(a) for a in addresses):
        raise UnsafeURL("That address points to a private or local network and cannot be fetched.")


def is_public_url(url: str) -> bool:
    try:
        assert_public_url(url)
    except UnsafeURL:
        return False
    return True
