#!/usr/bin/env python3
"""
Test script to verify the new code executor with virtual environment works correctly.
"""

import os
import tempfile
import shutil
from pathlib import Path
from utilities.venv_manager import VenvManager
from utilities.custom_manager import ChatContext
from capabilities.python_developer.manager import PythonDeveloper


def test_code_executor():
    """Test the new code executor with virtual environment isolation."""
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Testing in temporary directory: {temp_dir}")
        
        # Create a mock OmniMemory instance
        from omni.memory import OmniMemory
        mock_memory = OmniMemory("test-user")
        
        # Create a mock chat context
        chat_context = ChatContext(
            user_id="test-user",
            chat_id="test-chat-001",
            chat_dir=temp_dir,
            call_id="test-call-001",
            capability_id="python_coder",
            capability_name="Python Developer",
            collection_name="test_collection",
            omni_memory=mock_memory
        )

        try:
            # Initialize PythonDeveloper with the new code executor
            print("Initializing PythonDeveloper...")
            python_dev = PythonDeveloper(chat_context)

            # Print virtual environment information
            venv_info = python_dev.get_venv_info()
            print(f"Virtual environment info:")
            print(f"  Python path: {venv_info['python_path']}")
            print(f"  Venv path: {venv_info['venv_path']}")
            print(f"  Bin path: {venv_info['bin_path']}")

            # Test if the virtual environment was created
            venv_path = Path(venv_info['venv_path'])
            if venv_path.exists():
                print("✅ Virtual environment created successfully")
            else:
                print("❌ Virtual environment not found")
                return False            # Test code execution
            print("\nTesting code execution...")
            
            test_code = """
print("Hello from isolated virtual environment!")
import sys
print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")

# Test basic computation
result = sum(range(1, 11))
print(f"Sum of 1-10: {result}")
"""
            
            # Get the actual LocalCommandLineCodeExecutor from the agent
            from autogen.coding import CodeBlock
            code_block = CodeBlock(language="python", code=test_code)
            result = python_dev.local_executor.execute_code_blocks([code_block])

            print(f"Code execution result:")
            print(f"  Exit code: {result.exit_code}")
            print(f"  Output: {result.output}")

            if result.exit_code == 0:
                print("✅ Code execution successful")
                return True
            else:
                print("❌ Code execution failed")
                return False

        except Exception as e:
            print(f"❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_package_installation():
    """Test package installation in virtual environment."""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"\nTesting package installation in: {temp_dir}")
        
        # Create a mock OmniMemory instance
        from omni.memory import OmniMemory
        mock_memory = OmniMemory("test-user")
        
        chat_context = ChatContext(
            user_id="test-user",
            chat_id="test-chat-002",
            chat_dir=temp_dir,
            call_id="test-call-002",
            capability_id="python_coder",
            capability_name="Python Developer",
            collection_name="test_collection",
            omni_memory=mock_memory
        )

        try:
            python_dev = PythonDeveloper(chat_context)

            # Test installing a package
            print("Installing 'requests' package...")
            success = python_dev.install_packages(['requests'])

            if success:
                print("✅ Package installation successful")

                # Test importing the package
                test_code = """
try:
    import requests
    print("Successfully imported requests")
    print(f"Requests version: {requests.__version__}")
except ImportError as e:
    print(f"Failed to import requests: {e}")
"""

                from autogen.coding import CodeBlock
                code_block = CodeBlock(language="python", code=test_code)
                result = python_dev.local_executor.execute_code_blocks([code_block])

                print(f"Import test result:")
                print(f"  Exit code: {result.exit_code}")
                print(f"  Output: {result.output}")

                return result.exit_code == 0
            else:
                print("❌ Package installation failed")
                return False

        except Exception as e:
            print(f"❌ Package installation test failed: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    print("🧪 Testing new code executor with virtual environment isolation")
    print("=" * 60)

    # Test basic functionality
    test1_success = test_code_executor()

    # Test package installation
    test2_success = test_package_installation()

    print("\n" + "=" * 60)
    print("Test Results:")
    print(f"  Basic code execution: {'✅ PASS' if test1_success else '❌ FAIL'}")
    print(f"  Package installation: {'✅ PASS' if test2_success else '❌ FAIL'}")

    if test1_success and test2_success:
        print("\n🎉 All tests passed! The new code executor is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Please check the implementation.")
