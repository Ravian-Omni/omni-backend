"""Settings business logic service.

This module provides the SettingsService class that encapsulates all
settings-related business logic including:
- Settings retrieval
- JWT token validation and management
- Email credentials validation and management
"""

import base64
import json
import re
import time

from fastapi import HTTPException, status

from src.configs.datetime_utils import dt
from src.configs.settings import settings


class SettingsService:
    """Service class for settings-related business logic."""

    # Email validation pattern
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    # Google App Password pattern (xxxx xxxx xxxx xxxx)
    APP_PASSWORD_PATTERN = re.compile(
        r"^[a-zA-Z0-9]{4}\s[a-zA-Z0-9]{4}\s[a-zA-Z0-9]{4}\s[a-zA-Z0-9]{4}$"
    )

    @staticmethod
    def get_all_settings() -> dict:
        """Get all current application settings.

        Returns:
            dict: Dictionary containing all settings and timestamp.
        """
        return {"settings": settings.get_all_settings(), "timestamp": time.time()}

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email address format.

        Args:
            email: Email address to validate.

        Returns:
            bool: True if email format is valid, False otherwise.
        """
        return SettingsService.EMAIL_PATTERN.match(email) is not None

    @staticmethod
    def validate_app_password(app_password: str) -> bool:
        """Validate Google App Password format.

        Expected format: "xxxx xxxx xxxx xxxx" (16 alphanumeric + 3 spaces = 19 chars).

        Args:
            app_password: App password string to validate.

        Returns:
            bool: True if password format is valid, False otherwise.
        """
        if len(app_password) != 19:
            return False
        return SettingsService.APP_PASSWORD_PATTERN.match(app_password) is not None

    @staticmethod
    def validate_jwt_token(token: str) -> dict:
        """Validate JWT token format and decode payload.

        Args:
            token: JWT token string to validate.

        Returns:
            dict: Decoded JWT payload.

        Raises:
            HTTPException: If token format is invalid or expired.
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JWT token format - must have 3 parts separated by dots",
            )

        try:
            payload_part = parts[1]
            # Add padding for base64 decoding
            payload_part += "=" * (4 - len(payload_part) % 4)

            decoded_payload = base64.urlsafe_b64decode(payload_part.encode())
            payload = json.loads(decoded_payload)

            # Check token expiration
            if "exp" in payload:
                if dt.now_timestamp() > payload["exp"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="JWT token is expired",
                    )

            return payload

        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JWT token - payload is not valid JSON",
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JWT token format",
            )

    @staticmethod
    def mask_token(token: str) -> str:
        """Create a masked preview of a token.

        Args:
            token: Token string to mask.

        Returns:
            str: Masked token preview showing first 20 and last 10 characters.
        """
        if len(token) > 30:
            return f"{token[:20]}...{token[-10:]}"
        return "***"

    @staticmethod
    def update_user_token(token: str) -> dict:
        """Update USER_TOKEN setting with validation.

        Args:
            token: JWT token string to set.

        Returns:
            dict: Success response with token preview and expiration info.

        Raises:
            HTTPException: If token format is invalid or expired.
        """
        payload = SettingsService.validate_jwt_token(token)

        success = settings.update_setting("USER_TOKEN", token)
        if not success:
            settings.USER_TOKEN = token

        return {
            "message": "USER_TOKEN updated successfully",
            "token_preview": SettingsService.mask_token(token),
            "expires_at": (
                dt.timestamp_to_iso(payload.get("exp")) if payload.get("exp") else None
            ),
            "timestamp": time.time(),
        }

    @staticmethod
    def get_user_token() -> dict:
        """Get current USER_TOKEN status.

        Returns:
            dict: Token status with masked preview.

        Raises:
            HTTPException: If USER_TOKEN not set.
        """
        token = getattr(settings, "USER_TOKEN", None)

        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="USER_TOKEN not set"
            )

        return {
            "key": "USER_TOKEN",
            "token_preview": SettingsService.mask_token(token),
            "is_set": True,
            "timestamp": time.time(),
        }

    @staticmethod
    def clear_user_token() -> dict:
        """Clear USER_TOKEN from settings.

        Returns:
            dict: Success message with timestamp.

        Raises:
            HTTPException: If USER_TOKEN not found.
        """
        if not hasattr(settings, "USER_TOKEN"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="USER_TOKEN not found"
            )

        settings.USER_TOKEN = None
        return {"message": "USER_TOKEN cleared successfully", "timestamp": time.time()}

    @staticmethod
    def update_email_credentials(email: str, email_password: str) -> dict:
        """Update USER_EMAIL and USER_EMAIL_PASSWORD with validation.

        Args:
            email: Email address in valid format.
            email_password: Google App Password in format "xxxx xxxx xxxx xxxx".

        Returns:
            dict: Success message with email and password length.

        Raises:
            HTTPException: If email or password format is invalid.
        """
        if not SettingsService.validate_email(email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email format"
            )

        if not SettingsService.validate_app_password(email_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid app password format - must be 'xxxx xxxx xxxx xxxx' (16 alphanumeric characters with spaces)",
            )

        email_success = settings.update_setting("USER_EMAIL", email)
        password_success = settings.update_setting(
            "USER_EMAIL_PASSWORD", email_password
        )

        if not email_success:
            settings.USER_EMAIL = email

        if not password_success:
            settings.USER_EMAIL_PASSWORD = email_password

        return {
            "message": "Email credentials updated successfully",
            "email": email,
            "password_length": len(email_password),
            "timestamp": time.time(),
        }

    @staticmethod
    def get_email_credentials() -> dict:
        """Get current USER_EMAIL and USER_EMAIL_PASSWORD status.

        Returns:
            dict: Email credentials status.

        Raises:
            HTTPException: If email credentials not set.
        """
        email = getattr(settings, "USER_EMAIL", None)
        password = getattr(settings, "USER_EMAIL_PASSWORD", None)

        if not email and not password:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email credentials not set",
            )

        if not email:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="USER_EMAIL not set"
            )

        if not password:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="USER_EMAIL_PASSWORD not set",
            )

        return {
            "email": email,
            "email_password_set": True,
            "password_length": len(password),
            "is_set": True,
            "timestamp": time.time(),
        }

    @staticmethod
    def clear_email_credentials() -> dict:
        """Clear USER_EMAIL and USER_EMAIL_PASSWORD from settings.

        Returns:
            dict: Success message with list of cleared items.

        Raises:
            HTTPException: If email credentials not found.
        """
        email_exists = hasattr(settings, "USER_EMAIL") and getattr(
            settings, "USER_EMAIL", None
        )
        password_exists = hasattr(settings, "USER_EMAIL_PASSWORD") and getattr(
            settings, "USER_EMAIL_PASSWORD", None
        )

        if not email_exists and not password_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email credentials not found",
            )

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
