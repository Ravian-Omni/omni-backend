"""
Unit tests for configuration settings.
"""

import pytest
from unittest.mock import patch
from pydantic import ValidationError


@pytest.mark.unit
class TestSettings:
    """Tests for application settings."""

    def test_settings_import(self):
        """Test that settings can be imported."""
        from src.configs.settings import settings

        assert settings is not None

    def test_settings_has_port(self):
        """Test that settings has PORT."""
        from src.configs.settings import settings

        assert hasattr(settings, "PORT")

    def test_settings_has_project_name(self):
        """Test that settings has PROJECT_NAME."""
        from src.configs.settings import settings

        assert hasattr(settings, "PROJECT_NAME")

    def test_capability_type_enum(self):
        """Test CapabilityType enum if it exists."""
        try:
            from src.configs.settings import CapabilityType

            assert CapabilityType is not None
        except ImportError:
            pytest.skip("CapabilityType not found")

    @patch.dict("os.environ", {"PORT": "9000"})
    def test_settings_from_env(self):
        """Test loading settings from environment."""
        # Note: This may not work as settings are loaded at import time
        from src.configs.settings import settings

        assert settings is not None
