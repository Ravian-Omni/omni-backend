from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from capabilities.chat_mode.gmail_auth import get_composio_auth_service

router = APIRouter()

# Pydantic models for request/response


class AuthenticateRequest(BaseModel):
    user_id: str
    provider: str


class ConnectionStatusRequest(BaseModel):
    connection_id: str


class WaitConnectionRequest(BaseModel):
    connection_request_id: str
    timeout: int = 300


class ListConnectionsRequest(BaseModel):
    user_id: str
    provider: Optional[str] = None


class GetToolsRequest(BaseModel):
    user_id: str
    provider: str


class DisconnectRequest(BaseModel):
    connection_id: str


class EnableRequest(BaseModel):
    connection_id: str


class DisableRequest(BaseModel):
    connection_id: str


@router.post("/authenticate")
async def authenticate_provider(request: AuthenticateRequest):
    """
    Initiate authentication for a specific provider

    Args:
        request: Contains user_id and provider name

    Returns:
        Authentication URL and connection details
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.authenticate_provider(request.user_id, request.provider)
    return result


@router.post("/status")
async def check_connection_status(request: ConnectionStatusRequest):
    """
    Check the status of a connection

    Args:
        request: Contains connection ID

    Returns:
        Connection status information
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.check_connection_status(request.connection_id)
    return result


@router.post("/wait")
async def wait_for_connection(request: WaitConnectionRequest):
    """
    Wait for authentication to complete

    Args:
        request: Contains connection request ID and optional timeout

    Returns:
        Final connection status
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.wait_for_connection(
        request.connection_request_id,
        request.timeout
    )
    return result


@router.post("/connections")
async def list_user_connections(request: ListConnectionsRequest):
    """
    List all connections for a user, optionally filtered by provider

    Args:
        request: Contains user_id and optional provider filter

    Returns:
        List of user's connections
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.list_user_connections(request.user_id, request.provider)
    return result


@router.get("/connections/all")
async def get_all_connections():
    """
    Get all connections (for debugging)

    Returns:
        List of all connections with details
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.get_all_connections()
    return result


@router.post("/tools")
async def get_provider_tools(request: GetToolsRequest):
    """
    Get available tools for a specific provider

    Args:
        request: Contains user_id and provider name

    Returns:
        Available tools for the provider
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.get_provider_tools(request.user_id, request.provider)
    return result


@router.post("/enable")
async def enable_provider(request: EnableRequest):
    """
    Enable a provider connection

    Args:
        request: Contains connection_id to enable

    Returns:
        Enable status
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.enable_provider(request.connection_id)
    return result


@router.post("/disable")
async def disable_provider(request: DisableRequest):
    """
    Disable a provider connection (without deleting it)

    Args:
        request: Contains connection_id to disable

    Returns:
        Disable status
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.disable_provider(request.connection_id)
    return result


@router.post("/disconnect")
async def disconnect_provider(request: DisconnectRequest):
    """
    Permanently delete a provider connection

    Args:
        request: Contains connection_id to permanently delete

    Returns:
        Deletion status
    """
    auth_service = get_composio_auth_service()
    result = await auth_service.disconnect_provider(request.connection_id)
    return result


@router.get("/providers")
async def get_supported_providers():
    """
    Get list of supported providers and their configuration status

    Returns:
        List of supported providers and their configuration status
    """
    auth_service = get_composio_auth_service()

    providers_status = {}
    for provider, config_id in auth_service.auth_config_mapping.items():
        providers_status[provider] = {
            "configured": not config_id.startswith("ac_YOUR_"),
            "toolkits": auth_service.get_toolkits(provider),
            "config_id": config_id if not config_id.startswith("ac_YOUR_") else "Not configured"
        }

    return {
        "success": True,
        "supported_providers": providers_status
    }


@router.get("/toolkits")
async def get_available_toolkits():
    """
    Get list of available toolkits for authentication

    Returns:
        Simple list of available toolkits with their status
    """
    auth_service = get_composio_auth_service()

    toolkits = []
    for provider, config_id in auth_service.auth_config_mapping.items():
        is_configured = not config_id.startswith("ac_YOUR_")
        toolkit_names = auth_service.get_toolkits(provider)

        toolkits.append({
            "provider": provider,
            "toolkit_names": toolkit_names,
            "is_configured": is_configured,
            "status": "ready" if is_configured else "needs_config",
            "display_name": provider.title(),
            "description": f"Authenticate with {provider.title()} to access {', '.join(toolkit_names)} tools"
        })

    return {
        "success": True,
        "available_toolkits": toolkits,
        "total_count": len(toolkits),
        "configured_count": sum(1 for t in toolkits if t["is_configured"]),
        "message": "Use these toolkits to authenticate users and access their tools"
    }
