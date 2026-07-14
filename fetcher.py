"""
Page fetching + HTML cleaning for the evidence pipeline.

Security: user-supplied URLs are fetched server-side, so every request —
including each redirect hop — is guarded against SSRF: http/https only,
and the hostname must not resolve to private/loopback/link-local/reserved
address space.
"""

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

MAX_HTML_CHARS = 80_000

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


class _Stripper(HTMLParser):
    """Drops <script>/<style> bodies but keeps tags + attributes so the model
    can reason about structure (nav, headings, alt text, aria, forms)."""

    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attr_str = "".join(
            f' {k}="{v}"' for k, v in attrs
            if k in ("href", "alt", "aria-label", "role", "type", "name",
                     "placeholder", "id", "class", "title", "lang", "label")
        )
        self.parts.append(f"<{tag}{attr_str}>")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def result(self):
        cleaned = " ".join(self.parts)
        return re.sub(r"\s+", " ", cleaned).strip()


def normalize_url(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("No URL provided.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


def _assert_public_host(url: str) -> None:
    """SSRF guard: scheme http/https and ALL resolved addresses public."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http(s) URLs can be evaluated.")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValueError(f"Could not resolve host: {host}")
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise ValueError("That address is not publicly reachable.")


async def fetch_page(url):
    """Return (cleaned_html, title) for a public page. Every redirect hop is
    re-checked by the SSRF guard via the request event hook."""
    _assert_public_host(url)

    async def _guard(request):
        _assert_public_host(str(request.url))

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=25, headers=FETCH_HEADERS,
            event_hooks={"request": [_guard]},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Could not fetch page (HTTP {e.response.status_code}).")
    except httpx.RequestError as e:
        raise ValueError(f"Could not reach the site ({e}).")

    html = resp.text
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html,
                            re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""

    stripper = _Stripper()
    try:
        stripper.feed(html)
    except Exception:
        pass
    cleaned = stripper.result()
    if len(cleaned) > MAX_HTML_CHARS:
        cleaned = cleaned[:MAX_HTML_CHARS] + " …[truncated]"
    return cleaned, title
