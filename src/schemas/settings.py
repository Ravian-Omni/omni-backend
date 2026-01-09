"""Settings-related Pydantic schemas for request/response validation.

This module defines all schema models used by settings endpoints including:
- Settings retrieval responses
- Token management
- Email credentials management
"""

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    """Response model for all application settings.

    Attributes:
        settings: Dictionary containing all current settings.
        timestamp: Unix timestamp of the response.
    """

    settings: dict = Field(..., description="All application settings")
    timestamp: float = Field(..., description="Unix timestamp of response")


class TokenResponse(BaseModel):
    """Response model for token status.

    Attributes:
        key: Setting key name (USER_TOKEN).
        token_preview: Masked preview of the token.
        is_set: Whether the token is configured.
        timestamp: Unix timestamp of the response.
    """

    key: str = Field(default="USER_TOKEN", description="Setting key name")
    token_preview: str = Field(..., description="Masked token preview")
    is_set: bool = Field(..., description="Whether token is configured")
    timestamp: float = Field(..., description="Unix timestamp of response")


class TokenUpdateResponse(BaseModel):
    """Response model for successful token update.

    Attributes:
        message: Success message.
        token_preview: Masked preview of the updated token.
        expires_at: ISO timestamp of token expiration (if available).
        timestamp: Unix timestamp of the response.
    """

    message: str = Field(..., description="Success message")
    token_preview: str = Field(..., description="Masked token preview")
    expires_at: str | None = Field(default=None, description="Token expiration time")
    timestamp: float = Field(..., description="Unix timestamp of response")


class TokenClearResponse(BaseModel):
    """Response model for token clear operation.

    Attributes:
        message: Success message.
        timestamp: Unix timestamp of the response.
    """

    message: str = Field(..., description="Success message")
    timestamp: float = Field(..., description="Unix timestamp of response")


class EmailUpdateRequest(BaseModel):
    """Request model for email credentials update.

    Attributes:
        email: Email address in valid format.
        email_password: Google App Password in format "xxxx xxxx xxxx xxxx".
    """

    email: str = Field(..., description="Email address")
    email_password: str = Field(..., description="Google App Password")


class EmailCredentialsResponse(BaseModel):
    """Response model for email credentials status.

    Attributes:
        email: The configured email address.
        email_password_set: Whether password is set.
        password_length: Length of the stored password.
        is_set: Whether credentials are fully configured.
        timestamp: Unix timestamp of the response.
    """

    email: str = Field(..., description="Configured email address")
    email_password_set: bool = Field(..., description="Whether password is set")
    password_length: int = Field(..., description="Password length")
    is_set: bool = Field(..., description="Whether credentials are configured")
    timestamp: float = Field(..., description="Unix timestamp of response")


class EmailUpdateResponse(BaseModel):
    """Response model for successful email credentials update.

    Attributes:
        message: Success message.
        email: The updated email address.
        password_length: Length of the stored password.
        timestamp: Unix timestamp of the response.
    """

    message: str = Field(..., description="Success message")
    email: str = Field(..., description="Updated email address")
    password_length: int = Field(..., description="Password length")
    timestamp: float = Field(..., description="Unix timestamp of response")


class EmailClearResponse(BaseModel):
    """Response model for email credentials clear operation.

    Attributes:
        message: Success message.
        cleared_items: List of cleared setting keys.
        timestamp: Unix timestamp of the response.
    """

    message: str = Field(..., description="Success message")
    cleared_items: list[str] = Field(..., description="List of cleared items")
    timestamp: float = Field(..., description="Unix timestamp of response")
