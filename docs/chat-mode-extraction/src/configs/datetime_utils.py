"""Date and time utilities for Chat Service.

This module provides standardized date/time operations.
"""

from datetime import datetime, timezone


class DateTimeUtils:
    """Utility class for date and time operations."""

    @staticmethod
    def now() -> datetime:
        """Get current UTC datetime.

        Returns:
            Timezone-aware datetime object in UTC.
        """
        return datetime.now(timezone.utc)

    @staticmethod
    def now_iso() -> str:
        """Get current UTC datetime as ISO format string.

        Returns:
            ISO formatted datetime string.
        """
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def from_iso(iso_string: str) -> datetime:
        """Parse ISO format string to datetime.

        Args:
            iso_string: ISO formatted datetime string.

        Returns:
            Parsed datetime object.
        """
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))

    @staticmethod
    def to_iso(dt_obj: datetime) -> str:
        """Convert datetime to ISO format string.

        Args:
            dt_obj: Datetime object to convert.

        Returns:
            ISO formatted string.
        """
        return dt_obj.isoformat()


# Global instance for convenience
dt = DateTimeUtils()
