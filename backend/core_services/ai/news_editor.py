import os
import json
import time
from datetime import datetime, timezone
import pytz
from shared.utils.response import create_response
from shared.utils.text_utils import format_list_simple
from shared.utils.ai_service import ai_service
from shared.utils.other_utils import format_time_ampm
from shared.db.queries import (
    get_run,
    get_curator_log,
    get_latest_completed_draft_for_brew,
    create_editor_log,
    update_editor_content,
    update_run_stage,
)
# from shared.utils.logger import logger


def lambda_handler(event, context):
    """
    News Editor Lambda Function
    Creates structured JSON content for TimeBrew briefings using AI.
    Reads from / writes to DynamoDB (run_tracker, curator_logs, editor_logs).
    """
    start_time = time.time()  # Use time.time() for precise millisecond calculation
    print(f"[NEWS_EDITOR] Request started - event: {event}, endpoint: ai/news_editor")

    run_id = None

    try:
        # Extract run_id from event
        run_id = event.get("run_id")
        if not run_id:
            print("[NEWS_EDITOR] ERROR: News editor failed: missing run_id in event")
            return create_response(400, {"error": "run_id is required"})

        # Retrieve run tracker (with denormalized user/brew snapshot)
        print("[NEWS_EDITOR] Retrieving run tracker and associated data")
        run = get_run(run_id)
        if not run:
            print("[NEWS_EDITOR] WARNING: Run not found for provided run_id")
            return create_response(404, {"error": "Run not found"})

        stage = run.get("current_stage")
        if stage != "editor":
            print(f"[NEWS_EDITOR] WARNING: Invalid run stage - run_id: {run_id}, current_stage: {stage}, expected_stage: editor")
            return create_response(400, {"error": f"Run stage is {stage}, expected editor"})

        brew_id = run.get("brew_id")
        user_id = run.get("user_id")
        brew_name = run.get("brew_name")
        topics = run.get("topics")
        delivery_time_raw = run.get("delivery_time")
        brew_timezone = run.get("timezone") or "UTC"
        email = run.get("email")
        first_name = run.get("first_name") or ""
        last_name = run.get("last_name") or ""

        print(f"[NEWS_EDITOR] Setting context - user_id: {user_id}, user_email: {email}, run_id: {run_id}, brew_id: {brew_id}")

        user_name = f"{first_name} {last_name}".strip()
        delivery_time = format_time_ampm(str(delivery_time_raw))

        # Retrieve raw articles and curator notes from curator_logs
        print("[NEWS_EDITOR] Retrieving articles from curator logs")
        try:
            curator_log = get_curator_log(run_id)
            if not curator_log:
                print(f"[NEWS_EDITOR] ERROR: No curator log found for run_id - run_id: {run_id}")
                return create_response(404, {"error": f"No curator log found for run_id {run_id}"})

            raw_articles = curator_log.get("raw_articles")
            curator_notes = curator_log.get("curator_notes") or ""

            print(f"[NEWS_EDITOR] Curator log retrieved successfully - run_id: {run_id}, articles_count: {len(raw_articles) if raw_articles else 0}")
        except Exception as curator_error:
            print(f"[NEWS_EDITOR] ERROR: Failed to retrieve curator log - error: {str(curator_error)}")
            return create_response(500, {"error": "Failed to retrieve curator data"})

        # Fetch the most recent prior editorial draft for this brew (for freshness)
        print("[NEWS_EDITOR] Fetching past editorial drafts for context")
        past_context_str = ""
        prior = get_latest_completed_draft_for_brew(brew_id, exclude_run_id=run_id)
        if prior:
            prior_draft, completed_at = prior
            if prior_draft:
                past_context_str = f"""
                Following was delivered on {completed_at.strftime('%Y-%m-%d %H:%M') if completed_at else 'previously'}:
                {prior_draft}

                Use this to ensure freshness and avoid repetition.
                """.strip()

        if isinstance(raw_articles, str):
            raw_articles = json.loads(raw_articles)

        # Get user timezone for personalization
        user_tz = pytz.timezone(brew_timezone)
        now = datetime.now(user_tz)

        # Parse topics
        if isinstance(topics, str):
            topics_list = json.loads(topics)
        elif topics is None:
            topics_list = []
        else:
            topics_list = topics

        topics_str = format_list_simple(topics_list)

        # Prepare articles text for AI processing
        if raw_articles:
            articles_text = "\n\n".join(
                [
                    f"Article {i+1}:\n"
                    f"Headline: {article['headline']}\n"
                    f"Summary: {article['summary']}\n"
                    f"Source: {article['source']}\n"
                    f"Published: {article['published_time']}\n"
                    f"URL: {article.get('url', 'N/A')}\n"
                    f"Relevance: {article['relevance']}"
                    for i, article in enumerate(raw_articles)
                ]
            )
        else:
            articles_text = "No articles found by curator - create valuable content anyway"

        prompt = f"""# TASK
You are the lead editor for TimeBrew, channeling that signature newsletter wit and obsession with impact. You're creating {user_name}'s "{brew_name}" briefing for {delivery_time} delivery.

# THE TIMEBREW VOICE
- **Your smartest, funniest friend explaining the news** - the one who makes complex stuff click with perfect analogies
- **Obsessed with "So what?"**
- **Balanced cultural references**
- **Insider knowledge, casual delivery**

# WRITING FORMULA (without explicit labels)
1. Hook — why should I care?
2. What happened? (concise facts)
3. Impact — money, life, future, bigger picture
4. Sticky takeaway (one-liner)
5. Transitions — Find nice ways to transition from one story to another and dont start are the article the same exact way!

# HUMOR DOs / DON'Ts
✅ Smart observation: "It's like Spotify for logistics."
✅ Relatable metaphor: "Playing economic Jenga."
❌ Forced pun: "It's a real game-changer!"
❌ Inside-baseball jargon.

# ORDER BY "HOLY-SMOKES" FACTOR based on {user_name}'s preference
1. Breaking news that changes everything
2. Major shifts in {topics_str}
3. Trends that will matter in six months
4. "Huh, that's fascinating" nuggets

# CONTEXT
- Reader: {user_name} (cares about {topics_str})
- Local vibe: {brew_timezone} • {now.strftime('%A, %B %d at %I:%M %p')}
*Curator note*: {curator_notes if curator_notes and curator_notes.strip() else "Standard curation day"}

# OUTPUT FORMAT (MUST)
{{
    "subject": "Short inbox-stopping subject here",
    "intro": "Personal, energetic greeting for {user_name}.",
    "articles": [
        {{
        "headline": "Hooky headline",
        "story_content": "One–three sentences: impact → what → meaning → takeaway. **(without explicit labels)**",
        "original_url": "https://...",
        "source": "Publication name or 'TimeBrew Analysis'",
        "published_time": "e.g., '4 h ago', 'yesterday'",
        "type": "news" | "analysis" | "trend" | "education"
        }}
    ],
    "outro": "Send-off that leaves the reader smarter and smiling."
}}

# SOURCE MATERIAL
{articles_text}

# SELF-CHECK BEFORE RESPONDING
✓ Article count vs. day-type rule followed
✓ Each story answers the four writing-formula questions
✓ No duplicate companies or events
✓ Output is valid JSON (no markdown)

BEGIN JSON:"""

        # Load AI model configuration
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "ai_models.json",
        )
        with open(config_path, "r") as f:
            ai_models = json.load(f)

        editor_config = ai_models["editor"]
        provider = editor_config["provider"]
        model = editor_config["model"]

        # Call AI API using the configured service
        print(f"[NEWS_EDITOR] Preparing {provider.title()} API call for content creation")
        api_start_time = datetime.now(timezone.utc)

        try:
            ai_response_data = ai_service.call(
                provider,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert newsletter editor who creates engaging, Morning Brew-style briefings. You MUST respond with ONLY a valid JSON object using the exact structure provided. CRITICAL: Your response MUST start with { and end with }. Output ONLY valid JSON - no explanations, no markdown, no extra text.",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=model,
                temperature=0.7,
                max_tokens=3000,
            )
            ai_response = ai_response_data["content"]
            api_duration = (datetime.now(timezone.utc) - api_start_time).total_seconds() * 1000

            print(f"[NEWS_EDITOR] External API call: {provider.title()} /chat/completions POST 200 - duration: {api_duration}ms, model: {model}, prompt_tokens: {len(prompt.split())}")
            print(f"[NEWS_EDITOR] Received response from AI editor - response_length: {len(ai_response)}, content_preview: {ai_response[:200] + '...' if len(ai_response) > 200 else ai_response}")

            # Calculate runtime for editor operation
            editor_runtime_ms = int((time.time() - start_time) * 1000)

            # Store raw AI response immediately in editor_logs
            print("[NEWS_EDITOR] Storing raw AI response in editor logs")
            try:
                log_id = create_editor_log(
                    run_id=run_id,
                    user_id=user_id,
                    brew_id=brew_id,
                    prompt_used=prompt,
                    raw_llm_response=ai_response,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    delivery_time=delivery_time_raw,
                    runtime_ms=editor_runtime_ms,
                )
                print(f"[NEWS_EDITOR] Raw AI response stored in editor logs - run_id: {run_id}, log_id: {log_id}, runtime_ms: {editor_runtime_ms}")
            except Exception as log_error:
                print(f"[NEWS_EDITOR] ERROR: Failed to store raw AI response in editor logs - error: {str(log_error)}")
                raise Exception(f"Critical failure: Unable to store raw AI response: {str(log_error)}")

        except Exception as e:
            api_duration = (datetime.now(timezone.utc) - api_start_time).total_seconds() * 1000
            print(f"[NEWS_EDITOR] ERROR: {provider.title()} API request failed - error: {str(e)}, api_duration: {api_duration}ms")
            raise Exception(f"{provider.title()} API error: {str(e)}")

        # Parse the JSON response
        try:
            editor_draft = ai_service.parse_json_from_response(ai_response)

            # Validate required keys
            required_keys = ["intro", "articles", "outro"]
            for key in required_keys:
                if key not in editor_draft:
                    raise Exception(f"Missing required key: {key}")

            # Validate articles structure
            if not isinstance(editor_draft["articles"], list):
                raise Exception("Articles must be a list")

            for i, article in enumerate(editor_draft["articles"]):
                required_article_keys = ["headline", "story_content", "source"]
                for key in required_article_keys:
                    if key not in article:
                        raise Exception(f"Article {i+1} missing required key: {key}")

        except (ValueError, Exception) as e:
            print(f"[NEWS_EDITOR] ERROR: Failed to parse or validate AI response - error: {e}, content_preview: {ai_response[:500]}")
            raise Exception(f"Failed to process AI response: {str(e)}")

        # Update editor_logs with the parsed draft and advance run_tracker stage
        print("[NEWS_EDITOR] Updating editor logs with structured content")
        try:
            update_editor_content(run_id, editor_draft)
            update_run_stage(run_id, "dispatcher")
            print(f"[NEWS_EDITOR] DB operation: update editor_logs, run_tracker - run_id: {run_id}, status: dispatcher")
        except Exception as update_error:
            print(f"[NEWS_EDITOR] ERROR: Failed to update editor logs and run tracker - error: {str(update_error)}")
            raise Exception(f"Critical failure: Unable to update editor completion: {str(update_error)}")

        # Calculate processing time
        processing_time = time.time() - start_time

        print(f"[NEWS_EDITOR] Content creation completed successfully - run_id: {run_id}, processing_time_seconds: {round(processing_time, 2)}, articles_created: {len(editor_draft['articles'])}, brew_name: {brew_name}")
        print(f"[NEWS_EDITOR] Request ended - endpoint: ai/news_editor, status: 200, duration: {processing_time * 1000}ms")

        return {
            "statusCode": 200,
            "body": {
                "message": "Briefing content created successfully",
                "run_id": run_id,
                "user_name": user_name,
                "brew_name": brew_name,
                "articles_created": len(editor_draft["articles"]),
                "curator_notes": curator_notes,
                "intro_preview": (
                    editor_draft["intro"][:100] + "..."
                    if len(editor_draft["intro"]) > 100
                    else editor_draft["intro"]
                ),
                "processing_time_seconds": round(processing_time, 2),
                "editor_draft": editor_draft,  # Include full content for debugging
            },
        }

    except Exception as e:
        print(f"[NEWS_EDITOR] ERROR: News editor failed: unexpected error - error: {e}")

        # Update run_tracker to failed state if run_id exists
        try:
            if run_id:
                update_run_stage(run_id, "failed", failed_stage="editor", error_message=str(e))
                print(f"[NEWS_EDITOR] Updated run tracker to failed state - run_id: {run_id}")
        except Exception as tracker_error:
            print(f"[NEWS_EDITOR] ERROR: Failed to update run tracker to failed state - error: {tracker_error}")

        # Calculate processing time for error response
        processing_time = time.time() - start_time
        print(f"[NEWS_EDITOR] Request ended - endpoint: ai/news_editor, status: 500, duration: {processing_time * 1000}ms")

        # Re-raise the exception to ensure Step Functions marks this as failed
        raise e
