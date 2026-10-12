import json
from unittest.mock import Mock

import pytest

from core_services.ai import news_curator

URL = "https://news.example.com/new-story"


@pytest.fixture
def curator_dependencies(monkeypatch):
    run = {"run_id": "run-1", "brew_id": "brew-1", "user_id": "user-1", "current_stage": "curator",
           "brew_name": "My AI news", "topics": ["AI"], "article_count": 2, "timezone": "UTC"}
    previous = [{"headline": "Already delivered", "url": "https://news.example.com/prior"}]
    feedback = [{"type": "like", "headline": "Useful robotics story", "url": "https://other.example.org/robotics", "source": "other.example.org"},
                {"type": "dislike", "article_position": 1}, ("like", 2)]
    mocks = {}
    for name, value in {"get_run": run, "get_brew_by_id": {"is_active": True, "article_count": 5},
                        "list_recent_curator_articles_for_user": [(previous, None)],
                        "list_recent_feedback_for_user": feedback,
                        "create_curator_log": "log-1", "update_curator_log": None, "update_run_stage": None}.items():
        mocks[name] = Mock(return_value=value)
        monkeypatch.setattr(news_curator, name, mocks[name])
    articles = [{"headline": f"New story {i}", "summary": "The source reports a product launch.", "url": URL + str(i)} for i in range(3)]
    response = {"content": json.dumps({"articles": articles, "curator_notes": "Search completed."}),
                "citations": [a["url"] for a in articles], "provider": "fixture", "model": "offline"}
    mocks["call"] = Mock(return_value=response)
    monkeypatch.setattr(news_curator.ai_service, "call", mocks["call"])
    return mocks, response


def test_curator_honors_count_and_uses_actual_feedback(curator_dependencies):
    mocks, _ = curator_dependencies
    result = news_curator.lambda_handler({"run_id": "run-1", "brew_id": "brew-1"}, None)
    assert result["body"]["articles_collected"] == 2
    prompt = mocks["call"].call_args.kwargs["prompt"]
    assert "Useful robotics story" in prompt
    assert "Already delivered" in prompt
    assert "article_position" not in prompt
    assert "up to 2" in prompt
    articles = mocks["update_curator_log"].call_args.args[1]
    assert len(articles) == 2
    assert all(article["source_id"] for article in articles)
    mocks["update_run_stage"].assert_called_once_with("run-1", "editor")


def test_curator_without_provider_evidence_fails_closed(curator_dependencies):
    mocks, response = curator_dependencies
    response["citations"] = []
    with pytest.raises(ValueError, match="No evidence-backed articles"):
        news_curator.lambda_handler({"run_id": "run-1", "brew_id": "brew-1"}, None)
    assert mocks["update_curator_log"].call_args.args[1] == []
    assert mocks["update_run_stage"].call_args.args == ("run-1", "failed")


def test_curator_empty_day_does_not_advance_to_editor(curator_dependencies):
    mocks, response = curator_dependencies
    response["content"] = json.dumps({"articles": [], "curator_notes": "Write analysis instead"})
    with pytest.raises(ValueError, match="withheld rather than fabricated"):
        news_curator.lambda_handler({"run_id": "run-1", "brew_id": "brew-1"}, None)
    assert mocks["update_run_stage"].call_args.args == ("run-1", "failed")


def test_curator_returns_fewer_when_evidence_is_thin(curator_dependencies):
    mocks, response = curator_dependencies
    response["citations"] = response["citations"][:1]
    result = news_curator.lambda_handler({"run_id": "run-1", "brew_id": "brew-1"}, None)
    assert result["body"]["articles_collected"] == 1
    assert "Only 1 of 2" in result["body"]["curator_notes"]


def test_curator_can_retry_story_not_in_delivered_history(curator_dependencies):
    mocks, _ = curator_dependencies
    # The DB helper excludes unsuccessful deliveries. Such stories stay eligible
    # on a retry; only the supplied delivered-history set is a hard exclusion.
    mocks["list_recent_curator_articles_for_user"].return_value = []
    result = news_curator.lambda_handler({"run_id": "run-1", "brew_id": "brew-1"}, None)
    assert result["body"]["articles_collected"] == 2
    mocks["update_run_stage"].assert_called_once_with("run-1", "editor")
