from datetime import datetime, time
from zoneinfo import ZoneInfo

SAST = ZoneInfo("Africa/Johannesburg")


def get_trading_session():
    now = datetime.now(SAST)
    current_time = now.time()

    london_start = time(9, 0)
    london_end = time(14, 0)

    new_york_start = time(15, 30)
    new_york_end = time(19, 0)

    if london_start <= current_time < london_end:
        return {
            "allowed": True,
            "session": "LONDON",
            "message": "London session active."
        }

    if new_york_start <= current_time < new_york_end:
        return {
            "allowed": True,
            "session": "NEW YORK",
            "message": "New York session active."
        }

    return {
        "allowed": False,
        "session": "OFF SESSION",
        "message": "Outside preferred trading hours. WAIT."
    }


def is_trade_time():
    return get_trading_session()["allowed"]
