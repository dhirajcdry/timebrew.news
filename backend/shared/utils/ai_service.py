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
                        system: str = None,
                        model: str = "openai/gpt-4",
                        temperature: float = 0.7,
                        max_tokens: int = 3000,
                        timeout: int = 60,
                        max_retries: int = 3) -> Dict[str, Any]:
        """Call OpenRouter's OpenAI-compatible Chat Completions API with retries.

        Accepts either a single `prompt` string (wrapped into a user message) or
        a pre-built `messages` list. An optional `system` message is prepended
        when using `prompt`.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise AIServiceError("OPENROUTER_API_KEY not found in environment variables")

        if messages is None:
            if prompt is None:
                raise AIServiceError("Either 'prompt' or 'messages' must be provided")
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

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
                finish_reason = response.choices[0].finish_reason
                print(f"[AI_SERVICE] OpenRouter response received - response_length: {len(content)}, model: {model}, attempt: {attempt + 1}, finish_reason: {finish_reason}")

                # A "length" finish means max_tokens cut the response off mid-way,
                # which usually yields truncated/invalid JSON. Surface it loudly
                # instead of letting the downstream JSON parse fail cryptically.
                if finish_reason == "length":
                    print(f"[AI_SERVICE] WARNING: Response truncated by max_tokens={max_tokens} (finish_reason=length) — output is likely incomplete JSON")

                return {
                    "content": content,
                    "model": model,
                    "provider": "openrouter",
                    "usage": response.usage.model_dump() if response.usage else {},
                    "finish_reason": finish_reason,
                    "raw_response": None,
                }

            # OpenRouter routinely returns transient 5xx (InternalServerError)
            # during model cold-routing — retry those alongside timeouts/rate limits.
            except (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as e:
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

    @staticmethod
    def _extract_balanced(text: str, open_ch: str, close_ch: str):
        """Return the first balanced open_ch..close_ch span, respecting strings.

        Unlike find/rfind this won't be fooled by stray braces in trailing prose
        (e.g. "... {smile}") because it tracks nesting depth and skips quoted
        content and escapes.
        """
        start = text.find(open_ch)
        if start == -1:
            return None
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
        return None

    def parse_json_from_response(self, content: str) -> Dict[str, Any]:
        """Parse a JSON object from an LLM response, handling common quirks."""
        print("[AI_SERVICE] Attempting to parse JSON from AI response")
        # Strip reasoning blocks some models emit.
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        content_clean = content.strip()

        # Models like perplexity/sonar-pro wrap JSON in prose + citations and
        # often fence it. Try strategies from most to least reliable.
        candidates = []

        # 1. Content inside a ```json ... ``` (or bare ```) fenced block.
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content_clean, re.DOTALL)
        if fenced:
            candidates.append(fenced.group(1).strip())

        # 2. The whole thing, in case it's already clean JSON.
        candidates.append(content_clean)

        # 3. The first *balanced* object, then array — prose with stray braces
        #    can't corrupt these (object preferred so we keep the full shape).
        candidates.append(self._extract_balanced(content_clean, "{", "}"))
        candidates.append(self._extract_balanced(content_clean, "[", "]"))

        last_error = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                response_data = json.loads(candidate)
                print("[AI_SERVICE] Successfully parsed JSON from AI response")
                return response_data
            except json.JSONDecodeError as e:
                last_error = e

        print(f"[AI_SERVICE] ERROR: Failed to parse JSON from AI response - error: {str(last_error)}, content_preview: {content[:500]}")
        raise ValueError(f"Failed to parse JSON from AI response: {str(last_error)}")


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
