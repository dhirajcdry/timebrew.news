import json
import os
import re
import openai
import time
from typing import Dict, List, Any
# from utils.logger import logger

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class AIServiceError(Exception):
    """Custom exception for AI service errors"""
    pass


class AIService:
    """AI service routed entirely through OpenRouter.

    OpenRouter exposes an OpenAI-compatible Chat Completions API, so a single
    handler serves both the curator (which passes a `prompt`) and the editor
    (which passes `messages`). Model selection (e.g. ``perplexity/sonar-pro``,
    ``openai/gpt-4``) is driven by ai_models.json. The legacy provider names are
    aliased to the same handler for backward compatibility.
    """

    def __init__(self):
        self.providers = {
            'openrouter': self._call_openrouter,
            # Legacy aliases — all routed through OpenRouter.
            'perplexity': self._call_openrouter,
            'openai': self._call_openrouter,
            'deepseek': self._call_openrouter,
        }

    def call(self, provider: str, **kwargs) -> Dict[str, Any]:
        """Main entry point — dispatches to the configured provider handler."""
        if provider not in self.providers:
            raise AIServiceError(
                f"Unsupported AI provider: {provider}. Supported: {list(self.providers.keys())}"
            )

        print(f"[AI_SERVICE] Making AI API call via OpenRouter (configured provider: {provider})")

        try:
            return self.providers[provider](**kwargs)
        except AIServiceError:
            raise
        except Exception as e:
            print(f"[AI_SERVICE] AI API call failed for {provider} - error: {str(e)}")
            raise AIServiceError(f"Failed to call {provider}: {str(e)}")

    def _call_openrouter(self,
                        prompt: str = None,
                        messages: List[Dict[str, str]] = None,
                        model: str = "openai/gpt-4",
                        temperature: float = 0.7,
                        max_tokens: int = 3000,
                        timeout: int = 60,
                        max_retries: int = 3) -> Dict[str, Any]:
        """Call OpenRouter's OpenAI-compatible Chat Completions API with retries.

        Accepts either a single `prompt` string (wrapped into a user message) or
        a pre-built `messages` list.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise AIServiceError("OPENROUTER_API_KEY not found in environment variables")

        if messages is None:
            if prompt is None:
                raise AIServiceError("Either 'prompt' or 'messages' must be provided")
            messages = [{"role": "user", "content": prompt}]

        client = openai.OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            timeout=timeout,
        )

        print(f"[AI_SERVICE] Calling OpenRouter - model: {model}, temperature: {temperature}, messages_count: {len(messages)}, timeout: {timeout}")

        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    delay = 2 ** attempt  # exponential backoff: 2, 4, 8s
                    print(f"[AI_SERVICE] Retrying OpenRouter call (attempt {attempt + 1}/{max_retries + 1}) after {delay}s delay")
                    time.sleep(delay)

                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                content = response.choices[0].message.content
                print(f"[AI_SERVICE] OpenRouter response received - response_length: {len(content)}, model: {model}, attempt: {attempt + 1}")

                return {
                    "content": content,
                    "model": model,
                    "provider": "openrouter",
                    "usage": response.usage.model_dump() if response.usage else {},
                    "raw_response": None,
                }

            except (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError) as e:
                last_exception = e
                print(f"[AI_SERVICE] WARNING: OpenRouter retryable error on attempt {attempt + 1}/{max_retries + 1} - error: {str(e)}")
                if attempt == max_retries:
                    print(f"[AI_SERVICE] ERROR: OpenRouter failed after all retry attempts - error: {str(e)}")
                    raise AIServiceError(f"Failed to call OpenRouter: {str(e)}")
            except Exception as e:
                print(f"[AI_SERVICE] ERROR: OpenRouter non-retryable error - error: {str(e)}, attempt: {attempt + 1}")
                raise AIServiceError(f"OpenRouter API error: {str(e)}")

        raise AIServiceError(f"Failed to call OpenRouter after {max_retries + 1} attempts: {str(last_exception)}")

    def add_provider(self, name: str, handler_func):
        """Register an additional AI provider handler."""
        self.providers[name] = handler_func
        print(f"[AI_SERVICE] Added new AI provider: {name}")

    def get_available_providers(self) -> List[str]:
        return list(self.providers.keys())

    def parse_json_from_response(self, content: str) -> Dict[str, Any]:
        """Parse a JSON object from an LLM response, handling common quirks."""
        print("[AI_SERVICE] Attempting to parse JSON from AI response")
        try:
            # Remove <think> blocks
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

            content_clean = content.strip()

            # Remove any potential markdown code blocks
            if content_clean.startswith("```json"):
                content_clean = content_clean[7:]
            if content_clean.startswith("```"):
                content_clean = content_clean[3:]
            if content_clean.endswith("```"):
                content_clean = content_clean[:-3]

            content_clean = content_clean.strip()

            # Fallback to extracting the first and last curly brace
            start_idx = content_clean.find("{")
            end_idx = content_clean.rfind("}") + 1

            if start_idx != -1 and end_idx != 0:
                json_str = content_clean[start_idx:end_idx]
                response_data = json.loads(json_str)
                print("[AI_SERVICE] Successfully extracted and parsed JSON from AI response")
                return response_data
            else:
                response_data = json.loads(content_clean)
                print("[AI_SERVICE] Successfully parsed entire content as JSON")
                return response_data

        except json.JSONDecodeError as e:
            print(f"[AI_SERVICE] ERROR: Failed to parse JSON from AI response - error: {str(e)}, content_preview: {content[:500]}")
            raise ValueError(f"Failed to parse JSON from AI response: {str(e)}")
        except Exception as e:
            print(f"[AI_SERVICE] ERROR: An unexpected error occurred during JSON parsing - error: {str(e)}")
            raise


# Global instance for easy importing
ai_service = AIService()


# Convenience functions (backward compatibility) — all routed through OpenRouter.
def call_openrouter(prompt: str = None, messages: List[Dict[str, str]] = None, **kwargs) -> str:
    result = ai_service.call('openrouter', prompt=prompt, messages=messages, **kwargs)
    return result['content']


def call_perplexity(prompt: str, **kwargs) -> str:
    result = ai_service.call('openrouter', prompt=prompt, **kwargs)
    return result['content']


def call_openai(messages: List[Dict[str, str]], **kwargs) -> str:
    result = ai_service.call('openrouter', messages=messages, **kwargs)
    return result['content']
