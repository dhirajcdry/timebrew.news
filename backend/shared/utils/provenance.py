"""Fail-closed source identity gates shared by curation, editing and delivery.

Only the provider's out-of-band citations/search results are evidence. Model
JSON, a resolving domain, and past newsletters cannot supply provenance. This
establishes citation identity, not independent claim-level fact verification or
HTTP page liveness. Unknown publication dates stay unknown.
"""
import hashlib
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from shared.utils.url_utils import canonical_article_url, is_collection_url

UNKNOWN_PUBLICATION = "Publication date unavailable"
PROVENANCE_VERSION = 1


def requested_article_count(value, default=5):
    """Validate the saved preference rather than silently choosing another size."""
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("article_count must be an integer from 1 to 10")
    try:
        count = int(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("article_count must be an integer from 1 to 10")
    if str(value).strip() not in {str(count), f"{count}.0"} or not 1 <= count <= 10:
        raise ValueError("article_count must be an integer from 1 to 10")
    return count


def source_id_for_url(url):
    canonical = canonical_article_url(url)
    if not canonical:
        raise ValueError("Article URL must be a safe public HTTP(S) URL")
    return "src_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def normalize_publication_date(value):
    """Accept explicit ISO dates/timestamps only; never invent a time or timezone."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
        if not re.match(r"^\d{4}-\d{2}-\d{2}T", value):
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _date_in_window(value, window_start, now):
    if not value:
        return True  # Unknown stays visibly unknown; recency is not asserted.
    if len(value) == 10:
        publication = date.fromisoformat(value)
        return (window_start is None or publication >= window_start.date()) and publication <= now.date()
    publication = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (window_start is None or publication >= window_start) and publication <= now


def provider_sources(response):
    """Index genuine provider envelope metadata, never parsed model content."""
    evidence = {}
    candidates = []
    for citation in response.get("citations", []) or []:
        if isinstance(citation, str):
            candidates.append({"url": citation})
        elif isinstance(citation, dict):
            candidates.append(citation)
    candidates.extend(item for item in (response.get("search_results", []) or []) if isinstance(item, dict))
    for annotation in response.get("annotations", []) or []:
        if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
            citation = annotation.get("url_citation")
            if isinstance(citation, dict):
                candidates.append(citation)
    for item in candidates:
        url = canonical_article_url(item.get("url"))
        if not url:
            continue
        record = evidence.setdefault(url, {"url": url})
        for field in ("title", "content"):
            if isinstance(item.get(field), str) and item[field].strip():
                record[field] = item[field].strip()[:12000]
        published = normalize_publication_date(item.get("published_at") or item.get("date") or item.get("published_date"))
        if published:
            record["published_at"] = published
    return evidence


def _required_text(record, key, max_length):
    value = record.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"Invalid or missing {key}")
    return value.strip()


def curate_with_provenance(articles, provider_response, *, desired_count=5,
                           previous_articles=None, window_start=None, now=None):
    """Admit supported, fresh-if-dated, nonduplicate articles up to the quota.

    Returns accepted articles and bounded rejection reasons for audit logs. A
    caller must fail a run with zero accepted sources, never fabricate filler.
    """
    if not isinstance(articles, list):
        raise ValueError("Curator articles must be a list")
    desired_count = requested_article_count(desired_count)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    if window_start is not None:
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
        window_start = window_start.astimezone(timezone.utc)
    evidence = provider_sources(provider_response)
    previous_articles = previous_articles or []
    seen_urls = {canonical_article_url(a.get("url") or a.get("original_url"))
                 for a in previous_articles if isinstance(a, dict)}
    seen_titles = {_headline_identity(a.get("headline")) for a in previous_articles if isinstance(a, dict)}
    accepted, rejected = [], []
    for candidate in articles:
        try:
            if not isinstance(candidate, dict):
                raise ValueError("Article must be an object")
            headline = _required_text(candidate, "headline", 500)
            summary = _required_text(candidate, "summary", 6000)
            url = canonical_article_url(candidate.get("url"))
            if not url or url not in evidence:
                raise ValueError("URL has no matching provider citation")
            if is_collection_url(url):
                raise ValueError("Source must link to a specific article, not a publisher collection")
            if url in seen_urls or _headline_identity(headline) in seen_titles:
                raise ValueError("Article repeats a previously selected or delivered story")
            source_record = evidence[url]
            published = source_record.get("published_at")
            if not _date_in_window(published, window_start, now):
                raise ValueError("Known publication date is outside the requested window")
            domain = urlsplit(url).hostname.removeprefix("www.")
            provenance = {
                "version": PROVENANCE_VERSION,
                "evidence_type": "provider_citation",
                "citation_url": url,
                "provider": str(provider_response.get("provider") or "unknown"),
                "model": str(provider_response.get("model") or "unknown"),
                "retrieved_at": now.isoformat().replace("+00:00", "Z"),
                "published_at": published,
            }
            if source_record.get("title"):
                provenance["source_title"] = source_record["title"]
            if source_record.get("content"):
                provenance["source_excerpt"] = source_record["content"]
            accepted.append({
                "source_id": source_id_for_url(url), "headline": headline,
                "summary": summary, "source": domain, "source_domain": domain,
                "url": url, "published_at": published,
                "published_time": published or UNKNOWN_PUBLICATION,
                "relevance": str(candidate.get("relevance") or "")[:2000],
                "provenance": provenance,
            })
            seen_urls.add(url)
            seen_titles.add(_headline_identity(headline))
            if len(accepted) == desired_count:
                break
        except ValueError as error:
            rejected.append(str(error))
    return accepted, rejected


def _headline_identity(headline):
    return re.sub(r"\W+", " ", str(headline or "").lower()).strip()


def validate_curated_articles(articles):
    """Verify persisted provenance before trusting a curator record downstream."""
    if not isinstance(articles, list) or not articles or len(articles) > 10:
        raise ValueError("No usable curated sources (expected 1–10 articles)")
    ids = set()
    for article in articles:
        if not isinstance(article, dict):
            raise ValueError("Curated article must be an object")
        _required_text(article, "headline", 500)
        _required_text(article, "summary", 6000)
        url = canonical_article_url(article.get("url"))
        provenance = article.get("provenance")
        if not url or not isinstance(provenance, dict):
            raise ValueError("Missing curated source provenance")
        if is_collection_url(url):
            raise ValueError("Curated source must link to a specific article, not a publisher collection")
        if (provenance.get("version") != PROVENANCE_VERSION or
                provenance.get("evidence_type") != "provider_citation" or
                provenance.get("citation_url") != url or article.get("url") != url or
                not normalize_publication_date(provenance.get("retrieved_at"))):
            raise ValueError("Invalid curated source provenance")
        source_id = source_id_for_url(url)
        if article.get("source_id") != source_id or source_id in ids:
            raise ValueError("Invalid or duplicate curated source ID")
        ids.add(source_id)
        domain = urlsplit(url).hostname.removeprefix("www.")
        if article.get("source") != domain or article.get("source_domain") != domain:
            raise ValueError("Curated source identity does not match URL")
        published = article.get("published_at")
        if (published is not None and normalize_publication_date(published) != published) or provenance.get("published_at") != published:
            raise ValueError("Invalid curated publication date")
        if article.get("published_time") != (published or UNKNOWN_PUBLICATION):
            raise ValueError("Curated publication label does not match evidence")
    return articles


def validate_editor_draft(draft, curated_articles, desired_count=None):
    """Bind every final story to exactly one curated record, or fail closed.

    The editor owns prose only. If it supplies immutable metadata, it must match
    exactly; omitted metadata is hydrated from the source of truth. This helper
    can be called again immediately before sending a persisted draft.
    """
    validate_curated_articles(curated_articles)
    if desired_count is not None and len(curated_articles) > requested_article_count(desired_count):
        raise ValueError("Curated article count exceeds requested count")
    if not isinstance(draft, dict):
        raise ValueError("Editorial draft must be an object")
    normalized = {key: _required_text(draft, key, limit) for key, limit in
                  (("subject", 180), ("intro", 2000), ("outro", 2000))}
    articles = draft.get("articles")
    if not isinstance(articles, list) or len(articles) != len(curated_articles):
        raise ValueError("Editor must cover exactly the curated source set; no filler or omissions")
    source_by_id = {a["source_id"]: a for a in curated_articles}
    seen = set()
    normalized["articles"] = []
    for story in articles:
        if not isinstance(story, dict):
            raise ValueError("Editorial story must be an object")
        source_id = story.get("source_id")
        if not isinstance(source_id, str) or source_id not in source_by_id or source_id in seen:
            raise ValueError("Editorial story has an unknown or duplicate source ID")
        seen.add(source_id)
        source = source_by_id[source_id]
        immutable = {"source_id": source_id, "original_url": source["url"],
                     "source": source["source"], "source_domain": source["source_domain"],
                     "published_at": source["published_at"], "published_time": source["published_time"],
                     "provenance": source["provenance"], "type": "news"}
        for key, expected in immutable.items():
            if key in story and story[key] != expected:
                raise ValueError(f"Editorial source mismatch: {key}")
        output = {"headline": _required_text(story, "headline", 500),
                  "story_content": _required_text(story, "story_content", 6000), **immutable}
        if "takeaway" in story:
            output["takeaway"] = _required_text(story, "takeaway", 1200)
        normalized["articles"].append(output)
    normalized["article_count"] = len(articles)
    normalized["provenance_version"] = PROVENANCE_VERSION
    return normalized
