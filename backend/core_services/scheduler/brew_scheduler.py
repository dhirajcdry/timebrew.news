import os
import json
import boto3
from datetime import datetime, timedelta, timezone

import pytz

from shared.utils.response import create_response
from shared.db.queries import (
    list_active_brews,
    get_user_by_id,
    get_active_run_for_brew,
    create_run,
)
from shared.utils.dynamo import parse_dt
from core_services.scheduler.trigger_brew import build_run_snapshot, trigger_ai_pipeline

DELIVERY_WINDOW_MINUTES = 30


def _parse_delivery_time(delivery_time):
    """Parse a 'HH:MM:SS' delivery time into a time object (24:00:00 -> 00:00:00)."""
    value = str(delivery_time)
    if value.startswith("24"):
        value = "00" + value[2:]
    return datetime.strptime(value, "%H:%M:%S").time()


def is_brew_due(brew, user, now_utc):
    """Timezone-aware check (replaces the old SQL window query).

    Returns (due: bool, delivery_datetime_utc: datetime|None).
    A brew is due when its local delivery time falls within the next 30 minutes,
    it hasn't already been delivered today (user-local), and there is no run
    currently in progress for it.
    """
    if not user or not user.get("is_active", True):
        return False, None

    tz = pytz.timezone(user.get("timezone") or "UTC")
    now_local = now_utc.astimezone(tz)

    try:
        delivery_t = _parse_delivery_time(brew.get("delivery_time"))
    except (ValueError, TypeError):
        return False, None

    delivery_local = tz.localize(datetime.combine(now_local.date(), delivery_t))

    # Within the next 30 minutes?
    if not (now_local <= delivery_local <= now_local + timedelta(minutes=DELIVERY_WINDOW_MINUTES)):
        return False, None

    # Already delivered today (in the user's local date)?
    last_sent = parse_dt(brew.get("last_sent_date"))
    if last_sent is not None:
        last_sent_local_date = last_sent.replace(tzinfo=pytz.UTC).astimezone(tz).date()
        if last_sent_local_date >= now_local.date():
            return False, None

    # Already processing (a recent active run within 2 hours)?
    active_run = get_active_run_for_brew(brew.get("id"))
    if active_run is not None:
        created = parse_dt(active_run.get("created_at"))
        if created is not None and created > (now_utc.replace(tzinfo=None) - timedelta(hours=2)):
            return False, None

    return True, delivery_local.astimezone(pytz.UTC)


def lambda_handler(event, context):
    """
    Brew Scheduler Lambda Function
    Runs every 15 minutes to check for brews due in the next 30 minutes.
    Timezone-aware filtering is done in Python over the active-brews index.
    """
    start_time = datetime.now(timezone.utc)

    try:
        print(f"[BREW_SCHEDULER] Brew scheduler started - triggered_at: {start_time.isoformat()}")

        print("[BREW_SCHEDULER] Querying for active brews")
        query_start_time = datetime.now(timezone.utc)
        active_brews = list_active_brews()
        query_duration = (datetime.now(timezone.utc) - query_start_time).total_seconds() * 1000
        print(f"[BREW_SCHEDULER] Active brews retrieved: {len(active_brews)}, query_duration_ms: {round(query_duration, 2)}")

        triggered_brews = []
        failed_triggers = []

        # Cache users to avoid repeated lookups within one run
        user_cache = {}

        for brew in active_brews:
            brew_id = brew.get("id")
            user_id = brew.get("user_id")

            if user_id not in user_cache:
                user_cache[user_id] = get_user_by_id(user_id)
            user = user_cache[user_id]

            email = user.get("email") if user else None

            due, delivery_datetime_utc = is_brew_due(brew, user, start_time)
            if not due:
                continue

            first_name = user.get("first_name")
            last_name = user.get("last_name")
            user_name = (
                f"{first_name} {last_name}"
                if first_name and last_name
                else first_name or "User"
            )

            print(f"[BREW_SCHEDULER] Brew due - brew_id: {brew_id}, user_id: {user_id}, user_email: {email}")

            try:
                run_id = create_run(brew_id, user_id, snapshot=build_run_snapshot(brew, user))
                print(f"[BREW_SCHEDULER] Run tracker entry created - run_id: {run_id}, brew_id: {brew_id}")

                print(f"[BREW_SCHEDULER] Triggering AI pipeline - brew_name: {brew.get('name')}, user_timezone: {user.get('timezone')}, delivery_time: {brew.get('delivery_time')}, run_id: {run_id}")
                success, execution_arn = trigger_ai_pipeline(brew_id, run_id, "scheduler")

                if success:
                    triggered_brews.append({
                        "brew_id": brew_id,
                        "run_id": run_id,
                        "user_name": user_name,
                        "user_email": email,
                        "brew_name": brew.get("name"),
                        "timezone": user.get("timezone"),
                        "delivery_time": str(brew.get("delivery_time")),
                        "execution_arn": execution_arn,
                        "triggered_at": start_time.isoformat(),
                        "scheduled_delivery_utc": delivery_datetime_utc.isoformat() if delivery_datetime_utc else None,
                    })
                    print(f"[BREW_SCHEDULER] Successfully triggered AI pipeline - execution_arn: {execution_arn}")
                else:
                    failed_triggers.append({
                        "brew_id": brew_id,
                        "user_email": email,
                        "error": "Failed to start Step Functions execution",
                    })
                    print(f"[BREW_SCHEDULER] ERROR: Failed to trigger AI pipeline - brew_id: {brew_id}")

            except Exception as brew_error:
                failed_triggers.append({"brew_id": brew_id, "user_email": email, "error": str(brew_error)})
                print(f"[BREW_SCHEDULER] ERROR: Error processing brew - error: {str(brew_error)}, brew_id: {brew_id}")
                continue

        end_time = datetime.now(timezone.utc)
        processing_time = (end_time - start_time).total_seconds()

        print(f"[BREW_SCHEDULER] Brew scheduler completed - active_brews_checked: {len(active_brews)}, successful_triggers: {len(triggered_brews)}, failed_triggers: {len(failed_triggers)}, processing_time_seconds: {round(processing_time, 2)}")

        response_body = {
            "message": f"Scheduler completed - triggered {len(triggered_brews)} brews",
            "summary": {
                "total_brews_checked": len(active_brews),
                "successful_triggers": len(triggered_brews),
                "failed_triggers": len(failed_triggers),
                "processing_time_seconds": round(processing_time, 2),
            },
            "triggered_brews": triggered_brews,
            "failed_triggers": failed_triggers,
            "checked_at": start_time.isoformat(),
        }

        return create_response(200, response_body)

    except Exception as e:
        end_time = datetime.now(timezone.utc)
        processing_time = (end_time - start_time).total_seconds()

        print(f"[BREW_SCHEDULER] ERROR: Brew scheduler failed with unexpected error - error: {str(e)}, error_type: {type(e).__name__}, processing_time_seconds: {round(processing_time, 2)}")

        return create_response(
            500,
            {
                "error": str(e),
                "processing_time_seconds": round(processing_time, 2),
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
