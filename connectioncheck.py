import os
import time
import subprocess

def is_connected():
    """Check if there is an active internet connection."""
    try:
        subprocess.check_call(['ping', '-c', '1', '8.8.8.8'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    fail_count = 0
    while True:
        if is_connected():
            fail_count = 0  # Reset counter if connection is successful
        else:
            fail_count += 1
            print(f"Connection failed {fail_count} times.")

        if fail_count >= 5:
            print("No internet connection for 5 consecutive checks. Rebooting...")
            os.system('sudo reboot')

        time.sleep(1)  # Wait 1 second before the next check

if __name__ == "__main__":
    main()
