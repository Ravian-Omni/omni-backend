from omni.controller import omni_manager
import sys

if len(sys.argv) < 2:
    print("[ERROR] No query provided.")
    sys.exit(1)

query = sys.argv[1]

print(f"[INFO] Starting agent with query: {query}")
omni_manager.initiate_chat(omni_manager, message=query)