#!/usr/bin/env python3
"""
Script to flush/kill processes occupying ports and free them up.
This script will kill processes running on ports 8000-8020 and any omni-backend related processes.
"""

import subprocess
import sys
import signal
import os
import time


def run_command(command, capture_output=True, shell=True):
    """Run a shell command and return the result"""
    try:
        result = subprocess.run(
            command,
            shell=shell,
            capture_output=capture_output,
            text=True,
            timeout=10
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"⚠️  Command timed out: {command}")
        return None
    except Exception as e:
        print(f"❌ Error running command '{command}': {e}")
        return None


def kill_processes_by_port_range(start_port=8001, end_port=8020):
    """Kill processes using ports in the specified range"""
    print(f"🔍 Checking ports {start_port}-{end_port}...")

    killed_any = False
    for port in range(start_port, end_port + 1):
        # Find processes using the port
        result = run_command(f"lsof -ti:{port}")

        if result and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid.strip():
                    print(f"🔫 Killing process {pid} on port {port}")
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        killed_any = True
                        time.sleep(0.5)  # Give process time to terminate

                        # Force kill if still running
                        try:
                            # Check if process still exists
                            os.kill(int(pid), 0)
                            print(f"💀 Force killing stubborn process {pid}")
                            os.kill(int(pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass  # Process already terminated

                    except (ProcessLookupError, ValueError):
                        pass  # Process already dead or invalid PID
                    except PermissionError:
                        print(
                            f"❌ Permission denied killing process {pid}, trying with sudo...")
                        run_command(f"sudo kill -9 {pid}")

    return killed_any


def kill_omni_backend_processes():
    """Kill any omni-backend related processes"""
    print("🔍 Looking for omni-backend processes...")

    # Find processes with omni-backend in name
    result = run_command("ps aux | grep -i omni-backend | grep -v grep")

    if result and result.stdout.strip():
        lines = result.stdout.strip().split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                pid = parts[1]
                print(
                    f"🔫 Killing omni-backend process {pid}: {' '.join(parts[10:])}")
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(0.5)

                    # Force kill if still running
                    try:
                        os.kill(int(pid), 0)
                        print(
                            f"💀 Force killing stubborn omni-backend process {pid}")
                        os.kill(int(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

                except (ProcessLookupError, ValueError):
                    pass
                except PermissionError:
                    print(f"❌ Permission denied, trying with sudo...")
                    run_command(f"sudo kill -9 {pid}")


def kill_python_uvicorn_processes():
    """Kill Python processes running uvicorn"""
    print("🔍 Looking for Python uvicorn processes...")

    result = run_command(
        "ps aux | grep -E '(python.*uvicorn|uvicorn.*python)' | grep -v grep")

    if result and result.stdout.strip():
        lines = result.stdout.strip().split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                pid = parts[1]
                print(
                    f"🔫 Killing uvicorn process {pid}: {' '.join(parts[10:])}")
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(0.5)

                    # Force kill if still running
                    try:
                        os.kill(int(pid), 0)
                        print(
                            f"💀 Force killing stubborn uvicorn process {pid}")
                        os.kill(int(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

                except (ProcessLookupError, ValueError):
                    pass
                except PermissionError:
                    print(f"❌ Permission denied, trying with sudo...")
                    run_command(f"sudo kill -9 {pid}")


def check_port_status(start_port=8000, end_port=8020):
    """Check which ports are still in use"""
    print(f"\n📊 Port status check ({start_port}-{end_port}):")

    busy_ports = []
    for port in range(start_port, end_port + 1):
        result = run_command(f"lsof -ti:{port}")
        if result and result.stdout.strip():
            busy_ports.append(port)
            print(f"  🔴 Port {port}: BUSY")
        else:
            print(f"  🟢 Port {port}: FREE")

    return busy_ports


def main():
    print("🧹 Port Flush Script - Cleaning up occupied ports")
    print("=" * 50)

    # Check initial status
    busy_ports_before = check_port_status()

    if not busy_ports_before:
        print("\n✅ All ports are already free!")
        return

    print(
        f"\n🎯 Found {len(busy_ports_before)} busy ports. Starting cleanup...")

    # Kill processes by different methods
    print("\n1️⃣ Killing processes by port range...")
    killed_by_port = kill_processes_by_port_range()

    print("\n2️⃣ Killing omni-backend processes...")
    kill_omni_backend_processes()

    print("\n3️⃣ Killing Python uvicorn processes...")
    kill_python_uvicorn_processes()

    # Wait a moment for processes to terminate
    print("\n⏳ Waiting for processes to terminate...")
    time.sleep(2)

    # Check final status
    print("\n" + "=" * 50)
    busy_ports_after = check_port_status()

    freed_ports = len(busy_ports_before) - len(busy_ports_after)

    if busy_ports_after:
        print(
            f"\n⚠️  {len(busy_ports_after)} ports still busy: {busy_ports_after}")
        print("💡 You might need to restart your terminal or reboot if ports remain stuck")

        # Try one more aggressive cleanup
        print("\n🚨 Attempting aggressive cleanup...")
        for port in busy_ports_after:
            run_command(f"sudo lsof -ti:{port} | xargs sudo kill -9")

        time.sleep(1)
        final_check = check_port_status()
        if not final_check:
            print("✅ All ports freed after aggressive cleanup!")
        else:
            print(f"❌ {len(final_check)} ports still busy after aggressive cleanup")
    else:
        print(
            f"\n🎉 Success! Freed {freed_ports} ports. All target ports are now available!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑 Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
