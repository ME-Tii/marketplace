import requests
import time

# Replace with your Render app URL
APP_URL = 'https://your-marketplace-app.onrender.com'

def keep_awake():
    while True:
        try:
            response = requests.get(APP_URL)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pinged {APP_URL}, status: {response.status_code}")
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error pinging: {e}")
        time.sleep(600)  # Sleep for 10 minutes (600 seconds)

if __name__ == '__main__':
    keep_awake()