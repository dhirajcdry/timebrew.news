import json
import boto3
import os
from shared.db.queries import get_user_by_cognito_id, get_brew
from shared.utils.dynamo import parse_dt, to_int
from shared.utils.response import create_response

cognito = boto3.client("cognito-idp")


def handler(event, context):
    try:
        # Check for Authorization header
        auth_header = event.get("headers", {}).get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return create_response(401, {"error": "Authorization token is required"})

        # Extract token
        token = auth_header.split(" ")[1]

        # Get user from Cognito
        try:
            user_response = cognito.get_user(AccessToken=token)
            cognito_id = user_response.get("Username")
        except Exception as e:
            print(f"Cognito error: {e}")
            return create_response(401, {"error": "Invalid or expired token"})

        # Get brew ID from path parameters
        brew_id = event.get("pathParameters", {}).get("id")
        if not brew_id:
            return create_response(400, {"error": "Brew ID is required"})

        try:
            # Resolve the user from the cognito_id
            user = get_user_by_cognito_id(cognito_id)
            if not user:
                return create_response(404, {"error": "User not found"})

            # Get specific brew by ID for this user
            brew_item = get_brew(user["id"], brew_id)
            if not brew_item:
                return create_response(404, {"error": "Brew not found"})

            topics = brew_item.get("topics")
            if not isinstance(topics, list):
                topics = []

            created_at = parse_dt(brew_item.get("created_at"))
            brew = {
                "id": str(brew_item.get("id")),
                "name": brew_item.get("name"),
                "topics": topics,
                "delivery_time": str(brew_item["delivery_time"]) if brew_item.get("delivery_time") else None,
                "article_count": to_int(brew_item.get("article_count"), 5),
                "created_at": created_at.isoformat() + "Z" if created_at else None,
                "is_active": bool(brew_item.get("is_active", True)),
            }

            return create_response(200, {"brew": brew})

        except Exception as e:
            print(f"Database error: {e}")
            return create_response(500, {"error": "Failed to retrieve brew"})

    except Exception as e:
        print(f"Unexpected error: {e}")
        return create_response(500, {"error": "Internal server error"})
