#!/usr/bin/env python3
"""
Entry point script for the Omni Backend server.
This script handles server startup logic and port management.
"""
import os
import sys
import socket
import fcntl
from pathlib import Path


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """Check if a port is available for binding"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def create_lock_file(lock_path: str) -> bool:
    """Create a lock file to prevent multiple instances. Returns True if successful."""
    try:
        lock_file = open(lock_path, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        return True
    except (IOError, OSError):
        return False


def is_running_as_executable() -> bool:
    """Check if the application is running as a PyInstaller executable"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_port() -> int:
    """Get the appropriate port based on execution mode"""
    if is_running_as_executable():
        return 8001  # Executable runs on port 8001
    else:
        return 8000  # Development runs on port 8000


def get_app_path() -> Path:
    """Get the appropriate app path based on execution mode"""
    if is_running_as_executable():
        # For executable, use the directory where the executable is located
        return Path(sys.executable).parent
    else:
        # For development, use the directory where this script is located
        return Path(__file__).parent


def main():
    """Main entry point for the server"""
    import uvicorn

    # Initialize paths and configuration
    app_path = get_app_path()
    port = get_port()
    is_executable = is_running_as_executable()

    print(f"🚀 Starting Omni Backend Server...")
    print(f"📁 App directory: {app_path}")
    print(f"🔧 Running as executable: {is_executable}")
    print(f"🌐 Target port: {port}")

    # For executable mode, implement single-instance check
    if is_executable:
        lock_file_path = app_path / "omni-backend.lock"

        if not create_lock_file(str(lock_file_path)):
            print(f"❌ Another instance of the application is already running!")
            print(
                f"💡 If you're sure no other instance is running, delete: {lock_file_path}")
            sys.exit(1)

        print(f"🔒 Lock file created: {lock_file_path}")

    # Check if the required port is available - fail fast if not
    if not is_port_available(port):
        print(f"❌ Port {port} is not available!")
        if is_executable:
            print(f"💡 The executable requires port {port} to be free.")
            print(f"💡 Use the flush_ports.py script to clear port conflicts:")
            print(f"💡 python flush_ports.py")
        else:
            print(f"💡 Development mode requires port {port} to be free.")
            print(
                f"💡 Kill any process using port {port} or use flush_ports.py")
        sys.exit(1)

    try:
        print(f"✅ Port {port} is available, starting server...")

        if is_executable:
            # For executable, import and run the app directly
            from main import app
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                reload=False,
                access_log=False
            )
        else:
            # For development, use module string for hot reload
            uvicorn.run(
                "main:app",
                host="0.0.0.0",
                port=port,
                reload=True,
                log_level="info"
            )
    except KeyboardInterrupt:
        print("🛑 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        print("💡 Check the logs for more details")
        sys.exit(1)


if __name__ == "__main__":
    main()
