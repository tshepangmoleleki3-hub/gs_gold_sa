
import os
import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from Market_data import get_xauusd_candles
from Strategy import calculate_signal

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
    server = ThreadingHTTPServer(
        ("0.0.0.0", port), HealthHandler
    )
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🥇 GS Gold SA is online!\n\n"
        "XAUUSD M15 signal engine connected.\n"
        "Use /signal for market analysis.\n"
        "Signals are educational, not financial advice."
    )


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Checking XAUUSD M15 market data..."
    )

    try:
        candles = await asyncio.to_thread(
            get_xauusd_candles
        )

        result = calculate_signal(candles)

    except Exception:
        logging.exception("Signal calculation failed")

        await update.message.reply_text(
            "⚠️ GS Gold SA\n\n"
            "Market data unavailable.\n"
            "No trading signal generated.\n"
            "Please check the API connection."
        )
        return

    direction = result["signal"]

    if direction not in ("BUY", "SELL"):
        await update.message.reply_text(
            "🥇 GS GOLD SA — XAUUSD M15\n\n"
            "SIGNAL: WAIT\n"
            f"Reason: {result.get('reason', 'No setup')}\n\n"
            "No confirmed trade setup."
        )
        return

    message = (
        "🥇 GS GOLD SA — XAUUSD M15\n\n"
        f"SIGNAL: {direction}\n"
        f"Entry: {result['entry']}\n"
        f"Stop Loss: {result['stop_loss']}\n"
        f"TP1: {result['take_profit_1']}\n"
        f"TP2: {result['take_profit_2']}\n"
        f"EMA50: {result['ema50']}\n\n"
        "Strategy: EMA50 + candle confirmation\n"
        "Market data must be verified before trading."
    )

    await update.message.reply_text(message)


def main():
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    threading.Thread(
        target=start_web_server,
        daemon=True
    ).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal))

    app.run_polling()


if __name__ == "__main__":
    main()
