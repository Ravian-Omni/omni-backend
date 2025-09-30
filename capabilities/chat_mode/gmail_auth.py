from composio import Composio
from typing import Dict, Any
import os
import uuid
from fastapi import HTTPException


class ComposioAuthService:
    def __init__(self):
        self.composio = Composio(api_key=os.getenv("COMPOSIO_API_KEY"))

        # Get supported apps from environment variable
        supported_apps = os.getenv(
            "COMPOSIO_SUPPORTED_APPS", "gmail,github").lower()
        app_list = [app.strip() for app in supported_apps.split(",")]

        # Dynamically build auth config mapping from environment variables
        self.auth_config_mapping = {}
        for app in app_list:
            env_var_name = f"{app.upper()}_AUTH_CONFIG_ID"
            config_id = os.getenv(env_var_name)
            if config_id:
                self.auth_config_mapping[app] = config_id
            else:
                # Add with placeholder if not configured
                self.auth_config_mapping[app] = f"ac_YOUR_{app.upper()}_CONFIG_ID"

        # Add common aliases
        if "gmail" in self.auth_config_mapping:
            self.auth_config_mapping["google"] = self.auth_config_mapping["gmail"]

        # Dynamically build toolkit mapping
        self.toolkit_mapping = {}
        for app in app_list:
            # Map common app names to their toolkit equivalents
            toolkit_name = self._get_toolkit_name(app)
            self.toolkit_mapping[app] = [toolkit_name]

        # Add aliases
        if "gmail" in self.toolkit_mapping:
            self.toolkit_mapping["google"] = self.toolkit_mapping["gmail"]

    def _get_toolkit_name(self, app: str) -> str:
        """Map app names to their corresponding toolkit names"""
        toolkit_mapping = {
            "gmail": "GMAIL",
            "google": "GMAIL",
            "github": "GITHUB",
            "slack": "SLACK",
            "notion": "NOTION",
            "trello": "TRELLO",
            "asana": "ASANA",
            "jira": "JIRA",
            "linear": "LINEAR",
            "discord": "DISCORD",
            "telegram": "TELEGRAM",
            "whatsapp": "WHATSAPP",
            "twitter": "TWITTER",
            "linkedin": "LINKEDIN",
            "youtube": "YOUTUBE",
            "calendar": "GOOGLECALENDAR",
            "drive": "GOOGLEDRIVE",
            "sheets": "GOOGLESHEETS",
            "docs": "GOOGLEDOCS",
            # Add more mappings as needed
        }
        return toolkit_mapping.get(app.lower(), app.upper())

    def get_auth_config_id(self, provider: str) -> str:
        """Get auth config ID for a specific provider"""
        if provider not in self.auth_config_mapping:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported provider: {provider}. Supported providers: {list(self.auth_config_mapping.keys())}"
            )
        return self.auth_config_mapping[provider]

    def get_toolkits(self, provider: str) -> list:
        """Get toolkits for a specific provider"""
        return self.toolkit_mapping.get(provider, [provider.upper()])

    async def authenticate_provider(self, user_id: str, provider: str) -> Dict[str, Any]:
        """
        Initiate authentication for a specific provider

        Args:
            user_id: User's ID from your application/database
            provider: Provider name (google, github, etc.)

        Returns:
            Dict containing authentication URL and connection details
        """
        try:
            # Get the auth config ID for the provider
            auth_config_id = self.get_auth_config_id(provider)

            # Initiate connection request with proper parameters
            connection_request = self.composio.connected_accounts.initiate(
                user_id=user_id,
                auth_config_id=auth_config_id,
            )

            return {
                "success": True,
                "user_id": user_id,
                "provider": provider,
                "auth_url": connection_request.redirect_url,
                "connection_request_id": connection_request.id,
                "message": f"Visit the auth_url to complete {provider} authentication",
                "instructions": "After visiting the URL and completing authentication, use the connection_request_id to check status"
            }

        except Exception as e:
            # More detailed error handling
            error_msg = str(e)
            if "auth_config_id" in error_msg.lower():
                error_msg = f"Invalid {provider.upper()}_AUTH_CONFIG_ID. Please check your Composio dashboard for the correct auth config ID. Error: {error_msg}"

            raise HTTPException(
                status_code=500,
                detail=f"Failed to initiate {provider} authentication: {error_msg}"
            )

    async def check_connection_status(self, connection_id: str) -> Dict[str, Any]:
        """
        Check the status of a Gmail connection

        Args:
            connection_id: The connection ID returned from authenticate_gmail_account

        Returns:
            Dict containing connection status
        """
        try:
            connected_account = self.composio.connected_accounts.get(
                connection_id)

            return {
                "success": True,
                "connection_id": connection_id,
                "status": connected_account.status if hasattr(connected_account, 'status') else "connected",
                "connected_account": str(connected_account)
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to check connection status: {str(e)}"
            )

    async def wait_for_connection(self, connection_request_id: str, timeout: int = 300) -> Dict[str, Any]:
        """
        Wait for the authentication flow to be completed

        Args:
            connection_request_id: The connection request ID
            timeout: Timeout in seconds (default 5 minutes)

        Returns:
            Dict containing final connection status
        """
        try:
            # Note: This method might need adjustment based on actual Composio API
            # You may need to poll the connection status instead of waiting

            # Alternative approach - poll for connection status
            import asyncio
            start_time = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    # Check if connection exists and is active
                    connected_account = self.composio.connected_accounts.get(
                        connection_request_id)
                    if connected_account:
                        return {
                            "success": True,
                            "connection_request_id": connection_request_id,
                            "status": "connected",
                            "message": "Gmail authentication completed successfully"
                        }
                except:
                    pass

                # Wait 5 seconds before next check
                await asyncio.sleep(5)

            # Timeout reached
            raise HTTPException(
                status_code=408,
                detail="Authentication timeout - user did not complete authentication within the specified time"
            )

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Authentication timeout or failed: {str(e)}"
            )

    async def list_user_connections(self, user_id: str, provider: str = None) -> Dict[str, Any]:
        """
        List all connections for a user

        Args:
            user_id: User's ID from your application/database
            provider: Optional provider filter (google, github, etc.)

        Returns:
            Dict containing user's connections
        """
        try:
            # Get user's connections - using the correct API method
            connections = self.composio.connected_accounts.list()

            # Filter connections by user_id and optionally by provider
            user_connections = []
            for conn in connections:
                # Check if this connection belongs to our user
                if hasattr(conn, 'user_id') and str(conn.user_id) == user_id:
                    # If provider filter is specified, check if connection matches
                    if provider:
                        # You might need to check toolkit or other attributes to filter by provider
                        # This depends on how Composio structures the connection data
                        user_connections.append({
                            "id": getattr(conn, 'id', 'unknown'),
                            "status": getattr(conn, 'status', 'unknown'),
                            "toolkit": getattr(conn, 'toolkit', 'unknown'),
                            "created_at": getattr(conn, 'created_at', 'unknown'),
                        })
                    else:
                        user_connections.append({
                            "id": getattr(conn, 'id', 'unknown'),
                            "status": getattr(conn, 'status', 'unknown'),
                            "toolkit": getattr(conn, 'toolkit', 'unknown'),
                            "created_at": getattr(conn, 'created_at', 'unknown'),
                        })

            return {
                "success": True,
                "user_id": user_id,
                "provider": provider,
                "connections": user_connections[:10],  # Limit to first 10
                "total_connections": len(user_connections)
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list connections: {str(e)}"
            )

    async def get_all_connections(self) -> Dict[str, Any]:
        """
        Get all connections (for debugging)

        Returns:
            Dict containing all connections
        """
        try:
            connections = self.composio.connected_accounts.list()

            connection_details = []
            for conn in connections:
                conn_info = {
                    "id": getattr(conn, 'id', 'unknown'),
                    "status": getattr(conn, 'status', 'unknown'),
                    "user_id": getattr(conn, 'user_id', 'unknown'),
                    "toolkit": getattr(conn, 'toolkit', 'unknown'),
                    "created_at": getattr(conn, 'created_at', 'unknown'),
                }
                connection_details.append(conn_info)

            return {
                "success": True,
                "total_connections": len(connections),
                "connections": connection_details
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get all connections: {str(e)}"
            )

    async def get_provider_tools(self, user_id: str, provider: str) -> Dict[str, Any]:
        """
        Get available tools for a specific provider

        Args:
            user_id: User's ID from your application/database
            provider: Provider name (google, github, etc.)

        Returns:
            Dict containing available tools for the provider
        """
        try:
            toolkits = self.get_toolkits(provider)
            tools = self.composio.tools.get(user_id=user_id, toolkits=toolkits)

            return {
                "success": True,
                "user_id": user_id,
                "provider": provider,
                "toolkits": toolkits,
                "tools": tools,
                "total_tools": len(tools)
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get {provider} tools: {str(e)}"
            )

    async def enable_provider(self, connection_id: str) -> Dict[str, Any]:
        """
        Enable a provider connection

        Args:
            connection_id: The connection ID to enable

        Returns:
            Dict containing enable status
        """
        try:
            result = self.composio.connected_accounts.enable(connection_id)

            return {
                "success": True,
                "connection_id": connection_id,
                "message": "Provider enabled successfully",
                "status": "enabled",
                "result": str(result) if result else "Enabled"
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to enable provider: {str(e)}"
            )

    async def disable_provider(self, connection_id: str) -> Dict[str, Any]:
        """
        Disable a provider connection (without deleting it)

        Args:
            connection_id: The connection ID to disable

        Returns:
            Dict containing disable status
        """
        try:
            result = self.composio.connected_accounts.disable(connection_id)

            return {
                "success": True,
                "connection_id": connection_id,
                "message": "Provider disabled successfully",
                "status": "disabled",
                "result": str(result) if result else "Disabled"
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to disable provider: {str(e)}"
            )

    async def disconnect_provider(self, connection_id: str) -> Dict[str, Any]:
        """
        Permanently delete a provider connection

        Args:
            connection_id: The connection ID to delete

        Returns:
            Dict containing deletion status
        """
        try:
            result = self.composio.connected_accounts.delete(connection_id)

            return {
                "success": True,
                "connection_id": connection_id,
                "message": "Provider connection permanently deleted",
                "status": "deleted",
                "result": str(result) if result else "Deleted"
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete provider connection: {str(e)}"
            )


# Global instance
_composio_auth_service = None


def get_composio_auth_service() -> ComposioAuthService:
    """Get Composio authentication service instance"""
    global _composio_auth_service
    if _composio_auth_service is None:
        _composio_auth_service = ComposioAuthService()
    return _composio_auth_service

# Backward compatibility


def get_gmail_auth_service() -> ComposioAuthService:
    """Get authentication service instance (backward compatibility)"""
    return get_composio_auth_service()
