"""Offline email rendering and SES-boundary regression tests."""

import copy
import json
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shared.utils.html_email import (
    EMPTY_MESSAGE,
    format_email_html,
    format_email_text,
    publication_date,
    safe_href,
    safe_url,
    source_domain,
)

NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def draft():
    return {
        "subject": "Your fresh perspective",
        "intro": "Coffee ready? Here's **what matters**.",
        "articles": [{
            "headline": "A clearer view of the ocean",
            "story_content": "A short **grounded fact**.\n\nAnd a second paragraph with *perspective*.",
            "takeaway": "A useful thing to remember.",
            "source": "Example News",
            "original_url": "https://www.example.com/story?a=1&b=2",
            "published_at": "2026-10-11",
        }],
        "outro": "Let the ideas steep.",
    }


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href"))


@pytest.mark.parametrize("url", [
    None, "", "null", 17, "javascript:alert(1)", "data:text/html,x", "ftp://example.com/a",
    "//example.com/story", "https:/story", "https://", "https://user:password@example.com/story",
    'https://example.com/"onclick="alert(1)', "https://example.com/with space", "https://example.com/\\evil",
    "https://exam\nple.com/story", "https://example.com/%0d%0aInjected", "https://localhost/x",
    "https://127.0.0.1/story", "https://192.168.1.1/story", "https://[::1]/story", "https://service.internal/x",
    "https://example.com:99999/x", "https://-bad.example/x",
])
def test_unsafe_links_are_not_clickable(url):
    assert safe_url(url) == ""
    assert safe_href(url) == ""


def test_url_escaping_and_domain():
    assert safe_href(" https://www.example.com/story?a=1&b=2 ") == "https://www.example.com/story?a=1&amp;b=2"
    assert source_domain("https://www.example.com/story") == "example.com"
    assert safe_url("https://example.com/story#section") == "https://example.com/story"


def test_editorial_hierarchy_and_plain_text(draft):
    html = format_email_html(draft, "The curious mind", NOW)
    text = format_email_text(draft, "The curious mind", NOW)
    assert '<html lang="en">' in html
    assert 'name="viewport"' in html
    assert 'max-width:640px' in html
    assert "The lead" in html and "The takeaway" in html
    assert "1 story · 1 min read" in html
    assert "Monday, October 12, 2026" in html
    assert "Example News · example.com" in html
    assert "Oct 11, 2026" in html
    assert "<strong>grounded fact</strong>" in html
    assert "<em>perspective</em>" in html
    assert "**" not in text
    assert "A short grounded fact.\n\nAnd a second paragraph with perspective." in text
    assert "Read the original: https://www.example.com/story?a=1&b=2" in text
    assert "Prepared with AI." in html and "Prepared with AI." in text


@pytest.mark.parametrize("separate_takeaway", [None, "A separate **synthetic point**."])
def test_trailing_inline_takeaway_renders_without_literal_markdown(draft, separate_takeaway):
    article = draft["articles"][0]
    article["story_content"] = "Synthetic story.\n\n**Takeaway:** Synthetic takeaway."
    article.pop("takeaway")
    if separate_takeaway is not None:
        article["takeaway"] = separate_takeaway

    html = format_email_html(draft, "Synthetic brew", NOW)
    text = format_email_text(draft, "Synthetic brew", NOW)

    assert "<strong>Takeaway:</strong> Synthetic takeaway.</p>" in html
    assert "Synthetic story.\n\nTakeaway: Synthetic takeaway." in text
    assert "**" not in html + text
    assert html.count("Synthetic takeaway.") == text.count("Synthetic takeaway.") == 1
    if separate_takeaway is not None:
        assert "<strong>The takeaway</strong><br>A separate <strong>synthetic point</strong>." in html
        assert "The takeaway: A separate synthetic point." in text
    else:
        assert "The takeaway" not in html + text


def test_untrusted_text_cannot_inject_html_or_add_links(draft):
    draft["intro"] = '<img src=x onerror="alert(1)">'
    draft["articles"][0].update({
        "headline": '<script>alert("x")</script>',
        "source": '<b>Fake Publisher</b>',
        "story_content": '**<img src="x">** and [injected](javascript:alert) and [extra link](https://evil.example/a)',
        "takeaway": '<a href="javascript:alert(1)">Click</a>',
    })
    html = format_email_html(draft, '<iframe src="x">', NOW)
    assert "<script>" not in html
    assert "<img " not in html
    assert "<iframe " not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;Fake Publisher&lt;/b&gt;" in html
    assert '<strong>&lt;img src=&quot;x&quot;&gt;</strong>' in html
    parsed = Links()
    parsed.feed(html)
    assert parsed.links == ["https://www.example.com/story?a=1&b=2"]


def test_unsafe_source_does_not_create_link(draft):
    draft["articles"][0]["original_url"] = "javascript:alert(1)"
    html = format_email_html(draft, "My brew", NOW)
    parsed = Links()
    parsed.feed(html)
    assert parsed.links == []
    assert "Original link unavailable" in html
    assert "Source unavailable" in html
    assert "javascript:" not in format_email_text(draft, "My brew", NOW)


@pytest.mark.parametrize("value", [None, "yesterday", "3 h ago", "not a date", "2026-99-99", "2026-10-01Tnoon", "2026-10-01T01:00:00"])
def test_unknown_dates_are_honest(value):
    assert publication_date({"published_time": value}, NOW) == "Publication date unavailable"


def test_source_date_is_stable_and_timezone_aware():
    local = NOW.astimezone(timezone(timedelta(hours=-7)))
    assert publication_date({"published_at": "2026-10-12T01:00:00Z"}, local) == "Oct 11, 2026"
    assert publication_date({"published_at": "2026-10-12"}, local) == "Oct 12, 2026"
    assert publication_date({"published_time": "2026-10-12"}, NOW) == "Oct 12, 2026"


def test_empty_state_never_invents_filler():
    draft = {"articles": [], "intro": "Invented breaking news", "outro": "Unsupported market rumor"}
    html = format_email_html(draft, "Empty brew", NOW)
    text = format_email_text(draft, "Empty brew", NOW)
    assert "A quieter brew today." in html
    assert EMPTY_MESSAGE in text
    assert "Invented breaking news" not in html + text
    assert "Unsupported market rumor" not in html + text
    assert "0 stories" not in html


@pytest.mark.parametrize("draft", [None, [], {}, {"articles": None}, {"articles": {}}, {"articles": [None]}])
def test_invalid_shapes_fail_before_render(draft):
    with pytest.raises(ValueError):
        format_email_html(draft, "My brew", NOW)
    with pytest.raises(ValueError):
        format_email_text(draft, "My brew", NOW)


def test_fixture_is_historical_offline_sample():
    fixture = Path(__file__).resolve().parents[2] / "scripts/fixtures/email-draft.json"
    draft = json.loads(fixture.read_text())
    html = format_email_html(draft, "My brew", NOW)
    assert "historical sample" in html
    assert len(html.encode("utf-8")) < 100_000  # Stay below common email clipping thresholds.
    parsed = Links()
    parsed.feed(html)
    assert len(parsed.links) == 3


@pytest.fixture
def dispatcher(monkeypatch, draft):
    from core_services.ai import email_dispatcher as module

    run = {"run_id": "run-1", "current_stage": "dispatcher", "user_id": "user-1", "brew_id": "brew-1", "brew_name": "My brew", "email": "reader@example.com", "timezone": "UTC", "article_count": 3}
    editor = {"editorial_content": copy.deepcopy(draft), "email_sent": False}
    curated = [{"source_id": "source-1", "url": "https://example.com/story"}]
    patches = {
        "get_run": MagicMock(return_value=run),
        "get_editor_log": MagicMock(return_value=editor),
        "get_curator_log": MagicMock(return_value={"raw_articles": curated}),
        "validate_editor_draft": MagicMock(return_value=copy.deepcopy(draft)),
        "update_run_stage": MagicMock(),
        "update_brew_last_sent": MagicMock(),
        "mark_editor_email_sent": MagicMock(),
    }
    for name, mock in patches.items():
        monkeypatch.setattr(module, name, mock)
    ses = MagicMock()
    ses.send_email.return_value = {"MessageId": "message-1"}
    client = MagicMock(return_value=ses)
    monkeypatch.setattr(module.boto3, "client", client)
    return module, patches, run, editor, curated, client, ses


def test_dispatch_validates_before_sending_both_mime_parts(dispatcher):
    module, mocks, run, editor, curated, client, ses = dispatcher
    order = MagicMock()
    for name in ("validate_editor_draft", "mark_editor_email_sent", "update_brew_last_sent", "update_run_stage"):
        order.attach_mock(mocks[name], name)
    order.attach_mock(ses.send_email, "send_email")
    result = module.lambda_handler({"run_id": "run-1"}, None)
    mocks["validate_editor_draft"].assert_called_once_with(editor["editorial_content"], curated, desired_count=3)
    assert result["statusCode"] == 200
    assert result["body"]["message"] == "Email accepted by SES"
    message = ses.send_email.call_args.kwargs["Message"]
    assert set(message["Body"]) == {"Text", "Html"}
    assert message["Body"]["Text"]["Charset"] == "UTF-8"
    assert "example.com" in message["Body"]["Text"]["Data"]
    names = [entry[0] for entry in order.mock_calls]
    assert names == ["validate_editor_draft", "send_email", "mark_editor_email_sent", "update_brew_last_sent", "update_run_stage"]


def test_validation_failure_cannot_reach_ses(dispatcher):
    module, mocks, _, _, _, client, ses = dispatcher
    mocks["validate_editor_draft"].side_effect = ValueError("Unbound source")
    with pytest.raises(ValueError, match="Unbound source"):
        module.lambda_handler({"run_id": "run-1"}, None)
    client.assert_not_called()
    ses.send_email.assert_not_called()
    mocks["update_run_stage"].assert_called_once_with("run-1", "failed", failed_stage="dispatcher", error_message="Unbound source")


def test_empty_briefing_cannot_reach_ses(dispatcher):
    module, mocks, _, _, _, client, _ = dispatcher
    mocks["validate_editor_draft"].return_value = {"articles": []}
    with pytest.raises(ValueError, match="No source-backed articles"):
        module.lambda_handler({"run_id": "run-1"}, None)
    client.assert_not_called()


def test_missing_curator_log_cannot_reach_ses(dispatcher):
    module, mocks, _, _, _, client, _ = dispatcher
    mocks["get_curator_log"].return_value = None
    with pytest.raises(ValueError, match="curated source"):
        module.lambda_handler({"run_id": "run-1"}, None)
    client.assert_not_called()


def test_sent_replay_is_not_sent_or_counted_twice(dispatcher):
    module, mocks, run, editor, _, client, _ = dispatcher
    editor["email_sent"] = True
    run["current_stage"] = "completed"
    result = module.lambda_handler({"run_id": "run-1"}, None)
    assert result["body"]["already_sent"] is True
    client.assert_not_called()
    mocks["validate_editor_draft"].assert_not_called()
    mocks["update_brew_last_sent"].assert_not_called()


def test_ses_failure_does_not_mark_sent(dispatcher):
    module, mocks, _, _, _, _, ses = dispatcher
    ses.send_email.side_effect = RuntimeError("SES rejected send")
    with pytest.raises(RuntimeError, match="SES rejected"):
        module.lambda_handler({"run_id": "run-1"}, None)
    mocks["mark_editor_email_sent"].assert_not_called()
    mocks["update_brew_last_sent"].assert_not_called()


def test_replay_after_bookkeeping_failure_does_not_resend(dispatcher):
    module, mocks, run, editor, _, client, ses = dispatcher
    mocks["mark_editor_email_sent"].side_effect = lambda *args: editor.update(email_sent=True, email_sent_time=args[1])
    mocks["update_brew_last_sent"].side_effect = [RuntimeError("Counter unavailable"), None]
    with pytest.raises(RuntimeError, match="Counter unavailable"):
        module.lambda_handler({"run_id": "run-1"}, None)
    run["current_stage"] = "failed"
    result = module.lambda_handler({"run_id": "run-1"}, None)
    assert result["body"]["already_sent"] is True
    ses.send_email.assert_called_once()
    assert mocks["update_brew_last_sent"].call_count == 2
    first, second = mocks["update_brew_last_sent"].call_args_list
    assert first == second
    assert mocks["update_run_stage"].call_args.args == ("run-1", "completed")


def test_raw_json_fallback_and_safe_subject(dispatcher):
    module, mocks, _, editor, _, _, ses = dispatcher
    editor["raw_llm_response"] = json.dumps(editor.pop("editorial_content"))
    mocks["validate_editor_draft"].return_value["subject"] = "**Your brew**\r\nInjected line"
    module.lambda_handler({"run_id": "run-1"}, None)
    assert ses.send_email.call_args.kwargs["Message"]["Subject"]["Data"] == "Your brew Injected line"
    assert isinstance(mocks["validate_editor_draft"].call_args.args[0], dict)


def _source_bound_draft(draft):
    from shared.utils.provenance import curate_with_provenance

    sources, rejected = curate_with_provenance(
        [{"headline": "Source title", "summary": "A short grounded fact.", "url": "https://example.com/story"}],
        {"provider": "offline-fixture", "search_results": [{"url": "https://example.com/story", "date": "2026-10-11"}]},
        now=NOW,
    )
    assert not rejected
    bound = copy.deepcopy(draft)
    bound["articles"] = [{
        "source_id": sources[0]["source_id"],
        "headline": "A clear view",
        "story_content": "A short grounded fact.",
        "takeaway": "A useful point.",
    }]
    return bound, sources


def test_real_final_gate_hydrates_source_before_sending(dispatcher, monkeypatch, draft):
    from shared.utils.provenance import validate_editor_draft

    module, mocks, _, editor, _, _, ses = dispatcher
    bound, sources = _source_bound_draft(draft)
    editor["editorial_content"] = bound
    mocks["get_curator_log"].return_value = {"raw_articles": json.dumps(sources)}
    monkeypatch.setattr(module, "validate_editor_draft", validate_editor_draft)
    module.lambda_handler({"run_id": "run-1"}, None)
    message = ses.send_email.call_args.kwargs["Message"]
    assert "Oct 11, 2026" in message["Body"]["Html"]["Data"]
    assert "https://example.com/story" in message["Body"]["Text"]["Data"]
    assert "Example News" not in message["Body"]["Html"]["Data"]


@pytest.mark.parametrize("change", [{"original_url": "https://other.example/fabricated"}, {"published_time": "yesterday"}, {"source": "Fake Newsroom"}])
def test_real_final_gate_blocks_mutated_metadata(dispatcher, monkeypatch, draft, change):
    from shared.utils.provenance import validate_editor_draft

    module, mocks, _, editor, _, client, _ = dispatcher
    bound, sources = _source_bound_draft(draft)
    bound["articles"][0].update(change)
    editor["editorial_content"] = bound
    mocks["get_curator_log"].return_value = {"raw_articles": sources}
    monkeypatch.setattr(module, "validate_editor_draft", validate_editor_draft)
    with pytest.raises(ValueError, match="source mismatch"):
        module.lambda_handler({"run_id": "run-1"}, None)
    client.assert_not_called()


def test_invalid_requested_count_is_not_silently_clamped(dispatcher):
    module, _, run, _, _, client, _ = dispatcher
    run["article_count"] = 11
    with pytest.raises(ValueError, match="article_count"):
        module.lambda_handler({"run_id": "run-1"}, None)
    client.assert_not_called()


def test_replay_bookkeeping_failure_cannot_mark_complete_or_resend(dispatcher):
    module, mocks, run, editor, _, client, _ = dispatcher
    editor.update(email_sent=True, email_sent_time="2026-10-12T08:00:00")
    run["current_stage"] = "failed"
    mocks["update_brew_last_sent"].side_effect = RuntimeError("Counter still unavailable")
    with pytest.raises(RuntimeError, match="Counter still unavailable"):
        module.lambda_handler({"run_id": "run-1"}, None)
    client.assert_not_called()
    assert all(entry.args[1] != "completed" for entry in mocks["update_run_stage"].call_args_list)


def test_legacy_sent_flag_without_time_never_resends(dispatcher):
    module, mocks, run, editor, _, client, _ = dispatcher
    editor["email_sent"] = True
    run["current_stage"] = "failed"
    with pytest.raises(ValueError, match="missing its timestamp"):
        module.lambda_handler({"run_id": "run-1"}, None)
    client.assert_not_called()
    mocks["update_brew_last_sent"].assert_not_called()
