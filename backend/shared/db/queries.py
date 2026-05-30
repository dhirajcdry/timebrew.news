"""DynamoDB data-access layer for TimeBrew.

Replaces the previous Postgres/psycopg2 implementation. Relational joins and
aggregations are gone; instead we use per-entity tables with GSIs and a few
denormalized snapshots (most importantly, the user+brew fields are snapshotted
onto the run_tracker item at run creation so the AI pipeline stages need no
cross-table reads).

`OptimizedQueries` keeps the exact method signatures and return shapes the API
handlers expect (tuples with datetime objects), so the handlers are untouched.
The module-level functions are the cleaner repository API used by the rewritten
schedulers / pipeline / auth code.

Table / index layout (see backend/serverless.yml):
  users         PK id                | GSI cognito_id-index (cognito_id), email-index (email)
  brews         PK user_id, SK id    | GSI id-index (id), active-index (active_flag, delivery_time)
  run_tracker   PK run_id            | GSI brew-index (brew_id, created_at), user-index (user_id, created_at)
  curator_logs  PK run_id            | GSI user-index (user_id, created_at)
  editor_logs   PK run_id            | GSI editorial-index (id), userbrew-index (user_brew, created_at),
                                       brew-index (brew_id, created_at)
  user_feedback PK editorial_id, SK sk(user_id#position) | GSI user-index (user_id, created_at)
"""
import json

from boto3.dynamodb.conditions import Key

from shared.utils.dynamo import (
    table,
    new_id,
    now_iso,
    parse_dt,
    to_int,
    compact,
)

ACTIVE_STAGES = ("curator", "editor", "dispatcher")
_FEEDBACK_OVERALL = "overall"  # SK marker for briefing-level (positionless) feedback


def _feedback_sk(user_id, article_position):
    """Build the user_feedback sort key (one item per user+editorial+position)."""
    if article_position is None:
        return f"{user_id}#{_FEEDBACK_OVERALL}"
    return f"{user_id}#{int(article_position)}"


# =============================================================================
# USERS
# =============================================================================

def create_user(cognito_id, email, first_name, last_name, country, interests, timezone):
    """Insert a user record. Returns (user_id, created_at_datetime)."""
    user_id = new_id()
    created = now_iso()
    table("users").put_item(
        Item=compact({
            "id": user_id,
            "cognito_id": cognito_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "country": country,
            "interests": interests or [],
            "timezone": timezone or "UTC",
            "is_active": True,
            "created_at": created,
            "updated_at": created,
        }),
        ConditionExpression="attribute_not_exists(id)",
    )
    return user_id, parse_dt(created)


def get_user_by_cognito_id(cognito_id):
    """Look up an active user by Cognito sub. Returns the item dict or None."""
    resp = table("users").query(
        IndexName="cognito_id-index",
        KeyConditionExpression=Key("cognito_id").eq(cognito_id),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    user = items[0]
    if not user.get("is_active", True):
        return None
    return user


def get_user_by_id(user_id):
    """Get a user item by primary key, or None."""
    resp = table("users").get_item(Key={"id": user_id})
    return resp.get("Item")


# =============================================================================
# BREWS
# =============================================================================

def get_brew_by_id(brew_id):
    """Look up a brew by its id alone (no user context) via the id-index."""
    resp = table("brews").query(
        IndexName="id-index",
        KeyConditionExpression=Key("id").eq(brew_id),
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def get_brew(user_id, brew_id):
    """Get a brew by its composite key (implicit ownership)."""
    resp = table("brews").get_item(Key={"user_id": user_id, "id": brew_id})
    return resp.get("Item")


def list_active_brews():
    """Return all active brews (sparse active-index). Used by the scheduler."""
    items = []
    kwargs = {
        "IndexName": "active-index",
        "KeyConditionExpression": Key("active_flag").eq("ACTIVE"),
    }
    while True:
        resp = table("brews").query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def update_brew_last_sent(user_id, brew_id, sent_at_iso):
    """Record the last successful delivery time and bump the briefings counter."""
    table("brews").update_item(
        Key={"user_id": user_id, "id": brew_id},
        UpdateExpression=(
            "SET last_sent_date = :d, updated_at = :u "
            "ADD briefings_sent :one"
        ),
        ExpressionAttributeValues={":d": sent_at_iso, ":u": now_iso(), ":one": 1},
    )


# =============================================================================
# RUN TRACKER
# =============================================================================

def create_run(brew_id, user_id, snapshot=None):
    """Create a run_tracker item (stage='curator'). `snapshot` denormalizes the
    user/brew fields the pipeline needs so later stages avoid cross-table reads.
    Returns the new run_id."""
    run_id = new_id()
    created = now_iso()
    item = {
        "run_id": run_id,
        "brew_id": brew_id,
        "user_id": user_id,
        "current_stage": "curator",
        "created_at": created,
        "updated_at": created,
    }
    if snapshot:
        item.update(snapshot)
    table("run_tracker").put_item(Item=compact(item))
    return run_id


def get_run(run_id):
    """Get a run_tracker item by run_id, or None."""
    resp = table("run_tracker").get_item(Key={"run_id": run_id})
    return resp.get("Item")


def get_active_run_for_brew(brew_id):
    """Most recent run for a brew that is still in an active stage, else None."""
    resp = table("run_tracker").query(
        IndexName="brew-index",
        KeyConditionExpression=Key("brew_id").eq(brew_id),
        ScanIndexForward=False,
        Limit=10,
    )
    for item in resp.get("Items", []):
        if item.get("current_stage") in ACTIVE_STAGES:
            return item
    return None


def update_run_stage(run_id, stage, failed_stage=None, error_message=None):
    """Advance (or fail) a run's stage."""
    expr = "SET current_stage = :s, updated_at = :u"
    values = {":s": stage, ":u": now_iso()}
    if failed_stage is not None:
        expr += ", failed_stage = :fs, error_message = :em"
        values[":fs"] = failed_stage
        values[":em"] = error_message
    table("run_tracker").update_item(
        Key={"run_id": run_id},
        UpdateExpression=expr,
        ExpressionAttributeValues=values,
    )


# =============================================================================
# CURATOR LOGS
# =============================================================================

def create_curator_log(run_id, user_id, raw_articles, topics_searched,
                       article_count, prompt_used, raw_llm_response,
                       curator_notes, runtime_ms):
    """Insert a curator_log. raw_articles is stored as a JSON string."""
    log_id = new_id()
    table("curator_logs").put_item(Item=compact({
        "run_id": run_id,
        "id": log_id,
        "user_id": user_id,
        "raw_articles": json.dumps(raw_articles or []),
        "topics_searched": topics_searched or [],
        "article_count": int(article_count or 0),
        "prompt_used": prompt_used,
        "raw_llm_response": raw_llm_response,
        "curator_notes": curator_notes or "",
        "runtime_ms": int(runtime_ms or 0),
        "created_at": now_iso(),
    }))
    return log_id


def update_curator_log(run_id, raw_articles, curator_notes, runtime_ms):
    """Update a curator_log with parsed articles."""
    table("curator_logs").update_item(
        Key={"run_id": run_id},
        UpdateExpression="SET raw_articles = :a, curator_notes = :n, runtime_ms = :r",
        ExpressionAttributeValues={
            ":a": json.dumps(raw_articles or []),
            ":n": curator_notes or "",
            ":r": int(runtime_ms or 0),
        },
    )


def get_curator_log(run_id):
    """Get a curator_log by run_id with raw_articles decoded to a list, or None."""
    resp = table("curator_logs").get_item(Key={"run_id": run_id})
    item = resp.get("Item")
    if not item:
        return None
    item["raw_articles"] = _load_json(item.get("raw_articles"), [])
    return item


def list_recent_curator_articles_for_user(user_id, limit=5):
    """Return [(articles_list, updated_at_datetime)] for a user's most recent
    curator logs — used to build the curator's no-repeat list."""
    resp = table("curator_logs").query(
        IndexName="user-index",
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    out = []
    for item in resp.get("Items", []):
        out.append((_load_json(item.get("raw_articles"), []),
                    parse_dt(item.get("created_at"))))
    return out


# =============================================================================
# EDITOR LOGS
# =============================================================================

def create_editor_log(run_id, user_id, brew_id, prompt_used, raw_llm_response,
                      email=None, first_name=None, last_name=None,
                      delivery_time=None, runtime_ms=0):
    """Insert an editor_log. Returns the editorial_id (the item's `id`)."""
    editorial_id = new_id()
    table("editor_logs").put_item(Item=compact({
        "run_id": run_id,
        "id": editorial_id,
        "user_id": user_id,
        "brew_id": brew_id,
        "user_brew": f"{user_id}#{brew_id}",
        "prompt_used": prompt_used,
        "raw_llm_response": raw_llm_response,
        "editorial_content": None,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "delivery_time": delivery_time,
        "email_sent": False,
        "email_sent_time": None,
        "runtime_ms": int(runtime_ms or 0),
        "created_at": now_iso(),
    }))
    return editorial_id


def update_editor_content(run_id, editorial_content):
    """Store the parsed editorial content (JSON string) on the editor_log."""
    table("editor_logs").update_item(
        Key={"run_id": run_id},
        UpdateExpression="SET editorial_content = :c",
        ExpressionAttributeValues={":c": json.dumps(editorial_content)},
    )


def mark_editor_email_sent(run_id, sent_at_iso):
    """Flag the editor_log as sent."""
    table("editor_logs").update_item(
        Key={"run_id": run_id},
        UpdateExpression="SET email_sent = :t, email_sent_time = :s",
        ExpressionAttributeValues={":t": True, ":s": sent_at_iso},
    )


def get_editor_log(run_id):
    """Get an editor_log by run_id with editorial_content decoded, or None."""
    resp = table("editor_logs").get_item(Key={"run_id": run_id})
    item = resp.get("Item")
    if not item:
        return None
    item["editorial_content"] = _load_json(item.get("editorial_content"), None)
    return item


def get_editor_log_by_editorial_id(editorial_id):
    """Get an editor_log by its editorial id (the `id` attribute), or None."""
    resp = table("editor_logs").query(
        IndexName="editorial-index",
        KeyConditionExpression=Key("id").eq(editorial_id),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    item = items[0]
    item["editorial_content"] = _load_json(item.get("editorial_content"), None)
    return item


def get_latest_completed_draft_for_brew(brew_id, exclude_run_id=None):
    """Most recent prior editorial raw response for a brew (for editor context).
    Returns (raw_llm_response, completed_at_datetime) or None."""
    resp = table("editor_logs").query(
        IndexName="brew-index",
        KeyConditionExpression=Key("brew_id").eq(brew_id),
        ScanIndexForward=False,
        Limit=5,
    )
    for item in resp.get("Items", []):
        if item.get("run_id") == exclude_run_id:
            continue
        if item.get("raw_llm_response"):
            return item.get("raw_llm_response"), parse_dt(item.get("created_at"))
    return None


# =============================================================================
# USER FEEDBACK (low-level used by curator personalization)
# =============================================================================

def list_recent_feedback_for_user(user_id, limit=10):
    """Return [(feedback_type, article_position)] for a user's recent feedback."""
    resp = table("user_feedback").query(
        IndexName="user-index",
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    out = []
    for item in resp.get("Items", []):
        pos = item.get("article_position")
        out.append((item.get("feedback_type"), to_int(pos, None) if pos is not None else None))
    return out


# =============================================================================
# Helpers
# =============================================================================

def _load_json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


# =============================================================================
# OptimizedQueries — handler-facing API (return shapes preserved exactly)
# =============================================================================

class OptimizedQueries:
    """Handler-facing queries. Return shapes mirror the legacy Postgres rows so
    the API handlers (brews/get, briefings/*, feedback/*) remain unchanged."""

    @staticmethod
    def get_briefings_for_user(user_id, brew_id, limit=20, offset=0):
        """Briefings list for a user+brew, newest first, offset-paginated.

        Returns rows of:
        (run_id, editorial_content, email_sent, email_sent_time, created_at,
         total_count, editorial_id)
        """
        # Fetch enough items to satisfy the requested offset window, then slice.
        resp = table("editor_logs").query(
            IndexName="userbrew-index",
            KeyConditionExpression=Key("user_brew").eq(f"{user_id}#{brew_id}"),
            ScanIndexForward=False,
            Limit=offset + limit,
        )
        items = resp.get("Items", [])
        total_count = len(items)
        window = items[offset:offset + limit]
        rows = []
        for item in window:
            rows.append((
                item.get("run_id"),
                _load_json(item.get("editorial_content"), None),
                bool(item.get("email_sent")),
                parse_dt(item.get("email_sent_time")),
                parse_dt(item.get("created_at")),
                total_count,
                item.get("id"),
            ))
        return rows

    @staticmethod
    def get_briefing_by_id(user_id, run_id):
        """Single briefing with denormalized user/brew fields, or None.

        Returns:
        (run_id, brew_id, editorial_content, email_sent, email_sent_time,
         created_at, email, first_name, last_name, delivery_time, last_sent_date)
        """
        item = get_editor_log(run_id)
        if not item or item.get("user_id") != user_id:
            return None
        # last_sent_date lives on the brew; fetch it (cheap GetItem).
        last_sent_date = None
        brew = get_brew(user_id, item.get("brew_id"))
        if brew:
            last_sent_date = parse_dt(brew.get("last_sent_date"))
        return (
            item.get("run_id"),
            item.get("brew_id"),
            item.get("editorial_content"),
            bool(item.get("email_sent")),
            parse_dt(item.get("email_sent_time")),
            parse_dt(item.get("created_at")),
            item.get("email"),
            item.get("first_name"),
            item.get("last_name"),
            item.get("delivery_time"),
            last_sent_date,
        )

    @staticmethod
    def get_user_brews(user_id):
        """All brews for a user, newest first.

        Returns rows of:
        (id, name, topics, delivery_time, created_at, is_active, briefings_sent)
        """
        resp = table("brews").query(
            KeyConditionExpression=Key("user_id").eq(user_id),
        )
        items = resp.get("Items", [])
        items.sort(key=lambda b: b.get("created_at") or "", reverse=True)
        rows = []
        for b in items:
            rows.append((
                b.get("id"),
                b.get("name"),
                b.get("topics") if isinstance(b.get("topics"), list) else [],
                b.get("delivery_time"),
                parse_dt(b.get("created_at")),
                bool(b.get("is_active", True)),
                to_int(b.get("briefings_sent"), 0),
            ))
        return rows

    @staticmethod
    def get_feedback_status(user_id, editorial_id):
        """Feedback status for an editorial. Returns (article_count, feedback_data)
        where feedback_data is a list of {position, feedback, title, source} (or
        None), mirroring the legacy aggregation. Returns None if editorial missing."""
        editor = get_editor_log_by_editorial_id(editorial_id)
        if not editor:
            return None
        content = editor.get("editorial_content") or {}
        article_count = len(content.get("articles", [])) if content else 0

        resp = table("user_feedback").query(
            KeyConditionExpression=(
                Key("editorial_id").eq(editorial_id) & Key("sk").begins_with(f"{user_id}#")
            ),
        )
        feedback_data = []
        for item in resp.get("Items", []):
            pos = item.get("article_position")
            feedback_data.append({
                "position": to_int(pos, None) if pos is not None else None,
                "feedback": item.get("feedback_type"),
                "title": item.get("article_title"),
                "source": item.get("article_source"),
            })
        return article_count, (feedback_data or None)

    @staticmethod
    def submit_feedback(user_id, editorial_id, feedback_type, article_position=None,
                       source_url=None, article_title=None, article_source=None):
        """Toggle/upsert feedback. Returns (feedback_id, action) where action is
        one of 'removed' | 'updated' | 'submitted'."""
        tbl = table("user_feedback")
        sk = _feedback_sk(user_id, article_position)
        existing = tbl.get_item(Key={"editorial_id": editorial_id, "sk": sk}).get("Item")

        if existing:
            if existing.get("feedback_type") == feedback_type:
                tbl.delete_item(Key={"editorial_id": editorial_id, "sk": sk})
                return None, "removed"
            tbl.update_item(
                Key={"editorial_id": editorial_id, "sk": sk},
                UpdateExpression="SET feedback_type = :t, created_at = :c",
                ExpressionAttributeValues={":t": feedback_type, ":c": now_iso()},
            )
            return existing.get("id"), "updated"

        feedback_id = new_id()
        tbl.put_item(Item=compact({
            "editorial_id": editorial_id,
            "sk": sk,
            "id": feedback_id,
            "user_id": user_id,
            "article_position": article_position,
            "feedback_type": feedback_type,
            "source_url": source_url,
            "article_title": article_title,
            "article_source": article_source,
            "created_at": now_iso(),
        }))
        return feedback_id, "submitted"

    @staticmethod
    def create_brew(user_id, name, topics, delivery_time):
        """Create a brew. Returns the new brew id."""
        return create_brew_item(user_id, name, topics, delivery_time)


def create_brew_item(user_id, name, topics, delivery_time):
    """Create a brew record (active). Returns the new brew id."""
    brew_id = new_id()
    created = now_iso()
    table("brews").put_item(Item=compact({
        "user_id": user_id,
        "id": brew_id,
        "name": name,
        "topics": topics or [],
        "delivery_time": delivery_time,
        "article_count": 5,
        "is_active": True,
        "active_flag": "ACTIVE",
        "briefings_sent": 0,
        "last_sent_date": None,
        "created_at": created,
        "updated_at": created,
    }))
    return brew_id
