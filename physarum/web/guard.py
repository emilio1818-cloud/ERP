"""Who may talk to the firm's ERP.

Physarum runs on the firm's own computer. Two things protect it from web pages the same
person has open in another tab:

* Host check: a page from evil.example that re-binds its domain to 127.0.0.1 still sends
  "Host: evil.example" and is refused (no download of the backup, no peek at records).
* Origin check: a form or script on another site cannot change anything here; every
  writing request must come from a page of Physarum itself (Origin/Referer, Sec-Fetch-Site).
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

LOCAL = {"localhost", "127.0.0.1", "::1", "testserver"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host_only(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _is_ip(h: str) -> bool:
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


# no foreign page may frame Physarum (a click there would be a click here), no inline script runs,
# nothing is loaded from elsewhere
SECURITY_HEADERS = [
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                 b"img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; "
                                 b"frame-ancestors 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
]


class Guard:
    def __init__(self, app, allowed: set[str] | None = None, any_ip: bool = False):
        self.app = app
        self.allowed = {h.lower() for h in (allowed or set())} | LOCAL
        self.any_ip = any_ip  # when serving the local network, its IP addresses are fine

    def host_ok(self, host: str) -> bool:
        h = _host_only(host)
        return h in self.allowed or (self.any_ip and _is_ip(h))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        if not self.host_ok(host):
            return await _refuse(send, 421, "Unbekannter Rechnername. Physarum bitte über http://127.0.0.1 öffnen.")
        if scope.get("method", "GET") not in SAFE_METHODS:
            src = headers.get("origin") or headers.get("referer")
            if src and src != "null":
                if urlsplit(src).netloc.lower() != host.lower():
                    return await _refuse(send, 403, "Diese Änderung kam nicht von einer Physarum-Seite und wurde abgelehnt.")
            elif src == "null" or headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
                return await _refuse(send, 403, "Diese Änderung kam nicht von einer Physarum-Seite und wurde abgelehnt.")
        async def send_secure(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message = dict(message, headers=list(message.get("headers", [])) +
                               [(k, v) for k, v in SECURITY_HEADERS if k not in present])
            await send(message)
        return await self.app(scope, receive, send_secure)


async def _refuse(send, status: int, text: str):
    body = text.encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
