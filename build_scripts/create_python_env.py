#!/usr/bin/env python3
import subprocess
import sys
import platform
from pathlib import Path

def create_code_execution_env():
    """Create a minimal Python environment for code execution"""
    env_dir = Path("build_resources/python_env")
    env_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a requirements file for the execution environment
    exec_requirements = env_dir / "exec_requirements.txt"
    with open(exec_requirements, 'w') as f:
        f.write("""numpy
pandas
matplotlib
scipy
requests
seaborn
""")
    
    print("Creating Python environment for code execution...")
    
    # Create virtual environment
    subprocess.run([
        sys.executable, "-m", "venv", 
        str(env_dir / "venv")
    ], check=True)
    
    # Determine pip path
    if platform.system() == "Windows":
        pip_path = env_dir / "venv" / "Scripts" / "pip.exe"
    else:
        pip_path = env_dir / "venv" / "bin" / "pip"
    
    # Upgrade pip, setuptools, and wheel first
    subprocess.run([str(pip_path), "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    # Install packages from requirements
    subprocess.run([
        str(pip_path), "install", "-r", str(exec_requirements)
    ], check=True)
    
    print("Python execution environment ready!")

if __name__ == "__main__":
    create_code_execution_env()
