"""Provider envelope tests use a fake SDK client, never a paid API call."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shared.utils.ai_service import AIService, AIServiceError


def provider_response(content='{"articles": []}', finish_reason="stop"):
    annotations = [{"type": "url_citation", "url_citation": {"url": "https://news.example.com/a", "title": "Actual source"}}]
    message = SimpleNamespace(content=content, model_dump=lambda: {"content": content, "annotations": annotations})
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], usage=None,
        model_dump=lambda: {"citations": ["https://news.example.com/a"],
                            "search_results": [{"url": "https://news.example.com/a", "date": "2026-10-12"}]})


def test_ai_service_retains_out_of_band_source_metadata(monkeypatch):
    response = provider_response()
    client = Mock()
    client.chat.completions.create.return_value = response
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fixture-not-a-real-key")
    monkeypatch.setattr("shared.utils.ai_service.openai.OpenAI", Mock(return_value=client))
    result = AIService().call("openrouter", prompt="Offline fixture")
    assert result["citations"] == ["https://news.example.com/a"]
    assert result["search_results"][0]["date"] == "2026-10-12"
    assert result["annotations"][0]["url_citation"]["title"] == "Actual source"


@pytest.mark.parametrize("response", [provider_response(finish_reason="length"), provider_response(finish_reason="content_filter"), provider_response(content=None)])
def test_ai_service_rejects_incomplete_provider_response(monkeypatch, response):
    client = Mock()
    client.chat.completions.create.return_value = response
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fixture-not-a-real-key")
    monkeypatch.setattr("shared.utils.ai_service.openai.OpenAI", Mock(return_value=client))
    with pytest.raises(AIServiceError):
        AIService().call("openrouter", prompt="Offline fixture", max_retries=0)
