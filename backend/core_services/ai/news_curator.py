import os
import json
import time
from datetime import datetime, timedelta, timezone
import pytz
from shared.utils.response import create_response
# from shared.utils.logger import logger  # Replaced with print statements
from shared.utils.ai_service import ai_service
from shared.utils.text_utils import format_list_with_quotes
from shared.utils.other_utils import format_time_ampm
from shared.db.queries import (
    get_run,
    get_brew_by_id,
    update_run_stage,
    create_curator_log,
    update_curator_log,
    list_recent_curator_articles_for_user,
    list_recent_feedback_for_user,
)
from shared.utils.dynamo import parse_dt


def lambda_handler(event, context):
    """
    News Curator Lambda Function
    Collects articles from AI and stores them in the curator_logs table (DynamoDB)
    """
    start_time = time.time()  # Use time.time() for precise millisecond calculation
    print(f"[NEWS_CURATOR] Request started: {event.get('brew_id', 'unknown')}")

    run_id = None

    try:
        # Extract and validate required parameters from event
        brew_id = event.get("brew_id")
        run_id = event.get("run_id")

        if not brew_id:
            print(f"[NEWS_CURATOR] ERROR: News collection failed: missing brew_id in event")
            return create_response(400, {"error": "brew_id is required"})

        if not run_id:
            print(f"[NEWS_CURATOR] ERROR: News collection failed: missing run_id in event")
            return create_response(400, {"error": "run_id is required"})

        print(f"[NEWS_CURATOR] Context set: brew_id={brew_id}, run_id={run_id}")

        # Validate that run_tracker exists and is in correct stage
        print(f"[NEWS_CURATOR] Validating run tracker state")
        run = get_run(run_id)
        if not run or run.get("brew_id") != brew_id:
            print(f"[NEWS_CURATOR] ERROR: Run tracker not found: run_id={run_id}, brew_id={brew_id}")
            return create_response(400, {"error": "Invalid run_id or brew_id"})

        current_stage = run.get("current_stage")
        if current_stage != "curator":
            print(f"[NEWS_CURATOR] ERROR: Invalid run tracker stage: current={current_stage}, expected=curator")
            return create_response(400, {"error": f"Invalid stage: {current_stage}, expected: curator"})
        print(f"[NEWS_CURATOR] Run tracker validation successful: stage={current_stage}")

        # Retrieve brew data (for active check + last_sent_date); user fields come
        # from the run snapshot.
        brew = get_brew_by_id(brew_id)
        if not brew or not brew.get("is_active", True):
            print(f"[NEWS_CURATOR] WARNING: Active brew not found for provided brew_id")
            return create_response(404, {"error": "Active brew not found"})

        user_id = run.get("user_id")
        brew_name = run.get("brew_name") or brew.get("name")
        topics = run.get("topics") if run.get("topics") is not None else brew.get("topics")
        delivery_time_raw = run.get("delivery_time") or brew.get("delivery_time")
        brew_timezone = run.get("timezone") or "UTC"
        email = run.get("email")
        first_name = run.get("first_name") or ""
        last_name = run.get("last_name") or ""
        last_sent_date = parse_dt(brew.get("last_sent_date"))

        print(f"[NEWS_CURATOR] Context updated: user_id={user_id}, email={email}, run_id={run_id}")

        delivery_time = format_time_ampm(str(delivery_time_raw))
        user_name = f"{first_name} {last_name}".strip()

        user_tz = pytz.timezone(brew_timezone)
        now = datetime.now(user_tz)

        # Parse topics
        if isinstance(topics, str):
            try:
                topics_list = json.loads(topics)
            except json.JSONDecodeError:
                topics_list = []
        elif topics is None:
            topics_list = []
        else:
            topics_list = topics

        print(
            f"[NEWS_CURATOR] Brew configuration loaded: brew_name={brew_name}, user_timezone={brew_timezone}, topics_count={len(topics_list)}"
        )

        # Calculate temporal context - database dates are UTC, convert to user timezone
        if last_sent_date:
            last_sent_user_tz = last_sent_date.replace(tzinfo=pytz.UTC).astimezone(user_tz)
            temporal_context = f"{last_sent_user_tz.strftime('%Y-%m-%d %H:%M %Z')} to {now.strftime('%Y-%m-%d %H:%M %Z')}"
        else:
            temporal_context = "past 3 days"

        # Get previous articles for context (avoid duplicates)
        print(f"[NEWS_CURATOR] Retrieving previous articles for context")
        previous_articles = []
        no_go_items = []

        for articles_data, sent_at in list_recent_curator_articles_for_user(user_id, limit=5):
            if not articles_data:
                continue
            if isinstance(articles_data, str):
                articles_data = json.loads(articles_data)

            for article in articles_data:
                headline = article.get("headline", "")
                url = article.get("url", "")
                sent_date = sent_at.strftime("%Y-%m-%d") if sent_at else "Unknown"
                source = article.get("source", "")

                previous_articles.append({
                    "headline": headline,
                    "url": url,
                    "sent_date": sent_date,
                    "source": source,
                })
                no_go_items.append(f'"{headline} ({url})"')

        # Get user feedback for personalization
        print(f"[NEWS_CURATOR] Retrieving user feedback for personalization")
        user_feedback = []
        for feedback_type, article_position in list_recent_feedback_for_user(user_id, limit=10):
            feedback_entry = {"type": feedback_type}
            if article_position:
                feedback_entry["article_position"] = article_position
            user_feedback.append(feedback_entry)

        # Format topics for prompt
        brew_focus_topics_str = format_list_with_quotes(topics_list)

        # Finalize NO-GO LIST
        if no_go_items:
            no_go_list = "Do not repeat these headlines/events:\n"
            for i, item in enumerate(no_go_items, 1):
                no_go_list += f"{i}. {item}\n"
        else:
            no_go_list = "No previous articles to avoid."

        # Build AI prompt using the exact tested template
        prompt = f"""# MISSION (MUST)
Return **3–8** distinct news stories for "{brew_name}" briefing that focuses on these topics- {brew_focus_topics_str}.
For broad or active topics there is almost always enough qualifying news — returning an empty "articles" array should be rare and is only allowed under the SLOW-DAY RULE below. Default to delivering articles.

# CONTEXT
- Reader: {user_name}
- Current local time: {now.strftime('%Y-%m-%d %H:%M %Z')}
- Time window: {temporal_context}
- Scheduled delivery: {delivery_time}

# NO-GO LIST (MUST NOT)
{no_go_list}

# DIVERSITY RULES (MUST)
1. Max one story per company / organization.
2. Use at least 3 different reputable publishers.
3. Cover user's interests and topics.
4. No duplicate events or announcements.

# QUALITY CRITERIA (SHOULD)
- Published within the specified window.
- Clear real-world impact.
- Well-known, reputable source.
- Never news aggregators or news summarizers, NEVER.

# SLOW-DAY RULE (MUST — GENUINE LAST RESORT)
This applies ONLY when, after relaxing the DIVERSITY RULES (e.g. allowing two stories from the same company or fewer publishers), you still genuinely cannot find **3** qualified stories in the window. Prefer returning articles — even slightly less diverse ones — over an empty list.
If and only if that genuine case holds:
- Return an empty `"articles"` array AND use `"curator_notes"` to explain the landscape: what's trending, why news is thin, references to the recent past. The more detail, the better the editor can write.

# OUTPUT FORMAT (MUST)
{{
    "articles": [
        {{
        "headline": "Article Title",
        "summary": "3-4 sentences summary on the article covering it end-to-end",
        "source": "Source of the original article",
        "published_time": "Relative article published time",
        "relevance": "Why is this story relevant for the {user_name}, and any other notes for the editor.",
        "url": "Actual working url to the original article"
        }}
    ],
    "curator_notes": "Brief insight about today's content landscape - availability, challenges, or trends you noticed. Anything to provide the Editor a good writing grounds!"
}}

# SELF-CHECK BEFORE RESPONDING
✓ 3–8 articles whenever they exist (the normal case); empty articles + detailed curator_notes ONLY for a genuine SLOW-DAY after relaxing diversity
✓ Look into a wide variety of news articles and pick only ones worth noting based on {user_name}'s interests
✓ No duplicate companies / events
✓ JSON parses without error
✓ Be sure to follow the time window- {temporal_context}

BEGIN JSON:"""

        # Load AI model configuration and make API call
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "ai_models.json",
        )
        with open(config_path, "r") as f:
            ai_models = json.load(f)

        curator_config = ai_models["curator"]
        provider = curator_config["provider"]
        model = curator_config["model"]

        print(f"[NEWS_CURATOR] Preparing {provider.title()} API call for article curation")
        api_start_time = datetime.now(timezone.utc)

        try:
            ai_response_data = ai_service.call(
                provider,
                prompt=prompt,
                system=(
                    "You are a precise JSON API. Respond with ONLY a single valid "
                    "JSON object matching the requested schema — no prose, no "
                    "markdown fences, no citations or source lists outside the JSON. "
                    "Start your response with { and end with }."
                ),
                model=model,
                temperature=0.2,
                max_tokens=4000,
                timeout=60,
            )
            content = ai_response_data["content"]
            api_duration = (datetime.now(timezone.utc) - api_start_time).total_seconds() * 1000

            print(f"[NEWS_CURATOR] {provider.title()} API call completed in {api_duration}ms")
        except Exception as e:
            api_duration = (datetime.now(timezone.utc) - api_start_time).total_seconds() * 1000
            print(f"[NEWS_CURATOR] ERROR: {provider.title()} API request failed: {str(e)}, duration: {api_duration}ms")
            raise Exception(f"{provider.title()} API error: {str(e)}")

        print(
            f"[NEWS_CURATOR] Received response from AI curator: length={len(content)}, preview={content[:200] + '...' if len(content) > 200 else content}"
        )

        # Calculate runtime for curator operation
        curator_runtime_ms = int((time.time() - start_time) * 1000)

        # Log raw LLM response immediately to ensure we have it even if parsing fails
        print(f"[NEWS_CURATOR] Logging raw LLM response to curator logs")
        try:
            log_id = create_curator_log(
                run_id=run_id,
                user_id=user_id,
                raw_articles=[],
                topics_searched=topics_list,
                article_count=0,
                prompt_used=prompt,
                raw_llm_response=content,
                curator_notes="",
                runtime_ms=curator_runtime_ms,
            )
            print(
                f"[NEWS_CURATOR] Raw LLM response successfully logged to curator logs: run_id={run_id}, log_id={log_id}, runtime_ms={curator_runtime_ms}"
            )
        except Exception as log_error:
            print(f"[NEWS_CURATOR] ERROR: Failed to log raw LLM response to curator logs: {str(log_error)}")
            raise Exception(f"Critical failure: Unable to log raw LLM response to database: {str(log_error)}")

        # Parse AI response
        print(f"[NEWS_CURATOR] Parsing articles from AI response")
        try:
            response_data = ai_service.parse_json_from_response(content)
        except ValueError as e:
            print(f"[NEWS_CURATOR] ERROR: Failed to parse JSON from AI response: {str(e)}")
            raise Exception(str(e))

        # Extract articles and curator notes. The model may return either an
        # {"articles": [...]} object or a bare [...] array; accept both.
        if isinstance(response_data, list):
            articles = response_data
            curator_notes = ""
        else:
            articles = response_data.get("articles", [])
            curator_notes = response_data.get("curator_notes", "") or ""

        print(
            f"[NEWS_CURATOR] Article curation completed: total_articles={len(articles)}, response_keys={list(response_data.keys()) if isinstance(response_data, dict) else 'list'}, curator_notes_provided={bool(curator_notes.strip())}"
        )

        # A genuine slow news day produces curator_notes explaining why; getting
        # neither articles nor notes means the response shape was wrong and we
        # silently lost the content. Fail loudly so it surfaces in the run.
        if not articles and not curator_notes.strip():
            raise Exception(
                "Curator returned no articles and no curator_notes — likely an "
                "unparseable or unexpected response shape (see raw_llm_response in curator log)"
            )

        # Update curator log with final parsed articles
        print(f"[NEWS_CURATOR] Updating curator log with parsed articles")
        final_runtime_ms = int((time.time() - start_time) * 1000)

        try:
            update_curator_log(run_id, articles, curator_notes, final_runtime_ms)
            # Advance run tracker to editor stage
            update_run_stage(run_id, "editor")
            print(
                f"[NEWS_CURATOR] Curator log updated successfully: run_id={run_id}, articles_stored={len(articles)}, final_runtime_ms={final_runtime_ms}"
            )
        except Exception as update_error:
            print(f"[NEWS_CURATOR] ERROR: Failed to update curator log: {str(update_error)}")
            raise Exception(f"Critical failure: Unable to update curator log: {str(update_error)}")

        # Calculate processing time
        processing_time = time.time() - start_time

        print(
            f"[NEWS_CURATOR] News collection completed successfully: run_id={run_id}, processing_time_seconds={round(processing_time, 2)}, articles_collected={len(articles)}, curator_notes={curator_notes}, temporal_context={temporal_context}, topics={topics_list}"
        )

        print(f"[NEWS_CURATOR] Request completed: ai/news_curator, status=200, duration={processing_time * 1000}ms")

        return {
            "statusCode": 200,
            "body": {
                "message": "Articles collected successfully",
                "run_id": run_id,
                "user_name": user_name,
                "brew_name": brew_name,
                "articles_collected": len(articles),
                "curator_notes": curator_notes,
                "topics": topics_list,
                "temporal_context": temporal_context,
                "processing_time_seconds": round(processing_time, 2),
            },
        }

    except Exception as e:
        print(f"[NEWS_CURATOR] ERROR: News collection failed: unexpected error: {str(e)}")

        # Update run tracker to failed state if we have a run_id
        if run_id:
            try:
                update_run_stage(run_id, "failed", failed_stage="curator", error_message=str(e))
                print(f"[NEWS_CURATOR] Run tracker updated to failed state: run_id={run_id}")
            except Exception as stage_error:
                print(f"[NEWS_CURATOR] ERROR: Failed to update run tracker to failed state: {str(stage_error)}")

        # Calculate processing time for failed request
        processing_time = time.time() - start_time
        print(f"[NEWS_CURATOR] Request failed: ai/news_curator, status=500, duration={processing_time * 1000}ms")

        raise e
