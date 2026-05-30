import json
from datetime import datetime, timezone
from shared.utils.dynamo import table
from shared.utils.response import create_response
# from shared.utils.logger import logger


def test_db_connection() -> bool:
    """Lightweight DynamoDB connectivity check (describe the users table)."""
    print(f"[HEALTH] Testing DynamoDB connectivity")
    try:
        table("users").table_status
        return True
    except Exception as e:
        print(f"[HEALTH] ERROR: DynamoDB connectivity check failed: {e}")
        return False


def handler(event, context):
    start_time = datetime.now(timezone.utc)
    print(f"[HEALTH] INFO: Request started for utils/health")

    try:
        # Test database connection
        print(f"[HEALTH] INFO: Testing database connection for health check")
        db_start_time = datetime.now(timezone.utc)

        db_status = test_db_connection()
        db_duration = (datetime.now(timezone.utc) - db_start_time).total_seconds() * 1000

        if db_status:
            print(f"[HEALTH] INFO: Database connection test successful, connection_time_ms={round(db_duration, 2)}")
        else:
            print(f"[HEALTH] ERROR: Database connection test failed, connection_time_ms={round(db_duration, 2)}")

        current_timestamp = datetime.now(timezone.utc).isoformat()

        response = create_response(
            200,
            {
                "message": "TimeBrew API is healthy!",
                "timestamp": current_timestamp,
                "service": "timebrew-backend",
                "database": "connected" if db_status else "disconnected",
                "response_time_ms": round(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000, 2
                ),
            },
        )

        total_time_ms = round((datetime.now(timezone.utc) - start_time).total_seconds() * 1000, 2)
        print(f"[HEALTH] INFO: Health check completed successfully, database_status={'connected' if db_status else 'disconnected'}, total_time_ms={total_time_ms}")
        return response

    except Exception as e:
        print(f"[HEALTH] ERROR: Health check failed: unexpected error - {str(e)}")
        error_response = create_response(
            500,
            {
                "message": "Health check failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": "timebrew-backend",
                "error": "Internal server error",
            },
        )
        print(f"[HEALTH] INFO: Request ended with status 500, duration_ms={round((datetime.now(timezone.utc) - start_time).total_seconds() * 1000, 2)}")
        return error_response
