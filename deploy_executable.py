#!/usr/bin/env python3
"""
Deployment script for the Omni Backend executable.
This script copies the executable and required configuration files to a target directory.
"""
import shutil
import sys
import os
from pathlib import Path


def deploy_executable(target_dir: str):
    """Deploy the executable and required files to target directory"""
    target_path = Path(target_dir)
    source_dir = Path(__file__).parent

    # Ensure target directory exists
    target_path.mkdir(parents=True, exist_ok=True)

    print(f"🚀 Deploying Omni Backend executable to: {target_path}")

    # Copy the executable
    executable_source = source_dir / "dist" / "omni-backend-app"
    executable_target = target_path / "omni-backend-app"

    if not executable_source.exists():
        print(f"❌ Executable not found at: {executable_source}")
        print("💡 Please build the executable first using: python build_executable.py")
        return False

    print(f"📦 Copying executable...")
    shutil.copy2(executable_source, executable_target)

    # Make it executable on Unix systems
    if os.name == 'posix':
        os.chmod(executable_target, 0o755)

    # Copy the .env file
    env_source = source_dir / ".env"
    env_target = target_path / ".env"

    if env_source.exists():
        print(f"📄 Copying .env file...")
        shutil.copy2(env_source, env_target)
        print(f"✅ Environment configuration copied")
    else:
        print(
            f"⚠️  No .env file found. You may need to create one manually at: {env_target}")
        # Create a template .env file
        template_env = """# Omni Backend Configuration
# Copy your actual environment variables here

# Database Configuration
MONGODB_URI=mongodb://localhost:27017
DATABASE_NAME=OMNI-DB

# API Keys (replace with your actual keys)
ANTHROPIC_API_KEY=your_anthropic_key_here
OPENAI_API_KEY=your_openai_key_here
AZURE_OPENAI_API_KEY=your_azure_key_here

# File paths
USER_FILES_PATH=/mnt/data
USER_EMAIL=your_email_here
"""
        with open(env_target, 'w') as f:
            f.write(template_env)
        print(f"📄 Created template .env file at: {env_target}")
        print(f"💡 Please edit the .env file with your actual configuration")

    # Create a simple start script
    start_script_content = """#!/bin/bash
# Start script for Omni Backend
cd "$(dirname "$0")"
./omni-backend-app
"""

    start_script_path = target_path / "start_omni_backend.sh"
    with open(start_script_path, 'w') as f:
        f.write(start_script_content)

    if os.name == 'posix':
        os.chmod(start_script_path, 0o755)

    print(f"✅ Deployment completed successfully!")
    print(f"📁 Files deployed to: {target_path}")
    print(f"🚀 To start the server, run: ./omni-backend-app")
    print(f"🔧 Or use the start script: ./start_omni_backend.sh")

    return True


def main():
    if len(sys.argv) != 2:
        print("Usage: python deploy_executable.py <target_directory>")
        print("Example: python deploy_executable.py /path/to/deployment/folder")
        sys.exit(1)

    target_dir = sys.argv[1]
    success = deploy_executable(target_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
