import json
import time
from datetime import date, datetime
from typing import Any

import httpx

from configs.settings import settings


class DateTimeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle datetime objects"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def serialize_json_data(data: Any) -> Any:
    """Convert data to JSON-serializable format"""
    if data is None:
        return None

    if isinstance(data, (str, int, float, bool)):
        return data
    elif isinstance(data, datetime):
        return data.isoformat()
    elif isinstance(data, date):
        return data.isoformat()
    elif isinstance(data, dict):
        return {key: serialize_json_data(value) for key, value in data.items()}
    elif isinstance(data, (list, tuple)):
        return [serialize_json_data(item) for item in data]
    else:
        # For other types, try to convert to string
        return str(data)


class APIError(Exception):
    """Custom exception for API errors"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_type: str = "API_ERROR",
    ):
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary format"""
        return {
            "success": False,
            "message": self.message,
            "data": {"error_type": self.error_type, "status_code": self.status_code},
        }


class APIResponse:
    """Enhanced response object"""

    def __init__(
        self,
        response: httpx.Response = None,
        request_time: float = 0,
        error: APIError = None,
    ):
        self.response = response
        self.request_time = request_time
        self.error = error

    @property
    def status_code(self) -> int:
        return (
            self.response.status_code
            if self.response
            else (self.error.status_code or 0)
        )

    @property
    def headers(self) -> dict[str, str]:
        return dict(self.response.headers) if self.response else {}

    @property
    def text(self) -> str:
        return (
            self.response.text
            if self.response
            else (self.error.message if self.error else "")
        )

    @property
    def content(self) -> bytes:
        return self.response.content if self.response else b""

    def json(self) -> dict[str, Any]:
        """Get JSON response with error handling"""
        if self.error:
            return self.error.to_dict()

        if not self.response:
            return {"success": False, "message": "No response data", "data": {}}

        try:
            return self.response.json()
        except Exception:
            return {
                "success": False,
                "message": "Invalid JSON response",
                "data": {"raw_response": self.text},
            }

    def standard_response(self) -> dict[str, Any]:
        """
        Parse response as StandardResponse and return key values directly

        Returns:
            dict: {"success": bool, "message": str, "data": dict}
        """
        if self.error:
            return self.error.to_dict()

        try:
            json_data = self.json()
            return {
                "success": json_data.get("success", self.is_success),
                "message": json_data.get(
                    "message", self.text if self.is_error else "Request completed"
                ),
                "data": json_data.get("data", {}),
            }
        except Exception:
            return {
                "success": self.is_success,
                "message": self.text if self.is_error else "Request completed",
                "data": {},
            }

    @property
    def success(self) -> bool:
        """Get success status from StandardResponse"""
        if self.error:
            return False

        try:
            return self.standard_response()["success"]
        except Exception as e:
            print(f"Error parsing success status: {str(e)}")
            return self.is_success

    @property
    def message(self) -> str:
        """Get message from StandardResponse"""
        if self.error:
            return self.error.message

        try:
            return self.standard_response()["message"]
        except Exception as e:
            print(f"Error parsing message: {str(e)}")
            return self.text

    @property
    def data(self) -> dict[str, Any]:
        """Get data from StandardResponse"""
        if self.error:
            return self.error.to_dict()["data"]

        try:
            return self.standard_response()["data"]
        except Exception as e:
            print(f"Error parsing data: {str(e)}")
            return {}

    @property
    def is_success(self) -> bool:
        return self.response and 200 <= self.response.status_code < 300

    @property
    def is_error(self) -> bool:
        return self.error is not None or (
            self.response and self.response.status_code >= 400
        )

    @property
    def elapsed_time(self) -> float:
        """Request duration in seconds"""
        return self.request_time


class ServerAPIClient:
    """Simple robust API client for server communication"""

    _instance = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.base_url = getattr(settings, "BACKEND_URL", "http://localhost:8000")
            self.timeout = 300.0
            self.default_headers = {"Content-Type": "application/json"}
            self._initialized = True

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _get_headers(
        self, custom_headers: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Build headers with JWT token and custom headers"""
        headers = self.default_headers.copy()

        # Add JWT token if available
        jwt_token = getattr(settings, "USER_TOKEN", None)
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"

        # Merge custom headers
        if custom_headers:
            headers.update(custom_headers)

        return headers

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint"""
        return f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    async def request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        data: dict | str | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """
        Make HTTP request with structured error handling

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path
            params: Query parameters
            data: Request body data (form/raw)
            json_data: JSON request body
            headers: Custom headers
        """
        start_time = time.time()

        try:
            client = await self._get_client()
            url = self._build_url(endpoint)

            # Handle different data types
            request_data = None
            request_json = None

            if json_data is not None:
                # Serialize datetime objects and other non-JSON types
                request_json = serialize_json_data(json_data)
            elif data is not None:
                if isinstance(data, dict):
                    # Serialize datetime objects in dict data
                    request_json = serialize_json_data(data)
                else:
                    request_data = data

            response = await client.request(
                method=method.upper(),
                url=url,
                params=params,
                data=request_data,
                json=request_json,
                headers=self._get_headers(headers),
            )

            request_time = time.time() - start_time
            return APIResponse(response, request_time)

        except TypeError as e:
            # Handle JSON serialization errors specifically
            request_time = time.time() - start_time
            if "not JSON serializable" in str(e):
                error = APIError(
                    message=f"Data contains non-serializable objects (datetime, custom objects, etc.): {str(e)}",
                    error_type="SERIALIZATION_ERROR",
                )
            else:
                error = APIError(
                    message=f"Data type error: {str(e)}", error_type="DATA_TYPE_ERROR"
                )
            return APIResponse(request_time=request_time, error=error)

        except httpx.TimeoutException as e:
            request_time = time.time() - start_time
            error = APIError(
                message=f"Request timeout after {self.timeout} seconds with error: {str(e)}",
                error_type="TIMEOUT_ERROR",
            )
            return APIResponse(request_time=request_time, error=error)

        except httpx.NetworkError as e:
            request_time = time.time() - start_time
            error = APIError(
                message=f"Network connection failed: {str(e)}",
                error_type="NETWORK_ERROR",
            )
            return APIResponse(request_time=request_time, error=error)

        except httpx.ConnectError as e:
            request_time = time.time() - start_time
            error = APIError(
                message=f"Connection failed - server may be down: {str(e)}",
                error_type="CONNECTION_ERROR",
            )
            return APIResponse(request_time=request_time, error=error)

        except httpx.HTTPStatusError as e:
            request_time = time.time() - start_time
            error = APIError(
                message=f"HTTP error {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
                error_type="HTTP_ERROR",
            )
            return APIResponse(request_time=request_time, error=error)

        except Exception as e:
            request_time = time.time() - start_time
            error = APIError(
                message=f"Unexpected error: {str(e)}", error_type="UNKNOWN_ERROR"
            )
            return APIResponse(request_time=request_time, error=error)

    # HTTP Methods
    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make GET request"""
        return await self.request("GET", endpoint, params=params, headers=headers)

    async def post(
        self,
        endpoint: str,
        data: dict | str | None = None,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make POST request"""
        return await self.request(
            "POST",
            endpoint,
            params=params,
            data=data,
            json_data=json_data,
            headers=headers,
        )

    async def put(
        self,
        endpoint: str,
        data: dict | str | None = None,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make PUT request"""
        return await self.request(
            "PUT",
            endpoint,
            params=params,
            data=data,
            json_data=json_data,
            headers=headers,
        )

    async def patch(
        self,
        endpoint: str,
        data: dict | str | None = None,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make PATCH request"""
        return await self.request(
            "PATCH",
            endpoint,
            params=params,
            data=data,
            json_data=json_data,
            headers=headers,
        )

    async def delete(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make DELETE request"""
        return await self.request("DELETE", endpoint, params=params, headers=headers)

    async def head(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make HEAD request"""
        return await self.request("HEAD", endpoint, params=params, headers=headers)

    async def options(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make OPTIONS request"""
        return await self.request("OPTIONS", endpoint, params=params, headers=headers)

    # Configuration methods
    def set_base_url(self, url: str):
        """Update base URL"""
        self.base_url = url

    def set_timeout(self, timeout: float):
        """Update default timeout"""
        self.timeout = timeout

    def set_default_headers(self, headers: dict[str, str]):
        """Update default headers"""
        self.default_headers.update(headers)

    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None


# Create singleton instance
api_client = ServerAPIClient()
