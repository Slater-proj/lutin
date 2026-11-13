"""Outbound web requests that cannot be turned against the local network (see docs/adr/0008-outbound-web-guard.md).

The web tools fetch addresses chosen by a model that has just read an untrusted page. Checking the host name before the request is not enough:

- the HTTP library resolves the name again when it connects, so a DNS answer that changes between the check and the connection (« rebinding »)
  reaches an internal service. Here the name is resolved ONCE, by the connection itself, and the socket is opened to the address that was checked;
- a redirection used to be followed before its target was checked: the internal service received the request (a blind request, but a request).
  Here redirections are never followed by the library: every hop goes through the caller's `check` before anything is sent;
- headers given for one host (an API key) are not carried to another host by a redirection.

Standard library only. This module knows nothing about Lutin: `lutin.web` supplies the checks and turns the errors into messages.
"""
from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

REDIRECTIONS = (301, 302, 303, 307, 308)
MAX_REDIRECTIONS = 5
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class ForbiddenAddress(Exception):
    """The host resolves to an address that is not on the public internet. Not an OSError: urllib would wrap it into a network failure and retry."""

    def __init__(self, host):
        super().__init__(host)
        self.host = host


class UnknownHost(Exception):
    def __init__(self, host):
        super().__init__(host)
        self.host = host


class TooManyRedirections(Exception):
    pass


def local_test_mode():
    """Tests reach fake services on 127.0.0.1. The switch needs BOTH variables: LUTIN_TESTS is set by tests/context.py only,
    so LUTIN_WEB_LOCAL left in a shell profile or a compose file no longer switches the guard off."""
    return os.environ.get("LUTIN_WEB_LOCAL") == "1" and os.environ.get("LUTIN_TESTS") == "1"


def forbidden_address(text):
    """True unless the address is a public internet address. Refused: loopback, private ranges, link-local, carrier-grade NAT (100.64.0.0/10, which is
    also where Tailscale puts its machines), multicast, reserved and unspecified addresses, and IPv6 forms that carry one of those IPv4 addresses."""
    ip = ipaddress.ip_address(str(text).split("%")[0])
    if ip.version == 6:
        embedded = ip.ipv4_mapped or (ip.sixtofour if ip.sixtofour else None) or (ip.teredo[1] if ip.teredo else None)
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            return forbidden_address(embedded)
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified or not ip.is_global)


def resolve_checked(host, port, allowed_host=None):
    """The addresses of `host`, all of them public (or the host is the one local host the user configured himself). One refused address refuses the host:
    a name that answers both a public and an internal address is not to be trusted."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise UnknownHost(host) from None
    if not (allowed_host and str(host).lower() == str(allowed_host).lower()):
        for info in infos:
            if forbidden_address(info[4][0]):
                raise ForbiddenAddress(host)
    return infos


def connect_checked(host, port, timeout=None, allowed_host=None):
    """A connected socket to an address of `host` that has just been checked: the address checked IS the address connected."""
    last = None
    for family, kind, proto, _, address in resolve_checked(host, port, allowed_host):
        sock = None
        try:
            sock = socket.socket(family, kind, proto)
            if isinstance(timeout, (int, float)):
                sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError as error:
            last = error
            if sock is not None:
                sock.close()
    raise last or OSError("no address for " + str(host))


class _GuardedHTTPConnection(http.client.HTTPConnection):
    allowed_host = None

    def connect(self):
        self.sock = connect_checked(self.host, self.port, self.timeout, self.allowed_host)


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    allowed_host = None

    def __init__(self, *args, **kwargs):
        self._guard_context = kwargs.get("context") or ssl.create_default_context()
        kwargs["context"] = self._guard_context
        super().__init__(*args, **kwargs)

    def connect(self):
        sock = connect_checked(self.host, self.port, self.timeout, self.allowed_host)
        self.sock = self._guard_context.wrap_socket(sock, server_hostname=self.host)          # the certificate is checked against the NAME, as usual


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, allowed_host):
        super().__init__()
        self._connection = type("GuardedHTTPConnection", (_GuardedHTTPConnection,), {"allowed_host": allowed_host})

    def http_open(self, req):
        return self.do_open(self._connection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allowed_host):
        super().__init__()
        self._connection = type("GuardedHTTPSConnection", (_GuardedHTTPSConnection,), {"allowed_host": allowed_host})

    def https_open(self, req):
        return self.do_open(self._connection, req)


class _NoRedirection(urllib.request.HTTPRedirectHandler):
    """The library never follows a redirection by itself: `open_following` does, one checked hop at a time."""

    def redirect_request(self, *args, **kwargs):
        return None


def uses_proxy(url):
    """True when the system sends this request through a proxy. The proxy then resolves the name: the address cannot be pinned from here."""
    parts = urllib.parse.urlsplit(url)
    try:
        return parts.scheme in urllib.request.getproxies() and not urllib.request.proxy_bypass(parts.hostname or "")
    except (OSError, ValueError):
        return False


def build_opener(allowed_host=None, pinned=True):
    """An opener that follows no redirection. `pinned`: connections go straight to an address checked at connection time (no proxy).
    Not pinned (a system proxy, or the tests' local mode): the standard connections, the caller's `check` being then the only guard."""
    if not pinned:
        return urllib.request.build_opener(_NoRedirection())
    return urllib.request.build_opener(_NoRedirection(), urllib.request.ProxyHandler({}), _GuardedHTTPHandler(allowed_host), _GuardedHTTPSHandler(allowed_host))


def open_following(url, *, check, data=None, headers=None, private_headers=None, timeout=15, allowed_host=None, pinned=True, opener=None):
    """Opens `url`, following redirections one hop at a time. `check(url)` is called before EVERY request, the first and each redirection target:
    it raises to refuse (wrong scheme, offline mode, local address). Returns the response; its `geturl()` is the final address.

    `headers` go to every host; `private_headers` (API keys) only as long as the host is the one first asked.
    As in the standard library: 301/302/303 turn a POST into a GET, and a POST is not replayed on 307/308."""
    opener = opener or build_opener(allowed_host, pinned)
    first_host = (urllib.parse.urlsplit(url).hostname or "").lower()
    for _ in range(MAX_REDIRECTIONS + 1):
        check(url)
        sent = dict(headers or {})
        if (urllib.parse.urlsplit(url).hostname or "").lower() == first_host:
            sent.update(private_headers or {})
        try:
            return opener.open(urllib.request.Request(url, data=data, headers=sent), timeout=timeout)
        except urllib.error.HTTPError as error:
            target = error.headers.get("Location") if error.headers else None
            if error.code not in REDIRECTIONS or not target or (data is not None and error.code in (307, 308)):
                raise
            error.close()
            url, data = urllib.parse.urljoin(url, target), None
    raise TooManyRedirections(url)
