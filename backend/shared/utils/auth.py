"""Authentication and authorization utilities for backend handlers."""
import json
from typing import Optional, Tuple, Dict, Any

import boto3

from .response import create_response
from shared.db.queries import get_user_by_cognito_id, get_brew, get_run, get_editor_log
# from .logger import get_logger

# logger = get_logger(__name__)


def validate_auth_token(event: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Validates authorization token and returns cognito_id and user data.

    Args:
        event: Lambda event object

    Returns:
        Tuple of (cognito_id, error_response)
        - If successful: (cognito_id, None)
        - If failed: (None, error_response_dict)
    """
    # Extract and validate authorization header
    auth_header = event.get("headers", {}).get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None, create_response(401, {"error": "Authorization token is required"})

    token = auth_header.split(" ")[1]
    if not token:
        return None, create_response(401, {"error": "Invalid authorization token format"})

    try:
        # Validate token with Cognito
        cognito = boto3.client("cognito-idp")
        user_response = cognito.get_user(AccessToken=token)
        cognito_id = user_response.get("Username")

        if not cognito_id:
            return None, create_response(401, {"error": "Invalid token: no user ID found"})

        return cognito_id, None

    except cognito.exceptions.NotAuthorizedException:
        return None, create_response(401, {"error": "Invalid or expired token"})
    except cognito.exceptions.UserNotFoundException:
        return None, create_response(401, {"error": "User not found"})
    except Exception as e:  # pylint: disable=broad-except
        print(f"[AUTH] ERROR: Authentication error: {str(e)}")
        return None, create_response(500, {"error": "Authentication service error"})


def get_authenticated_user(event: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, Any]]]:
    """
    Validates token and retrieves user from database.

    Args:
        event: Lambda event object

    Returns:
        Tuple of (user_data, error_response)
        - If successful: ({"id": uuid, "email": str, "cognito_id": str}, None)
        - If failed: (None, error_response_dict)
    """
    # Validate token first
    cognito_id, auth_error = validate_auth_token(event)
    if auth_error:
        return None, auth_error

    # Get user from DynamoDB
    try:
        user = get_user_by_cognito_id(cognito_id)

        if not user:
            return None, create_response(404, {"error": "User account not found or inactive"})

        return {
            "id": str(user["id"]),
            "email": user["email"],
            "cognito_id": user["cognito_id"]
        }, None

    except Exception as e:  # pylint: disable=broad-except
        print(f"[AUTH] ERROR: Database error in get_authenticated_user: {str(e)}")
        return None, create_response(500, {"error": "Failed to retrieve user information"})


def validate_resource_ownership(user_id: str, resource_type: str,
                               resource_id: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Validates that a user owns a specific resource.

    Args:
        user_id: User's UUID
        resource_type: Type of resource ('brew', 'briefing', 'feedback')
        resource_id: Resource UUID or identifier

    Returns:
        Tuple of (is_owner, error_response)
        - If valid: (True, None)
        - If invalid: (False, error_response_dict)
    """
    try:
        if resource_type == 'brew':
            owned = get_brew(user_id, resource_id) is not None
        elif resource_type == 'briefing':
            # editor_logs keyed by run_id; the run_id is the editor_log PK
            editor = get_editor_log(resource_id)
            owned = bool(editor) and str(editor.get("user_id")) == str(user_id)
        elif resource_type == 'run':
            run = get_run(resource_id)
            owned = bool(run) and str(run.get("user_id")) == str(user_id)
        else:
            return False, create_response(400, {"error": f"Invalid resource type: {resource_type}"})

        if not owned:
            return False, create_response(403,
                                          {"error": "Access denied: resource not found or not owned by user"})

        return True, None

    except Exception as e:  # pylint: disable=broad-except
        print(f"[AUTH] ERROR: Database error in validate_resource_ownership: {str(e)}")
        return False, create_response(500, {"error": "Failed to validate resource ownership"})


def safe_parse_json_array(value: Any) -> list:
    """
    Safely parse JSON array from string or return as-is if already a list.

    Args:
        value: Value to parse (string, list, or other)

    Returns:
        Parsed list or empty list on error
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    return []