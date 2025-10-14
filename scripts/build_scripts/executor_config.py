"""Configuration for AG2AI code executor"""

import os
import sys
from pathlib import Path


def get_python_executor_path():
    """Get the path to Python executable for code execution"""

    # Check environment variable first
    if "AG2AI_PYTHON_PATH" in os.environ:
        return os.environ["AG2AI_PYTHON_PATH"]

    # Detect if running as packaged
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).parent / "resources"
    else:
        base_path = Path(__file__).parent / "build_resources"

    # Platform-specific Python path
    if sys.platform == "win32":
        python_exe = base_path / "python_env" / "venv" / "Scripts" / "python.exe"
    else:
        python_exe = base_path / "python_env" / "venv" / "bin" / "python"

    return str(python_exe) if python_exe.exists() else "python"


def create_code_executor(**kwargs):
    """Factory function to create configured executor"""
    from autogen import LocalCommandLineCodeExecutor

    default_config = {
        "timeout": 60,
        "work_dir": "./code_execution",
        "python": get_python_executor_path(),
    }

    # Merge with any provided kwargs
    default_config.update(kwargs)

    return LocalCommandLineCodeExecutor(**default_config)


# Usage in your code:
# from executor_config import create_code_executor
# executor = create_code_executor()
