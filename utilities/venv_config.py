"""
AG2AI compatible virtual environment context for AutoGen.
Works with your existing configuration structure and packaged apps.
"""

import os
import platform
import sys
from pathlib import Path
from types import SimpleNamespace

from configs.settings import settings


class AG2AIVirtualEnvContext:
    """Virtual environment context compatible with AG2AI configuration structure."""

    def __init__(self, venv_path: str | None = None):
        """
        Initialize with AG2AI configuration.

        Args:
            venv_path: Path to venv directory (if None, uses get_venv_path())
        """
        self.venv_path = venv_path or self._get_venv_path()
        self.venv_directory = Path(self.venv_path).resolve()
        self._setup_environment()

    def _get_venv_path(self) -> str:
        """Get the path to venv directory for code execution (from your config)"""

        # Check environment variable first
        return settings.AG2AI_PYTHON_PATH
        # if 'AG2AI_VENV_PATH' in os.environ:
        #     return os.environ['AG2AI_VENV_PATH']

        # # Detect if running as packaged
        # if getattr(sys, 'frozen', False):
        #     base_path = Path(sys.executable).parent / "resources"
        # else:
        #     base_path = Path(__file__).parent / "build_resources"

        # # Path to venv directory
        # venv_path = base_path / "python_env" / "venv"

        # return str(venv_path) if venv_path.exists() else str(Path.cwd() / "venv")

    def _setup_environment(self) -> None:
        """Setup virtual environment paths and variables."""
        if not self.venv_directory.exists():
            raise FileNotFoundError(
                f"Virtual environment directory not found: {self.venv_directory}"
            )

        # Get Python executable from venv directory
        self.python_executable = self._get_python_executable()
        self.scripts_directory = self._get_scripts_directory()
        self.env_variables = self._get_env_variables()

    def _get_python_executable(self) -> Path:
        """Get Python executable from venv directory."""
        if sys.platform == "win32":
            scripts_dir = self.venv_directory / "Scripts"
            python_names = ["python.exe", "python3.exe"]
        else:
            scripts_dir = self.venv_directory / "bin"
            python_names = ["python", "python3"]

        # Try each possible Python executable name
        for python_name in python_names:
            python_path = scripts_dir / python_name
            if python_path.exists():
                return python_path

        # If standard names don't work, find any python* executable
        if scripts_dir.exists():
            for file in scripts_dir.iterdir():
                if file.is_file() and file.name.lower().startswith("python"):
                    return file

        raise FileNotFoundError(f"Python executable not found in {self.venv_directory}")

    def _get_scripts_directory(self) -> Path:
        """Get scripts/bin directory."""
        if sys.platform == "win32":
            return self.venv_directory / "Scripts"
        else:
            return self.venv_directory / "bin"

    def _get_env_variables(self) -> dict:
        """Get environment variables for the virtual environment."""
        path_separator = ";" if sys.platform == "win32" else ":"
        current_path = os.environ.get("PATH", "")

        env_vars = {
            "VIRTUAL_ENV": str(self.venv_directory),
            "PATH": f"{self.scripts_directory}{path_separator}{current_path}",
        }

        # Add AG2AI specific environment variables if they exist
        if "AG2AI_VENV_PATH" in os.environ:
            env_vars["AG2AI_VENV_PATH"] = os.environ["AG2AI_VENV_PATH"]

        return env_vars

    def get_context(self) -> SimpleNamespace:
        """
        Get SimpleNamespace for AutoGen LocalCommandLineCodeExecutor.

        Returns:
            SimpleNamespace with virtual environment context
        """
        return SimpleNamespace(
            python=str(self.python_executable),
            python_path=str(self.python_executable),
            venv_path=str(self.venv_directory),
            bin_path=str(self.scripts_directory),
            scripts_path=str(self.scripts_directory),
            env_vars=self.env_variables,
            platform=platform.system(),
            is_packaged=getattr(sys, "frozen", False),
        )

    def is_valid(self) -> bool:
        """Check if virtual environment setup is valid."""
        return (
            self.python_executable.exists()
            and self.python_executable.is_file()
            and self.venv_directory.exists()
            and self.scripts_directory.exists()
        )

    def get_info(self) -> dict:
        """Get detailed information about the environment setup."""
        return {
            "python_executable": str(self.python_executable),
            "venv_directory": str(self.venv_directory),
            "scripts_directory": str(self.scripts_directory),
            "platform": platform.system(),
            "is_packaged": getattr(sys, "frozen", False),
            "is_valid": self.is_valid(),
            "ag2ai_python_path": os.environ.get("AG2AI_PYTHON_PATH"),
            "environment_structure": "AG2AI Compatible",
        }


def create_ag2ai_executor(
    venv_path: str | None = None,
    work_dir: str | Path = "./code_execution",
    timeout: int = 60,
    **kwargs,
):
    """
    Create AutoGen LocalCommandLineCodeExecutor compatible with AG2AI configuration.

    Args:
        venv_path: Path to venv directory (if None, auto-detects from AG2AI config)
        work_dir: Working directory for code execution
        timeout: Execution timeout in seconds
        **kwargs: Additional arguments for LocalCommandLineCodeExecutor

    Returns:
        Configured LocalCommandLineCodeExecutor with proper virtual_env_context

    Examples:
        # Auto-detect from AG2AI configuration
        executor = create_ag2ai_executor()

        # Specify custom venv path
        executor = create_ag2ai_executor("/path/to/venv")

        # Custom work directory and timeout
        executor = create_ag2ai_executor(venv_path="/path/to/venv", work_dir="/tmp/ag2ai_work", timeout=120)
    """
    from autogen.coding import LocalCommandLineCodeExecutor

    # Create virtual environment context
    venv_context = AG2AIVirtualEnvContext(python_path)

    if not venv_context.is_valid():
        info = venv_context.get_info()
        raise ValueError(f"Invalid AG2AI virtual environment setup.\nDetails: {info}")

    # Prepare configuration
    config = {
        "timeout": timeout,
        "work_dir": str(work_dir),
        "virtual_env_context": venv_context.get_context(),
    }
    config.update(kwargs)

    return LocalCommandLineCodeExecutor(**config)


def get_ag2ai_python_path() -> str:
    """
    Get AG2AI Python executor path (same as your original function).

    Returns:
        Path to Python executable
    """
    context = AG2AIVirtualEnvContext()
    return str(context.python_executable)


def validate_ag2ai_setup() -> dict:
    """
    Validate AG2AI virtual environment setup.

    Returns:
        Dictionary with validation results and details
    """
    try:
        context = AG2AIVirtualEnvContext()
        info = context.get_info()
        info["validation_status"] = "SUCCESS" if context.is_valid() else "FAILED"
        return info
    except Exception as e:
        return {
            "validation_status": "ERROR",
            "error": str(e),
            "platform": platform.system(),
            "is_packaged": getattr(sys, "frozen", False),
        }


# Drop-in replacement for your original create_code_executor
def create_code_executor(**kwargs):
    """
    Drop-in replacement for your original create_code_executor function.
    Now uses virtual_env_context instead of deprecated 'python' parameter.
    """
    # Extract AG2AI specific parameters
    timeout = kwargs.pop("timeout", 60)
    work_dir = kwargs.pop("work_dir", "./code_execution")
    python_path = kwargs.pop("python", None)  # Handle legacy 'python' parameter

    return create_ag2ai_executor(
        python_path=python_path, work_dir=work_dir, timeout=timeout, **kwargs
    )


# Example usage and testing
if __name__ == "__main__":
    print("=== AG2AI Virtual Environment Context Testing ===")

    # Test validation
    validation = validate_ag2ai_setup()
    print(f"\nValidation Status: {validation['validation_status']}")
    for key, value in validation.items():
        print(f"  {key}: {value}")

    x = AG2AIVirtualEnvContext()
    print(x.get_context())
    # Test executor creation
    print("\n=== Testing Executor Creation ===")
    try:
        executor = create_ag2ai_executor()
        print("✓ Successfully created AG2AI executor")

        # Test legacy compatibility
        legacy_executor = create_code_executor()
        print("✓ Legacy create_code_executor still works")

    except Exception as e:
        print(f"✗ Failed to create executor: {e}")

    # Test custom paths
    print("\n=== Python Path Detection ===")
    python_path = get_ag2ai_python_path()
    print(f"Detected Python path: {python_path}")
    print(
        f"Environment variable AG2AI_PYTHON_PATH: {os.environ.get('AG2AI_PYTHON_PATH', 'Not set')}"
    )
    print(f"Is packaged: {getattr(sys, 'frozen', False)}")
    print(f"Platform: {platform.system()}")
