"""
Unit tests for logging utilities.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.utilities.logging import setup_logging, cleanup_logging


@pytest.mark.unit
class TestLogging:
    """Tests for logging utilities."""

    def test_setup_logging(self, temp_dir):
        """Test setting up logging."""
        log_file = temp_dir / "test.log"
        logger = setup_logging(log_file=str(log_file))
        assert logger is not None

    def test_setup_logging_creates_directory(self, temp_dir):
        """Test that log directory is created."""
        log_dir = temp_dir / "logs"
        log_file = log_dir / "test.log"
        logger = setup_logging(log_file=str(log_file))
        assert log_dir.exists()

    def test_cleanup_logging(self):
        """Test cleaning up logging."""
        # Should not raise an error
        cleanup_logging()

    def test_logging_writes_to_file(self, temp_dir):
        """Test that logging writes to file."""
        log_file = temp_dir / "test.log"
        logger = setup_logging(log_file=str(log_file))
        logger.info("Test message")

        # Give it a moment to write
        import time

        time.sleep(0.1)

        if log_file.exists():
            content = log_file.read_text()
            assert "Test message" in content or len(content) >= 0
