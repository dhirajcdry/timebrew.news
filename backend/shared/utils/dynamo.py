"""Low-level DynamoDB access helpers.

Centralizes the boto3 resource, table-name resolution (from env vars set by
serverless.yml) and small conversion utilities shared by the data layer.

Timestamps are stored as naive-UTC ISO-8601 strings (microsecond precision) so
they sort lexicographically/chronologically when used as GSI sort keys and so
they preserve the naive-UTC semantics the legacy Postgres `timestamp` columns
had. `parse_dt` turns them back into datetime objects for the API handlers.
"""
import os
import uuid
from decimal import Decimal
from datetime import datetime, timezone

import boto3

_resource_cache = None


def _resource():
    global _resource_cache
    if _resource_cache is None:
        _resource_cache = boto3.resource("dynamodb")
    return _resource_cache


# Logical entity name -> env var holding the physical table name.
_TABLE_ENV = {
    "users": "USERS_TABLE",
    "brews": "BREWS_TABLE",
    "run_tracker": "RUN_TRACKER_TABLE",
    "curator_logs": "CURATOR_LOGS_TABLE",
    "editor_logs": "EDITOR_LOGS_TABLE",
    "user_feedback": "USER_FEEDBACK_TABLE",
}


def table(entity):
    """Return the boto3 Table handle for a logical entity name."""
    return _resource().Table(os.environ[_TABLE_ENV[entity]])


def new_id():
    """Generate a new UUID4 string (replaces Postgres gen_random_uuid())."""
    return str(uuid.uuid4())


def now_iso():
    """Current time as a naive-UTC ISO-8601 string (sortable, legacy-compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def to_iso(dt):
    """Convert a datetime to a naive-UTC ISO string; pass through None."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat()


def parse_dt(value):
    """Parse a stored ISO timestamp string into a naive-UTC datetime.

    Returns None for empty values, and is a no-op for datetime inputs.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def to_int(value, default=0):
    """Coerce a DynamoDB number (Decimal) into a Python int."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return int(value)
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def compact(item):
    """Drop keys whose value is None so we never write null attributes."""
    return {k: v for k, v in item.items() if v is not None}
