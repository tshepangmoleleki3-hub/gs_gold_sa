
import os
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_signal(message):
    if not TOKEN or not CHAT_ID:
        print("Telegram settings are missing.")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": message},
        timeout=15
    )
    response.raise_for_status()

if __name__ == "__main__":
    send_signal(
        "GS Gold SA is online!\n"
        "XAUUSD M15 signal delivery test.\n"
        "This is a test, not a trading signal."
    )
