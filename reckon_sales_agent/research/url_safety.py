"""SSRF-safe fetching of public web pages (pure: no Frappe imports).

* Only http/https on standard ports, no credentials in URLs.
* The hostname is resolved here; every address must be public (no loopback,
  private, link-local, carrier-grade NAT, reserved, multicast or metadata).
* The connection is made to the exact IP that was checked, with the hostname
  kept for TLS verification (SNI + certificate check), so DNS rebinding cannot
  swap in an internal address between check and connect.
* Redirects are followed manually and every hop is validated again.
* Response size, time, redirect count and content type are bounded.
* Downloaded content is never executed; callers treat it as untrusted text.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import certifi
import urllib3

ALLOWED_SCHEMES = {"http": 80, "https": 443}
ALLOWED_PORTS = {80, 443, 8080, 8443}
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata"}
METADATA_ADDRESSES = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}
CGNAT = ipaddress.ip_network("100.64.0.0/10")


class UnsafeURL(ValueError):
    pass


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    text: str
    truncated: bool


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip in METADATA_ADDRESSES or (isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT):
        return False
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified or not ip.is_global
    )


def resolve(host: str, port: int, resolver=socket.getaddrinfo) -> list[str]:
    try:
        infos = resolver(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeURL(f"Cannot resolve {host}") from exc
    return sorted({info[4][0] for info in infos})


def validate_url(url: str, resolver=socket.getaddrinfo) -> tuple[str, str, int, str]:
    """(scheme, host, port, ip) for a URL that is safe to fetch, else UnsafeURL."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise UnsafeURL("Malformed URL") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL("Only http and https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeURL("URLs with credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host or host in BLOCKED_HOSTNAMES or host.endswith((".local", ".internal", ".localhost")):
        raise UnsafeURL("Host is not public")
    port = port or ALLOWED_SCHEMES[scheme]
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("Port is not allowed")
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    addresses = [host] if literal else resolve(host, port, resolver)
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise UnsafeURL("Host resolves to a non-public address")
    return scheme, host, port, addresses[0]


def fetch(url: str, *, user_agent: str, timeout: float = 10.0, max_bytes: int = 1_048_576,
          max_redirects: int = 3, resolver=socket.getaddrinfo, pool_factory=None) -> FetchResult:
    """GET a public page with every safety check above applied."""
    deadline = time.monotonic() + timeout
    current = url
    for _hop in range(max_redirects + 1):
        scheme, host, port, ip = validate_url(current, resolver)
        parts = urlsplit(current)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        host_header = host if port == ALLOWED_SCHEMES[scheme] else f"{host}:{port}"
        remaining = max(deadline - time.monotonic(), 0.5)
        pool = (pool_factory or _pool)(scheme, ip, port, host, remaining)
        try:
            response = pool.urlopen(
                "GET", path,
                headers={"Host": host_header, "User-Agent": user_agent,
                         "Accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.5",
                         "Accept-Language": "en,bn;q=0.8"},
                redirect=False, retries=False, preload_content=False,
            )
        except urllib3.exceptions.HTTPError as exc:
            raise FetchError(f"Connection failed: {type(exc).__name__}") from exc
        try:
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise FetchError("Redirect without a location")
                current = urljoin(current, location)
                continue
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if response.status >= 400:
                raise FetchError(f"HTTP {response.status}")
            if content_type and not content_type.startswith(ALLOWED_CONTENT_TYPES):
                raise FetchError(f"Content type {content_type} is not a web page")
            body, truncated = _read_limited(response, max_bytes, deadline)
            charset = _charset(response.headers.get("Content-Type") or "")
            return FetchResult(current, response.status, content_type, body.decode(charset, "replace"), truncated)
        finally:
            response.release_conn()
    raise FetchError("Too many redirects")


def _read_limited(response, max_bytes: int, deadline: float) -> tuple[bytes, bool]:
    chunks, size = [], 0
    while True:
        if time.monotonic() > deadline:
            raise FetchError("Timed out")
        chunk = response.read(16_384)
        if not chunk:
            return b"".join(chunks), False
        size += len(chunk)
        if size > max_bytes:
            chunks.append(chunk[: len(chunk) - (size - max_bytes)])
            return b"".join(chunks), True
        chunks.append(chunk)


def _charset(content_type: str) -> str:
    for part in content_type.split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            try:
                "".encode(value.strip('"'))
                return value.strip('"')
            except LookupError:
                break
    return "utf-8"


def _pool(scheme: str, ip: str, port: int, host: str, timeout: float):
    t = urllib3.Timeout(connect=min(5.0, timeout), read=timeout)
    if scheme == "https":
        return urllib3.HTTPSConnectionPool(
            ip, port=port, server_hostname=host, assert_hostname=host,
            cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(), timeout=t, maxsize=1,
        )
    return urllib3.HTTPConnectionPool(ip, port=port, timeout=t, maxsize=1)
