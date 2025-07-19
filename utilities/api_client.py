# src/api_client.py
import httpx
import asyncio
from typing import Dict, Any, Optional
from configs.settings import settings

class ServerAPIClient:
    """Simple singleton API client for server communication"""
    
    _instance = None
    _client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.base_url = getattr(settings, 'BACKEND_URL', 'http://localhost:8000')
            self.timeout = 30
            self._initialized = True
    
    async def _get_client(self):
        """Get or create HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers with JWT token"""
        headers = {"Content-Type": "application/json"}
        
        jwt_token = getattr(settings, 'USER_TOKEN', None)
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"
        
        return headers
    
    async def get(self, endpoint: str, params: Dict = None) -> Dict[str, Any]:
        """Make GET request"""
        client = await self._get_client()
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = await client.get(url, params=params, headers=self._get_headers())
            return {
                "success": response.status_code < 400,
                "status": response.status_code,
                "data": response.json() if response.status_code < 400 else None,
                "error": response.text if response.status_code >= 400 else None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def post(self, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """Make POST request"""
        client = await self._get_client()
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = await client.post(url, json=data, headers=self._get_headers())
            return {
                "success": response.status_code < 400,
                "status": response.status_code,
                "data": response.json() if response.status_code < 400 else None,
                "error": response.text if response.status_code >= 400 else None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def put(self, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """Make PUT request"""
        client = await self._get_client()
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = await client.put(url, json=data, headers=self._get_headers())
            return {
                "success": response.status_code < 400,
                "status": response.status_code,
                "data": response.json() if response.status_code < 400 else None,
                "error": response.text if response.status_code >= 400 else None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def delete(self, endpoint: str) -> Dict[str, Any]:
        """Make DELETE request"""
        client = await self._get_client()
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = await client.delete(url, headers=self._get_headers())
            return {
                "success": response.status_code < 400,
                "status": response.status_code,
                "data": response.json() if response.status_code < 400 else None,
                "error": response.text if response.status_code >= 400 else None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None

# Create singleton instance
api_client = ServerAPIClient()