
import os
import json
import urllib.parse
import urllib.request


MARKETS = {
    "XAUUSD": "XAU/USD",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "USDCHF": "USD/CHF",
    "AUDUSD": "AUD/USD",
    "USDCAD": "USD/CAD",
    "NZDUSD": "NZD/USD",
}

TIMEFRAMES = {
    "M15": "15min",
    "H1": "1h",
    "H4": "4h",
}


def get_market_candles(symbol, interval="15min"):
    """
    Fetch market candles from Twelve Data.
    Returns candles in chronological order.
    """

    api_key = os.getenv("TWELVE_DATA_API_KEY")

    if not api_key:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing"
        )

    if symbol not in MARKETS:
        raise ValueError(f"Unsupported market: {symbol}")

    if interval not in TIMEFRAMES.values():
        raise ValueError(f"Unsupported timeframe: {interval}")

    params = {
        "symbol": MARKETS[symbol],
        "interval": interval,
        "outputsize": 100,
        "order": "asc",
        "timezone": "UTC",
        "apikey": api_key
    }

    url = (
        "https://api.twelvedata.com/time_series?"
        + urllib.parse.urlencode(params)
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GS-Gold-SA/1.0"}
    )

    try:
        with urllib.request.urlopen(
            request, timeout=20
        ) as response:
            data = json.loads(
                response.read().decode()
            )

    except Exception as error:
        raise RuntimeError(
            f"Market data connection failed: {error}"
        )

    if "values" not in data:
        raise RuntimeError(
            f"Market data error: {data.get('message', data)}"
        )

    candles = []

    for item in data["values"]:
        candles.append({
            "datetime": item["datetime"],
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"])
        })

    if len(candles) < 52:
        raise RuntimeError(
            f"Not enough candles for {symbol} {interval}"
        )

    return candles


def get_xauusd_candles():
    """Keep compatibility with the existing gold bot."""
    return get_market_candles("XAUUSD", "15min")
