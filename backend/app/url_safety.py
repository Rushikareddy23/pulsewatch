"""SSRF protection: users choose the URLs our servers request, so block internal targets.

`resolve_target` resolves the host ONCE, checks every address, and returns the address the
checker must connect to. Connecting to that exact IP (with the original Host header and TLS
SNI) closes the DNS-rebinding gap between "validate" and "connect"."""
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


class UnsafeURL(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedTarget:
    connect_url: str   # URL with the host replaced by a validated IP
    host: str          # original hostname: sent as Host header and TLS SNI / cert check
    ip: str


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified)


def resolve_host(host: str) -> list[str]:
    return list(dict.fromkeys(i[4][0] for i in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)))


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _check_syntax(url: str):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Only http and https URLs are allowed")
    if not parts.hostname:
        raise UnsafeURL("URL must include a host")
    if parts.username or parts.password:
        raise UnsafeURL("Credentials in URLs are not allowed")
    return parts


def resolve_target(url: str, allow_private: bool = False) -> ResolvedTarget:
    parts = _check_syntax(url)
    host = parts.hostname
    try:
        ips = [host] if _looks_like_ip(host) else resolve_host(host)
    except socket.gaierror:
        raise UnsafeURL("Host does not resolve")
    if not ips:
        raise UnsafeURL("Host does not resolve")
    if not allow_private and not all(_is_public(ip) for ip in ips):
        raise UnsafeURL("URL points to a private or internal address")
    ip = ips[0]
    netloc = f"[{ip}]" if ":" in ip else ip
    if parts.port:
        netloc += f":{parts.port}"
    return ResolvedTarget(urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), host, ip)


def validate_target(url: str, allow_private: bool = False) -> str:
    """Used when a monitor is created: raises UnsafeURL, returns the URL unchanged."""
    resolve_target(url, allow_private)
    return url
