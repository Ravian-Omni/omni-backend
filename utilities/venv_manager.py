import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional
from types import SimpleNamespace
from loguru import logger
import platform
from .python_bundle_manager import PythonBundleManager


class VenvManager:
    """Manages Python virtual environments for project isolation."""

    def __init__(self, base_venv_path: Optional[str] = None):
        """
        Initialize VenvManager.

        Args:
            base_venv_path: Path to the base virtual environment to copy from.
                           If None, creates fresh venvs.
        """
        self.base_venv_path = Path(base_venv_path) if base_venv_path else None

    def create_project_venv(self, project_dir: str) -> SimpleNamespace:
        """
        Create or copy a virtual environment for a specific project.

        Args:
            project_dir: The project directory where the venv should be created

        Returns:
            SimpleNamespace: Virtual environment context for autogen
        """
        project_path = Path(project_dir)
        venv_path = project_path / ".venv"

        # Create project directory if it doesn't exist
        project_path.mkdir(parents=True, exist_ok=True)

        if venv_path.exists():
            logger.info(f"Virtual environment already exists at {venv_path}")
        else:
            if self.base_venv_path and self.base_venv_path.exists():
                # For executable mode, don't copy the venv (it has broken paths)
                # Instead, create fresh and install packages from requirements
                if self._is_running_as_executable():
                    logger.info(f"Creating fresh venv and installing packages from base venv at {self.base_venv_path}")
                    self._create_fresh_venv(venv_path)
                    self._install_packages_from_base_venv(venv_path, self.base_venv_path)
                else:
                    logger.info(f"Copying base venv from {self.base_venv_path} to {venv_path}")
                    self._copy_venv(self.base_venv_path, venv_path)
            else:
                logger.info(f"Creating new virtual environment at {venv_path}")
                self._create_fresh_venv(venv_path)

        return self._create_venv_context(venv_path)

    def _create_fresh_venv(self, venv_path: Path) -> None:
        """Create a fresh virtual environment."""
        try:
            # Get the appropriate Python executable
            python_executable = self._get_system_python()
            
            # Create the venv using the system Python
            subprocess.run([
                python_executable, "-m", "venv", str(venv_path)
            ], check=True, capture_output=True, text=True)

            # Install basic packages
            pip_path = self._get_pip_path(venv_path)
            subprocess.run([
                str(pip_path), "install", "--upgrade", "pip"
            ], check=True, capture_output=True, text=True)

            # Install common packages for code execution
            subprocess.run([
                str(pip_path), "install", "requests", "beautifulsoup4", "pandas", "numpy"
            ], check=True, capture_output=True, text=True)

            logger.info(
                f"Successfully created fresh virtual environment at {venv_path}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create virtual environment: {e}")
            logger.error(f"Stdout: {e.stdout}")
            logger.error(f"Stderr: {e.stderr}")
            raise

    def _copy_venv(self, src_venv: Path, dest_venv: Path) -> None:
        """Copy a virtual environment from source to destination."""
        try:
            shutil.copytree(src_venv, dest_venv, symlinks=True)

            # Update pyvenv.cfg to point to the correct location
            pyvenv_cfg = dest_venv / "pyvenv.cfg"
            if pyvenv_cfg.exists():
                with open(pyvenv_cfg, 'r') as f:
                    content = f.read()

                # Update the home path in pyvenv.cfg
                lines = content.split('\n')
                updated_lines = []
                for line in lines:
                    if line.startswith('home = '):
                        # Keep the original Python path
                        updated_lines.append(line)
                    else:
                        updated_lines.append(line)

                with open(pyvenv_cfg, 'w') as f:
                    f.write('\n'.join(updated_lines))

            logger.info(
                f"Successfully copied virtual environment from {src_venv} to {dest_venv}")

        except Exception as e:
            logger.error(f"Failed to copy virtual environment: {e}")
            # Fall back to creating a fresh venv
            if dest_venv.exists():
                shutil.rmtree(dest_venv)
            self._create_fresh_venv(dest_venv)

    def _install_packages_from_base_venv(self, target_venv: Path, base_venv: Path) -> None:
        """Install packages from base venv into the target venv."""
        try:
            # Get the pip path for the target venv
            pip_path = self._get_pip_path(target_venv)
            
            # First, upgrade pip in the target venv
            subprocess.run([
                str(pip_path), "install", "--upgrade", "pip"
            ], check=True, capture_output=True, text=True)
            
            # Try to get list of packages from base venv's pip freeze
            base_pip = self._get_pip_path(base_venv)
            
            # Use a simpler approach - install common packages directly
            # This avoids issues with freeze from a potentially broken base venv
            common_packages = [
                "requests", "beautifulsoup4", "lxml", "pandas", "numpy",
                "matplotlib", "seaborn", "pillow", "openpyxl", "python-dateutil",
                "urllib3", "certifi", "charset-normalizer", "idna", "six", "pytz"
            ]
            
            logger.info(f"Installing common packages in {target_venv}")
            subprocess.run([
                str(pip_path), "install"
            ] + common_packages, check=True, capture_output=True, text=True)
            
            logger.info(f"Successfully installed packages in {target_venv}")
            
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to install packages from base venv: {e}")
            # Continue without packages - the fresh venv will still work

    def _get_pip_path(self, venv_path: Path) -> Path:
        """Get the pip executable path for the virtual environment."""
        if platform.system() == "Windows":
            return venv_path / "Scripts" / "pip.exe"
        else:
            return venv_path / "bin" / "pip"

    def _get_python_path(self, venv_path: Path) -> Path:
        """Get the Python executable path for the virtual environment."""
        if platform.system() == "Windows":
            return venv_path / "Scripts" / "python.exe"
        else:
            return venv_path / "bin" / "python"

    def _create_venv_context(self, venv_path: Path) -> SimpleNamespace:
        """Create a virtual environment context for autogen."""
        python_path = self._get_python_path(venv_path)

        # Create context similar to autogen's create_virtual_env
        context = SimpleNamespace()
        context.python_path = str(python_path)
        context.pip_path = str(self._get_pip_path(venv_path))
        context.venv_path = str(venv_path)

        # Additional attributes that autogen expects
        if platform.system() == "Windows":
            context.bin_path = str(venv_path / "Scripts")
        else:
            context.bin_path = str(venv_path / "bin")

        return context

    def install_packages(self, venv_context: SimpleNamespace, packages: list) -> bool:
        """Install packages in the virtual environment."""
        try:
            pip_path = venv_context.pip_path
            subprocess.run([
                pip_path, "install"
            ] + packages, check=True, capture_output=True, text=True)

            logger.info(f"Successfully installed packages: {packages}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install packages {packages}: {e}")
            logger.error(f"Stderr: {e.stderr}")
            return False

    @staticmethod
    def get_base_venv_from_executable() -> Optional[Path]:
        """
        Get the path to bundle a base virtual environment with the executable.
        This would be used when the app is running as an executable.
        """
        if getattr(sys, 'frozen', False):
            # Running as executable - look for bundled base_venv
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller bundle
                base_venv = Path(sys._MEIPASS) / "base_venv"
            else:
                # Other bundling methods
                executable_dir = Path(sys.executable).parent
                base_venv = executable_dir / "base_venv"

            if base_venv.exists():
                logger.info(
                    f"Found bundled base virtual environment at: {base_venv}")
                return base_venv
            else:
                logger.warning(
                    f"Base virtual environment not found at: {base_venv}")

        return None

    def _get_system_python(self) -> str:
        """Get the best available Python executable path."""
        # Use the Python Bundle Manager to get the best Python
        return PythonBundleManager.get_best_python_executable()

    def _is_running_as_executable(self) -> bool:
        """Check if the application is running as a bundled executable."""
        return getattr(sys, 'frozen', False)
