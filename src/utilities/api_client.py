"""HTTP API client for server communication with enhanced error handling.

This module provides a robust HTTP client implementation for communicating with
backend services, featuring automatic JSON serialization, standardized error
handling, JWT authentication, and response wrapping.
"""

import json
import time
from datetime import date, datetime
from typing import Any

import httpx

from src.configs.settings import settings


class DateTimeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle datetime objects.

    Extends json.JSONEncoder to automatically serialize Python datetime and
    date objects to ISO format strings.

    Example:
        >>> encoder = DateTimeJSONEncoder()
        >>> data = {"timestamp": datetime.now()}
        >>> json.dumps(data, cls=DateTimeJSONEncoder)
    """

    def default(self, obj):
        """Encode datetime objects to ISO format strings.

        Args:
            obj: Object to encode.

        Returns:
            ISO format string for datetime/date objects, otherwise calls
            the parent encoder.
        """
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def serialize_json_data(data: Any) -> Any:
    """Convert data to JSON-serializable format.

    Recursively process data structures to convert non-JSON-serializable types
    (like datetime objects) to serializable formats.

    Args:
        data: Data to serialize (can be dict, list, datetime, or primitives).

    Returns:
        JSON-serializable version of the input data.

    Example:
        >>> data = {"created": datetime.now(), "count": 42}
        >>> serialized = serialize_json_data(data)
        >>> json.dumps(serialized)  # Works without error
    """
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
    """Custom exception for API errors.

    Represents errors that occur during API communication, including HTTP
    errors, network errors, timeouts, and serialization errors.

    Attributes:
        message: Human-readable error message.
        status_code: HTTP status code if applicable.
        error_type: Category of error (e.g., "TIMEOUT_ERROR", "NETWORK_ERROR").
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_type: str = "API_ERROR",
    ):
        """Initialize APIError with message and optional status code.

        Args:
            message: Error message describing what went wrong.
            status_code: HTTP status code if applicable. Defaults to None.
            error_type: Type of error for categorization. Defaults to "API_ERROR".
        """
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary format.

        Returns:
            Dictionary with success=False, message, and error details.
        """
        return {
            "success": False,
            "message": self.message,
            "data": {"error_type": self.error_type, "status_code": self.status_code},
        }


class APIResponse:
    """Enhanced response object wrapping HTTP responses and errors.

    Provides a unified interface for accessing HTTP response data with
    additional features like timing information, standardized error handling,
    and automatic JSON parsing.

    Attributes:
        response: Original httpx.Response object if successful.
        request_time: Time taken for the request in seconds.
        error: APIError instance if an error occurred.

    Example:
        >>> response = await api_client.get("/users/123")
        >>> if response.is_success:
        ...     data = response.json()
        ...     print(f"Request took {response.elapsed_time}s")
    """

    def __init__(
        self,
        response: httpx.Response = None,
        request_time: float = 0,
        error: APIError = None,
    ):
        """Initialize APIResponse with response data or error.

        Args:
            response: HTTP response object. Defaults to None.
            request_time: Request duration in seconds. Defaults to 0.
            error: APIError if request failed. Defaults to None.
        """
        self.response = response
        self.request_time = request_time
        self.error = error

    @property
    def status_code(self) -> int:
        """Get HTTP status code.

        Returns:
            HTTP status code from response or error, or 0 if neither.
        """
        return (
            self.response.status_code
            if self.response
            else (self.error.status_code or 0)
        )

    @property
    def headers(self) -> dict[str, str]:
        """Get response headers.

        Returns:
            Dictionary of response headers, or empty dict if no response.
        """
        return dict(self.response.headers) if self.response else {}

    @property
    def text(self) -> str:
        """Get response body as text.

        Returns:
            Response text, error message, or empty string.
        """
        return (
            self.response.text
            if self.response
            else (self.error.message if self.error else "")
        )

    @property
    def content(self) -> bytes:
        """Get response body as bytes.

        Returns:
            Response content as bytes, or empty bytes if no response.
        """
        return self.response.content if self.response else b""

    def json(self) -> dict[str, Any]:
        """Get JSON response with error handling.

        Parse the response body as JSON with automatic error handling
        for invalid JSON or error responses.

        Returns:
            Parsed JSON dictionary, or error dictionary if parsing fails.
        """
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
        """Get success status from StandardResponse.

        Returns:
            True if the request was successful, False otherwise.
        """
        if self.error:
            return False

        try:
            return self.standard_response()["success"]
        except Exception as e:
            print(f"Error parsing success status: {str(e)}")
            return self.is_success

    @property
    def message(self) -> str:
        """Get message from StandardResponse.

        Returns:
            Message string from response or error.
        """
        if self.error:
            return self.error.message

        try:
            return self.standard_response()["message"]
        except Exception as e:
            print(f"Error parsing message: {str(e)}")
            return self.text

    @property
    def data(self) -> dict[str, Any]:
        """Get data from StandardResponse.

        Returns:
            Data dictionary from response, or empty dict if unavailable.
        """
        if self.error:
            return self.error.to_dict()["data"]

        try:
            return self.standard_response()["data"]
        except Exception as e:
            print(f"Error parsing data: {str(e)}")
            return {}

    @property
    def is_success(self) -> bool:
        """Check if response indicates success (2xx status code).

        Returns:
            True if status code is in 200-299 range, False otherwise.
        """
        return self.response and 200 <= self.response.status_code < 300

    @property
    def is_error(self) -> bool:
        """Check if response indicates an error.

        Returns:
            True if error exists or status code is 400+, False otherwise.
        """
        return self.error is not None or (
            self.response and self.response.status_code >= 400
        )

    @property
    def elapsed_time(self) -> float:
        """Request duration in seconds.

        Returns:
            Time taken for the request in seconds.
        """
        return self.request_time


class ServerAPIClient:
    """Simple robust API client for server communication.

    Singleton HTTP client providing a unified interface for making API requests
    with automatic JWT authentication, error handling, JSON serialization, and
    request timing. Supports all standard HTTP methods (GET, POST, PUT, etc.).

    Attributes:
        base_url: Base URL for all API requests.
        timeout: Request timeout in seconds.
        default_headers: Default headers applied to all requests.

    Example:
        >>> client = ServerAPIClient()
        >>> response = await client.get("/users/123")
        >>> if response.success:
        ...     print(response.data)
    """

    _instance = None
    _client = None

    def __new__(cls):
        """Create or return singleton instance.

        Returns:
            The singleton ServerAPIClient instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the API client with default configuration."""
        if not self._initialized:
            self.base_url = getattr(settings, "BACKEND_URL", "http://localhost:8000")
            self.timeout = 300.0
            self.default_headers = {"Content-Type": "application/json"}
            self._initialized = True

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client.

        Returns:
            Configured httpx.AsyncClient instance.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _get_headers(
        self, custom_headers: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Build headers with JWT token and custom headers.

        Merge default headers with JWT authentication and any custom headers.

        Args:
            custom_headers: Additional headers to include. Defaults to None.

        Returns:
            Complete headers dictionary for the request.
        """
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
        """Build full URL from endpoint.

        Args:
            endpoint: API endpoint path.

        Returns:
            Complete URL combining base_url and endpoint.
        """
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
        """Make GET request.

        Args:
            endpoint: API endpoint path.
            params: URL query parameters. Defaults to None.
            headers: Custom headers. Defaults to None.

        Returns:
            APIResponse object wrapping the response.
        """
        return await self.request("GET", endpoint, params=params, headers=headers)

    async def post(
        self,
        endpoint: str,
        data: dict | str | None = None,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make POST request.

        Args:
            endpoint: API endpoint path.
            data: Form data or raw request body. Defaults to None.
            json_data: JSON request body. Defaults to None.
            params: URL query parameters. Defaults to None.
            headers: Custom headers. Defaults to None.

        Returns:
            APIResponse object wrapping the response.
        """
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
        """Make PUT request.

        Args:
            endpoint: API endpoint path.
            data: Form data or raw request body. Defaults to None.
            json_data: JSON request body. Defaults to None.
            params: URL query parameters. Defaults to None.
            headers: Custom headers. Defaults to None.

        Returns:
            APIResponse object wrapping the response.
        """
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
        """Make PATCH request.

        Args:
            endpoint: API endpoint path.
            data: Form data or raw request body. Defaults to None.
            json_data: JSON request body. Defaults to None.
            params: URL query parameters. Defaults to None.
            headers: Custom headers. Defaults to None.

        Returns:
            APIResponse object wrapping the response.
        """
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
        """Make DELETE request.

        Args:
            endpoint: API endpoint path.
            params: URL query parameters. Defaults to None.
            headers: Custom headers. Defaults to None.

        Returns:
            APIResponse object wrapping the response.
        """
        return await self.request("DELETE", endpoint, params=params, headers=headers)

    async def head(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make HEAD request.

        Args:
            endpoint: API endpoint path.
            params: URL query parameters. Defaults to None.
            headers: Custom headers. Defaults to None.

        Returns:
            APIResponse object wrapping the response.
        """
        return await self.request("HEAD", endpoint, params=params, headers=headers)

    async def options(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> APIResponse:
        """Make OPTIONS request.

        Args:
            endpoint: API endpoint path.
            params: URL query parameters. Defaults to None.
            headers: Custom headers. Defaults to None.

        Returns:
            APIResponse object wrapping the response.
        """
        return await self.request("OPTIONS", endpoint, params=params, headers=headers)

    # Configuration methods
    def set_base_url(self, url: str):
        """Update base URL.

        Args:
            url: New base URL for API requests.
        """
        self.base_url = url

    def set_timeout(self, timeout: float):
        """Update default timeout.

        Args:
            timeout: New timeout value in seconds.
        """
        self.timeout = timeout

    def set_default_headers(self, headers: dict[str, str]):
        """Update default headers.

        Args:
            headers: Headers to merge with existing default headers.
        """
        self.default_headers.update(headers)

    async def close(self):
        """Close HTTP client.

        Clean up resources by closing the underlying HTTP client connection.
        """
        if self._client:
            await self._client.aclose()
            self._client = None


# Create singleton instance
api_client = ServerAPIClient()
