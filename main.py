import os
import asyncio
import logging
import threading

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import Application, CommandHandler, ContextTypes

from Market_data import MARKETS, TIMEFRAMES, get_market_candles
from Strategy import calculate_multi_timeframe_signal
from trading_session import get_trading_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CONFIGURED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SAST = ZoneInfo("Africa/Johannesburg")

MAX_DAILY_ALERTS = 2
MAX_DAILY_TRADES = 2
API_REQUESTS_PER_BATCH = 8
BATCH_WAIT_SECONDS = 61
ENTRY_WINDOW_MINUTES = 4

SUBSCRIBERS = set()

if CONFIGURED_CHAT_ID:
    try:
        SUBSCRIBERS.add(int(CONFIGURED_CHAT_ID))
    except ValueError:
        logging.error("Invalid TELEGRAM_CHAT_ID")

LATEST_RESULTS = {}
LATEST_SCAN_TIME = None
DAILY_ALERT_COUNT = 0
DAILY_TRADE_COUNT = 0
DAILY_COUNT_DATE = None
SEEN_SETUPS = set()

# Active trades are held in memory only. A Render restart clears this dictionary.
ACTIVE_TRADES = {}


def format_sast_time(value=None):
    if value is None:
        value = datetime.now(SAST)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=SAST)
    else:
        value = value.astimezone(SAST)

    return value.strftime("%Y-%m-%d %H:%M:%S SAST")


def parse_candle_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    # Market_data returns UTC timestamps. Treat naive timestamps as UTC.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))

    return parsed.astimezone(SAST)


def get_m15_countdown():
    now = datetime.now(SAST)
    elapsed = (now.minute % 15) * 60 + now.second
    remaining = 900 - elapsed
    minutes, seconds = divmod(remaining, 60)
    return f"{minutes:02d}:{seconds:02d}"


def seconds_until_next_m15_close():
    now = datetime.now(SAST)
    next_boundary = (
        now.replace(second=0, microsecond=0)
        + timedelta(minutes=15 - now.minute % 15)
    )
    target = next_boundary + timedelta(seconds=5)
    return max(1, (target - now).total_seconds())


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GS GOLD SA is running!")

    def log_message(self, format, *args):
        pass


def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def reset_daily_counter_if_needed():
    global DAILY_ALERT_COUNT, DAILY_TRADE_COUNT, DAILY_COUNT_DATE, SEEN_SETUPS

    today = datetime.now(SAST).date()

    if DAILY_COUNT_DATE != today:
        DAILY_COUNT_DATE = today
        DAILY_ALERT_COUNT = 0
        DAILY_TRADE_COUNT = 0
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
    global LATEST_RESULTS, LATEST_SCAN_TIME

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
            *[fetch_one(symbol, timeframe) for symbol, timeframe in batch],
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

            if any(
                candles is None or len(candles) < 52
                for candles in (m15, h1, h4)
            ):
                results[symbol] = {
                    "signal": "WAIT",
                    "reason": "Insufficient candle data"
                }
                continue

            result = calculate_multi_timeframe_signal(
                symbol, m15, h1, h4
            )

            # Strategy uses closed candles; m15[-2] is the last completed M15 candle.
            result["signal_candle"] = m15[-2]["datetime"]
            results[symbol] = result

        except Exception:
            logging.exception("Strategy failed for %s", symbol)
            results[symbol] = {
                "signal": "WAIT",
                "reason": "Strategy calculation failed"
            }

    LATEST_RESULTS = results
    LATEST_SCAN_TIME = datetime.now(SAST)

    logging.info("Market scan completed")
    return results


def format_alert(symbol, result):
    try:
        candle_close = parse_candle_time(result["signal_candle"]) + timedelta(minutes=15)
        entry_deadline = candle_close + timedelta(minutes=ENTRY_WINDOW_MINUTES)
        timing_text = (
            f"Next M15 entry candle starts: {format_sast_time(candle_close)}\n"
            f"Entry confirmation deadline: {format_sast_time(entry_deadline)}\n"
            f"Only enter if your Exness price still gives a valid setup."
        )
    except Exception:
        timing_text = "Check the current M15 candle time before considering entry."

    return (
        "🥇 GS GOLD SA — TRADE SIGNAL\n\n"
        f"Market: {symbol}\n"
        f"Direction: {result['signal']}\n"
        "Timeframe: M15\n\n"
        f"Entry reference: {result['entry']}\n"
        f"Stop Loss: {result['stop_loss']}\n"
        f"TP1: {result['take_profit_1']}\n"
        f"TP2: {result['take_profit_2']}\n\n"
        f"H4 trend: {result['trend_h4']}\n"
        f"H1 trend: {result['trend_h1']}\n"
        f"Reason: {result['reason']}\n\n"
        f"Signal detected: {format_sast_time()}\n"
        f"{timing_text}\n\n"
        f"If you manually open this demo trade, send /entered {symbol} "
        "within the entry window.\n"
        "DEMO TESTING ONLY. The entry reference is not a guaranteed fill."
    )


def format_results(results):
    session = get_trading_session()

    lines = [
        "🥇 GS GOLD SA — MARKET SCANNER",
        "H4 + H1 + M15 strategy",
        f"South African scan time: {format_sast_time(LATEST_SCAN_TIME)}",
        f"Current South African time: {format_sast_time()}",
        f"Trading session: {session['session']}",
        f"M15 candle closes in: {get_m15_countdown()}",
        f"Daily alerts: {DAILY_ALERT_COUNT}/{MAX_DAILY_ALERTS}",
        f"Daily registered trades: {DAILY_TRADE_COUNT}/{MAX_DAILY_TRADES}",
        ""
    ]

    for symbol, result in results.items():
        direction = result.get("signal", "WAIT")
        lines.append(f"{symbol}: {direction}")

        if direction in ("BUY", "SELL"):
            lines.extend([
                f"Entry reference: {result['entry']}",
                f"Stop Loss: {result['stop_loss']}",
                f"TP1: {result['take_profit_1']}",
                f"TP2: {result['take_profit_2']}"
            ])
        else:
            lines.append(
                f"Reason: {result.get('reason', 'No setup')}"
            )

        lines.append("")

    lines.append("Maximum two alerts and two registered trades per South African day.")
    lines.append("Demo testing only. No profit is guaranteed.")
    return "\n".join(lines)


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)

    await update.message.reply_text(
        f"Your Telegram Chat ID is: {chat_id}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)

    await update.message.reply_text(
        "🥇 GS GOLD SA is online!\n\n"
        "Automatic scanner for the configured markets.\n"
        "H4 + H1 confirmation with closed M15 candles.\n"
        "London and New York sessions only for new signals.\n"
        "Maximum two alerts and two registered trades per South African day.\n\n"
        "Commands:\n"
        "/signal — latest market scan\n"
        "/entered XAUUSD — register a demo trade you opened manually\n"
        "/trades — show active monitored trades\n"
        "/myid — show your Telegram Chat ID\n\n"
        "The bot does not place or close trades in Exness."
    )


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_trading_session()

    if not session["allowed"]:
        await update.message.reply_text(
            "🥇 GS GOLD SA\n\n"
            "MARKET CLOSED\n"
            f"South African time: {format_sast_time()}\n"
            f"Session: {session['session']}\n\n"
            "Please wait for the next approved trading session."
        )
        return

    if not LATEST_RESULTS:
        await update.message.reply_text(
            "No completed market scan yet. Please wait."
        )
        return

    await update.message.reply_text(
        format_results(LATEST_RESULTS) + "\n\n" + session["message"]
    )


async def entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DAILY_TRADE_COUNT

    reset_daily_counter_if_needed()

    if not context.args:
        await update.message.reply_text(
            "Use this command after manually opening a demo trade:\n"
            "/entered XAUUSD"
        )
        return

    symbol = context.args[0].upper()

    if symbol not in MARKETS:
        await update.message.reply_text(
            "Unknown market. Use one of: " + ", ".join(MARKETS.keys())
        )
        return

    if symbol in ACTIVE_TRADES:
        await update.message.reply_text(
            f"{symbol} already has a trade being monitored. Use /trades."
        )
        return

    if DAILY_TRADE_COUNT >= MAX_DAILY_TRADES:
        await update.message.reply_text(
            "Daily trade limit reached (2). No more trades should be registered today."
        )
        return

    result = LATEST_RESULTS.get(symbol)
    if not result or result.get("signal") not in ("BUY", "SELL"):
        await update.message.reply_text(
            f"No current BUY/SELL setup is available for {symbol}. Do not register a trade."
        )
        return

    try:
        signal_close = parse_candle_time(result["signal_candle"]) + timedelta(minutes=15)
    except Exception:
        await update.message.reply_text(
            "I cannot read the signal candle time. Please wait for a fresh scan."
        )
        return

    now = datetime.now(SAST)
    deadline = signal_close + timedelta(minutes=ENTRY_WINDOW_MINUTES)

    if now < signal_close or now > deadline:
        await update.message.reply_text(
            "The entry confirmation window has passed or has not started.\n"
            f"Expected entry candle: {format_sast_time(signal_close)}\n"
            f"Deadline: {format_sast_time(deadline)}\n"
            "Wait for a fresh signal. Do not chase the price."
        )
        return

    ACTIVE_TRADES[symbol] = {
        "direction": result["signal"],
        "entry_reference": result["entry"],
        "stop_loss": result["stop_loss"],
        "take_profit_1": result["take_profit_1"],
        "take_profit_2": result["take_profit_2"],
        "signal_candle": result["signal_candle"],
        "entry_candle_open": signal_close,
        "registered_at": now,
        "chat_id": update.effective_chat.id,
    }
    DAILY_TRADE_COUNT += 1

    await update.message.reply_text(
        "🥇 GS GOLD SA — DEMO TRADE REGISTERED\n\n"
        f"Market: {symbol}\n"
        f"Direction: {result['signal']}\n"
        f"Entry reference (not confirmed fill): {result['entry']}\n"
        f"Stop Loss: {result['stop_loss']}\n"
        f"TP1: {result['take_profit_1']}\n"
        f"TP2: {result['take_profit_2']}\n\n"
        f"Monitoring the M15 candle ending at "
        f"{format_sast_time(signal_close + timedelta(minutes=15))}.\n"
        "At that candle close, the bot will check available candle high/low "
        "and send a status. You must manage/close the position manually in Exness.\n\n"
        "Daily registered trades: "
        f"{DAILY_TRADE_COUNT}/{MAX_DAILY_TRADES}."
    )


async def trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ACTIVE_TRADES:
        await update.message.reply_text("There are no trades currently registered for monitoring.")
        return

    lines = ["🥇 GS GOLD SA — REGISTERED TRADES", ""]
    for symbol, trade in ACTIVE_TRADES.items():
        lines.extend([
            f"{symbol}: {trade['direction']}",
            f"Entry reference: {trade['entry_reference']}",
            f"SL: {trade['stop_loss']}",
            f"TP1: {trade['take_profit_1']}",
            f"TP2: {trade['take_profit_2']}",
            f"Entry candle: {format_sast_time(trade['entry_candle_open'])}",
            ""
        ])
    lines.append("Check your actual position in Exness; the bot cannot see your account.")
    await update.message.reply_text("\n".join(lines))


async def evaluate_active_trades(application):
    """Evaluate only the completed M15 candle; OHLC cannot reveal intrabar order."""
    for symbol, trade in list(ACTIVE_TRADES.items()):
        try:
            candles = await asyncio.to_thread(
                get_market_candles, symbol, TIMEFRAMES["M15"]
            )

            if not candles or len(candles) < 2:
                continue

            # The final candle may still be forming; use the previous, completed candle.
            completed = candles[-2]
            completed_open = parse_candle_time(completed["datetime"])
            expected_open = trade["entry_candle_open"]

            if completed_open < expected_open:
                continue

            if completed_open > expected_open:
                message = (
                    "🥇 GS GOLD SA — CHECK EXNESS\n\n"
                    f"{symbol}: the bot missed the exact entry candle while scanning.\n"
                    "It cannot reliably determine whether TP or SL was reached.\n"
                    "Please check your Exness demo position and close/manage it yourself."
                )
                await application.bot.send_message(
                    chat_id=trade["chat_id"], text=message
                )
                ACTIVE_TRADES.pop(symbol, None)
                continue

            high = float(completed["high"])
            low = float(completed["low"])
            stop = float(trade["stop_loss"])
            target = float(trade["take_profit_1"])

            if trade["direction"] == "BUY":
                sl_hit = low <= stop
                tp_hit = high >= target
            else:
                sl_hit = high >= stop
                tp_hit = low <= target

            if sl_hit and tp_hit:
                status = (
                    "BOTH TP1 AND SL WERE INSIDE THE SAME M15 CANDLE.\n"
                    "Candle OHLC cannot tell which was reached first. "
                    "Check Exness history immediately."
                )
            elif sl_hit:
                status = "STOP LOSS level was touched in the completed M15 candle. Check Exness."
            elif tp_hit:
                status = "TP1 level was touched in the completed M15 candle. Check Exness."
            else:
                status = (
                    "CLOSE / CHECK POSITION: neither TP1 nor SL appears in the completed "
                    "M15 candle. Your agreed time rule is to close at this candle's end."
                )

            message = (
                "🥇 GS GOLD SA — M15 TRADE CHECK\n\n"
                f"Market: {symbol}\n"
                f"Direction: {trade['direction']}\n"
                f"Completed candle: {format_sast_time(completed_open)}\n"
                f"Status: {status}\n\n"
                "The bot cannot see your Exness account and cannot close orders. "
                "Confirm and manage the position manually. Candle data is not tick-by-tick."
            )
            await application.bot.send_message(
                chat_id=trade["chat_id"], text=message
            )
            ACTIVE_TRADES.pop(symbol, None)

        except Exception:
            logging.exception("Could not evaluate active trade for %s", symbol)


async def auto_monitor(application):
    global DAILY_ALERT_COUNT

    logging.info("GS GOLD SA automatic monitor started")

    while True:
        try:
            reset_daily_counter_if_needed()

            # Keep checking registered demo trades even outside new-entry sessions.
            if ACTIVE_TRADES:
                await evaluate_active_trades(application)

            session = get_trading_session()
            if not session["allowed"]:
                await asyncio.sleep(60)
                continue

            delay = seconds_until_next_m15_close()
            logging.info("Next M15 scan in %.1f seconds", delay)
            await asyncio.sleep(delay)

            # Check monitored positions after the candle boundary.
            if ACTIVE_TRADES:
                await evaluate_active_trades(application)

            session = get_trading_session()
            if not session["allowed"]:
                continue

            results = await scan_all_markets()

            session = get_trading_session()
            if not session["allowed"]:
                continue

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
                            symbol, result["signal"],
                            DAILY_ALERT_COUNT, MAX_DAILY_ALERTS
                        )

        except asyncio.CancelledError:
            raise

        except Exception:
            logging.exception("Automatic monitor error")
            await asyncio.sleep(30)


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
    app.add_handler(CommandHandler("entered", entered))
    app.add_handler(CommandHandler("trades", trades))

    logging.info("Starting GS GOLD SA Telegram bot")
    app.run_polling(bootstrap_retries=5)


if __name__ == "__main__":
    main()
