import json
import boto3
import os
import re
import uuid
import json
import pytz
from datetime import datetime, timezone as timezone_module
from shared.db.queries import create_user
from shared.utils.response import create_response
# from shared.utils.logger import logger  # Replaced with print statements

# Basic email format sanity check (not a full RFC validator)
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

cognito = boto3.client("cognito-idp")


def generate_secure_temp_password():
    """Generate a 12-character password that meets all Cognito requirements"""
    import secrets
    import string

    # Ensure at least one from each required category
    uppercase = secrets.choice(string.ascii_uppercase)
    lowercase = secrets.choice(string.ascii_lowercase)
    digit = secrets.choice(string.digits)
    special = secrets.choice("!@#$%^&*")

    # Fill remaining 8 characters from all categories
    all_chars = string.ascii_letters + string.digits + "!@#$%^&*"
    remaining = "".join(secrets.choice(all_chars) for _ in range(8))

    # Combine and shuffle to avoid predictable patterns
    password_chars = list(uppercase + lowercase + digit + special + remaining)
    secrets.SystemRandom().shuffle(password_chars)

    return "".join(password_chars)


def handler(event, context):
    print(f"[REGISTER] Starting user registration handler")
    try:
        # Parse request body
        if not event.get("body"):
            print(f"[REGISTER] WARNING: Registration attempt without request body")
            return create_response(400, {"error": "Request body is required"})

        body = json.loads(event["body"])

        # Validate required fields
        required_fields = ["email", "firstName", "lastName", "country", "interests"]
        for field in required_fields:
            if not body.get(field):
                print(f"[REGISTER] WARNING: Registration attempt missing required field: {field}")
                return create_response(400, {"error": f"{field} is required"})

        email = body["email"].lower().strip()
        first_name = body["firstName"].strip()
        last_name = body["lastName"].strip()
        country = body["country"].strip()
        interests = body["interests"]  # Should be an array
        timezone = body.get("timezone", "UTC")

        # Basic email format sanity check before calling Cognito
        if not EMAIL_REGEX.match(email):
            print(f"[REGISTER] WARNING: Registration attempt with invalid email format")
            return create_response(400, {"error": "Invalid email format"})

        # Validate field lengths
        if len(first_name) > 100:
            return create_response(400, {"error": "firstName must be at most 100 characters"})
        if len(last_name) > 100:
            return create_response(400, {"error": "lastName must be at most 100 characters"})
        if len(country) > 100:
            return create_response(400, {"error": "country must be at most 100 characters"})

        # Validate interests is an array
        if not isinstance(interests, list) or len(interests) == 0:
            print(f"[REGISTER] WARNING: Registration attempt with invalid interests for {email}")
            return create_response(400, {"error": "At least one interest is required"})

        # Validate each interest is a non-empty string <= 100 chars
        for interest in interests:
            if not isinstance(interest, str) or not interest.strip():
                return create_response(400, {"error": "Each interest must be a non-empty string"})
            if len(interest.strip()) > 100:
                return create_response(400, {"error": "Each interest must be at most 100 characters"})

        # Validate timezone is a real zone; default to UTC rather than break signup
        try:
            pytz.timezone(timezone)
        except Exception:
            print(f"[REGISTER] WARNING: Invalid timezone provided, defaulting to UTC")
            timezone = "UTC"

        # Create user in Cognito using sign_up (this sends verification email automatically)
        try:
            # Generate a temporary random password (required by sign_up, but user won't use it)
            import secrets
            import string

            temp_password = generate_secure_temp_password()

            cognito_response = cognito.sign_up(
                ClientId=os.environ["CLIENT_ID"],
                Username=email,
                Password=temp_password,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "given_name", "Value": first_name},
                    {"Name": "family_name", "Value": last_name},
                ],
            )

            cognito_id = cognito_response["UserSub"]

            # Verification email is automatically sent by Cognito!
            print(f"[REGISTER] User created in Cognito: {cognito_id}, verification email sent to: {email}")

        except cognito.exceptions.UsernameExistsException:
            # Account enumeration protection: return the SAME generic success-style
            # response a new registration returns, without creating/duplicating
            # anything, sending another email, or revealing the account exists.
            print(f"[REGISTER] WARNING: Registration attempt for an already-registered email")
            return create_response(
                201,
                {
                    "message": "Account created successfully! Please check your email to verify your account before signing in.",
                    "user": {
                        "id": str(uuid.uuid4()),
                        "email": email,
                        "firstName": first_name,
                        "lastName": last_name,
                        "country": country,
                        "interests": interests,
                        "timezone": timezone,
                        "createdAt": datetime.now(timezone_module.utc).isoformat(),
                        "emailVerified": False,
                        "nextStep": "verify_email",
                    },
                },
            )
        except cognito.exceptions.InvalidPasswordException:
            # This shouldn't happen with our generated password, but just in case
            print(f"[REGISTER] ERROR: Invalid password generated for user registration: {email}")
            return create_response(
                400, {"error": "Password does not meet requirements"}
            )
        except Exception as e:
            print(f"[REGISTER] ERROR: Cognito error during registration for {email}: {e}")
            return create_response(500, {"error": "Failed to create user account"})

        # Store user profile in DynamoDB
        try:
            user_id, created_at = create_user(
                cognito_id=cognito_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                country=country,
                interests=interests,
                timezone=timezone,
            )
            print(f"[REGISTER] User profile created in database for {email} with ID: {user_id}")

        except Exception as e:
            print(f"[REGISTER] ERROR: Database error during registration for {email}: {e}")
            # Rollback: Delete user from Cognito if database insert failed
            try:
                cognito.admin_delete_user(
                    UserPoolId=os.environ["USER_POOL_ID"], Username=email
                )
                print(f"[REGISTER] Rolled back Cognito user creation for {email}")
            except Exception as rollback_error:
                print(f"[REGISTER] ERROR: Failed to rollback Cognito user for {email}: {rollback_error}")
            return create_response(500, {"error": "Failed to create user profile"})

        # Return success response
        print(f"[REGISTER] User registration completed successfully for {email}")
        return create_response(
            201,
            {
                "message": "Account created successfully! Please check your email to verify your account before signing in.",
                "user": {
                    "id": str(user_id),
                    "email": email,
                    "firstName": first_name,
                    "lastName": last_name,
                    "country": country,
                    "interests": interests,
                    "timezone": timezone,
                    "createdAt": created_at.isoformat(),
                    "emailVerified": False,
                    "nextStep": "verify_email",
                },
            },
        )

    except json.JSONDecodeError:
        print(f"[REGISTER] ERROR: Invalid JSON in registration request body")
        return create_response(400, {"error": "Invalid JSON in request body"})
    except Exception as e:
        print(f"[REGISTER] ERROR: Unexpected error in registration handler: {e}")
        return create_response(500, {"error": "Internal server error"})
