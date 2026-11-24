"""
GS GOLD SA - M15 trade timing rules

Rules:
- A signal is evaluated only after its signal M15 candle has CLOSED.
- The entry time is the opening time of the NEXT M15 candle.
- If neither TP nor SL has been reached, issue CLOSE_TRADE at the end
  of the entry M15 candle.

This module calculates timing and exit instructions. It does not place or
close orders at Exness; the Telegram bot must call these functions and send
the returned instruction to the user.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SAST = ZoneInfo("Africa/Johannesburg")
M15 = timedelta(minutes=15)


def _require_aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{name} must include a timezone. Do not pass a timezone-naive datetime."
        )
    return value


def to_sast(value: datetime) -> datetime:
    """Convert a timezone-aware datetime to South African time."""
    return _require_aware(value, "value").astimezone(SAST)


def get_trade_schedule(signal_candle_open: datetime) -> dict:
    """
    Calculate entry and time-based exit from the M15 signal candle's open.

    Example:
      Signal candle: 10:00-10:15 SAST
      Entry candle:  10:15-10:30 SAST
      Time exit:     10:30 SAST, if TP and SL were both untouched
    """
    signal_open = _require_aware(
        signal_candle_open, "signal_candle_open"
    )
    signal_close = signal_open + M15
    entry_time = signal_close
    exit_deadline = entry_time + M15

    return {
        "signal_candle_open": signal_open.astimezone(SAST),
        "signal_candle_close": signal_close.astimezone(SAST),
        "entry_time": entry_time.astimezone(SAST),
        "exit_deadline": exit_deadline.astimezone(SAST),
        "timezone": "SAST",
    }


def get_exit_instruction(
    entry_candle_open: datetime,
    now: datetime,
    *,
    tp_hit: bool = False,
    sl_hit: bool = False,
) -> dict:
    """
    Return the correct trade status for an open trade.

    TP/SL outcomes take priority. If neither has been reached by the end
    of the entry M15 candle, return CLOSE_TRADE.
    """
    entry_open = _require_aware(entry_candle_open, "entry_candle_open")
    current_time = _require_aware(now, "now")
    deadline = entry_open + M15

    if tp_hit and sl_hit:
        status = "CHECK_TP_SL_DATA"
        message = (
            "TP and SL are both marked as reached. Check candle/tick data "
            "before deciding the trade outcome."
        )
    elif tp_hit:
        status = "TP_HIT"
        message = "TAKE PROFIT reached. Trade is complete."
    elif sl_hit:
        status = "SL_HIT"
        message = "STOP LOSS reached. Trade is complete."
    elif current_time >= deadline:
        status = "CLOSE_TRADE"
        message = (
            "TIME EXIT: The entry M15 candle has closed and neither TP nor "
            "SL was reached. Close the trade now."
        )
    else:
        status = "HOLD"
        message = (
            "HOLD: The entry M15 candle is still active. Keep monitoring "
            "TP and SL until the candle closes."
        )

    return {
        "status": status,
        "message": message,
        "entry_candle_open": entry_open.astimezone(SAST),
        "exit_deadline": deadline.astimezone(SAST),
        "checked_at": current_time.astimezone(SAST),
        "timezone": "SAST",
    }

