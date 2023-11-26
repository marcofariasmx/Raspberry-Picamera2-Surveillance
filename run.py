import subprocess
import time
import os
import sys

script_path = "./flask_picam2_stream_and_pic.py"

# Custom exit code to stop the wrapper
CUSTOM_EXIT_CODE = 100

# Check if the script exists
if not os.path.exists(script_path):
    print(f"Error: Script not found at {script_path}. Exiting.")
    sys.exit(1)

run_counter = 0

while True:
    run_counter += 1
    print(f"Starting script... (Run count: {run_counter})")
    result = subprocess.run(["python", script_path])

    if result.returncode == CUSTOM_EXIT_CODE:
        print(f"Script exited with custom exit code {CUSTOM_EXIT_CODE}. Stopping wrapper.")
        break

    print(f"Script exited with return code {result.returncode}. Restarting... (Run count: {run_counter})")
    time.sleep(5)  # Optional: Pause before restarting
