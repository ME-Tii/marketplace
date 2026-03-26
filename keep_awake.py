import requests
import time

# List of Render app URLs to keep awake
APP_URLS = [
    'https://marketplace-g2xq.onrender.com',
    'https://aschau-regional.onrender.com/'
]

def keep_awake():
    while True:
        for url in APP_URLS:
            try:
                response = requests.get(url)
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pinged {url}, status: {response.status_code}")
            except Exception as e:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error pinging {url}: {e}")
        time.sleep(300)  # Sleep for 5 minutes (300 seconds)

if __name__ == '__main__':
    keep_awake()