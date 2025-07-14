#!/usr/bin/env python3
import subprocess
import time

# Test the executable
print("🧪 Testing the executable...")
try:
    # Run the executable
    process = subprocess.Popen(
        ["./dist/omni-backend-app"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Wait a bit for the server to start
    time.sleep(3)

    # Check if process is still running
    if process.poll() is None:
        print("✅ Executable is running successfully!")
        print("🌐 FastAPI server should be available at: http://localhost:8002")

        # Terminate the process
        process.terminate()
        process.wait()
    else:
        stdout, stderr = process.communicate()
        print(f"❌ Executable failed to start")
        print(f"stdout: {stdout}")
        print(f"stderr: {stderr}")

except Exception as e:
    print(f"❌ Error testing executable: {e}")
