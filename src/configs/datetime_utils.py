"""Centralized datetime utility functions.

This module provides consistent, timezone-aware datetime operations across the application.
All datetime functions return timezone-aware datetime objects using UTC.
"""

from datetime import datetime, timezone


class DateTimeUtils:
    """Centralized datetime utility functions.

    Provides consistent, timezone-aware datetime operations across the application.
    All datetime functions return timezone-aware datetime objects using UTC.
    """

    @staticmethod
    def now() -> datetime:
        """Get current datetime in UTC timezone.

        Returns:
            Timezone-aware datetime object in UTC
        """
        return datetime.now(timezone.utc)

    @staticmethod
    def now_iso() -> str:
        """Get current datetime as ISO 8601 formatted string.

        Returns:
            Current datetime in ISO 8601 format (UTC)
        """
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def now_timestamp() -> float:
        """Get current datetime as Unix timestamp.

        Returns:
            Current datetime as Unix timestamp (seconds since epoch)
        """
        return datetime.now(timezone.utc).timestamp()

    @staticmethod
    def today_date() -> datetime:
        """Get current date with time set to midnight UTC.

        Returns:
            Timezone-aware datetime object representing today at 00:00:00 UTC
        """
        return datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    @staticmethod
    def today_date_iso() -> str:
        """Get current date as ISO 8601 date string.

        Returns:
            Current date in ISO 8601 format (YYYY-MM-DD)
        """
        return datetime.now(timezone.utc).date().isoformat()

    @staticmethod
    def format_datetime(
        dt: datetime | None = None, format_str: str = "%Y-%m-%d"
    ) -> str:
        """Format datetime object to string.

        Args:
            dt: Datetime object to format (default: current datetime)
            format_str: Format string (default: "%Y-%m-%d")

        Returns:
            Formatted datetime string
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        return dt.strftime(format_str)

    @staticmethod
    def timestamp_to_iso(timestamp: float) -> str:
        """Convert Unix timestamp to ISO 8601 formatted string.

        Args:
            timestamp: Unix timestamp (seconds since epoch)

        Returns:
            ISO 8601 formatted datetime string
        """
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    @staticmethod
    def iso_to_datetime(iso_string: str) -> datetime:
        """Convert ISO 8601 formatted string to datetime object.

        Args:
            iso_string: ISO 8601 formatted datetime string

        Returns:
            Timezone-aware datetime object
        """
        dt = datetime.fromisoformat(iso_string)
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def timestamp_to_datetime(timestamp: float) -> datetime:
        """Convert Unix timestamp to datetime object.

        Args:
            timestamp: Unix timestamp (seconds since epoch)

        Returns:
            Timezone-aware datetime object in UTC
        """
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)


# Create global instance
dt = DateTimeUtils()


# Convenience exports
def get_current_datetime() -> datetime:
    """Get current datetime in UTC timezone.

    Returns:
        Timezone-aware datetime object in UTC
    """
    return dt.now()


def get_current_datetime_iso() -> str:
    """Get current datetime as ISO 8601 formatted string.

    Returns:
        Current datetime in ISO 8601 format (UTC)
    """
    return dt.now_iso()


def get_today_date() -> datetime:
    """Get current date with time set to midnight UTC.

    Returns:
        Timezone-aware datetime object representing today at 00:00:00 UTC
    """
    return dt.today_date()


def get_today_date_iso() -> str:
    """Get current date as ISO 8601 date string.

    Returns:
        Current date in ISO 8601 format (YYYY-MM-DD)
    """
    return dt.today_date_iso()
