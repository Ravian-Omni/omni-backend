from composio import Composio
from typing import Dict, Any
import os
import uuid
from fastapi import HTTPException


class GmailAuthService:
    def __init__(self):
        self.composio = Composio(api_key=os.getenv("COMPOSIO_API_KEY"))
        # You can configure this as environment variable or fetch from your auth config
        self.gmail_auth_config_id = os.getenv(
            "GMAIL_AUTH_CONFIG_ID", "ac_YOUR_GMAIL_CONFIG_ID")

    def generate_user_id(self, email: str) -> str:
        """Generate a consistent user ID from email address"""
        # Create a deterministic UUID based on email
        # Standard namespace
        namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
        return str(uuid.uuid5(namespace, email))

    async def authenticate_gmail_account(self, email: str) -> Dict[str, Any]:
        """
        Initiate Gmail authentication for a user

        Args:
            email: User's Gmail address

        Returns:
            Dict containing authentication URL and connection details
        """
        try:
            # Generate consistent user ID from email
            user_id = self.generate_user_id(email)

            # Initiate connection request with proper parameters
            connection_request = self.composio.connected_accounts.initiate(
                user_id=user_id,
                auth_config_id=self.gmail_auth_config_id,
            )

            return {
                "success": True,
                "user_id": user_id,
                "email": email,
                "auth_url": connection_request.redirect_url,
                "connection_request_id": connection_request.id,
                "message": "Visit the auth_url to complete Gmail authentication",
                "instructions": "After visiting the URL and completing authentication, use the connection_request_id to check status"
            }

        except Exception as e:
            # More detailed error handling
            error_msg = str(e)
            if "auth_config_id" in error_msg.lower():
                error_msg = f"Invalid GMAIL_AUTH_CONFIG_ID. Please check your Composio dashboard for the correct auth config ID. Error: {error_msg}"

            raise HTTPException(
                status_code=500,
                detail=f"Failed to initiate Gmail authentication: {error_msg}"
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

    async def list_user_connections(self, email: str) -> Dict[str, Any]:
        """
        List all connections for a user

        Args:
            email: User's email address

        Returns:
            Dict containing user's connections
        """
        try:
            user_id = self.generate_user_id(email)

            # Get user's connections - using the correct API method
            connections = self.composio.connected_accounts.list()

            # Filter connections by user_id if the API returns user-specific data
            # If not, we'll return all connections for now
            user_connections = []
            for conn in connections:
                # Check if this connection belongs to our user
                if hasattr(conn, 'user_id') and str(conn.user_id) == user_id:
                    user_connections.append(str(conn))
                elif hasattr(conn, 'metadata') and conn.metadata and conn.metadata.get('user_id') == user_id:
                    user_connections.append(str(conn))
                else:
                    # If we can't filter by user, include all for now
                    user_connections.append(str(conn))

            return {
                "success": True,
                "user_id": user_id,
                "email": email,
                "connections": user_connections[:10],  # Limit to first 10
                "total_connections": len(connections)
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


# Global instance
_gmail_auth_service = None


def get_gmail_auth_service() -> GmailAuthService:
    """Get Gmail authentication service instance"""
    global _gmail_auth_service
    if _gmail_auth_service is None:
        _gmail_auth_service = GmailAuthService()
    return _gmail_auth_service
