import os
from email.utils import formataddr
from datetime import datetime, timezone
import pytz
import json
import time
import boto3
from shared.utils.response import create_response
# from shared.utils.logger import Logger  # Replaced with print statements
from shared.utils.text_utils import format_list_simple
from shared.db.queries import (
    get_run,
    get_editor_log,
    update_run_stage,
    update_brew_last_sent,
    mark_editor_email_sent,
)
from shared.utils.dynamo import to_iso


def format_email_html(editor_draft, brew_name, current_time):
    """
    Convert JSON editor draft into HTML email using TimeBrew template
    """
    intro = editor_draft.get("intro")
    articles = editor_draft.get("articles")
    outro = editor_draft.get("outro")

    # Format current date for header
    date_str = current_time.strftime("%A, %B %d")

    # Start building HTML
    html = f"""
    <div style="margin: 0 auto; font-family: 'Segoe UI', Tahoma, Arial, sans-serif; padding: 20px; background: transparent;">
        <!-- Header -->
        <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #e9ecef; margin-bottom: 24px; background: transparent;">
            <h1 style="font-size: 20px; font-weight: 600; color: #1a252f; margin: 0;">Your {brew_name} • {date_str}</h1>
        </div>
        
        <!-- Personal Greeting -->
        <div style="margin-bottom: 24px; background: transparent;">
            <p style="font-size: 16px; line-height: 1.6; color: #2c3e50; margin: 0;">{intro}</p>
        </div>
    """

    # Add each article
    for article in articles:
        headline = article.get("headline", "")
        story_content = article.get("story_content", "")
        source = article.get("source", "")
        original_url = article.get("original_url")
        published_time = article.get("published_time", "")

        # Use published_time directly as it's already formatted (e.g., '3 days ago', 'hours ago')
        time_ago = published_time if published_time else ""

        # Source and time display
        source_time = source if source else "Unknown Source"
        if time_ago:
            source_time += f" • {time_ago}"

        # Read more link - only if we have a URL
        read_more_link = ""
        if original_url and original_url != "null" and original_url.strip():
            read_more_link = f"""
            <a href="{original_url}" style="color: #3498db; text-decoration: none; font-weight: 500; font-size: 15px;">
                Read the full story →
            </a>
            """

        # Add article card
        html += f"""
        <!-- Story Card -->
        <div style="padding: 20px; margin: 16px 0; border: 1px solid #e9ecef; border-radius: 8px; background: transparent;">
            <!-- SOURCE and TIME AGO -->
            <div style="font-size: 14px; color: #6c757d; margin-bottom: 8px; font-weight: 500;">
                {source_time}
            </div>
            <!-- HEADLINE -->
            <h3 style="font-size: 18px; font-weight: 600; margin: 0 0 12px 0; color: #1a252f; line-height: 1.4;">
                {headline}
            </h3>
            <!-- STORY CONTENT -->
            <p style="margin: 0 0 16px 0; line-height: 1.6; color: #2c3e50; font-size: 16px;">
                {story_content}
            </p>
            {read_more_link}
        </div>
        """

    # Add sign-off
    html += f"""
        <!-- Sign-off -->
        <div style="margin-top: 32px; padding-top: 20px; border-top: 1px solid #e9ecef; background: transparent;">
            <p style="font-size: 16px; line-height: 1.6; color: #2c3e50; margin: 0;">{outro}</p>
            <p style="font-size: 14px; color: #6c757d; margin: 8px 0 0 0;">Your TimeBrew Team</p>
        </div>
    </div>
    """

    return html


def lambda_handler(event, context):
    """
    Email Dispatcher Lambda Function
    Reads JSON editor draft from editor_logs, formats to HTML, and sends email
    """
    start_time = time.time()
    run_id = None

    try:
        print(f"[EMAIL_DISPATCHER] Email dispatcher started: {event}")
        # Extract run_id from event
        run_id = event.get("run_id")
        if not run_id:
            print(f"[EMAIL_DISPATCHER] ERROR: Missing run_id in event")
            return create_response(400, {"error": "run_id is required"})

        print(f"[EMAIL_DISPATCHER] Context set: run_id={run_id}")

        # Retrieve run data (with denormalized user/brew snapshot)
        run = get_run(run_id)
        if not run:
            print(f"[EMAIL_DISPATCHER] ERROR: Run not found in database")
            return create_response(404, {"error": "Run not found"})

        brew_id = run.get("brew_id")
        user_id = run.get("user_id")
        stage = run.get("current_stage")
        brew_name = run.get("brew_name")
        topics = run.get("topics")
        brew_timezone = run.get("timezone") or "UTC"
        email = run.get("email")
        first_name = run.get("first_name")
        last_name = run.get("last_name")

        if stage != "dispatcher":
            print(f"[EMAIL_DISPATCHER] ERROR: Invalid run stage: {stage}, expected dispatcher")
            return create_response(
                400,
                {"error": f"Run stage is {stage}, expected dispatcher"},
            )

        # Get editor draft from editor_logs
        print(f"[EMAIL_DISPATCHER] Retrieving editor draft from editor logs")
        try:
            editor_log = get_editor_log(run_id)
            if not editor_log:
                print(f"[EMAIL_DISPATCHER] ERROR: Editor log not found")
                return create_response(404, {"error": "Editor log not found"})

            # Use editorial_content if available, fallback to raw_llm_response
            editorial_content = editor_log.get("editorial_content")
            raw_llm_response = editor_log.get("raw_llm_response")

            if editorial_content:
                # editorial_content is already parsed JSON
                editor_draft = editorial_content
            elif raw_llm_response:
                # Fallback to parsing raw_llm_response for backward compatibility
                try:
                    if isinstance(raw_llm_response, str):
                        editor_draft = json.loads(raw_llm_response)
                    else:
                        editor_draft = raw_llm_response
                except json.JSONDecodeError as e:
                    print(f"[EMAIL_DISPATCHER] ERROR: Failed to parse raw_llm_response: {str(e)}")
                    return create_response(400, {"error": "Invalid editor draft content"})
            else:
                print(f"[EMAIL_DISPATCHER] ERROR: Missing editor draft content in editor logs")
                return create_response(400, {"error": "Missing editor draft content"})

        except Exception as e:
            print(f"[EMAIL_DISPATCHER] ERROR: Failed to retrieve editor log: {str(e)}")
            return create_response(500, {"error": "Failed to retrieve editor draft"})

        # editor_draft is already parsed from editorial_content or raw_llm_response above

        # Parse topics JSON if it exists
        if isinstance(topics, str):
            try:
                topics_list = json.loads(topics)
            except json.JSONDecodeError:
                topics_list = []
        elif topics is None:
            topics_list = []
        else:
            topics_list = topics

        topics_str = format_list_simple(topics_list)

        # Build user name
        user_name = (
            f"{first_name} {last_name}"
            if first_name and last_name
            else first_name or "there"
        )

        # Get current time in user's timezone for formatting
        user_tz = pytz.timezone(brew_timezone)
        current_time = datetime.now(user_tz)

        print(f"[EMAIL_DISPATCHER] Context updated: user_email={email}, user_name={user_name}")
        print(f"[EMAIL_DISPATCHER] Retrieved briefing data successfully: brew_name={brew_name}, articles_count={len(editor_draft.get('articles', []))}")

        # Generate HTML content and extract subject from JSON
        try:
            html_content = format_email_html(editor_draft, brew_name, current_time)
            subject_line = editor_draft.get("subject")

        except Exception as e:
            print(f"[EMAIL_DISPATCHER] ERROR: Error formatting email content: {str(e)}")
            return create_response(500, {"error": "Failed to format email content"})

        # Amazon SES configuration
        ses_region = os.environ.get("SES_REGION", os.environ.get("AWS_REGION", "us-east-1"))
        from_email = os.environ.get("SES_FROM_EMAIL", "no-reply@timebrew.news")
        from_name = os.environ.get("SES_FROM_NAME", "TimeBrew")
        source = formataddr((from_name, from_email))

        # Send email via SES
        print(f"[EMAIL_DISPATCHER] Attempting to send email via SES: from={from_email}, recipient={email}, subject_line={subject_line[:50] if subject_line else ''}")

        try:
            ses = boto3.client("ses", region_name=ses_region)
            ses.send_email(
                Source=source,
                Destination={"ToAddresses": [email]},
                Message={
                    "Subject": {"Data": subject_line or f"Your {brew_name}", "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html_content, "Charset": "UTF-8"}},
                },
            )

            delivery_status = "dispatched"
            error_message = None
            print(f"[EMAIL_DISPATCHER] Email sent successfully")

        except Exception as e:
            print(f"[EMAIL_DISPATCHER] ERROR: SES Error: {str(e)}, from={from_email}, error_type={type(e).__name__}")
            delivery_status = "failed"
            error_message = str(e)
            raise e

        # Get current time in user's timezone
        sent_at = current_time
        sent_at_iso = to_iso(sent_at)

        # Update tracking records with delivery status
        try:
            if delivery_status == "dispatched":
                update_run_stage(run_id, "completed")
                # Record last-sent on the brew (also bumps briefings_sent counter)
                update_brew_last_sent(user_id, brew_id, sent_at_iso)
                # Flag the editor log as sent
                mark_editor_email_sent(run_id, sent_at_iso)
            else:
                update_run_stage(run_id, "failed", failed_stage="dispatcher", error_message=error_message)

            print(f"[EMAIL_DISPATCHER] Updated run tracker and brew data: run_id={run_id}, stage={'completed' if delivery_status == 'dispatched' else 'failed'}")

        except Exception as update_error:
            print(f"[EMAIL_DISPATCHER] ERROR: Failed to update run tracker: {str(update_error)}")
            raise Exception(f"Failed to update run status: {str(update_error)}")

        # Calculate processing time
        end_time = time.time()
        processing_time = end_time - start_time

        print(f"[EMAIL_DISPATCHER] Email dispatch completed: delivery_status={delivery_status}, processing_time_seconds={round(processing_time, 2)}")

        if delivery_status == "dispatched":
            return {
                "statusCode": 200,
                "body": {
                    "message": "Email sent successfully",
                    "run_id": run_id,
                    "user_name": user_name,
                    "email": email,
                    "subject_line": subject_line,
                    "sent_at": sent_at.isoformat(),
                    "content_length": len(html_content),
                    "processing_time_seconds": round(processing_time, 2),
                },
            }
        else:
            return {
                "statusCode": 500,
                "body": {
                    "message": "Failed to send email",
                    "run_id": run_id,
                    "error": error_message,
                    "processing_time_seconds": round(processing_time, 2),
                },
            }

    except Exception as e:
        # Calculate processing time for failed request
        end_time = time.time()
        processing_time = end_time - start_time

        print(f"[EMAIL_DISPATCHER] ERROR: Error in email_dispatcher: {str(e)}, error_type={type(e).__name__}, processing_time_seconds={round(processing_time, 2)}")

        # Try to update run_tracker status to failed if we have run_id
        try:
            if run_id:
                print(f"[EMAIL_DISPATCHER] Updating run tracker status to failed")
                update_run_stage(run_id, "failed", failed_stage="dispatcher", error_message=str(e))
        except Exception as db_error:
            print(f"[EMAIL_DISPATCHER] ERROR: Failed to update run tracker status: {str(db_error)}")

        # Re-raise the exception to ensure Step Functions marks this as failed
        raise e
