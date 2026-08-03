from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
import json
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

BASE_DIR = Path(__file__).resolve().parent

# 1. 載入本地股票/商品資料庫 (帶防錯)
SYMBOL_DATABASE = []
json_path = BASE_DIR / "assets" / "symbols.json"
if json_path.exists():
    try:
        with open(json_path, encoding="utf-8") as f:
            SYMBOL_DATABASE = json.load(f)
    except Exception as e:
        print("載入 symbols.json 失敗:", e)

# 2. 同步 Binance 期貨資料庫 (帶防錯)
try:
    from services.exchange_sync import sync_binance_futures
    BINANCE_DATABASE = sync_binance_futures()
except Exception as e:
    print("Binance sync error:", e)
    BINANCE_DATABASE = []

SYMBOL_DATABASE.extend(BINANCE_DATABASE)

# ALIASES 別名對照表
ALIASES = {
    "台積電": "2330.TW",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD"
}

# TIMEFRAME 策略預設配置表
TIMEFRAME_CONFIG = {
    "1m":  {"source": "1m",  "range": "7d",  "bucket": 1,  "mode": "cross",    "fast": 5,  "slow": 20, "trend": 60,  "lookback": 20, "tp_atr": 1.5, "sl_atr": 1.0, "name": "1分極速衝浪", "description": "極短線動能策略"},
    "3m":  {"source": "1m",  "range": "7d",  "bucket": 3,  "mode": "cross",    "fast": 5,  "slow": 20, "trend": 60,  "lookback": 20, "tp_atr": 1.5, "sl_atr": 1.0, "name": "3分極短線策略", "description": "微觀趨勢交叉策略"},
    "5m":  {"source": "5m",  "range": "60d", "bucket": 5,   "mode": "cross",    "fast": 5,  "slow": 20, "trend": 60,  "lookback": 20, "tp_atr": 1.5, "sl_atr": 1.0, "name": "5分動能策略",   "description": "5分鐘極速衝浪"},
    "10m": {"source": "5m",  "range": "60d", "bucket": 10,  "mode": "cross",    "fast": 5,  "slow": 20, "trend": 60,  "lookback": 20, "tp_atr": 1.8, "sl_atr": 1.0, "name": "10分動能策略",  "description": "10分鐘聚合波段"},
    "15m": {"source": "15m", "range": "60d", "bucket": 15,  "mode": "cross",    "fast": 8,  "slow": 21, "trend": 80,  "lookback": 20, "tp_atr": 1.8, "sl_atr": 1.0, "name": "15分日內策略",  "description": "當沖經典短線策略"},
    "30m": {"source": "15m", "range": "60d", "bucket": 30,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.0, "sl_atr": 1.2, "name": "30分區間突破",  "description": "半小時區間突破策略"},
    "45m": {"source": "15m", "range": "60d", "bucket": 45,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.0, "sl_atr": 1.2, "name": "45分區間突破",  "description": "波段進場過濾策略"},
    "1h":  {"source": "1h",  "range": "1y",  "bucket": 60,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.0, "sl_atr": 1.2, "name": "1小時突破策略", "description": "趨勢區間突破策略"},
    "2h":  {"source": "1h",  "range": "1y",  "bucket": 120, "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.2, "sl_atr": 1.2, "name": "2小時亞盤/歐盤策略", "description": "跨時區區間突破策略"},
    "3h":  {"source": "1h",  "range": "1y",  "bucket": 180, "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.5, "sl_atr": 1.5, "name": "3小時趨勢策略", "description": "中長線區間突破"},
    "4h":  {"source": "1h",  "range": "1y",  "bucket": 240, "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.5, "sl_atr": 1.5, "name": "4小時四小時線策略", "description": "機構級波段突破策略"},
    "1d":  {"source": "1d",  "range": "1y",  "bucket": 1,  "mode": "cross",    "fast": 10, "slow": 30, "trend": 200, "lookback": 20, "tp_atr": 3.0, "sl_atr": 1.5, "name": "日線長線策略",   "description": "大週期 EMA 交叉策略"},
    "1w":  {"source": "1wk", "range": "2y",  "bucket": 1,  "mode": "cross",    "fast": 10, "slow": 30, "trend": 200, "lookback": 20, "tp_atr": 3.5, "sl_atr": 2.0, "name": "週線戰略策略",   "description": "長線戰略佈局策略"},
    "1mo": {"source": "1mo", "range": "5y",  "bucket": 1,  "mode": "cross",    "fast": 5,  "slow": 15, "trend": 50,  "lookback": 12, "tp_atr": 4.0, "sl_atr": 2.0, "name": "月線宏觀策略",   "description": "宏觀週期投資策略"}
}

app = FastAPI(title="SmartNavigator")
VISITS_DB = Path(os.getenv("VISITS_DB_PATH", BASE_DIR / "smartnavigator.db"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

def aggregate_candles(candles, bucket_minutes):
    if bucket_minutes <= 1 or not candles:
        return candles
    aggregated = []
    bucket_sec = bucket_minutes * 60
    current_bucket = None
    
    for c in candles:
        b_time = (c["time"] // bucket_sec) * bucket_sec
        if current_bucket is None or current_bucket["time"] != b_time:
            if current_bucket:
                aggregated.append(current_bucket)
            current_bucket = {"time": b_time, "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
        else:
            current_bucket["high"] = max(current_bucket["high"], c["high"])
            current_bucket["low"] = min(current_bucket["low"], c["low"])
            current_bucket["close"] = c["close"]
            
    if current_bucket:
        aggregated.append(current_bucket)
    return aggregated

@app.get("/", response_class=HTMLResponse)
def read_index():
    with sqlite3.connect(VISITS_DB) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS site_stats (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO site_stats (name, value) VALUES ('visits', 0)")
        connection.execute("UPDATE site_stats SET value = value + 1 WHERE name = 'visits'")
    
    index_file = BASE_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html 檔案不存在")
    with open(index_file, "r", encoding="utf-8") as file:
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

    results = []
    lower_keyword = keyword.lower()

    # 1. 本地資料庫搜尋
    for item in SYMBOL_DATABASE:
        if any(lower_keyword in key.lower() for key in item.get("keywords", [])):
            results.append({
                "symbol": item["symbol"],
                "name": item.get("name", item["symbol"]),
                "type": item.get("type", "ASSET"),
                "exchange": item.get("exchange", "LOCAL"),
                "source": "Local"
            })

    # 2. TradingView 全球大數據搜尋
    if not results:
        try:
            response = requests.get(
                "https://symbol-search.tradingview.com/symbol_search/",
                params={"text": keyword, "type": ""},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=2
            )
            if response.status_code == 200:
                data = response.json()
                for item in data[:8]:
                    results.append({
                        "symbol": item.get("symbol"),
                        "name": item.get("description"),
                        "type": item.get("type"),
                        "exchange": item.get("exchange"),
                        "source": "TradingView"
                    })
        except Exception as e:
            print("TradingView 搜尋失敗:", e)

    # 3. Yahoo Search 備用
    if not results:
        try:
            import yfinance as yf
            yf_search = yf.Search(keyword, max_results=5)
            if yf_search and yf_search.quotes:
                for q in yf_search.quotes:
                    results.append({
                        "symbol": q.get("symbol"),
                        "name": q.get("longname") or q.get("shortname") or keyword,
                        "type": q.get("quoteType", "STOCK"),
                        "exchange": q.get("exchDisp", "YAHOO"),
                        "source": "Yahoo"
                    })
        except Exception as e:
            print("Yahoo 搜尋失敗:", e)

    return {"status": "success", "results": results}

@app.get("/api/analyze")
def analyze_market(symbol: str, interval: str = "1h"):
    interval = interval.strip().lower()
    symbol_upper = symbol.strip().upper()
    
    if symbol_upper in ALIASES:
        symbol = ALIASES[symbol_upper]
        
    symbol = symbol.split(":")[-1]
    if not symbol:
        raise HTTPException(status_code=400, detail="請輸入商品代號。")
    if interval not in TIMEFRAME_CONFIG:
        raise HTTPException(status_code=400, detail=f"不支援的時間週期: {interval}")
    
    config = TIMEFRAME_CONFIG[interval]

    try:
        encoded_symbol = quote(symbol, safe=".-")
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}",
            params={"interval": config["source"], "range": config["range"]},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote_data = result["indicators"]["quote"][0]
    except Exception as error:
        print("Yahoo K線錯誤:", error)
        raise HTTPException(status_code=502, detail=f"無法取得 {symbol} 的市場 K 線資料。") from error

    candles = []
    for timestamp, open_, high, low, close in zip(
        timestamps, quote_data["open"], quote_data["high"], quote_data["low"], quote_data["close"]
    ):
        if None not in (open_, high, low, close):
            candles.append({"time": timestamp, "open": open_, "high": high, "low": low, "close": close})
    
    candles = aggregate_candles(candles, config["bucket"])
    lookback = config.get("lookback", 0)
    if len(candles) < max(config["trend"], lookback) + 2:
        raise HTTPException(status_code=422, detail=f"資料歷史不足，無法計算 {interval} 策略。")

    closes = [candle["close"] for candle in candles]
    fast_ema = calculate_ema(closes, config["fast"])
    slow_ema = calculate_ema(closes, config["slow"])
    trend_ema = calculate_ema(closes, config["trend"])
    atr = calculate_atr(candles)
    
    if atr is None or not fast_ema or not slow_ema or not trend_ema:
        raise HTTPException(status_code=422, detail="指標計算數據不足。")

    current = candles[-1]
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
        "status": "success",
        "strategy_name": config["name"],
        "strategy_description": config["description"],
        "direction": direction,
        "message": message,
        "current_price": round(price, 4),
        "tp": round(tp, 4) if tp is not None else "—",
        "sl": round(sl, 4) if sl is not None else "—",
        "reason": reason,
        "chart_data": [{key: round(value, 4) if key != "time" else value for key, value in candle.items()} for candle in candles],
    }
