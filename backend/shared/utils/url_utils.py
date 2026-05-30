"""URL validation helpers (stdlib-only, Lambda-safe — no extra requirements).

We deliberately validate URLs by DNS resolution of their host, NOT by fetching
them. An HTTP fetch from inside Lambda is unreliable as a liveness signal: major
publishers (TechCrunch, Bloomberg, Guardian, …) time out or block AWS egress IPs,
and many serve soft-404s (HTTP 200 on a missing page). Both produce false signals.
DNS resolution, by contrast, is fast, isn't bot-blocked, and cleanly catches the
dominant hallucination failure mode — an invented domain that doesn't exist
(NXDOMAIN) — without dropping real articles that merely reject our user-agent.
"""
import socket
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor


def url_host_resolves(url, timeout=5):
    """True if the URL is well-formed and its host resolves in DNS.

    A real article on a real publisher resolves even if the page 404s or blocks
    bots; a hallucinated domain raises NXDOMAIN (socket.gaierror) -> False.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        host = urlparse(url).hostname
    except Exception:
        return False
    if not host:
        return False
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        socket.getaddrinfo(host, None)
        return True
    except (socket.gaierror, socket.herror, OSError):
        return False
    finally:
        socket.setdefaulttimeout(old)


def filter_live_article_urls(articles, min_keep=1, timeout=5):
    """Drop articles whose URL host doesn't resolve (likely hallucinated domain).

    Resolves hosts concurrently. Has a safety floor: if filtering would leave
    fewer than `min_keep` articles but we started with some, the original list is
    kept unchanged — a possibly-stale link beats an empty briefing on a false
    negative.

    Returns (kept_articles, dropped_articles).
    """
    if not articles:
        return articles, []

    urls = [a.get("url") for a in articles]
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as ex:
        ok = list(ex.map(lambda u: url_host_resolves(u, timeout), urls))

    kept = [a for a, good in zip(articles, ok) if good]
    dropped = [a for a, good in zip(articles, ok) if not good]

    if len(kept) < min_keep and articles:
        # Don't trust the filter to empty out an otherwise-good run.
        return articles, []

    return kept, dropped
