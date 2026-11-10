
import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GS Gold SA is running!")

    def log_message(self, format, *args):
        pass


def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🥇 GS Gold SA is online!\n\n"
        "Gold signal bot setup started.\n"
        "Use /signal to see the demo signal format.\n"
        "Signals are for learning, not financial advice."
    )


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🥇 GS GOLD SA — XAUUSD M15\n\n"
        "DEMO ONLY — no live market analysis yet.\n"
        "BUY/SELL: WAIT\n"
        "Entry: Not available\n"
        "Stop Loss: Not available\n"
        "TP1: Not available\n"
        "TP2: Not available\n\n"
        "This bot is a setup test, not a trading signal."
    )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    threading.Thread(target=start_web_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal))
    app.run_polling()


if __name__ == "__main__":
    main()
