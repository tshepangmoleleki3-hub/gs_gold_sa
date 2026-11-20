import os
import asyncio
import logging
import threading

from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

from Market_data import MARKETS, TIMEFRAMES, get_market_candles
from Strategy import calculate_multi_timeframe_signal
from trading_session import get_trading_session, is_trade_time


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CONFIGURED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SOUTH_AFRICA = ZoneInfo("Africa/Johannesburg")

SCAN_INTERVAL = 900
MAX_DAILY_ALERTS = 2
API_REQUESTS_PER_BATCH = 8
BATCH_WAIT_SECONDS = 61

SUBSCRIBERS = set()

if CONFIGURED_CHAT_ID:
    try:
        SUBSCRIBERS.add(int(CONFIGURED_CHAT_ID))
    except ValueError:
        logging.error("Invalid TELEGRAM_CHAT_ID")

LATEST_RESULTS = {}
LATEST_SCAN_TIME = None
DAILY_ALERT_COUNT = 0
DAILY_COUNT_DATE = None
SEEN_SETUPS = set()


class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GS GOLD SA is running!")

    def log_message(self, format, *args):
        pass


def start_web_server():

    port = int(os.environ.get("PORT", 10000))

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    server.serve_forever()


def reset_daily_counter_if_needed():

    global DAILY_ALERT_COUNT
    global DAILY_COUNT_DATE
    global SEEN_SETUPS

    today = datetime.now(SOUTH_AFRICA).date()

    if DAILY_COUNT_DATE != today:
        DAILY_COUNT_DATE = today
        DAILY_ALERT_COUNT = 0
        SEEN_SETUPS.clear()
        logging.info("New South African trading day")


async def fetch_one(symbol, timeframe):

    candles = await asyncio.to_thread(
        get_market_candles,
        symbol,
        TIMEFRAMES[timeframe]
    )

    return symbol, timeframe, candles


async def scan_all_markets():

    global LATEST_RESULTS
    global LATEST_SCAN_TIME

    reset_daily_counter_if_needed()

    jobs = [
        (symbol, timeframe)
        for symbol in MARKETS
        for timeframe in ("M15", "H1", "H4")
    ]

    candle_data = {symbol: {} for symbol in MARKETS}
    data_errors = {}

    for start in range(0, len(jobs), API_REQUESTS_PER_BATCH):

        batch = jobs[start:start + API_REQUESTS_PER_BATCH]

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
                    symbol,
                    timeframe,
                    response
                )
                continue

            _, returned_timeframe, candles = response
            candle_data[symbol][returned_timeframe] = candles

        if start + API_REQUESTS_PER_BATCH < len(jobs):
            await asyncio.sleep(BATCH_WAIT_SECONDS)

    results = {}

    for symbol in MARKETS:

        if symbol in data_errors or len(candle_data[symbol]) != 3:
            results[symbol] = {
                "signal": "WAIT",
                "reason": "Market data unavailable"
            }
            continue

        try:
            m15 = candle_data[symbol]["M15"]
            h1 = candle_data[symbol]["H1"]
            h4 = candle_data[symbol]["H4"]

            result = calculate_multi_timeframe_signal(
                symbol, m15, h1, h4
            )

            result["signal_candle"] = m15[-2]["datetime"]
            results[symbol] = result

        except Exception:
            logging.exception("Strategy failed for %s", symbol)
            results[symbol] = {
                "signal": "WAIT",
                "reason": "Strategy calculation failed"
            }

    LATEST_RESULTS = results
    LATEST_SCAN_TIME = datetime.now(SOUTH_AFRICA)

    logging.info("Market scan completed")
    return results


def format_alert(symbol, result):

    return (
        "🥇 GS GOLD SA — TRADE SIGNAL\n\n"
        f"Market: {symbol}\n"
        f"Direction: {result['signal']}\n"
        "Timeframe: M15\n\n"
        f"Entry: {result['entry']}\n"
        f"Stop Loss: {result['stop_loss']}\n"
        f"TP1: {result['take_profit_1']}\n"
        f"TP2: {result['take_profit_2']}\n\n"
        f"H4 trend: {result['trend_h4']}\n"
        f"H1 trend: {result['trend_h1']}\n"
        f"Reason: {result['reason']}\n\n"
        f"South African time: "
        f"{datetime.now(SOUTH_AFRICA).strftime('%Y-%m-%d %H:%M')}\n\n"
        "DEMO TESTING ONLY. Verify the setup before trading."
    )


def format_results(results):

    lines = [
        "🥇 GS GOLD SA — MARKET SCANNER",
        "H4 + H1 + M15 strategy",
        f"South African time: {LATEST_SCAN_TIME}",
        f"Daily alerts: {DAILY_ALERT_COUNT}/{MAX_DAILY_ALERTS}",
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
                f"TP2: {result['take_profit_2']}"
            ])
        else:
            lines.append(
                f"Reason: {result.get('reason', 'No setup')}"
            )

        lines.append("")

    lines.append("Bot alerts are limited to two per SA day.")
    lines.append("Demo testing only. No profit is guaranteed.")

    return "\n".join(lines)


# TELEGRAM COMMANDS

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)

    await update.message.reply_text(
        f"Your Telegram Chat ID is: {chat_id}"
    )

    logging.info("Subscriber added: %s", chat_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)

    await update.message.reply_text(
        "🥇 GS GOLD SA is online!\n\n"
        "Automatic 8-market scanner.\n"
        "H4 + H1 confirmation with closed M15 candles.\n"
        "London and New York sessions only.\n"
        "Maximum two new alerts per South African day.\n\n"
        "Use /signal for the latest market scan.\n"
        "Use /myid to see your Telegram Chat ID."
    )

    logging.info("Subscriber added: %s", chat_id)


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not LATEST_RESULTS:
        await update.message.reply_text(
            "No completed market scan yet. "
            "Please wait for an active trading session."
        )
        return

    session = get_trading_session()

    await update.message.reply_text(
        format_results(LATEST_RESULTS)
        + "\n\nCurrent session: "
        + session["session"]
        + "\n"
        + session["message"]
    )


async def auto_monitor(application):

    global DAILY_ALERT_COUNT

    logging.info("GS GOLD SA automatic monitor started")

    while True:

        try:
            reset_daily_counter_if_needed()

            if not is_trade_time():
                session = get_trading_session()
                logging.info(
                    "Outside trading session: %s",
                    session["session"]
                )
                await asyncio.sleep(60)
                continue

            logging.info("Trading session active. Scanning markets.")

            results = await scan_all_markets()

            if DAILY_ALERT_COUNT < MAX_DAILY_ALERTS:

                for symbol, result in results.items():

                    if result.get("signal") not in ("BUY", "SELL"):
                        continue

                    setup_key = (
                        symbol,
                        result["signal"],
                        result.get("signal_candle")
                    )

                    if setup_key in SEEN_SETUPS:
                        continue

                    if DAILY_ALERT_COUNT >= MAX_DAILY_ALERTS:
                        break

                    if not SUBSCRIBERS:
                        logging.warning("No Telegram subscribers configured")
                        break

                    delivered = False
                    message = format_alert(symbol, result)

                    for chat_id in list(SUBSCRIBERS):
                        try:
                            await application.bot.send_message(
                                chat_id=chat_id,
                                text=message
                            )
                            delivered = True

                        except Exception:
                            logging.exception(
                                "Telegram delivery failed for %s",
                                chat_id
                            )

                    if delivered:
                        SEEN_SETUPS.add(setup_key)
                        DAILY_ALERT_COUNT += 1

                        logging.info(
                            "New alert sent: %s %s (%s/%s)",
                            symbol,
                            result["signal"],
                            DAILY_ALERT_COUNT,
                            MAX_DAILY_ALERTS
                        )

            logging.info(
                "Scan finished. Daily alerts: %s/%s",
                DAILY_ALERT_COUNT,
                MAX_DAILY_ALERTS
            )

        except asyncio.CancelledError:
            raise

        except Exception:
            logging.exception("Automatic monitor error")

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
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    threading.Thread(
        target=start_web_server,
        daemon=True
    ).start()

    telegram_request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30
    )

    app = (
        Application.builder()
        .token(TOKEN)
        .request(telegram_request)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("signal", signal))

    logging.info("Starting GS GOLD SA Telegram bot")

    app.run_polling(bootstrap_retries=5)


if __name__ == "__main__":
    main()
