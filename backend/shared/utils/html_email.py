"""HTML email safety helpers (stdlib only).

LLM-generated and user-controlled values (brew names, article content, source
names, URLs, Cognito given_name, etc.) are interpolated into outbound HTML
emails. Without escaping, those values can inject arbitrary HTML/markup, and raw
URLs placed into `href` attributes can carry dangerous schemes
(e.g. `javascript:`, `data:`). These helpers prevent HTML/link injection from
LLM/user content in emails:

- `esc(value)` HTML-escapes a value for both text and attribute contexts.
- `safe_href(url)` allows a URL into an `href` only if its scheme is
  http or https; otherwise returns an empty string.
"""

import html
from urllib.parse import urlparse


def esc(value):
    """Escape a value for safe use in HTML text and attribute contexts."""
    return html.escape(str(value or ""), quote=True)


def safe_href(url):
    """Return the URL only if it is an http/https URL, else an empty string.

    Strips surrounding whitespace and treats None, "", and "null" as empty.
    Rejects any other scheme (e.g. javascript:, data:) to prevent link
    injection from LLM/user-supplied content.
    """
    if not url or not isinstance(url, str):
        return ""
    candidate = url.strip()
    if not candidate or candidate.lower() == "null":
        return ""
    try:
        scheme = urlparse(candidate).scheme
    except ValueError:
        return ""
    if scheme in ("http", "https"):
        # Escape so the URL is safe to drop directly into an href attribute
        # (prevents attribute breakout via a stray quote).
        return html.escape(candidate, quote=True)
    return ""
