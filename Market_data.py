
import os
import json
import urllib.parse
import urllib.request


def get_xauusd_candles():
    """
    Fetch XAU/USD 15-minute candles.
    Returns candles in chronological order.
    """

    api_key = os.getenv("TWELVE_DATA_API_KEY")

    if not api_key:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing"
        )

    params = {
        "symbol": "XAU/USD",
        "interval": "15min",
        "outputsize": 60,
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
            data = json.loads(response.read().decode())

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
            "Not enough candles for EMA50 strategy"
        )

    return candles
