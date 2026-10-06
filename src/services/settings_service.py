"""Settings business logic service.

This module provides the SettingsService class that encapsulates all
settings-related business logic including:
- Settings retrieval
- JWT token validation and management
- Email credentials validation and management
"""

import re
import time

from fastapi import HTTPException, status

from src.configs.settings import settings


# Provider name → settings attribute mapping
_PROVIDER_ATTR_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "together": "TOGETHER_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "brave": "BRAVE_API_KEY",
    "composio": "COMPOSIO_API_KEY",
    "jev": "JEV_API_KEY",
}

# User profile field → settings attribute mapping
_PROFILE_ATTR_MAP = {
    "first_name": "USER_FIRST_NAME",
    "last_name": "USER_LAST_NAME",
    "email": "USER_EMAIL",
    "dob": "USER_DOB",
    "gender": "USER_GENDER",
    "country": "USER_COUNTRY",
}


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
        """Validate email address format."""
        return SettingsService.EMAIL_PATTERN.match(email) is not None

    @staticmethod
    def validate_app_password(app_password: str) -> bool:
        """Validate Google App Password format."""
        if len(app_password) != 19:
            return False
        return SettingsService.APP_PASSWORD_PATTERN.match(app_password) is not None

    @staticmethod
    def mask_token(token: str) -> str:
        """Create a masked preview of a token/key."""
        if len(token) > 12:
            return f"{token[:6]}...{token[-4:]}"
        return "***"

    # =========================================================================
    # API KEY MANAGEMENT
    # =========================================================================

    @staticmethod
    def update_api_keys(keys: dict) -> dict:
        """Update one or more provider API keys.

        Args:
            keys: Dict of provider_name → api_key.

        Returns:
            dict: Summary of updated keys.
        """
        from src.configs.llm_configs_manager import LLMConfigManager

        updated = []
        for provider, api_key in keys.items():
            attr = _PROVIDER_ATTR_MAP.get(provider)
            if not attr:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown provider: {provider}. Valid: {list(_PROVIDER_ATTR_MAP.keys())}",
                )
            settings.update_setting(attr, api_key)
            updated.append(provider)

        # Rebuild LLM configs with new keys
        LLMConfigManager.clear_cache()

        return {
            "message": f"API keys updated for: {', '.join(updated)}",
            "updated_providers": updated,
            "timestamp": time.time(),
        }

    @staticmethod
    def get_api_keys_status() -> dict:
        """Get status of all configured API keys (masked)."""
        providers = {}
        for provider, attr in _PROVIDER_ATTR_MAP.items():
            key = getattr(settings, attr, None)
            providers[provider] = {
                "is_set": bool(key),
                "key_preview": SettingsService.mask_token(key) if key else None,
            }
        return {"providers": providers, "timestamp": time.time()}

    @staticmethod
    def clear_api_key(provider: str) -> dict:
        """Clear an API key for a specific provider."""
        from src.configs.llm_configs_manager import LLMConfigManager

        attr = _PROVIDER_ATTR_MAP.get(provider)
        if not attr:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown provider: {provider}",
            )

        settings.update_setting(attr, None)
        LLMConfigManager.clear_cache()

        return {
            "message": f"API key cleared for {provider}",
            "timestamp": time.time(),
        }

    # =========================================================================
    # USER PROFILE MANAGEMENT
    # =========================================================================

    @staticmethod
    def update_user_profile(profile: dict) -> dict:
        """Update user profile fields.

        Args:
            profile: Dict of field_name → value.

        Returns:
            dict: Updated profile summary.
        """
        updated = []
        for field, value in profile.items():
            attr = _PROFILE_ATTR_MAP.get(field)
            if not attr:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown profile field: {field}",
                )
            settings.update_setting(attr, value)
            updated.append(field)

        return {
            "message": f"Profile updated: {', '.join(updated)}",
            "updated_fields": updated,
            "timestamp": time.time(),
        }

    @staticmethod
    def get_user_profile() -> dict:
        """Get current user profile."""
        profile = {}
        for field, attr in _PROFILE_ATTR_MAP.items():
            profile[field] = getattr(settings, attr, "") or ""
        profile["timestamp"] = time.time()
        return profile

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
