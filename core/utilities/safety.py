# core/utilities/safety.py
"""
URL safety + SSRF protection for !xray and any utility that fetches a URL.

Blocks localhost, private/loopback/link-local/metadata ranges, non-http(s)
schemes, and file URLs. Pure-stdlib so it always works.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "dict", "ssh", "telnet"}
ALLOWED_SCHEMES = {"http", "https"}

# cloud metadata + obvious internal hosts
BLOCKED_HOSTS = {
    "localhost", "metadata.google.internal", "metadata", "instance-data",
}


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or
        ip.is_multicast or ip.is_reserved or ip.is_unspecified or
        # cloud metadata endpoint
        ip_str == "169.254.169.254"
    )


def is_safe_url(url: str, resolve_dns: bool = True) -> tuple[bool, str]:
    """Return (safe, reason). reason is '' when safe."""
    if not url or len(url) > 2048:
        return False, "missing or overlong URL"
    try:
        p = urlparse(url.strip())
    except Exception:
        return False, "unparseable URL"

    scheme = (p.scheme or "").lower()
    if scheme in BLOCKED_SCHEMES or scheme not in ALLOWED_SCHEMES:
        return False, "only http/https links are allowed"

    host = (p.hostname or "").lower()
    if not host:
        return False, "no host in URL"
    if host in BLOCKED_HOSTS:
        return False, "internal host blocked"

    # direct IP literal?
    if _is_private_ip(host):
        return False, "private/loopback address blocked"

    # resolve DNS and check every resolved address (DNS-rebinding guard)
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, None)
        except Exception:
            return False, "could not resolve host"
        for info in infos:
            addr = info[4][0]
            if _is_private_ip(addr):
                return False, "resolves to a private address"

    return True, ""


def canonicalize_url(url: str) -> str:
    """Light canonicalization for dedup: strip fragments + common tracking params."""
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        s = urlsplit(url.strip())
        drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                "utm_content", "igshid", "fbclid", "gclid", "si", "feature"}
        q = [(k, v) for k, v in parse_qsl(s.query) if k.lower() not in drop]
        return urlunsplit((s.scheme.lower(), s.netloc.lower(), s.path,
                           urlencode(q), ""))
    except Exception:
        return url.strip()
