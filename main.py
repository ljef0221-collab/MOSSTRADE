from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse


app = FastAPI(title="SmartNavigator")
BASE_DIR = Path(__file__).resolve().parent
VISITS_DB = Path(os.getenv("VISITS_DB_PATH", BASE_DIR / "smartnavigator.db"))

# The page is served by this app. Keep CORS narrow if a separate frontend is added later.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = [prices[0]]
    for price in prices[1:]:
        ema.append(price * multiplier + ema[-1] * (1 - multiplier))
    return ema


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    true_ranges = [candles[0]["high"] - candles[0]["low"]]
    for index in range(1, len(candles)):
        candle, previous = candles[index], candles[index - 1]
        true_ranges.append(max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous["close"]),
            abs(candle["low"] - previous["close"]),
        ))
    atr = sum(true_ranges[:period]) / period
    for value in true_ranges[period:]:
        atr = (atr * (period - 1) + value) / period
    return atr


@app.get("/", response_class=HTMLResponse)
def read_index():
    with sqlite3.connect(VISITS_DB) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS site_stats (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO site_stats (name, value) VALUES ('visits', 0)")
        connection.execute("UPDATE site_stats SET value = value + 1 WHERE name = 'visits'")
    with open(BASE_DIR / "index.html", "r", encoding="utf-8") as file:
        return file.read()


@app.get("/api/stats")
def site_stats():
    with sqlite3.connect(VISITS_DB) as connection:
        row = connection.execute("SELECT value FROM site_stats WHERE name = 'visits'").fetchone()
    return {"visits": row[0] if row else 0}


@app.get("/api/search")
def search_symbol(keyword: str):
    keyword = keyword.strip()
    if not keyword:
        return {"status": "success", "results": []}
    # Prefer TradingView-style search when the endpoint is available. It is not
    # a public guaranteed API, so Yahoo's live catalogue remains the fallback.
    try:
        response = requests.get(
            "https://symbol-search.tradingview.com/symbol_search/",
            params={"text": keyword, "hl": "1", "lang": "zh_TW"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=5,
        )
        response.raise_for_status()
        tv_results = response.json()
        if tv_results:
            return {"status": "success", "source": "TradingView", "results": [{
                "symbol": item.get("symbol", ""),
                "name": item.get("description") or item.get("symbol", ""),
                "type": item.get("type", ""),
                "exchange": item.get("exchange", ""),
            } for item in tv_results if item.get("symbol")]}
    except (requests.RequestException, ValueError):
        pass

    try:
        response = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": keyword, "quotesCount": 20, "newsCount": 0},
            headers={"User-Agent": "SmartNavigator/1.0"},
            timeout=8,
        )
        response.raise_for_status()
        quotes = response.json().get("quotes", [])
    except (requests.RequestException, ValueError) as error:
        raise HTTPException(status_code=502, detail="市場搜尋服務暫時無法使用，請稍後再試。") from error

    results = []
    for item in quotes:
        symbol = item.get("symbol")
        if not symbol:
            continue
        results.append({
            "symbol": symbol,
            "name": item.get("shortname") or item.get("longname") or symbol,
            "type": item.get("quoteType") or "",
            "exchange": item.get("exchDisp") or item.get("exchange") or "",
        })
    return {"status": "success", "source": "Yahoo Finance", "results": results}


SCALP = {"fast": 9, "slow": 21, "trend": 50, "lookback": 12, "tp_atr": 1.8, "sl_atr": 1.0, "mode": "cross"}
INTRADAY = {"fast": 20, "slow": 50, "trend": 200, "lookback": 20, "tp_atr": 3.0, "sl_atr": 1.5, "mode": "breakout"}
SWING = {"fast": 50, "slow": 200, "trend": 200, "lookback": 55, "tp_atr": 4.5, "sl_atr": 2.0, "mode": "breakout"}
POSITION = {"fast": 20, "slow": 50, "trend": 50, "lookback": 20, "tp_atr": 4.0, "sl_atr": 2.0, "mode": "breakout"}
MONTHLY = {"fast": 12, "slow": 24, "trend": 36, "lookback": 12, "tp_atr": 5.0, "sl_atr": 2.5, "mode": "breakout"}

# TradingView-style intervals. Periods absent from Yahoo are built by aggregating
# smaller candles on the server, so they still use genuine OHLC data.
TIMEFRAME_CONFIG = {
    "1m": {**SCALP, "source": "1m", "range": "7d", "bucket": 60},
    "3m": {**SCALP, "source": "1m", "range": "7d", "bucket": 180},
    "5m": {**SCALP, "source": "5m", "range": "60d", "bucket": 300},
    "10m": {**SCALP, "source": "5m", "range": "60d", "bucket": 600},
    "15m": {**SCALP, "source": "15m", "range": "60d", "bucket": 900},
    "30m": {**SCALP, "source": "30m", "range": "60d", "bucket": 1800},
    "45m": {**SCALP, "source": "15m", "range": "60d", "bucket": 2700},
    "1h": {**INTRADAY, "source": "1h", "range": "1y", "bucket": 3600},
    "2h": {**INTRADAY, "source": "1h", "range": "1y", "bucket": 7200},
    "3h": {**INTRADAY, "source": "1h", "range": "1y", "bucket": 10800},
    "4h": {**INTRADAY, "source": "1h", "range": "1y", "bucket": 14400},
    "1d": {**SWING, "source": "1d", "range": "2y", "bucket": 86400},
    "1w": {**POSITION, "source": "1d", "range": "10y", "bucket": "week"},
    "1mo": {**MONTHLY, "source": "1d", "range": "10y", "bucket": "month"},
}


def aggregate_candles(candles, bucket):
    """Combine source candles without fabricating prices."""
    groups = {}
    for candle in candles:
        timestamp = candle["time"]
        if bucket == "week":
            dt = datetime.fromtimestamp(timestamp, timezone.utc)
            key = (dt.isocalendar().year, dt.isocalendar().week)
        elif bucket == "month":
            dt = datetime.fromtimestamp(timestamp, timezone.utc)
            key = (dt.year, dt.month)
        else:
            key = timestamp // bucket
        groups.setdefault(key, []).append(candle)
    return [{
        "time": values[0]["time"], "open": values[0]["open"],
        "high": max(value["high"] for value in values),
        "low": min(value["low"] for value in values), "close": values[-1]["close"],
    } for values in groups.values()]


@app.get("/api/analyze")
def analyze_market(symbol: str, interval: str = "1h"):
    symbol = symbol.strip().upper().split(":")[-1]
    if not symbol:
        raise HTTPException(status_code=400, detail="請輸入商品代號。")
    if interval not in TIMEFRAME_CONFIG:
        raise HTTPException(status_code=400, detail="不支援的時間週期。")
    config = TIMEFRAME_CONFIG[interval]

    try:
        encoded_symbol = quote(symbol, safe=".-")
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}",
            params={"interval": config["source"], "range": config["range"]},
            headers={"User-Agent": "SmartNavigator/1.0"},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote_data = result["indicators"]["quote"][0]
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as error:
        raise HTTPException(status_code=502, detail=f"無法取得 {symbol} 的市場資料。") from error

    candles = []
    for timestamp, open_, high, low, close in zip(
        timestamps, quote_data["open"], quote_data["high"], quote_data["low"], quote_data["close"]
    ):
        if None not in (open_, high, low, close):
            candles.append({"time": timestamp, "open": open_, "high": high, "low": low, "close": close})
    candles = aggregate_candles(candles, config["bucket"])
    if len(candles) < max(config["trend"], config["lookback"]) + 2:
        raise HTTPException(status_code=422, detail=f"資料不足，無法計算 {interval} 策略。")

    closes = [candle["close"] for candle in candles]
    fast_ema = calculate_ema(closes, config["fast"])
    slow_ema = calculate_ema(closes, config["slow"])
    trend_ema = calculate_ema(closes, config["trend"])
    atr = calculate_atr(candles)
    if atr is None:
        raise HTTPException(status_code=422, detail="資料不足，無法計算 ATR。")

    current, previous = candles[-1], candles[-2]
    price = current["close"]
    trend_up = price > trend_ema[-1] and fast_ema[-1] > slow_ema[-1]
    trend_down = price < trend_ema[-1] and fast_ema[-1] < slow_ema[-1]
    direction, message = "HOLD", "目前沒有符合條件的訊號"
    reason = "等待下一根 K 線確認"

    if config["mode"] == "cross":
        long_signal = trend_up and fast_ema[-2] <= slow_ema[-2] and fast_ema[-1] > slow_ema[-1]
        short_signal = trend_down and fast_ema[-2] >= slow_ema[-2] and fast_ema[-1] < slow_ema[-1]
        reason = f"{interval} 策略：{config['fast']}／{config['slow']} EMA 交叉，{config['trend']} EMA 趨勢濾網"
    else:
        recent_high = max(candle["high"] for candle in candles[-config["lookback"] - 1:-1])
        recent_low = min(candle["low"] for candle in candles[-config["lookback"] - 1:-1])
        buffer = atr * 0.15
        long_signal = trend_up and price > recent_high + buffer and price > current["open"]
        short_signal = trend_down and price < recent_low - buffer and price < current["open"]
        reason = f"{interval} 策略：{config['fast']}／{config['slow']}／{config['trend']} EMA 趨勢；{config['lookback']} 根區間突破＋ATR 過濾"

    if long_signal:
        direction, message = "BUY", "多頭進場訊號"
        tp, sl = price + atr * config["tp_atr"], price - atr * config["sl_atr"]
    elif short_signal:
        direction, message = "SELL", "空頭進場訊號"
        tp, sl = price - atr * config["tp_atr"], price + atr * config["sl_atr"]
    else:
        tp = sl = None

    return {
        "status": "success", "direction": direction, "message": message,
        "current_price": round(price, 4),
        "tp": round(tp, 4) if tp is not None else "—",
        "sl": round(sl, 4) if sl is not None else "—",
        "reason": reason,
        "chart_data": [{key: round(value, 4) if key != "time" else value for key, value in candle.items()} for candle in candles],
    }
