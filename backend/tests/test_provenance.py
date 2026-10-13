"""Offline source-identity regression tests. No provider or publisher requests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from shared.utils.provenance import (
    UNKNOWN_PUBLICATION, curate_with_provenance, normalize_publication_date,
    provider_sources, requested_article_count, source_id_for_url, validate_curated_articles,
    validate_editor_draft,
)
from shared.utils.url_utils import canonical_article_url, filter_live_article_urls, safe_article_url, url_host_resolves

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
URL = "https://news.example.com/story/real-story"


def candidate(url=URL, **overrides):
    return {"headline": "A supported announcement", "summary": "The source reports a new product.",
            "source": "Invented Publisher", "url": url, "published_time": "4 hours ago", **overrides}


def curated(**kwargs):
    return curate_with_provenance([candidate()], {"citations": [URL], "provider": "fixture"}, now=NOW, **kwargs)[0]


def draft(sources):
    return {"subject": "A product announcement", "intro": "Here is your briefing.",
            "outro": "See you next time.", "articles": [
                {"source_id": source["source_id"], "headline": "The latest product",
                 "story_content": "The source reports a new product.", "takeaway": "There is a new option."}
                for source in sources]}


@pytest.mark.parametrize("url", [None, "", "javascript:alert(1)", "data:text/html,hi", "ftp://news.example.com/x",
    "https://user:secret@news.example.com/x", "https://localhost/x", "https://127.0.0.1/x",
    "https://169.254.169.254/latest", "https://[::1]/x", "https://internal/x", "https://host.local/x",
    "https://news.example.com:9999/x", "https://news.example.com/has space", "https://news.example.com\n/x",
    "https://news.example.com\\@other.example.org/x", "https://2130706433/x", "https://news.example.com/a%0d%0aInjected",
    'https://news.example.com/<script>', 'https://news.example.com/"quoted"'])
def test_rejects_unsafe_urls(url):
    assert safe_article_url(url) is None


def test_canonical_preserves_identity_query_and_removes_trackers():
    assert canonical_article_url("https://NEWS.example.com/a?b=2&utm_source=x&a=1#top") == "https://news.example.com/a?a=1&b=2"
    assert canonical_article_url(URL + "?article=one") != canonical_article_url(URL + "?article=two")


def test_dns_filter_never_restores_failed_candidates():
    with patch("shared.utils.url_utils.url_host_resolves", return_value=False):
        kept, rejected = filter_live_article_urls([candidate()], min_keep=5)
    assert kept == []
    assert len(rejected) == 1


def test_dns_check_does_not_change_global_timeout_and_rejects_private_ip():
    with patch("shared.utils.url_utils.socket.getaddrinfo", return_value=[(None, None, None, None, ("10.0.0.1", 0))]), \
         patch("shared.utils.url_utils.socket.setdefaulttimeout") as setter:
        assert not url_host_resolves(URL)
        setter.assert_not_called()


def test_model_json_citations_and_resolving_domain_are_not_evidence():
    assert curate_with_provenance([candidate(citations=[URL])], {"content": '{"citations": ["' + URL + '"]}'}, now=NOW)[0] == []
    assert curate_with_provenance([candidate()], {"citations": ["https://news.example.com/different-page"]}, now=NOW)[0] == []


@pytest.mark.parametrize("path", ["/", "/news/", "/business/technology", "/Business/Technology/",
    "/business/technology?utm_source=fixture", "/category/robotics", "/topics/new-products"])
def test_section_citations_are_not_full_story_sources(path):
    url = "https://news.example.com" + path
    sources, reasons = curate_with_provenance([candidate(url)], {"citations": [url]}, now=NOW)
    assert sources == []
    assert "article" in reasons[0].lower()


@pytest.mark.parametrize("path", ["/business/technology/a-specific-product-launch", "/science/a-new-mission",
    "/?p=123", "/index.php?article_id=abc-123", "/news/?p=123",
    "/category/robotics/2026/10/12/a-specific-product-launch"])
def test_article_paths_and_query_identity_remain_eligible(path):
    url = "https://news.example.com" + path
    sources, reasons = curate_with_provenance([candidate(url)], {"citations": [url]}, now=NOW)
    assert len(sources) == 1
    assert reasons == []


@pytest.mark.parametrize("path", ["/business/technology", "/category/robotics"])
def test_persisted_collection_sources_cannot_bypass_final_validation(path):
    sources = curated()
    url = "https://news.example.com" + path
    sources[0]["url"] = url
    sources[0]["source_id"] = source_id_for_url(url)
    sources[0]["provenance"]["citation_url"] = url
    with pytest.raises(ValueError, match="specific article"):
        validate_editor_draft(draft(sources), sources)


def test_provider_annotation_is_preserved_and_model_date_is_ignored():
    evidence = {"annotations": [{"type": "url_citation", "url_citation": {
        "url": URL, "title": "Original title", "content": "Original source excerpt"}}]}
    sources, _ = curate_with_provenance([candidate(published_at="2026-10-12")], evidence, now=NOW)
    article = sources[0]
    assert article["source"] == "news.example.com"
    assert article["published_at"] is None
    assert article["published_time"] == UNKNOWN_PUBLICATION
    assert article["provenance"]["source_excerpt"] == "Original source excerpt"
    assert validate_curated_articles(sources) == sources


def test_provider_search_result_supplies_known_date():
    sources, _ = curate_with_provenance([candidate()], {"search_results": [{"url": URL, "date": "2026-10-12"}]}, now=NOW)
    assert sources[0]["published_at"] == "2026-10-12"
    assert sources[0]["published_time"] == "2026-10-12"


@pytest.mark.parametrize("value", ["4 h ago", "yesterday", "2026-10-12T10:00:00", "2026-99-99", "next week", 5])
def test_dates_never_invent_timezone_or_relative_publication(value):
    assert normalize_publication_date(value) is None


@pytest.mark.parametrize("date", ["2026-10-01", "2026-10-13", "2026-10-12T13:00:00Z"])
def test_rejects_known_stale_and_future_publication(date):
    sources, reasons = curate_with_provenance([candidate()], {"search_results": [{"url": URL, "date": date}]},
        now=NOW, window_start=NOW - timedelta(days=3))
    assert sources == []
    assert "outside" in reasons[0]


@pytest.mark.parametrize("field", ["retrieved_at", "last_updated", "updated_at", "last_crawled_at"])
def test_retrieval_and_update_dates_never_become_publication(field):
    sources, _ = curate_with_provenance([candidate()],
        {"search_results": [{"url": URL, field: "2026-10-12T10:00:00Z"}]}, now=NOW)
    assert sources[0]["published_at"] is None
    assert sources[0]["published_time"] == UNKNOWN_PUBLICATION


@pytest.mark.parametrize("publication", [
    {"published_date": "2026-10-01", "date": "2026-10-12"},
    {"published_at": "2026-10-01", "last_updated": "2026-10-12"},
    {"published_at": "not a date", "published_date": "2026-10-01", "date": "2026-10-12"},
    {"published_at": "not a date", "date": "2026-10-01"},
])
def test_recent_or_invalid_alias_cannot_mask_known_stale_publication(publication):
    sources, reasons = curate_with_provenance([candidate()],
        {"search_results": [{"url": URL, **publication}]},
        now=NOW, window_start=NOW - timedelta(days=3))
    assert sources == []
    assert "outside" in reasons[0]


@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_publication_wins_across_duplicate_evidence_records(reverse):
    records = [{"url": URL, "published_at": "2026-10-01"},
               {"url": URL + "?utm_source=fixture", "date": "2026-10-12"}]
    if reverse:
        records.reverse()
    sources, reasons = curate_with_provenance([candidate()],
        {"citations": records[:1], "search_results": records[1:]},
        now=NOW, window_start=NOW - timedelta(days=3))
    assert sources == []
    assert "outside" in reasons[0]


@pytest.mark.parametrize("records", [
    [{"published_at": "2026-10-11", "published_date": "2026-10-12"}],
    [{"published_at": "2026-10-11"}, {"published_date": "2026-10-12"}],
    [{"date": "2026-10-11"}, {"date": "2026-10-12"}],
    [{"published_at": "2026-10-12T08:00:00Z"}, {"published_at": "2026-10-12T09:00:00Z"}],
])
@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_publication_evidence_fails_closed(records, reverse):
    if reverse:
        records = list(reversed(records))
    sources, reasons = curate_with_provenance([candidate()],
        {"search_results": [{"url": URL, **record} for record in records]}, now=NOW)
    assert sources == []
    assert "conflict" in reasons[0].lower()


@pytest.mark.parametrize("reverse", [False, True])
def test_equivalent_and_different_precision_publication_dates_are_compatible(reverse):
    records = [{"url": URL, "published_at": "2026-10-12T10:00:00+02:00"},
               {"url": URL, "published_date": "2026-10-12"},
               {"url": URL, "published_at": "2026-10-12T08:00:00Z"}]
    if reverse:
        records.reverse()
    sources, reasons = curate_with_provenance([candidate()], {"search_results": records}, now=NOW)
    assert reasons == []
    assert sources[0]["published_at"] == "2026-10-12T08:00:00Z"


def test_unusable_date_alias_does_not_mask_valid_publication_alias():
    sources, reasons = curate_with_provenance([candidate()], {"search_results": [{
        "url": URL, "published_at": "not a date", "published_date": "2026-10-11",
    }]}, now=NOW)
    assert reasons == []
    assert sources[0]["published_at"] == "2026-10-11"


def test_deduplicates_history_and_honors_requested_count():
    candidates = [candidate(URL + str(i), headline=f"Story {i}") for i in range(5)]
    sources, rejected = curate_with_provenance(candidates, {"citations": [a["url"] for a in candidates]},
        desired_count=2, previous_articles=[candidates[0]], now=NOW)
    assert [a["url"] for a in sources] == [URL + "1", URL + "2"]
    assert len(rejected) == 1


def test_editor_hydrates_only_bound_metadata_and_validates_roundtrip():
    sources = curated()
    result = validate_editor_draft(draft(sources), sources)
    assert result["articles"][0]["original_url"] == URL
    assert result["articles"][0]["provenance"] == sources[0]["provenance"]
    assert validate_editor_draft(result, sources) == result


@pytest.mark.parametrize("field,value", [("source_id", "invented"), ("source", "TimeBrew Analysis"),
    ("original_url", "https://news.example.com/other-story"), ("published_time", "4 h ago"),
    ("published_at", "2026-10-12"), ("type", "analysis"), ("provenance", {})])
def test_editor_cannot_change_identity_or_date(field, value):
    sources = curated()
    edited = draft(sources)
    edited["articles"][0][field] = value
    with pytest.raises(ValueError):
        validate_editor_draft(edited, sources)


@pytest.mark.parametrize("change", ["omit", "extra", "duplicate"])
def test_editor_must_cover_exact_source_set(change):
    sources = curated()
    edited = draft(sources)
    if change == "omit":
        edited["articles"] = []
    else:
        edited["articles"].append(deepcopy(edited["articles"][0]))
    with pytest.raises(ValueError):
        validate_editor_draft(edited, sources)


def test_legacy_unprovenanced_articles_and_empty_sources_fail_closed():
    for articles in ([], [candidate()]):
        with pytest.raises(ValueError):
            validate_editor_draft({"articles": []}, articles)


@pytest.mark.parametrize("value", [0, 11, True, "five", 2.5])
def test_invalid_requested_counts_fail(value):
    with pytest.raises(ValueError):
        requested_article_count(value)
