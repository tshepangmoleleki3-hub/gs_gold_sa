
import os
import asyncio
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from Market_data import MARKETS, TIMEFRAMES, get_market_candles
from Strategy import calculate_multi_timeframe_signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CONFIGURED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SUBSCRIBERS = set()
if CONFIGURED_CHAT_ID:
    SUBSCRIBERS.add(int(CONFIGURED_CHAT_ID))

SCAN_INTERVAL = 3600
MAX_DAILY_SIGNALS = 2
API_REQUESTS_PER_MINUTE = 8
SOUTH_AFRICA = ZoneInfo("Africa/Johannesburg")

LATEST_RESULTS = {}
LATEST_SCAN_TIME = None
DAILY_SIGNAL_COUNT = 0
DAILY_COUNT_DATE = None
SEEN_SETUPS = set()


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


def reset_daily_counter_if_needed():
    global DAILY_SIGNAL_COUNT, DAILY_COUNT_DATE, SEEN_SETUPS

    today = datetime.now(SOUTH_AFRICA).date()

    if DAILY_COUNT_DATE != today:
        DAILY_COUNT_DATE = today
        DAILY_SIGNAL_COUNT = 0
        SEEN_SETUPS.clear()

    return today


async def fetch_one(symbol, timeframe):
    candles = await asyncio.to_thread(
        get_market_candles,
        symbol,
        TIMEFRAMES[timeframe]
    )
    return symbol, timeframe, candles


async def scan_all_markets():
    global DAILY_SIGNAL_COUNT
    global LATEST_RESULTS, LATEST_SCAN_TIME

    jobs = [
        (symbol, timeframe)
        for symbol in MARKETS
        for timeframe in ("M15", "H1", "H4")
    ]

    candle_data = {
        symbol: {} for symbol in MARKETS
    }
    data_errors = {}

    # Respect Twelve Data's 8-credit/minute limit.
    for start in range(0, len(jobs), API_REQUESTS_PER_MINUTE):
        batch = jobs[start:start + API_REQUESTS_PER_MINUTE]

        responses = await asyncio.gather(
            *[
                fetch_one(symbol, timeframe)
                for symbol, timeframe in batch
            ],
            return_exceptions=True
        )

        for job, response in zip(batch, responses):
            symbol, timeframe = job

            if isinstance(response, Exception):
                data_errors[symbol] = str(response)
                logging.error(
                    "Data error: %s %s: %s",
                    symbol, timeframe, response
                )
                continue

            _, returned_timeframe, candles = response
            candle_data[symbol][returned_timeframe] = candles

        if start + API_REQUESTS_PER_MINUTE < len(jobs):
            await asyncio.sleep(61)

    results = {}

    for symbol in MARKETS:
        if symbol in data_errors or len(candle_data[symbol]) != 3:
            results[symbol] = {
                "signal": "WAIT",
                "reason": "Market data unavailable"
            }
            continue

        try:
            result = calculate_multi_timeframe_signal(
                symbol,
                candle_data[symbol]["M15"],
                candle_data[symbol]["H1"],
                candle_data[symbol]["H4"]
            )

            result["signal_candle"] = (
                candle_data[symbol]["M15"][-2]["datetime"]
            )

            results[symbol] = result

        except Exception as error:
            logging.exception("Strategy failed for %s", symbol)
            results[symbol] = {
                "signal": "WAIT",
                "reason": "Strategy calculation failed"
            }

    reset_daily_counter_if_needed()

    # Maximum two new actionable alerts per SA day.
    for symbol, result in results.items():
        if result.get("signal") not in ("BUY", "SELL"):
            continue

        setup_key = (
            symbol,
            result["signal"],
            result.get("signal_candle")
        )

        if setup_key in SEEN_SETUPS:
            result["signal"] = "WAIT"
            result["reason"] = "Setup already alerted"
            continue

        if DAILY_SIGNAL_COUNT >= MAX_DAILY_SIGNALS:
            result["signal"] = "WAIT"
            result["reason"] = "Daily alert limit reached"
            continue

        SEEN_SETUPS.add(setup_key)
        DAILY_SIGNAL_COUNT += 1

    LATEST_RESULTS = results
    LATEST_SCAN_TIME = datetime.now(SOUTH_AFRICA)

    logging.info(
        "Scan complete. Alerts: %s/%s",
        DAILY_SIGNAL_COUNT, MAX_DAILY_SIGNALS
    )

    return results


def format_results(results):
    lines = [
        "GS GOLD SA — 8 MARKET SCANNER",
        "H4 + H1 + M15 strategy",
        f"South Africa: {LATEST_SCAN_TIME}",
        f"Daily alerts: {DAILY_SIGNAL_COUNT}/2",
        ""
    ]

    for symbol, result in results.items():
        direction = result.get("signal", "WAIT")
        lines.append(f"{symbol}: {direction}")

        if direction in ("BUY", "SELL"):
            lines.extend([
                f"Entry: {result['entry']}",
                f"Stop Loss: {result['stop_loss']}",
                f"TP1: {result['take_profit_1']}",
                f"TP2: {result['take_profit_2']}",
                f"H4: {result['trend_h4']}",
                f"H1: {result['trend_h1']}"
            ])
        else:
            lines.append(
                f"Reason: {result.get('reason', 'No setup')}"
            )

        lines.append("")

    lines.append("Demo testing only. Verify before trading.")
    lines.append(
        "Alert limit does not track manual MT5 trades."
    )

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)

    await update.message.reply_text(
        "GS GOLD SA is online!\n\n"
        "Automatic 8-market scanner activated.\n"
        "H4 + H1 confirmation, M15 entries.\n"
        "Scanning approximately every hour.\n"
        "Maximum two actionable alerts per SA day.\n\n"
        "Use /signal for the latest scan."
    )

    logging.info("Subscriber added: %s", chat_id)


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not LATEST_RESULTS:
        await update.message.reply_text(
            "First market scan is not finished yet. "
            "Please try again shortly."
        )
        return

    await update.message.reply_text(
        format_results(LATEST_RESULTS)
    )


async def auto_monitor(application):
    logging.info("Hourly 8-market monitoring started")

    while True:
        try:
            if not SUBSCRIBERS:
                logging.info("Waiting for subscribers")
                await asyncio.sleep(30)
                continue

            results = await scan_all_markets()
            message = format_results(results)

            for chat_id in list(SUBSCRIBERS):
                try:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=message
                    )
                except Exception:
                    logging.exception(
                        "Telegram delivery failed"
                    )

        except asyncio.CancelledError:
            raise

        except Exception:
            logging.exception("Automatic scan failed")

        await asyncio.sleep(SCAN_INTERVAL)


async def post_init(application):
    application.bot_data["monitor_task"] = asyncio.create_task(
        auto_monitor(application)
    )


async def post_stop(application):
    task = application.bot_data.pop("monitor_task", None)

    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


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
        .post_stop(post_stop)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal))

    app.run_polling()


if __name__ == "__main__":
    main()
