
def calculate_signal(candles):
    """
    GS Gold SA - XAUUSD M15 strategy
    Uses completed candle data.
    Expected candle fields: open, high, low, close
    """

    if candles is None or len(candles) < 52:
        return {"signal": "WAIT", "reason": "Not enough candle data"}

    closes = [float(c["close"]) for c in candles]
    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    def ema(values, period):
        multiplier = 2 / (period + 1)
        result = values[0]

        for price in values[1:]:
            result = (price * multiplier) + (
                result * (1 - multiplier)
            )

        return result

    # Use the latest completed candle
    close = closes[-2]
    open_price = opens[-2]
    previous_close = closes[-3]
    previous_open = opens[-3]

    ema50 = ema(closes[:-1], 50)

    # Candle confirmation
    bullish = close > open_price
    bearish = close < open_price

    previous_bullish = previous_close > previous_open
    previous_bearish = previous_close < previous_open

    buy = close > ema50 and bullish and previous_bearish
    sell = close < ema50 and bearish and previous_bullish

    if not buy and not sell:
        return {
            "signal": "WAIT",
            "reason": "No confirmed setup"
        }

    signal = "BUY" if buy else "SELL"

    # Calculate stop loss using recent candle structure
    recent_high = max(highs[-7:-1])
    recent_low = min(lows[-7:-1])

    entry = close

    if signal == "BUY":
        sl = recent_low
        risk = entry - sl
    else:
        sl = recent_high
        risk = sl - entry

    if risk <= 0:
        return {
            "signal": "WAIT",
            "reason": "Invalid risk calculation"
        }

    # Risk/reward targets
    tp1 = entry + risk if signal == "BUY" else entry - risk
    tp2 = entry + (risk * 2) if signal == "BUY" else entry - (risk * 2)

    return {
        "signal": signal,
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "entry": round(entry, 2),
        "stop_loss": round(sl, 2),
        "take_profit_1": round(tp1, 2),
        "take_profit_2": round(tp2, 2),
        "ema50": round(ema50, 2),
        "reason": "EMA50 trend and candle confirmation"
    }
