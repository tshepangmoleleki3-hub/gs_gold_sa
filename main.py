
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

SUBSCRIBERS = set()
LAST_ALERT = None
AUTO_INTERVAL = 15 * 60


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


async def get_market_signal():
    candles = await asyncio.to_thread(get_xauusd_candles)
    return calculate_signal(candles)


def format_signal(result):
    direction = result["signal"]

    return (
        "🥇 GS GOLD SA — XAUUSD M15\n\n"
        f"SIGNAL: {direction}\n"
        f"Entry: {result['entry']}\n"
        f"Stop Loss: {result['stop_loss']}\n"
        f"TP1: {result['take_profit_1']}\n"
        f"TP2: {result['take_profit_2']}\n"
        f"EMA50: {result['ema50']}\n\n"
        "Strategy: EMA50 + candle confirmation\n"
        "Verify market conditions before trading."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)

    await update.message.reply_text(
        "🥇 GS Gold SA is online!\n\n"
        "You are subscribed to automatic XAUUSD M15 alerts.\n"
        "Market monitoring runs every 15 minutes.\n\n"
        "Use /signal for manual analysis.\n"
        "Signals are educational, not financial advice."
    )


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    SUBSCRIBERS.add(update.effective_chat.id)

    await update.message.reply_text(
        "Checking XAUUSD M15 market data..."
    )

    try:
        result = await get_market_signal()

    except Exception:
        logging.exception("Signal calculation failed")
        await update.message.reply_text(
            "⚠️ Market data unavailable.\n"
            "No trading signal generated."
        )
        return

    if result["signal"] not in ("BUY", "SELL"):
        await update.message.reply_text(
            "🥇 GS GOLD SA — XAUUSD M15\n\n"
            "SIGNAL: WAIT\n"
            f"Reason: {result.get('reason', 'No setup')}\n\n"
            "No confirmed trade setup."
        )
        return

    await update.message.reply_text(format_signal(result))


async def auto_monitor(application):
    global LAST_ALERT

    logging.info("GS Gold SA automatic monitoring started")

    while True:
        try:
            if SUBSCRIBERS:
                result = await get_market_signal()
                direction = result["signal"]

                if direction in ("BUY", "SELL"):
                    signature = (
                        direction,
                        result.get("entry"),
                        result.get("stop_loss"),
                        result.get("take_profit_1"),
                        result.get("take_profit_2"),
                    )

                    if signature != LAST_ALERT:
                        message = format_signal(result)

                        for chat_id in list(SUBSCRIBERS):
                            try:
                                await application.bot.send_message(
                                    chat_id=chat_id,
                                    text=message
                                )
                            except Exception:
                                logging.exception(
                                    "Telegram alert delivery failed"
                                )

                        LAST_ALERT = signature

                else:
                    LAST_ALERT = None
                    logging.info("Automatic check: WAIT")

        except Exception:
            logging.exception("Automatic market check failed")

        await asyncio.sleep(AUTO_INTERVAL)


async def post_init(application):
    application.create_task(auto_monitor(application))


def main():
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    threading.Thread(
        target=start_web_server,
        daemon=True
    ).start()

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal))

    app.run_polling()


if __name__ == "__main__":
    main()
