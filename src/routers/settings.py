"""Settings and configuration management REST API endpoints.

This module provides endpoints for:
- Retrieving all application settings
- Managing user authentication tokens (JWT)
- Managing email credentials with validation
- Secure handling of sensitive configuration data
"""

from fastapi import APIRouter

from src.services.settings_service import SettingsService

router = APIRouter()


# =============================================================================
# SETTINGS RETRIEVAL
# =============================================================================


@router.get("/api/settings")
async def get_all_settings():
    """Get all current application settings.

    Returns:
        dict: All settings with current timestamp.
    """
    return SettingsService.get_all_settings()


# =============================================================================
# USER TOKEN MANAGEMENT
# =============================================================================


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
    return SettingsService.update_user_token(token)


@router.get("/api/settings/user-token")
async def get_user_token():
    """Get current USER_TOKEN with secure masking.

    Returns:
        dict: Token preview (masked), status, and timestamp.

    Raises:
        HTTPException: 404 if USER_TOKEN not set.
    """
    return SettingsService.get_user_token()


@router.delete("/api/settings/user-token")
async def clear_user_token():
    """Clear/remove USER_TOKEN from settings.

    Returns:
        dict: Success message with timestamp.

    Raises:
        HTTPException: 404 if USER_TOKEN not found.
    """
    return SettingsService.clear_user_token()


# =============================================================================
# EMAIL CREDENTIALS MANAGEMENT
# =============================================================================


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
    return SettingsService.update_email_credentials(email, email_password)


@router.get("/api/settings/user-email")
async def get_user_email():
    """Get current USER_EMAIL and USER_EMAIL_PASSWORD status.

    Returns:
        dict: Email address, password status, and timestamp.

    Raises:
        HTTPException: 404 if email credentials not set.
    """
    return SettingsService.get_email_credentials()


@router.delete("/api/settings/user-email")
async def clear_user_email():
    """Clear/remove USER_EMAIL and USER_EMAIL_PASSWORD from settings.

    Returns:
        dict: Success message with list of cleared items and timestamp.

    Raises:
        HTTPException: 404 if email credentials not found.
    """
    return SettingsService.clear_email_credentials()
