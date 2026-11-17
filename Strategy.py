
def ema(values, period=50):
    if len(values) < period:
        return None

    result = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        result = (
            price * multiplier
            + result * (1 - multiplier)
        )

    return result


def get_trend(candles):
    if candles is None or len(candles) < 52:
        return "UNKNOWN"

    closed = candles[:-1]
    closes = [float(c["close"]) for c in closed]

    ema50 = ema(closes, 50)

    if closes[-1] > ema50:
        return "BULLISH"

    if closes[-1] < ema50:
        return "BEARISH"

    return "NEUTRAL"


def calculate_multi_timeframe_signal(
    symbol, m15, h1, h4
):
    if any(
        candles is None or len(candles) < 52
        for candles in (m15, h1, h4)
    ):
        return {
            "signal": "WAIT",
            "reason": "Insufficient timeframe data"
        }

    trend_h4 = get_trend(h4)
    trend_h1 = get_trend(h1)

    if trend_h4 != trend_h1:
        return {
            "signal": "WAIT",
            "reason": "H4 and H1 trends disagree"
        }

    closed = m15[:-1]

    closes = [float(c["close"]) for c in closed]
    opens = [float(c["open"]) for c in closed]
    highs = [float(c["high"]) for c in closed]
    lows = [float(c["low"]) for c in closed]

    ema50 = ema(closes, 50)

    close = closes[-1]
    open_price = opens[-1]

    previous_close = closes[-2]
    previous_open = opens[-2]

    bullish = close > open_price
    bearish = close < open_price

    previous_bearish = previous_close < previous_open
    previous_bullish = previous_close > previous_open

    buy = (
        trend_h4 == "BULLISH"
        and trend_h1 == "BULLISH"
        and close > ema50
        and bullish
        and previous_bearish
    )

    sell = (
        trend_h4 == "BEARISH"
        and trend_h1 == "BEARISH"
        and close < ema50
        and bearish
        and previous_bullish
    )

    if not buy and not sell:
        return {
            "signal": "WAIT",
            "reason": "No confirmed multi-timeframe setup"
        }

    direction = "BUY" if buy else "SELL"

    recent_high = max(highs[-6:])
    recent_low = min(lows[-6:])

    entry = close

    if direction == "BUY":
        stop_loss = recent_low
        risk = entry - stop_loss
    else:
        stop_loss = recent_high
        risk = stop_loss - entry

    if risk <= 0:
        return {
            "signal": "WAIT",
            "reason": "Invalid risk calculation"
        }

    tp1 = (
        entry + risk if direction == "BUY"
        else entry - risk
    )

    tp2 = (
        entry + (risk * 2) if direction == "BUY"
        else entry - (risk * 2)
    )

    return {
        "signal": direction,
        "symbol": symbol,
        "timeframe": "M15",
        "trend_h4": trend_h4,
        "trend_h1": trend_h1,
        "entry": round(entry, 3),
        "stop_loss": round(stop_loss, 3),
        "take_profit_1": round(tp1, 3),
        "take_profit_2": round(tp2, 3),
        "ema50": round(ema50, 3),
        "reason": "H4 + H1 trend and M15 confirmation"
    }


def calculate_signal(candles):
    return {
        "signal": "WAIT",
        "reason": "Multi-timeframe confirmation required"
    }

