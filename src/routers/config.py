"""Settings and configuration management REST API endpoints.

This module provides endpoints for:
- Retrieving all application settings
- Managing user authentication tokens (JWT)
- Managing email credentials with validation
- Secure handling of sensitive configuration data
"""

import base64
import json
import re
import time

from fastapi import APIRouter, HTTPException

from src.configs.datetime_utils import dt
from src.configs.settings import settings

router = APIRouter()


@router.get("/api/settings")
async def get_all_settings():
    """Get all current application settings.

    Returns:
        dict: All settings with current timestamp.
    """
    return {"settings": settings.get_all_settings(), "timestamp": time.time()}


# # Get specific setting
# @router.get("/api/settings/{key}")
# async def get_setting(key: str):
#     """Get specific setting value"""
#     if not hasattr(settings, key):
#         raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

#     value = settings.get_setting(key)
#     return {
#         "key": key,
#         "value": value,
#         "timestamp": time.time()
#     }

# # Update single setting
# @router.put("/api/settings/{key}")
# async def update_setting(key: str, value: str):
#     """Update a single setting"""
#     success = settings.update_setting(key, value)

#     if not success:
#         raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

#     return {
#         "message": f"Setting '{key}' updated successfully",
#         "key": key,
#         "value": value,
#         "timestamp": time.time()
#     }

# # Update multiple settings
# @router.post("/api/settings/bulk")
# async def update_multiple_settings(updates: Dict[str, str]):
#     """Update multiple settings at once"""
#     results = settings.update_settings(updates)

#     successful = {k: v for k, v in results.items() if v}
#     failed = [k for k, v in results.items() if not v]

#     return {
#         "message": f"Updated {len(successful)} settings",
#         "successful": list(successful.keys()),
#         "failed": failed,
#         "timestamp": time.time()
#     }


@router.put("/api/settings/user-token")
async def update_user_token(token: str):
    """Update USER_TOKEN setting with JWT validation.

    Validates JWT format and expiration before updating the token.

    Args:
        token: JWT token string to set as USER_TOKEN.

    Returns:
        dict: Success message with token preview and expiration info.

    Raises:
        HTTPException: 400 if token format invalid or expired.
    """
    # Basic JWT format validation
    try:
        # Check if token has 3 parts separated by dots
        parts = token.split(".")
        if len(parts) != 3:
            raise HTTPException(
                status_code=400,
                detail="Invalid JWT token format - must have 3 parts separated by dots",
            )

        # Try to decode the payload (middle part) to validate it's a valid JWT
        header_part, payload_part, signature_part = parts

        # Add padding if needed for base64 decoding
        payload_part += "=" * (4 - len(payload_part) % 4)

        # Decode payload to check if it's valid JSON
        decoded_payload = base64.urlsafe_b64decode(payload_part.encode())
        payload = json.loads(decoded_payload)

        # Optional: Check if token is expired
        if "exp" in payload:
            exp_timestamp = payload["exp"]
            if dt.now_timestamp() > exp_timestamp:
                raise HTTPException(status_code=400, detail="JWT token is expired")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400, detail="Invalid JWT token - payload is not valid JSON"
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JWT token format")

    # Update the setting
    success = settings.update_setting("USER_TOKEN", token)

    if not success:
        # If USER_TOKEN doesn't exist, add it dynamically
        settings.USER_TOKEN = token
        success = True

    return {
        "message": "USER_TOKEN updated successfully",
        "token_preview": f"{token[:20]}...{token[-10:]}" if len(token) > 30 else "***",
        "expires_at": (
            dt.timestamp_to_iso(payload.get("exp")) if payload.get("exp") else None
        ),
        "timestamp": time.time(),
    }


@router.get("/api/settings/user-token")
async def get_user_token():
    """Get current USER_TOKEN with secure masking.

    Returns:
        dict: Token preview (masked), status, and timestamp.

    Raises:
        HTTPException: 404 if USER_TOKEN not set.
    """
    token = getattr(settings, "USER_TOKEN", None)

    if not token:
        raise HTTPException(status_code=404, detail="USER_TOKEN not set")

    # Show only preview for security
    token_preview = f"{token[:20]}...{token[-10:]}" if len(token) > 30 else "***"

    return {
        "key": "USER_TOKEN",
        "token_preview": token_preview,
        "is_set": True,
        "timestamp": time.time(),
    }


@router.delete("/api/settings/user-token")
async def clear_user_token():
    """Clear/remove USER_TOKEN from settings.

    Returns:
        dict: Success message with timestamp.

    Raises:
        HTTPException: 404 if USER_TOKEN not found.
    """
    if hasattr(settings, "USER_TOKEN"):
        settings.USER_TOKEN = None
        return {"message": "USER_TOKEN cleared successfully", "timestamp": time.time()}
    else:
        raise HTTPException(status_code=404, detail="USER_TOKEN not found")


def validate_email(email: str) -> bool:
    """Validate email address format.

    Args:
        email: Email address to validate.

    Returns:
        bool: True if email format is valid, False otherwise.
    """
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(email_pattern, email) is not None


def validate_app_password(app_password: str) -> bool:
    """Validate Google App Password format.

    Expected format: "xxxx xxxx xxxx xxxx" (16 alphanumeric + 3 spaces = 19 chars).

    Args:
        app_password: App password string to validate.

    Returns:
        bool: True if password format is valid, False otherwise.
    """
    # Should match pattern: "xxxx xxxx xxxx xxxx" (16 chars + 3 spaces)
    if len(app_password) != 19:
        return False

    # Check format with spaces
    if not re.match(
        r"^[a-zA-Z0-9]{4}\s[a-zA-Z0-9]{4}\s[a-zA-Z0-9]{4}\s[a-zA-Z0-9]{4}$",
        app_password,
    ):
        return False

    return True


@router.put("/api/settings/user-email")
async def update_user_email(email: str, email_password: str):
    """Update USER_EMAIL and USER_EMAIL_PASSWORD with validation.

    Args:
        email: Email address in valid format.
        email_password: Google App Password in format "xxxx xxxx xxxx xxxx".

    Returns:
        dict: Success message with email and password length.

    Raises:
        HTTPException: 400 if email or password format is invalid.
    """
    # Validate email format
    if not validate_email(email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Validate app password format
    if not validate_app_password(email_password):
        raise HTTPException(
            status_code=400,
            detail="Invalid app password format - must be 'xxxx xxxx xxxx xxxx' (16 alphanumeric characters with spaces)",
        )

    # Update the settings (keep original format with spaces)
    email_success = settings.update_setting("USER_EMAIL", email)
    password_success = settings.update_setting("USER_EMAIL_PASSWORD", email_password)

    if not email_success:
        # If USER_EMAIL doesn't exist, add it dynamically
        settings.USER_EMAIL = email
        email_success = True

    if not password_success:
        # If USER_EMAIL_PASSWORD doesn't exist, add it dynamically
        settings.USER_EMAIL_PASSWORD = email_password
        password_success = True

    return {
        "message": "Email credentials updated successfully",
        "email": email,
        "password_length": len(email_password),
        "timestamp": time.time(),
    }


@router.get("/api/settings/user-email")
async def get_user_email():
    """Get current USER_EMAIL and USER_EMAIL_PASSWORD status.

    Returns:
        dict: Email address, password status, and timestamp.

    Raises:
        HTTPException: 404 if email credentials not set.
    """
    email = getattr(settings, "USER_EMAIL", None)
    password = getattr(settings, "USER_EMAIL_PASSWORD", None)

    if not email and not password:
        raise HTTPException(status_code=404, detail="Email credentials not set")

    if not email:
        raise HTTPException(status_code=404, detail="USER_EMAIL not set")

    if not password:
        raise HTTPException(status_code=404, detail="USER_EMAIL_PASSWORD not set")

    return {
        "email": email,
        "email_password_set": True,
        "password_length": len(password),
        "is_set": True,
        "timestamp": time.time(),
    }


@router.delete("/api/settings/user-email")
async def clear_user_email():
    """Clear/remove USER_EMAIL and USER_EMAIL_PASSWORD from settings.

    Returns:
        dict: Success message with list of cleared items and timestamp.

    Raises:
        HTTPException: 404 if email credentials not found.
    """
    email_exists = hasattr(settings, "USER_EMAIL") and getattr(
        settings, "USER_EMAIL", None
    )
    password_exists = hasattr(settings, "USER_EMAIL_PASSWORD") and getattr(
        settings, "USER_EMAIL_PASSWORD", None
    )

    if not email_exists and not password_exists:
        raise HTTPException(status_code=404, detail="Email credentials not found")

    cleared_items = []

    if email_exists:
        settings.USER_EMAIL = None
        cleared_items.append("USER_EMAIL")

    if password_exists:
        settings.USER_EMAIL_PASSWORD = None
        cleared_items.append("USER_EMAIL_PASSWORD")

    return {
        "message": "Email credentials cleared successfully",
        "cleared_items": cleared_items,
        "timestamp": time.time(),
    }
