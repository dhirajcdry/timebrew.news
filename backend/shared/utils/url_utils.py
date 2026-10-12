"""Conservative public-news URL helpers.

DNS is only a reachability check, never proof an article exists or supports a
claim. Provider citation provenance is checked separately in ``provenance``.
No filter is allowed to restore rejected links to fill a briefing.
"""
import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_SECTION_NAMES = {
    "news", "business", "technology", "tech", "science", "politics", "world",
    "economy", "economics", "markets", "finance", "health", "sports", "culture",
    "entertainment", "opinion", "lifestyle", "travel", "education", "environment",
    "climate", "space", "startups", "innovation", "newsroom", "latest",
}
_COLLECTION_PREFIXES = {"category", "categories", "topic", "topics", "tag", "tags", "search"}


def safe_article_url(value):
    """Return a normalized public HTTP(S) URL, or None (without network I/O).

    This is a link-policy check, not an SSRF-safe HTTP fetching primitive. Any
    future fetcher must also validate resolved IPs and every redirect.
    """
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    if re.search(r"[\s\\\x00-\x1f\x7f<>\"']|%(?:0[0-9a-f]|1[0-9a-f]|7f)", value, re.IGNORECASE):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or parts.username or parts.password:
            return None
        host = parts.hostname
        if not host or parts.port not in (None, 80, 443):
            return None
        host = host.encode("idna").decode("ascii").lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
            return None
        # News sources are named public hosts, never IP literals or numeric aliases.
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        labels = host.split(".")
        if len(labels) < 2 or labels[-1].isdigit() or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        ):
            return None
        scheme = parts.scheme.lower()
        port = parts.port
        authority = host if port is None or (scheme, port) in {("https", 443), ("http", 80)} else f"{host}:{port}"
        return urlunsplit((scheme, authority, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError):
        return None


def canonical_article_url(value):
    """Identity URL: preserve meaningful query parameters, remove trackers."""
    safe = safe_article_url(value)
    if not safe:
        return None
    parts = urlsplit(safe)
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(query)), ""))


def is_collection_url(value):
    """Identify obvious publisher indexes that cannot be a full-story link.

    This deliberately narrow URL-shape gate rejects home/section/topic pages,
    even when a provider cites them. It does not prove other URLs are articles
    or that their content supports a claim; that requires fetching the page.
    Preserve common CMS article identity queries, including CMS installations
    beneath a section path. Collection prefixes alone cannot disqualify deeper
    article paths that happen to live within the publisher's category hierarchy.
    """
    canonical = canonical_article_url(value)
    if not canonical:
        return True
    parts = urlsplit(canonical)
    segments = [segment for segment in unquote(parts.path).lower().split("/") if segment]
    article_query = any(
        (key.lower() == "p" and val.isdigit()) or
        (key.lower() in {"article_id", "story_id"} and re.fullmatch(r"[\w-]+", val))
        for key, val in parse_qsl(parts.query)
    )
    if article_query:
        return False
    if not segments or segments in (["index.html"], ["index.htm"], ["index.php"]):
        return True
    return (len(segments) <= 2 and segments[0] in _COLLECTION_PREFIXES) or all(
        segment in _SECTION_NAMES for segment in segments
    )


def url_host_resolves(url, timeout=5):
    """Whether a safe URL resolves exclusively to public IPs.

    ``timeout`` is retained for caller compatibility. The OS resolver controls
    individual DNS calls; the batch filter bounds its wait without changing the
    process-wide socket timeout (which is unsafe under concurrent Lambda work).
    """
    safe = safe_article_url(url)
    if not safe:
        return False
    try:
        addresses = socket.getaddrinfo(urlsplit(safe).hostname, None)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (ValueError, socket.gaierror, socket.herror, OSError):
        return False


def filter_live_article_urls(articles, min_keep=1, timeout=5):
    """Return (kept, rejected), never reinstating rejected or timed-out URLs.

    Historical ``min_keep`` is ignored: a quota cannot bypass a safety check.
    DNS success does not establish HTTP liveness or article provenance.
    """
    if not articles:
        return [], []
    executor = ThreadPoolExecutor(max_workers=min(8, len(articles)))
    futures = [executor.submit(url_host_resolves, a.get("url"), timeout)
               if isinstance(a, dict) else None for a in articles]
    completed, _ = wait([f for f in futures if f is not None], timeout=timeout)
    good = []
    for future in futures:
        try:
            good.append(future in completed and bool(future.result()))
        except Exception:
            good.append(False)
    executor.shutdown(wait=False, cancel_futures=True)
    return ([a for a, ok in zip(articles, good) if ok],
            [a for a, ok in zip(articles, good) if not ok])
