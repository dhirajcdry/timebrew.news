import json
import os
import boto3
from datetime import datetime, timezone
from shared.utils.response import create_response
from shared.db.queries import (
    get_brew_by_id,
    get_user_by_id,
    get_active_run_for_brew,
    create_run,
)
from shared.utils.dynamo import parse_dt
from shared.middleware.auth import authenticate_user, validate_ownership
# from shared.utils.logger import Logger


def build_run_snapshot(brew, user):
    """Denormalized user/brew fields stored on the run so pipeline stages need
    no cross-table reads."""
    return {
        "email": user.get("email"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "timezone": user.get("timezone") or "UTC",
        "brew_name": brew.get("name"),
        "topics": brew.get("topics") if isinstance(brew.get("topics"), list) else [],
        "delivery_time": brew.get("delivery_time"),
    }


def lambda_handler(event, context):
    """
    Manual Brew Trigger Lambda Function
    Allows manual triggering of the AI pipeline for a specific brew
    """
    start_time = datetime.now(timezone.utc)

    try:
        print(f"[TRIGGER_BREW] Manual brew trigger started - triggered_at: {start_time.isoformat()}")
        # Parse request body
        if "body" in event:
            if isinstance(event["body"], str):
                body = json.loads(event["body"])
            else:
                body = event["body"]
        else:
            body = event

        brew_id = body.get("brew_id")
        if not brew_id:
            print("[TRIGGER_BREW] WARNING: Manual trigger attempt without brew_id")
            return create_response(400, {"error": "brew_id is required"})

        # This endpoint starts a paid pipeline (OpenRouter + an email send), so
        # require an authenticated caller who owns the brew.
        auth_user, auth_error = authenticate_user(event)
        if auth_error:
            return auth_error
        owns_brew, ownership_error = validate_ownership(auth_user["id"], "brew", brew_id)
        if ownership_error:
            return ownership_error

        print(f"[TRIGGER_BREW] Processing manual trigger request - brew_id: {brew_id}")

        # Verify brew exists
        print("[TRIGGER_BREW] Verifying brew exists and is active")
        brew = get_brew_by_id(brew_id)
        if not brew:
            print("[TRIGGER_BREW] WARNING: Brew not found in database")
            return create_response(404, {"error": "Brew not found"})

        user_id = brew.get("user_id")
        user = get_user_by_id(user_id)
        if not user:
            print("[TRIGGER_BREW] WARNING: Owning user not found")
            return create_response(404, {"error": "User not found"})

        email = user.get("email")
        first_name = user.get("first_name")
        last_name = user.get("last_name")
        user_timezone = user.get("timezone")
        is_active = bool(brew.get("is_active", True))

        user_name = (
            f"{first_name} {last_name}"
            if first_name and last_name
            else first_name or "User"
        )

        print(f"[TRIGGER_BREW] Brew found - brew_id: {brew_id}, user_id: {user_id}, user_timezone: {user_timezone}, is_active: {is_active}")

        if not is_active:
            print("[TRIGGER_BREW] WARNING: Attempted to trigger inactive brew")
            return create_response(400, {"error": "Brew is not active"})

        # Check for existing in-progress runs
        print("[TRIGGER_BREW] Checking for existing in-progress runs")
        in_progress_run = get_active_run_for_brew(brew_id)
        if in_progress_run:
            run_id_in_progress = in_progress_run.get("run_id")
            current_stage = in_progress_run.get("current_stage")
            created_at = parse_dt(in_progress_run.get("created_at"))
            print(f"[TRIGGER_BREW] WARNING: Run already in progress - run_id: {run_id_in_progress}, stage: {current_stage}")
            return create_response(
                409,
                {
                    "error": "Run already in progress",
                    "run_id": run_id_in_progress,
                    "stage": current_stage,
                    "created_at": created_at.isoformat() if created_at else None,
                },
            )

        # Create run_tracker entry with denormalized snapshot
        run_id = create_run(brew_id, user_id, snapshot=build_run_snapshot(brew, user))
        print(f"[TRIGGER_BREW] Run tracker entry created - run_id: {run_id}, brew_id: {brew_id}")

        # Trigger Step Functions workflow
        print(f"[TRIGGER_BREW] Triggering AI pipeline - triggered_by: manual, run_id: {run_id}")
        success, execution_arn = trigger_ai_pipeline(brew_id, run_id, "manual")

        if success:
            end_time = datetime.now(timezone.utc)
            processing_time = (end_time - start_time).total_seconds()

            print(f"[TRIGGER_BREW] AI pipeline triggered successfully - execution_arn: {execution_arn}, processing_time_seconds: {round(processing_time, 2)}")

            return create_response(
                200,
                {
                    "message": "AI pipeline triggered successfully",
                    "brew_id": brew_id,
                    "user_email": email,
                    "user_name": user_name,
                    "execution_arn": execution_arn,
                    "triggered_at": start_time.isoformat(),
                },
            )
        else:
            print("[TRIGGER_BREW] ERROR: Failed to trigger AI pipeline")
            return create_response(
                500, {"error": "Failed to trigger AI pipeline", "brew_id": brew_id}
            )

    except json.JSONDecodeError as e:
        print(f"[TRIGGER_BREW] ERROR: Invalid JSON in request body - error: {e}")
        return create_response(400, {"error": "Invalid JSON in request body"})
    except Exception as e:
        end_time = datetime.now(timezone.utc)
        processing_time = (end_time - start_time).total_seconds()

        print(f"[TRIGGER_BREW] ERROR: Manual brew trigger failed with unexpected error - error: {str(e)}, error_type: {type(e).__name__}, processing_time_seconds: {round(processing_time, 2)}")

        return create_response(500, {"error": str(e)})


def trigger_ai_pipeline(brew_id, run_id, triggered_by="manual"):
    """
    Trigger the Step Functions AI pipeline for a specific brew
    Returns (success: bool, execution_arn: str)
    """
    try:
        # Get Step Functions client
        stepfunctions = boto3.client("stepfunctions")

        # Get the state machine ARN from environment
        state_machine_arn = os.environ.get("AI_PIPELINE_STATE_MACHINE_ARN")
        if not state_machine_arn:
            error_msg = "AI_PIPELINE_STATE_MACHINE_ARN not found in environment"
            print(f"[TRIGGER_BREW] ERROR: {error_msg}")
            return False, None

        # Create execution input
        execution_input = {
            "brew_id": brew_id,
            "run_id": run_id,
            "triggered_by": triggered_by,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Generate unique execution name
        execution_name = f"brew-{brew_id}-{run_id[:8]}-{triggered_by}-{int(datetime.now(timezone.utc).timestamp())}"

        # Start execution
        response = stepfunctions.start_execution(
            stateMachineArn=state_machine_arn,
            name=execution_name,
            input=json.dumps(execution_input),
        )

        execution_arn = response["executionArn"]

        print(f"[TRIGGER_BREW] Step Functions execution started - execution_arn: {execution_arn}")

        return True, execution_arn

    except Exception as e:
        print(f"[TRIGGER_BREW] ERROR: Failed to trigger Step Functions - error: {str(e)}, brew_id: {brew_id}")
        return False, None
