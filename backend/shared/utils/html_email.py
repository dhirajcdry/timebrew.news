"""Safe, dependency-free TimeBrew email rendering.

All publisher/model/user text is untrusted. Only the small formatting vocabulary
below becomes markup; links come from validated HTTP(S) article URLs. Rendering
never performs network requests. Dispatch performs the separate provenance gate.
"""

import html
import math
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from shared.utils.url_utils import safe_article_url


EMPTY_TITLE = "A quieter brew today."
EMPTY_MESSAGE = (
    "We couldn't prepare a source-backed briefing this time. "
    "There's no news roundup in this edition."
)
DISCLOSURE = "Prepared with AI. Original reporting is linked with each story."


def esc(value):
    """Escape a value for HTML text and quoted attribute contexts."""
    return html.escape(str(value or ""), quote=True)


def safe_url(url):
    """Return a safe public source URL, without making any network requests.

    Share the curator's link policy so anything admitted for delivery remains
    clickable. This checks URL structure, not article existence or factuality.
    """
    if not isinstance(url, str):
        return ""
    candidate = url.strip()
    if re.search(r'[<>"\\]', candidate) or re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f)", candidate, re.I):
        return ""
    return safe_article_url(candidate) or ""


def safe_href(url):
    """Return a safe, HTML-escaped link destination, or an empty string."""
    return esc(safe_url(url))


def source_domain(url):
    """Derive the visible destination from the actual safe link, never AI text."""
    clean = safe_url(url)
    if not clean:
        return ""
    host = urlsplit(clean).hostname.lower()
    return host[4:] if host.startswith("www.") else host


def plain_text(value):
    """Readable text for MIME/plain and restrained inline Markdown support.

    Embedded Markdown links become labels: the sole clickable destination for
    an article is its source link. Raw HTML is left as text, never interpreted.
    """
    text = value if isinstance(value, str) else ""
    text = re.sub(r"!?\[([^\]\n]+)\]\([^\)\n]*\)", r"\1", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__", lambda m: m[1] or m[2], text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return text.strip()


def _inline(value):
    text = value if isinstance(value, str) else ""
    text = re.sub(r"!?\[([^\]\n]+)\]\([^\)\n]*\)", r"\1", text)
    text = esc(text)
    text = re.sub(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__", lambda m: "<strong>" + (m[1] or m[2]) + "</strong>", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return text


def _paragraphs(value):
    text = value if isinstance(value, str) else ""
    blocks = re.split(r"\n\s*\n", text.strip())
    return "".join(
        '<p style="margin:0 0 14px;font-size:16px;line-height:1.75;color:#443b33;overflow-wrap:anywhere;">'
        + _inline(block).replace("\n", "<br>") + "</p>"
        for block in blocks if block.strip()
    )


def publication_date(article, current_time):
    """Absolute, stable source dates; never turn 'yesterday' into a guessed date."""
    raw = article.get("published_at") or article.get("published_time")
    if not isinstance(raw, str):
        return "Publication date unavailable"
    raw = raw.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            published = date.fromisoformat(raw)
        elif re.match(r"^\d{4}-\d{2}-\d{2}T", raw):
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return "Publication date unavailable"
            published = parsed.astimezone(current_time.tzinfo or timezone.utc).date()
        else:
            return "Publication date unavailable"
    except ValueError:
        return "Publication date unavailable"
    return f"{published.strftime('%b')} {published.day}, {published.year}"


def _draft_parts(editor_draft):
    if not isinstance(editor_draft, dict) or not isinstance(editor_draft.get("articles"), list):
        raise ValueError("Email draft must be an object with an articles array")
    articles = editor_draft["articles"]
    if any(not isinstance(article, dict) for article in articles):
        raise ValueError("Each email article must be an object")
    return articles


def _issue_date(current_time):
    return f"{current_time.strftime('%A, %B')} {current_time.day}, {current_time.year}"


def _reading_time(draft, articles):
    words = sum(len(plain_text(article.get(key)).split()) for article in articles for key in ("headline", "story_content", "takeaway"))
    words += len(plain_text(draft.get("intro")).split()) + len(plain_text(draft.get("outro")).split())
    return max(1, math.ceil(words / 220))


def format_email_html(editor_draft, brew_name, current_time):
    """Render a responsive, table-based HTML email with no external assets."""
    articles = _draft_parts(editor_draft)
    title = plain_text(brew_name) or "Your daily brew"
    issue_date = _issue_date(current_time)
    count = len(articles)
    edition = f"{count} {'story' if count == 1 else 'stories'} · {_reading_time(editor_draft, articles)} min read" if articles else "No roundup this edition"
    preheader = plain_text(articles[0].get("headline")) if articles else EMPTY_MESSAGE
    intro = _paragraphs(editor_draft.get("intro")) if articles else ""
    stories = []
    for index, article in enumerate(articles, 1):
        url = safe_url(article.get("original_url"))
        domain = source_domain(url)
        source = plain_text(article.get("source"))
        # Show a display name only alongside the actual link destination.
        attribution = f"{source} · {domain}" if source and domain and source.lower() != domain.lower() else domain or "Source unavailable"
        date_label = publication_date(article, current_time)
        headline = esc(plain_text(article.get("headline")))
        link = f'<a href="{esc(url)}" style="color:#775139;text-decoration:underline;text-underline-offset:3px;font-size:14px;font-weight:bold;line-height:1.6;">Read the original at {esc(domain)} <span aria-hidden="true">↗</span></a>' if url else '<span style="font-size:14px;color:#72685e;">Original link unavailable</span>'
        takeaway = article.get("takeaway")
        takeaway_html = ""
        if isinstance(takeaway, str) and takeaway.strip():
            takeaway_html = f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 18px;"><tr><td style="padding:13px 16px;background:#f3eee5;border-left:3px solid #ab7955;font-size:15px;line-height:1.65;color:#443b33;"><strong>The takeaway</strong><br>{_inline(takeaway)}</td></tr></table>'
        stories.append(f'''<tr><td class="content" style="padding:28px 40px 30px;border-top:1px solid #e5ddd0;">
          <p style="margin:0 0 10px;font-size:11px;line-height:1.5;font-weight:bold;letter-spacing:1.6px;text-transform:uppercase;color:#986b47;">{index:02d} / {'The lead' if index == 1 else 'In the brew'}</p>
          <h2 style="margin:0 0 12px;font-family:Georgia,'Times New Roman',serif;font-size:{28 if index == 1 else 24}px;line-height:1.22;letter-spacing:-0.4px;font-weight:normal;color:#30271f;overflow-wrap:anywhere;">{headline}</h2>
          <p style="margin:0 0 17px;font-size:12px;line-height:1.65;color:#72685e;overflow-wrap:anywhere;">{esc(attribution)}<br>{esc(date_label)}</p>
          {_paragraphs(article.get('story_content'))}
          {takeaway_html}{link}
        </td></tr>''')
    if not articles:
        stories.append(f'<tr><td class="content" style="padding:28px 40px 36px;border-top:1px solid #e5ddd0;"><h2 style="font-family:Georgia,serif;font-size:28px;font-weight:normal;color:#30271f;margin:0 0 16px;">{EMPTY_TITLE}</h2>{_paragraphs(EMPTY_MESSAGE)}</td></tr>')
    outro = _paragraphs(editor_draft.get("outro")) if articles else ""
    return f'''<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>{esc(title)} · TimeBrew</title>
<style>body,table,td,a{{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}table{{border-collapse:collapse;}}body{{margin:0;padding:0;}}a:hover{{text-decoration:none!important;}}@media only screen and (max-width:600px){{.outer{{padding:16px 8px!important;}}.content{{padding-left:24px!important;padding-right:24px!important;}}.masthead{{font-size:36px!important;}}}}</style>
</head><body style="margin:0;padding:0;background:#f1ede5;color:#30271f;font-family:Arial,Helvetica,sans-serif;">
<div style="display:none;font-size:1px;color:#f1ede5;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{esc(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f1ede5;"><tr><td class="outer" align="center" style="padding:36px 16px;">
<!--[if mso]><table role="presentation" width="640" align="center"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;background:#fffdf8;border-top:4px solid #8e6041;">
<tr><td class="content" style="padding:30px 40px 25px;">
<p style="margin:0 0 25px;font-size:15px;line-height:1.5;font-weight:bold;letter-spacing:3px;color:#775139;">TIMEBREW <span style="font-weight:normal;letter-spacing:0;color:#b08b6c;">/</span></p>
<p style="margin:0 0 13px;font-size:12px;line-height:1.6;color:#72685e;">{esc(issue_date)}<br>{esc(edition)}</p>
<h1 class="masthead" style="margin:0 0 15px;font-family:Georgia,'Times New Roman',serif;font-size:42px;line-height:1.12;letter-spacing:-1.2px;font-weight:normal;color:#30271f;overflow-wrap:anywhere;">{esc(title)}</h1>
<p style="margin:0 0 24px;font-size:14px;line-height:1.6;font-style:italic;color:#986b47;">A little clarity. Freshly brewed.</p>
{intro}</td></tr>
{''.join(stories)}
<tr><td class="content" style="padding:26px 40px 30px;border-top:1px solid #e5ddd0;">{outro}<p style="margin:8px 0 0;font-family:Georgia,'Times New Roman',serif;font-size:18px;font-style:italic;line-height:1.6;color:#775139;">Until your next cup,<br>TimeBrew</p></td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;"><tr><td align="center" style="padding:20px 24px 4px;font-size:11px;line-height:1.7;color:#72685e;">{DISCLOSURE if articles else 'Prepared by TimeBrew.'}<br>{esc(issue_date)} · {esc(current_time.tzname() or 'UTC')}</td></tr></table>
</td></tr></table></body></html>'''


def format_email_text(editor_draft, brew_name, current_time):
    """Plain-text equivalent for email clients and accessibility."""
    articles = _draft_parts(editor_draft)
    lines = ["TIMEBREW", plain_text(brew_name) or "Your daily brew", _issue_date(current_time), ""]
    if not articles:
        lines.extend([EMPTY_TITLE, EMPTY_MESSAGE, "", "Until your next cup,", "TimeBrew"])
        return "\n".join(lines)
    lines.extend([plain_text(editor_draft.get("intro")), ""])
    for index, article in enumerate(articles, 1):
        url = safe_url(article.get("original_url"))
        domain = source_domain(url)
        source = plain_text(article.get("source"))
        attribution = f"{source} · {domain}" if source and domain and source.lower() != domain.lower() else domain or "Source unavailable"
        lines.extend([f"{index:02d}. {plain_text(article.get('headline'))}", f"{attribution} · {publication_date(article, current_time)}", "", plain_text(article.get("story_content"))])
        if plain_text(article.get("takeaway")):
            lines.extend(["", "The takeaway: " + plain_text(article["takeaway"])])
        lines.extend(["", f"Read the original: {url}" if url else "Original link unavailable", "", "---", ""])
    lines.extend([plain_text(editor_draft.get("outro")), "", "Until your next cup,", "TimeBrew", "", DISCLOSURE])
    return "\n".join(lines)
