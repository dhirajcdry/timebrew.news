import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from core_services.ai import news_editor
from shared.utils.provenance import curate_with_provenance

URL = "https://news.example.com/story"


@pytest.fixture
def editor_dependencies(monkeypatch):
    sources, _ = curate_with_provenance(
        [{"headline": "Source headline", "summary": "The company announced a product.", "url": URL}],
        {"citations": [URL], "provider": "fixture"}, now=datetime.now(timezone.utc))
    run = {"run_id": "run-1", "brew_id": "brew-1", "current_stage": "editor", "user_id": "user-1",
           "article_count": 3, "first_name": "Reader", "topics": ["AI"], "email": "reader@example.com"}
    mocks = {}
    for name, value in {"get_run": run, "get_curator_log": {"raw_articles": sources, "curator_notes": "Only one qualified."},
                        "get_latest_completed_draft_for_brew": ('Prior delivered phrase', datetime.now(timezone.utc)),
                        "create_editor_log": "log-1", "update_editor_content": None, "update_run_stage": None}.items():
        mocks[name] = Mock(return_value=value)
        monkeypatch.setattr(news_editor, name, mocks[name])
    content = {"subject": "A new product", "intro": "Hello Reader.", "outro": "Until next time.",
               "articles": [{"source_id": sources[0]["source_id"], "headline": "A product arrives",
                             "story_content": "The company announced a product.", "takeaway": "A new option to consider."}]}
    mocks["call"] = Mock(return_value={"content": json.dumps(content)})
    monkeypatch.setattr(news_editor.ai_service, "call", mocks["call"])
    return mocks, sources, content


def test_editor_uses_history_and_persists_source_bound_draft(editor_dependencies):
    mocks, sources, _ = editor_dependencies
    result = news_editor.lambda_handler({"run_id": "run-1"}, None)
    assert result["statusCode"] == 200
    prompt = mocks["call"].call_args.kwargs["messages"][1]["content"]
    assert "Prior delivered phrase" in prompt
    assert "never add filler" in prompt
    story = mocks["update_editor_content"].call_args.args[1]["articles"][0]
    assert story["original_url"] == URL
    assert story["provenance"] == sources[0]["provenance"]
    mocks["update_run_stage"].assert_called_once_with("run-1", "dispatcher")


def test_editor_never_calls_provider_with_empty_sources(editor_dependencies):
    mocks, _, _ = editor_dependencies
    mocks["get_curator_log"].return_value = {"raw_articles": [], "curator_notes": "Please make filler"}
    with pytest.raises(ValueError, match="No usable curated sources"):
        news_editor.lambda_handler({"run_id": "run-1"}, None)
    mocks["call"].assert_not_called()
    mocks["update_editor_content"].assert_not_called()
    assert mocks["update_run_stage"].call_args.args == ("run-1", "failed")


def test_editor_source_mismatch_never_advances_or_saves(editor_dependencies):
    mocks, _, content = editor_dependencies
    content["articles"][0]["original_url"] = "https://elsewhere.example.org/invented"
    mocks["call"].return_value = {"content": json.dumps(content)}
    with pytest.raises(ValueError, match="source mismatch"):
        news_editor.lambda_handler({"run_id": "run-1"}, None)
    mocks["create_editor_log"].assert_called_once()
    mocks["update_editor_content"].assert_not_called()
    assert mocks["update_run_stage"].call_args.args == ("run-1", "failed")


def test_editor_rejects_legacy_articles_before_call(editor_dependencies):
    mocks, sources, _ = editor_dependencies
    sources[0].pop("provenance")
    with pytest.raises(ValueError, match="provenance"):
        news_editor.lambda_handler({"run_id": "run-1"}, None)
    mocks["call"].assert_not_called()
