"""Validate, render and deliver source-backed TimeBrew briefings through SES."""

import json
import os
import re
import time
from datetime import datetime
from email.utils import formataddr

import boto3
import pytz

from shared.db.queries import (
    get_run,
    get_curator_log,
    get_editor_log,
    update_run_stage,
    update_brew_last_sent,
    mark_editor_email_sent,
)
from shared.utils.dynamo import to_iso
from shared.utils.html_email import format_email_html, format_email_text, plain_text
from shared.utils.provenance import requested_article_count, validate_editor_draft
from shared.utils.response import create_response


def _decode(value, label):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid {label} JSON") from error
    return value


def lambda_handler(event, context):
    """Fail closed before SES if provenance or editorial structure is invalid.

    A persisted sent flag prevents sequential replay after acknowledged sends.
    SES and DynamoDB are not atomic: a crash after SES accepts a message but
    before the flag is persisted can still duplicate it. Concurrent invocations
    need a durable dispatch/outbox design; this guard does not claim exactly-once
    delivery. SES acceptance also does not establish inbox delivery.
    """
    start_time = time.time()
    run_id = event.get("run_id")
    if not run_id:
        return create_response(400, {"error": "run_id is required"})

    try:
        run = get_run(run_id)
        if not run:
            raise ValueError("Run not found")
        editor_log = get_editor_log(run_id)
        if not editor_log:
            raise ValueError("Editor log not found")

        # Check before stage/provenance validation, so an already-sent legacy
        # run never gets sent again just because its content shape changed.
        if editor_log.get("email_sent") is True:
            if run.get("current_stage") != "completed":
                sent_at_iso = editor_log.get("email_sent_time")
                if not sent_at_iso:
                    raise ValueError("Sent email is missing its timestamp; no email was resent")
                # Timestamp-idempotent bookkeeping repairs a partial previous
                # attempt without incrementing the count or sending again.
                update_brew_last_sent(run.get("user_id"), run.get("brew_id"), sent_at_iso)
                update_run_stage(run_id, "completed")
            print(f"[EMAIL_DISPATCHER] Skipping already-sent run: {run_id}")
            return {
                "statusCode": 200,
                "body": {"message": "Email already sent", "run_id": run_id, "already_sent": True},
            }

        if run.get("current_stage") != "dispatcher":
            raise ValueError(f"Run stage is {run.get('current_stage')}, expected dispatcher")

        draft_content = editor_log.get("editorial_content")
        if draft_content is None:
            draft_content = editor_log.get("raw_llm_response")
        editor_draft = _decode(draft_content, "editor draft")
        curator_log = get_curator_log(run_id)
        if not curator_log:
            raise ValueError("Cannot dispatch without the curated source records")
        curated_articles = _decode(curator_log.get("raw_articles"), "curated articles")
        desired_count = requested_article_count(run.get("article_count"))
        editor_draft = validate_editor_draft(editor_draft, curated_articles, desired_count=desired_count)
        if not editor_draft.get("articles"):
            raise ValueError("No source-backed articles are available; no email was sent")

        email = run.get("email")
        if not isinstance(email, str) or not email.strip():
            raise ValueError("Missing recipient email")
        brew_name = run.get("brew_name") or "Your daily brew"
        current_time = datetime.now(pytz.timezone(run.get("timezone") or "UTC"))
        html_content = format_email_html(editor_draft, brew_name, current_time)
        text_content = format_email_text(editor_draft, brew_name, current_time)
        subject_line = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", plain_text(editor_draft.get("subject"))).split())
        subject_line = (subject_line or f"Your {plain_text(brew_name)}")[:180]

        ses_region = os.environ.get("SES_REGION", os.environ.get("AWS_REGION", "us-east-1"))
        from_email = os.environ.get("SES_FROM_EMAIL", "no-reply@timebrew.news")
        from_name = os.environ.get("SES_FROM_NAME", "TimeBrew")
        ses = boto3.client("ses", region_name=ses_region)
        response = ses.send_email(
            Source=formataddr((from_name, from_email)),
            Destination={"ToAddresses": [email]},
            Message={
                "Subject": {"Data": subject_line, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_content, "Charset": "UTF-8"},
                    "Html": {"Data": html_content, "Charset": "UTF-8"},
                },
            },
        )

        sent_at_iso = to_iso(current_time)
        # Persist the replay guard first, before counters or run bookkeeping.
        mark_editor_email_sent(run_id, sent_at_iso)
        update_brew_last_sent(run.get("user_id"), run.get("brew_id"), sent_at_iso)
        update_run_stage(run_id, "completed")
        print(f"[EMAIL_DISPATCHER] SES accepted run: {run_id}")
        return {
            "statusCode": 200,
            "body": {
                "message": "Email accepted by SES",
                "run_id": run_id,
                "email": email,
                "subject_line": subject_line,
                "sent_at": current_time.isoformat(),
                "message_id": response.get("MessageId"),
                "content_length": len(html_content),
                "processing_time_seconds": round(time.time() - start_time, 2),
            },
        }
    except Exception as error:
        print(f"[EMAIL_DISPATCHER] Dispatch failed for run {run_id}: {type(error).__name__}: {error}")
        try:
            update_run_stage(run_id, "failed", failed_stage="dispatcher", error_message=str(error))
        except Exception as tracking_error:
            print(f"[EMAIL_DISPATCHER] Could not record failure for {run_id}: {type(tracking_error).__name__}")
        # A 4xx/5xx-shaped return is still a successful Lambda invocation. Raise
        # so Step Functions follows its failure path rather than completing it.
        raise
