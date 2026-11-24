
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
        session = "LONDON"
        allowed = True
        message = "London session active."

    elif new_york_start <= current_time < new_york_end:
        session = "NEW YORK"
        allowed = True
        message = "New York session active."

    else:
        session = "OFF SESSION"
        allowed = False
        message = "Outside preferred trading hours. WAIT."

    return {
        "allowed": allowed,
        "session": session,
        "message": message,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timezone": "SAST"
    }


def is_trade_time():
    return get_trading_session()["allowed"]
