"""
Unit tests for AI capabilities.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.mark.unit
@pytest.mark.capability
class TestCapabilities:
    """Tests for AI capabilities."""

    def test_capability_imports(self):
        """Test that capabilities can be imported."""
        try:
            from src.capabilities.browser_manager.manager import BrowserManager
            from src.capabilities.email_manager.manager import EmailManager
            from src.capabilities.file_finder.manager import FileFinder
            from src.capabilities.image_generator.manager import ImageGenerator
            from src.capabilities.python_developer.manager import PythonDeveloper
            assert True
        except ImportError as e:
            pytest.fail(f"Failed to import capabilities: {e}")

    def test_capability_manager_initialization(self, mock_capability_manager):
        """Test capability manager initialization."""
        assert mock_capability_manager is not None
        assert hasattr(mock_capability_manager, 'run')

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


@pytest.mark.unit
@pytest.mark.capability
class TestEmailManager:
    """Tests for Email Manager capability."""

    def test_email_manager_exists(self):
        """Test that EmailManager class exists."""
        from src.capabilities.email_manager.manager import EmailManager
        assert EmailManager is not None


@pytest.mark.unit
@pytest.mark.capability
class TestFileFinder:
    """Tests for File Finder capability."""

    def test_file_finder_exists(self):
        """Test that FileFinder class exists."""
        from src.capabilities.file_finder.manager import FileFinder
        assert FileFinder is not None


@pytest.mark.unit
@pytest.mark.capability
class TestImageGenerator:
    """Tests for Image Generator capability."""

    def test_image_generator_exists(self):
        """Test that ImageGenerator class exists."""
        from src.capabilities.image_generator.manager import ImageGenerator
        assert ImageGenerator is not None


@pytest.mark.unit
@pytest.mark.capability
class TestPythonDeveloper:
    """Tests for Python Developer capability."""

    def test_python_developer_exists(self):
        """Test that PythonDeveloper class exists."""
        from src.capabilities.python_developer.manager import PythonDeveloper
        assert PythonDeveloper is not None
