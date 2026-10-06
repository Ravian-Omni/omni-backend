"""Settings and configuration management REST API endpoints.

This module provides endpoints for:
- Retrieving all application settings
- Managing user authentication tokens (JWT)
- Managing email credentials with validation
- Secure handling of sensitive configuration data
"""

from fastapi import APIRouter

from src.database import delete_api_key, save_api_key, save_user_profile
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
# API KEY MANAGEMENT
# =============================================================================


@router.put("/api/settings/api-keys")
async def update_api_keys(
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    together_api_key: str | None = None,
    tavily_api_key: str | None = None,
    brave_api_key: str | None = None,
    composio_api_key: str | None = None,
    jev_api_key: str | None = None,
):
    """Set one or more LLM provider API keys.

    Args:
        openai_api_key: OpenAI API key.
        anthropic_api_key: Anthropic API key.
        together_api_key: Together AI API key.
        tavily_api_key: Tavily API key.
        brave_api_key: Brave Search API key.
        composio_api_key: Composio API key.

    Returns:
        dict: Updated keys summary.
    """
    keys = {
        "openai": openai_api_key,
        "anthropic": anthropic_api_key,
        "together": together_api_key,
        "tavily": tavily_api_key,
        "brave": brave_api_key,
        "composio": composio_api_key,
        "jev": jev_api_key,
    }
    filtered = {k: v for k, v in keys.items() if v is not None}
    result = SettingsService.update_api_keys(filtered)
    # Persist to database
    for provider, key in filtered.items():
        await save_api_key(provider, key)
    return result


@router.get("/api/settings/api-keys")
async def get_api_keys():
    """Get status of all configured API keys (masked).

    Returns:
        dict: Provider names with masked key previews and set status.
    """
    return SettingsService.get_api_keys_status()


@router.delete("/api/settings/api-keys/{provider}")
async def clear_api_key(provider: str):
    """Clear an API key for a specific provider.

    Args:
        provider: Provider name (openai, anthropic, together, etc.).

    Returns:
        dict: Confirmation of key removal.
    """
    result = SettingsService.clear_api_key(provider)
    await delete_api_key(provider)
    return result


# =============================================================================
# USER PROFILE MANAGEMENT
# =============================================================================


@router.put("/api/settings/user-profile")
async def update_user_profile(
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    dob: str | None = None,
    gender: str | None = None,
    country: str | None = None,
):
    """Update user profile fields.

    Args:
        first_name: User's first name.
        last_name: User's last name.
        email: User's email address.
        dob: Date of birth.
        gender: Gender.
        country: Country code (e.g., "US", "IN").

    Returns:
        dict: Updated profile.
    """
    profile = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "dob": dob,
        "gender": gender,
        "country": country,
    }
    filtered = {k: v for k, v in profile.items() if v is not None}
    result = SettingsService.update_user_profile(filtered)
    # Persist full profile to database (merge with existing)
    from src.services.settings_service import _PROFILE_ATTR_MAP
    from src.configs.settings import settings as _settings
    full_profile = {
        field: getattr(_settings, attr, "") or ""
        for field, attr in _PROFILE_ATTR_MAP.items()
    }
    await save_user_profile(full_profile)
    return result


@router.get("/api/settings/user-profile")
async def get_user_profile():
    """Get current user profile.

    Returns:
        dict: User profile fields and timestamp.
    """
    return SettingsService.get_user_profile()


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


# =============================================================================
# COMPOSIO APP MANAGEMENT
# =============================================================================


@router.get("/api/composio/apps")
async def list_composio_apps(user_id: str = "local_user"):
    """List all Composio app connections for the user.

    Returns active, initiated, and expired connections with their status.

    Args:
        user_id: User identifier. Defaults to "local_user".

    Returns:
        dict: List of connected apps with status.
    """
    from composio import Composio
    from src.configs.llm_configs_manager import LLMConfigManager

    try:
        composio_key = LLMConfigManager.get_config("composio_api_key")
        api_key = composio_key.get("config_list", [])[0].get("api_key")
        if not api_key:
            return {"apps": [], "message": "Composio API key not set"}

        client = Composio(api_key=api_key)
        connections = client.connected_accounts.list(user_ids=[user_id])

        apps = []
        for conn in connections.items:
            toolkit = conn.toolkit.slug if conn.toolkit else "unknown"
            apps.append({
                "app": toolkit.upper(),
                "connection_id": conn.id,
                "status": conn.status,
                "created_at": str(getattr(conn, "created_at", "")),
            })

        return {
            "user_id": user_id,
            "apps": apps,
            "active_count": sum(1 for a in apps if a["status"] == "ACTIVE"),
            "total_count": len(apps),
        }
    except Exception as e:
        return {"apps": [], "error": str(e)}


@router.post("/api/composio/connect/{app_name}")
async def connect_composio_app(
    app_name: str,
    user_id: str = "local_user",
    api_key_value: str | None = None,
):
    """Initiate a Composio app connection.

    If the app already has an active connection, returns success.
    For OAuth apps (e.g., Gmail): initiates OAuth and returns the authorization URL.
    For API key apps (e.g., Tavily): pass api_key_value to connect directly.

    Args:
        app_name: App name (e.g., "gmail", "slack", "tavily").
        user_id: User identifier. Defaults to "local_user".
        api_key_value: API key for apps that use API key auth (e.g., Tavily).

    Returns:
        dict: Connection status. If OAuth required, includes redirect_url.
    """
    import httpx
    from composio import Composio
    from src.configs.llm_configs_manager import LLMConfigManager

    app_upper = app_name.upper()
    app_lower = app_name.lower()

    try:
        composio_key = LLMConfigManager.get_config("composio_api_key")
        composio_api_key = composio_key.get("config_list", [])[0].get("api_key")
        if not composio_api_key:
            return {"success": False, "app": app_upper, "error": "Composio API key not set"}

        client = Composio(api_key=composio_api_key)

        # Check for existing active connection
        connections = client.connected_accounts.list(user_ids=[user_id])
        for conn in connections.items:
            toolkit = conn.toolkit.slug.lower() if conn.toolkit else ""
            if toolkit == app_lower and conn.status == "ACTIVE":
                return {
                    "success": True,
                    "app": app_upper,
                    "status": "ACTIVE",
                    "connection_id": conn.id,
                    "message": f"{app_upper} is already connected",
                }

        # Find or create auth config
        auth_config_id = None
        auth_scheme = None
        try:
            config = client.auth_configs.create(
                app_lower, {"type": "use_composio_managed_auth"}
            )
            auth_config_id = config.id
            auth_scheme = getattr(config, "auth_scheme", "OAUTH2")
        except Exception:
            # Try custom auth for API key apps
            if api_key_value:
                try:
                    config = client.auth_configs.create(
                        app_lower,
                        {"type": "use_custom_auth", "authScheme": "API_KEY", "credentials": {"api_key": api_key_value}},
                    )
                    auth_config_id = config.id
                    auth_scheme = "API_KEY"
                except Exception:
                    pass

            # Fall back to finding existing config
            if not auth_config_id:
                configs = client.auth_configs.list()
                for c in configs.items:
                    name = getattr(c, "name", "") or ""
                    toolkit_slug = getattr(c, "toolkit_slug", "") or ""
                    if app_lower in name.lower() or toolkit_slug.lower() == app_lower:
                        auth_config_id = c.id
                        auth_scheme = getattr(c, "auth_scheme", "OAUTH2")
                        break

        if not auth_config_id:
            # No usable auth config. Report the toolkit's real auth scheme so the
            # caller knows whether to ask for an API key or for OAuth credentials.
            toolkit_scheme = None
            try:
                # auth_config_details carries the schemes on toolkits.get();
                # `mode` is the scheme name (OAUTH2, API_KEY, ...).
                toolkit = client.toolkits.get(app_lower)
                details = getattr(toolkit, "auth_config_details", None) or []
                modes = [getattr(d, "mode", None) for d in details]
                modes = [str(m).upper() for m in modes if m]
                toolkit_scheme = modes[0] if modes else None
            except Exception:
                pass

            if toolkit_scheme == "API_KEY":
                return {
                    "success": False,
                    "app": app_upper,
                    "auth_scheme": "API_KEY",
                    "requires_api_key": True,
                    "error": f"{app_upper} connects with an API key, not OAuth. Provide your {app_upper} API key.",
                }

            return {
                "success": False,
                "app": app_upper,
                "auth_scheme": toolkit_scheme,
                "error": (
                    f"Composio has no managed credentials for {app_upper}"
                    f"{f' ({toolkit_scheme})' if toolkit_scheme else ''}. "
                    "It needs your own OAuth client (client_id/client_secret) configured in Composio."
                ),
            }

        # For API_KEY auth, connect directly via low-level API
        if auth_scheme == "API_KEY":
            if not api_key_value:
                return {
                    "success": False,
                    "app": app_upper,
                    "error": f"{app_upper} requires an API key. Pass it as api_key_value parameter.",
                    "auth_scheme": "API_KEY",
                }

            # Get expected field names from auth config
            auth_config_details = client.auth_configs.get(nanoid=auth_config_id)
            fields = getattr(auth_config_details, "expected_input_fields", [])
            credentials = {}
            for field in fields:
                field_name = field.get("name", "")
                legacy_name = field.get("legacy_template_name", "")
                credentials[field_name] = api_key_value
                if legacy_name:
                    credentials[legacy_name] = api_key_value

            # Use low-level HTTP call for API key connection
            resp = httpx.post(
                "https://backend.composio.dev/api/v3/connected_accounts",
                headers={"x-api-key": composio_api_key, "Content-Type": "application/json"},
                json={
                    "auth_config": {"id": auth_config_id},
                    "connection": {
                        "user_id": user_id,
                        "state": {"authScheme": "API_KEY", "val": {"authScheme": "API_KEY", **credentials}},
                    },
                },
                timeout=15.0,
            )
            if resp.status_code == 201:
                data = resp.json()
                return {
                    "success": True,
                    "app": app_upper,
                    "status": "ACTIVE",
                    "connection_id": data.get("id"),
                    "message": f"{app_upper} connected with API key",
                }
            else:
                return {"success": False, "app": app_upper, "error": resp.text[:300]}

        # For OAuth apps, initiate OAuth flow
        conn_request = client.connected_accounts.initiate(
            user_id=user_id,
            auth_config_id=auth_config_id,
        )

        return {
            "success": True,
            "app": app_upper,
            "status": "INITIATED",
            "connection_id": conn_request.id,
            "redirect_url": conn_request.redirect_url,
            "message": f"Please authorize {app_upper} at the provided URL, then call this endpoint again to verify.",
        }
    except Exception as e:
        return {"success": False, "app": app_upper, "error": str(e)}


@router.delete("/api/composio/disconnect/{app_name}")
async def disconnect_composio_app(app_name: str, user_id: str = "local_user"):
    """Disconnect a Composio app by deleting all connections.

    Removes the connected account from Composio. User will need to
    re-authorize via OAuth to use the app again.

    Args:
        app_name: App name (e.g., "gmail", "slack").
        user_id: User identifier. Defaults to "local_user".

    Returns:
        dict: Disconnection result with count of removed connections.
    """
    from composio import Composio
    from src.configs.llm_configs_manager import LLMConfigManager

    app_upper = app_name.upper()
    app_lower = app_name.lower()

    try:
        composio_key = LLMConfigManager.get_config("composio_api_key")
        api_key = composio_key.get("config_list", [])[0].get("api_key")
        if not api_key:
            return {"success": False, "app": app_upper, "error": "Composio API key not set"}

        client = Composio(api_key=api_key)
        connections = client.connected_accounts.list(user_ids=[user_id])

        deleted = 0
        for conn in connections.items:
            toolkit = conn.toolkit.slug.lower() if conn.toolkit else ""
            if toolkit == app_lower:
                try:
                    client.connected_accounts.delete(conn.id)
                    deleted += 1
                except Exception as e:
                    pass  # Some connections may fail to delete (already expired)

        return {
            "success": True,
            "app": app_upper,
            "deleted_connections": deleted,
            "message": f"Disconnected {app_upper}. {deleted} connection(s) removed. Re-authorization required to use again.",
        }
    except Exception as e:
        return {"success": False, "app": app_upper, "error": str(e)}


@router.get("/api/composio/status/{app_name}")
async def composio_app_status(app_name: str, user_id: str = "local_user"):
    """Check connection status of a specific Composio app.

    Args:
        app_name: App name (e.g., "gmail", "slack").
        user_id: User identifier. Defaults to "local_user".

    Returns:
        dict: Connection status (ACTIVE, INITIATED, EXPIRED, or NOT_CONNECTED).
    """
    from composio import Composio
    from src.configs.llm_configs_manager import LLMConfigManager

    app_upper = app_name.upper()
    app_lower = app_name.lower()

    try:
        composio_key = LLMConfigManager.get_config("composio_api_key")
        api_key = composio_key.get("config_list", [])[0].get("api_key")
        if not api_key:
            return {"app": app_upper, "status": "NOT_CONFIGURED", "message": "Composio API key not set"}

        client = Composio(api_key=api_key)
        connections = client.connected_accounts.list(user_ids=[user_id])

        for conn in connections.items:
            toolkit = conn.toolkit.slug.lower() if conn.toolkit else ""
            if toolkit == app_lower and conn.status == "ACTIVE":
                return {
                    "app": app_upper,
                    "status": "ACTIVE",
                    "connection_id": conn.id,
                    "message": f"{app_upper} is connected and active",
                }

        return {
            "app": app_upper,
            "status": "NOT_CONNECTED",
            "message": f"{app_upper} is not connected. Use POST /settings/api/composio/connect/{app_name} to connect.",
        }
    except Exception as e:
        return {"app": app_upper, "status": "ERROR", "error": str(e)}


@router.get("/api/token-usage")
async def get_token_usage():
    """Get local token usage summary (informational only)."""
    return {
        "total_tokens": 0,
        "total_cost": 0.0,
        "message": "Local token usage tracking",
    }
