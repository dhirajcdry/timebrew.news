"""Optimized authentication middleware - eliminates duplication across 8+ handlers."""
import boto3
from shared.db.queries import get_user_by_cognito_id, get_brew, get_run, get_editor_log_by_editorial_id
from shared.utils.response import create_response


def authenticate_user(event):
    """Single function that handles all auth validation and user lookup.

    Returns: (user_data, error_response)
    - Success: ({"id": str, "email": str, "cognito_id": str}, None)
    - Failure: (None, error_response_dict)
    """
    print(f"[AUTH] Starting user authentication")

    # Extract token
    auth_header = event.get("headers", {}).get("Authorization", "")
    print(f"[AUTH] Auth header present: {bool(auth_header)}")

    if not auth_header.startswith("Bearer "):
        print(f"[AUTH] ERROR: Invalid authorization header format")
        return None, create_response(401, {"error": "Invalid authorization"})

    token = auth_header.split(" ")[1]
    print(f"[AUTH] Token extracted, length: {len(token) if token else 0}")

    try:
        # Validate with Cognito and get user from DynamoDB in one flow
        print(f"[AUTH] Validating token with Cognito")
        cognito = boto3.client("cognito-idp")
        user_response = cognito.get_user(AccessToken=token)
        cognito_id = user_response.get("Username")
        print(f"[AUTH] Cognito validation successful, cognito_id: {cognito_id}")

        print(f"[AUTH] Looking up user in database")
        user = get_user_by_cognito_id(cognito_id)

        if not user:
            print(f"[AUTH] ERROR: User not found in database for cognito_id: {cognito_id}")
            return None, create_response(404, {"error": "User not found"})

        print(f"[AUTH] User authentication successful: user_id={user['id']}")
        return {"id": str(user["id"]), "email": user["email"], "cognito_id": user["cognito_id"]}, None

    except Exception as e:
        print(f"[AUTH] ERROR: Authentication failed: {str(e)}")
        import traceback
        print(f"[AUTH] ERROR: Traceback: {traceback.format_exc()}")
        return None, create_response(401, {"error": "Invalid token"})


def validate_ownership(user_id, resource_type, resource_id):
    """Fast ownership validation against DynamoDB.

    Returns: (is_valid, error_response)
    """
    print(f"[AUTH] Validating ownership: user_id={user_id}, resource_type={resource_type}, resource_id={resource_id}")

    try:
        if resource_type == 'brew':
            print(f"[AUTH] Checking brew ownership")
            owned = get_brew(user_id, resource_id) is not None
        elif resource_type in ['briefing', 'run']:
            print(f"[AUTH] Checking briefing/run ownership")
            run = get_run(resource_id)
            owned = bool(run) and str(run.get("user_id")) == str(user_id)
        elif resource_type == 'editorial':
            print(f"[AUTH] Checking editorial ownership")
            editor = get_editor_log_by_editorial_id(resource_id)
            owned = bool(editor) and str(editor.get("user_id")) == str(user_id)
        else:
            print(f"[AUTH] ERROR: Invalid resource type: {resource_type}")
            return False, create_response(400, {"error": "Invalid resource type"})

        print(f"[AUTH] Ownership result: {owned}")

        if not owned:
            print(f"[AUTH] ERROR: Access denied - no ownership found")
            return False, create_response(403, {"error": "Access denied"})

        print(f"[AUTH] Ownership validation successful")
        return True, None

    except Exception as e:
        print(f"[AUTH] ERROR: Ownership validation failed: {str(e)}")
        import traceback
        print(f"[AUTH] ERROR: Traceback: {traceback.format_exc()}")
        return False, create_response(500, {"error": "Validation failed"})
