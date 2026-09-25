"""
Unit tests for AI capabilities.
"""

import pytest


@pytest.mark.unit
@pytest.mark.capability
class TestCapabilities:
    """Tests for AI capabilities."""

    def test_capability_imports(self):
        """Test that the remaining capabilities can be imported."""
        from src.capabilities.browser_manager.manager import BrowserManager
        from src.capabilities.software_developer.manager import SoftwareDeveloper

        assert BrowserManager is not None
        assert SoftwareDeveloper is not None

    def test_capability_manager_initialization(self, mock_capability_manager):
        """Test capability manager initialization."""
        assert mock_capability_manager is not None
        assert hasattr(mock_capability_manager, "run")

    @pytest.mark.asyncio
    async def test_capability_run(self, mock_capability_manager):
        """Test running a capability."""
        result = await mock_capability_manager.run()
        assert result is not None
        mock_capability_manager.run.assert_called_once()

    def test_capability_resume(self, mock_capability_manager):
        """Test resuming a capability."""
        result = mock_capability_manager.resume(messages=[])
        assert result is not None


@pytest.mark.unit
@pytest.mark.capability
class TestBrowserManager:
    """Tests for Browser Manager capability."""

    def test_browser_manager_exists(self):
        """Test that BrowserManager class exists."""
        from src.capabilities.browser_manager.manager import BrowserManager

        assert BrowserManager is not None
