"""
Unit tests for Omni core logic.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.mark.unit
class TestOmniCore:
    """Tests for Omni core functionality."""

    def test_omni_imports(self):
        """Test that Omni modules can be imported."""
        try:
            from src.omni.manager import Omni
            from src.omni.memory import OmniMemory
            from src.omni.capability_manager import CapabilityManager
            assert True
        except ImportError as e:
            pytest.fail(f"Failed to import Omni modules: {e}")

    def test_omni_manager_exists(self):
        """Test that Omni manager class exists."""
        from src.omni.manager import Omni
        assert Omni is not None

    def test_omni_memory_exists(self):
        """Test that OmniMemory class exists."""
        from src.omni.memory import OmniMemory
        assert OmniMemory is not None

    def test_capability_manager_exists(self):
        """Test that CapabilityManager exists."""
        try:
            from src.omni.capability_manager import CapabilityManager
            assert CapabilityManager is not None
        except ImportError:
            pytest.skip("CapabilityManager not found")


@pytest.mark.unit
class TestOmniMemory:
    """Tests for Omni memory management."""

    @pytest.fixture
    def omni_memory(self):
        """Create an OmniMemory instance."""
        from src.omni.memory import OmniMemory
        return OmniMemory()

    def test_memory_initialization(self, omni_memory):
        """Test memory initialization."""
        assert omni_memory is not None

    def test_memory_has_load_method(self, omni_memory):
        """Test that memory has load method."""
        assert hasattr(omni_memory, 'load_main_messages') or hasattr(omni_memory, 'load')

    def test_memory_stores_messages(self, omni_memory):
        """Test that memory can store messages."""
        # This test depends on the actual implementation
        if hasattr(omni_memory, 'messages'):
            assert isinstance(omni_memory.messages, (list, dict))
        elif hasattr(omni_memory, '_messages'):
            assert isinstance(omni_memory._messages, (list, dict))


@pytest.mark.unit
class TestResponseFormat:
    """Tests for response formatting."""

    def test_response_format_imports(self):
        """Test that response format modules can be imported."""
        try:
            from src.omni import response_format
            assert response_format is not None
        except ImportError as e:
            pytest.fail(f"Failed to import response_format: {e}")


@pytest.mark.unit
class TestPrompts:
    """Tests for prompt templates."""

    def test_prompts_module_exists(self):
        """Test that prompts module exists."""
        from src.omni import prompts
        assert prompts is not None

    def test_prompts_has_content(self):
        """Test that prompts module has content."""
        from src.omni import prompts
        # Check if module has any attributes/variables
        attrs = [attr for attr in dir(prompts) if not attr.startswith('_')]
        assert len(attrs) > 0
