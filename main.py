from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
import json
import time
import threading
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
SYMBOL_DATABASE.extend([
    {"symbol": "AAPL", "name": "Apple Inc.", "type": "US Stock", "exchange": "NASDAQ", "keywords": ["apple", "蘋果"]},
    {"symbol": "MSFT", "name": "Microsoft", "type": "US Stock", "exchange": "NASDAQ", "keywords": ["microsoft", "微軟"]},
    {"symbol": "NVDA", "name": "NVIDIA", "type": "US Stock", "exchange": "NASDAQ", "keywords": ["nvidia", "輝達"]},
    {"symbol": "TSLA", "name": "Tesla", "type": "US Stock", "exchange": "NASDAQ", "keywords": ["tesla", "特斯拉"]},
    {"symbol": "2330.TW", "name": "台積電", "type": "Taiwan Stock", "exchange": "TWSE", "keywords": ["2330", "tsmc"]},
    {"symbol": "2317.TW", "name": "鴻海", "type": "Taiwan Stock", "exchange": "TWSE", "keywords": ["2317", "foxconn"]},
    {"symbol": "2454.TW", "name": "聯發科", "type": "Taiwan Stock", "exchange": "TWSE", "keywords": ["2454", "mediatek"]},
    {"symbol": "0050.TW", "name": "元大台灣50", "type": "Taiwan ETF", "exchange": "TWSE", "keywords": ["0050", "台灣50"]},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "type": "Precious Metals ETF", "exchange": "NYSEARCA", "keywords": ["gold", "黃金", "xau"]},
    {"symbol": "SLV", "name": "iShares Silver Trust", "type": "Precious Metals ETF", "exchange": "NYSEARCA", "keywords": ["silver", "白銀", "xag"]},
    {"symbol": "PPLT", "name": "abrdn Physical Platinum", "type": "Precious Metals ETF", "exchange": "NYSEARCA", "keywords": ["platinum", "鉑金"]},
    {"symbol": "PALL", "name": "abrdn Physical Palladium", "type": "Precious Metals ETF", "exchange": "NYSEARCA", "keywords": ["palladium", "鈀金"]},
])

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
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "SmartNavigator/1.0"})
API_CACHE = {}
API_CACHE_LOCK = threading.Lock()

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


def cached_json(url, params, ttl=60):
    """Avoid repeated upstream calls and use stale data during rate limits."""
    key = (url, tuple(sorted(params.items())))
    now = time.time()
    with API_CACHE_LOCK:
        cached = API_CACHE.get(key)
        if cached and now - cached[0] < ttl:
            return cached[1]
    try:
        response = HTTP.get(url, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        if cached:
            return cached[1]
        raise
    with API_CACHE_LOCK:
        API_CACHE[key] = (now, payload)
    return payload


def yahoo_json(path, params, ttl):
    """Retry Yahoo's two public hosts before returning an upstream failure."""
    last_error = None
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        try:
            return cached_json(f"https://{host}{path}", params, ttl)
        except (requests.RequestException, ValueError) as error:
            last_error = error
    raise last_error


def number_value(value):
    """Parse exchange values such as '$1,234.50' or '--'."""
    if value in (None, "", "--", "-"):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").replace("+", ""))
    except ValueError:
        return None


def nasdaq_daily_candles(symbol):
    """Keyless daily US-stock/ETF fallback when Yahoo blocks Render's IP."""
    end = datetime.now(timezone.utc).date()
    start = end.replace(year=end.year - 3)
    params = {"assetclass": "stocks", "fromdate": start.isoformat(), "todate": end.isoformat(), "limit": 5000}
    url = f"https://api.nasdaq.com/api/quote/{quote(symbol.lower(), safe='')}/historical"
    payload = cached_json(url, params, 300)
    if not (payload.get("data") or {}).get("tradesTable", {}).get("rows"):
        params["assetclass"] = "etf"
        payload = cached_json(url, params, 300)
    rows = (payload.get("data") or {}).get("tradesTable", {}).get("rows", [])
    candles = []
    for row in reversed(rows):
        try:
            stamp = int(datetime.strptime(row["date"], "%m/%d/%Y").replace(tzinfo=timezone.utc).timestamp())
            open_, high, low, close = (number_value(row.get(key)) for key in ("open", "high", "low", "close"))
            if None not in (open_, high, low, close):
                candles.append({"time": stamp, "open": open_, "high": high, "low": low, "close": close, "volume": number_value(row.get("volume")) or 0})
        except (KeyError, ValueError):
            continue
    return candles


def twse_daily_candles(symbol):
    """Official TWSE daily fallback; 24 months is enough for EMA strategies."""
    stock_no = symbol.split(".")[0]
    now = datetime.now(timezone.utc)
    candles = []
    for offset in range(24):
        month = now.month - offset
        year = now.year
        if month <= 0:
            month += 12
            year -= 1
        payload = cached_json("https://www.twse.com.tw/exchangeReport/STOCK_DAY", {"response": "json", "date": f"{year}{month:02d}01", "stockNo": stock_no}, 86400)
        for row in payload.get("data", []):
            try:
                y, m, d = (int(part) for part in row[0].split("/") )
                stamp = int(datetime(y + 1911, m, d, tzinfo=timezone.utc).timestamp())
                open_, high, low, close = (number_value(row[index]) for index in (3, 4, 5, 6))
                if None not in (open_, high, low, close):
                    candles.append({"time": stamp, "open": open_, "high": high, "low": low, "close": close, "volume": number_value(row[1]) or 0})
            except (IndexError, ValueError):
                continue
    return sorted({candle["time"]: candle for candle in candles}.values(), key=lambda candle: candle["time"])


def okx_history_candles(symbol, bar, pages=5):
    """Page OKX candles backwards so aggregated hourly strategies have history."""
    rows, after = [], None
    for _ in range(pages):
        params = {"instId": symbol, "bar": bar, "limit": 300}
        if after:
            params["after"] = after
        payload = cached_json("https://www.okx.com/api/v5/market/history-candles", params, ttl=60)
        page = payload.get("data", [])
        if not page:
            break
        rows.extend(page)
        if len(page) < 300:
            break
        after = page[-1][0]
    unique = {row[0]: row for row in rows}
    return [unique[key] for key in sorted(unique, key=int)]

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
            current_bucket = {"time": b_time, "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "volume": c.get("volume", 0)}
        else:
            current_bucket["high"] = max(current_bucket["high"], c["high"])
            current_bucket["low"] = min(current_bucket["low"], c["low"])
            current_bucket["close"] = c["close"]
            current_bucket["volume"] += c.get("volume", 0)
            
    if current_bucket:
        aggregated.append(current_bucket)
    return aggregated


def detect_structure(candles, pivot_size=2):
    """Return the latest CHoCH marker and recent three-candle FVG zones."""
    swing_highs, swing_lows = [], []
    for index in range(pivot_size, len(candles) - pivot_size):
        window = candles[index - pivot_size:index + pivot_size + 1]
        if candles[index]["high"] == max(item["high"] for item in window):
            swing_highs.append(candles[index])
        if candles[index]["low"] == min(item["low"] for item in window):
            swing_lows.append(candles[index])

    markers, choch = [], None
    current = candles[-1]
    if swing_highs and current["close"] > swing_highs[-1]["high"]:
        level = swing_highs[-1]["high"]
        choch = {"direction": "bullish", "level": level, "time": current["time"]}
        markers.append({"time": current["time"], "position": "belowBar", "color": "#26a69a", "shape": "arrowUp", "text": "Bullish CHoCH"})
    elif swing_lows and current["close"] < swing_lows[-1]["low"]:
        level = swing_lows[-1]["low"]
        choch = {"direction": "bearish", "level": level, "time": current["time"]}
        markers.append({"time": current["time"], "position": "aboveBar", "color": "#ef5350", "shape": "arrowDown", "text": "Bearish CHoCH"})

    zones = []
    for index in range(2, len(candles)):
        first, last = candles[index - 2], candles[index]
        if first["high"] < last["low"]:
            zones.append({"side": "bullish", "low": first["high"], "high": last["low"], "time": last["time"]})
        elif first["low"] > last["high"]:
            zones.append({"side": "bearish", "low": last["high"], "high": first["low"], "time": last["time"]})
    return {"markers": markers, "fvg_zones": zones[-3:], "choch": choch}

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

    # 1. 本地資料庫搜尋（包含 Binance 永續合約）
    for item in SYMBOL_DATABASE:
        searchable = [item.get("symbol", ""), item.get("name", ""), *item.get("keywords", [])]
        if any(lower_keyword in key.lower() for key in searchable):
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

    # 3. Yahoo Search 備用；使用快取避免 Render 共用 IP 被限流。
    if not results:
        try:
            payload = yahoo_json(
                "/v1/finance/search",
                {"q": keyword, "quotesCount": 8, "newsCount": 0},
                300,
            )
            for q in payload.get("quotes", []):
                if q.get("symbol"):
                    results.append({
                        "symbol": q.get("symbol"),
                        "name": q.get("longname") or q.get("shortname") or keyword,
                        "type": q.get("quoteType", "STOCK"),
                        "exchange": q.get("exchDisp", "YAHOO"),
                        "source": "Yahoo"
                    })
        except Exception:
            pass

    return {"status": "success", "results": results}


@app.get("/api/market-rankings")
def market_rankings():
    """OKX USDT perpetual 24-hour gain/loss and quote-volume leaders."""
    try:
        payload = cached_json("https://www.okx.com/api/v5/market/tickers", {"instType": "SWAP"}, ttl=45)
        items = []
        for item in payload.get("data", []):
            if not item.get("instId", "").endswith("-USDT-SWAP"):
                continue
            last, open_ = float(item.get("last") or 0), float(item.get("open24h") or 0)
            if last <= 0 or open_ <= 0:
                continue
            items.append({
                "symbol": f"OKX:{item['instId']}",
                "name": item["instId"],
                "change": round((last - open_) / open_ * 100, 2),
                "volume": round(float(item.get("volCcy24h") or 0), 2),
                "price": last,
            })
        futures = {
            "status": "success",
            "gainers": sorted(items, key=lambda row: row["change"], reverse=True)[:10],
            "losers": sorted(items, key=lambda row: row["change"])[:10],
            "volume": sorted(items, key=lambda row: row["volume"], reverse=True)[:10],
        }
        def ranked_symbols(symbols, label):
            rows = []
            for ticker in symbols:
                try:
                    candles = nasdaq_daily_candles(ticker)
                    if len(candles) < 2:
                        continue
                    latest, previous = candles[-1], candles[-2]
                    rows.append({"symbol": ticker, "name": f"{ticker} · {label}", "change": round((latest["close"] - previous["close"]) / previous["close"] * 100, 2), "volume": latest.get("volume", 0), "price": latest["close"]})
                except Exception:
                    continue
            return {"gainers": sorted(rows, key=lambda row: row["change"], reverse=True)[:10], "losers": sorted(rows, key=lambda row: row["change"])[:10], "volume": sorted(rows, key=lambda row: row["volume"], reverse=True)[:10]}
        stocks = ranked_symbols(["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "AMD", "NFLX", "INTC"], "US Stock")
        metals = ranked_symbols(["GLD", "IAU", "SLV", "SIVR", "PPLT", "PALL", "GDX", "GDXJ", "SIL", "COPX"], "Metals")
        taiwan_rows = []
        for ticker in ["2330.TW", "2317.TW", "2454.TW", "2303.TW", "2881.TW", "2882.TW", "2308.TW", "3711.TW", "2382.TW", "0050.TW"]:
            try:
                candles = twse_daily_candles(ticker)
                if len(candles) >= 2:
                    latest, previous = candles[-1], candles[-2]
                    taiwan_rows.append({"symbol": ticker, "name": ticker, "change": round((latest["close"] - previous["close"]) / previous["close"] * 100, 2), "volume": latest.get("volume", 0), "price": latest["close"]})
            except Exception:
                continue
        taiwan = {"gainers": sorted(taiwan_rows, key=lambda row: row["change"], reverse=True)[:10], "losers": sorted(taiwan_rows, key=lambda row: row["change"])[:10], "volume": sorted(taiwan_rows, key=lambda row: row["volume"], reverse=True)[:10]}
        return {"status": "success", "markets": {"futures": futures, "taiwan": taiwan, "us": stocks, "metals": metals}}
    except Exception as error:
        raise HTTPException(status_code=502, detail="排行榜資料暫時無法載入，請稍後再試。") from error

@app.get("/api/analyze")
def analyze_market(symbol: str, interval: str = "1h"):
    interval = interval.strip().lower()
    symbol_upper = symbol.strip().upper()
    
    if symbol_upper in ALIASES:
        symbol = ALIASES[symbol_upper]
        
    is_binance = symbol_upper.startswith("BINANCE:")
    is_bybit = symbol_upper.startswith("BYBIT:")
    is_okx = symbol_upper.startswith("OKX:")
    symbol = symbol_upper.split(":")[-1].replace(".P", "")
    is_okx_swap = is_okx and symbol.endswith("-SWAP")
    if not symbol:
        raise HTTPException(status_code=400, detail="請輸入商品代號。")
    if interval not in TIMEFRAME_CONFIG:
        raise HTTPException(status_code=400, detail=f"不支援的時間週期: {interval}")
    
    config = TIMEFRAME_CONFIG[interval]
    market_source = "OKX Perpetual Futures" if is_okx_swap else "OKX Spot" if is_okx else "Yahoo Finance"

    try:
        if is_okx:
            okx_bar = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "1d": "1Dutc", "1wk": "1Wutc", "1mo": "1Mutc"}.get(config["source"])
            if not okx_bar:
                raise ValueError("OKX does not support this interval")
            rows = okx_history_candles(symbol, okx_bar)
            candles = [{"time": int(row[0]) // 1000, "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5] or 0)} for row in rows]
        elif is_binance:
            binance_interval = {"1wk": "1w", "1mo": "1M"}.get(config["source"], config["source"])
            rows = cached_json(
                "https://fapi.binance.com/fapi/v1/klines",
                {"symbol": symbol, "interval": binance_interval, "limit": 1500},
                ttl=30,
            )
            candles = [{"time": row[0] // 1000, "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5] or 0)} for row in rows]
        elif is_bybit:
            bybit_interval = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "1d": "D", "1wk": "W", "1mo": "M"}.get(config["source"])
            if not bybit_interval:
                raise ValueError("Bybit does not support this interval")
            payload = cached_json(
                "https://api.bybit.com/v5/market/kline",
                {"category": "linear", "symbol": symbol, "interval": bybit_interval, "limit": 1000},
                ttl=30,
            )
            rows = payload.get("result", {}).get("list", [])
            candles = [{"time": int(row[0]) // 1000, "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5] or 0)} for row in reversed(rows)]
        else:
            encoded_symbol = quote(symbol, safe=".-")
            payload = yahoo_json(
                f"/v8/finance/chart/{encoded_symbol}",
                {"interval": config["source"], "range": config["range"]},
                60,
            )
            result = payload["chart"]["result"][0]
            quote_data = result["indicators"]["quote"][0]
            candles = []
            for timestamp, open_, high, low, close, volume in zip(result["timestamp"], quote_data["open"], quote_data["high"], quote_data["low"], quote_data["close"], quote_data.get("volume", [])):
                if None not in (open_, high, low, close):
                    candles.append({"time": timestamp, "open": open_, "high": high, "low": low, "close": close, "volume": volume or 0})
    except Exception as error:
        if not (is_okx or is_binance or is_bybit):
            try:
                if symbol.endswith(".TW"):
                    candles = twse_daily_candles(symbol)
                    market_source = "TWSE official daily data"
                else:
                    candles = nasdaq_daily_candles(symbol)
                    market_source = "Nasdaq daily data"
                if not candles:
                    raise ValueError("No fallback candles")
            except Exception:
                raise HTTPException(status_code=502, detail=f"Yahoo 與備援資料來源暫時無法提供 {symbol} 的 K 線資料，請稍後再試。") from error
        else:
            source = "OKX Perpetual Futures" if is_okx_swap else "OKX Spot" if is_okx else "Binance Futures" if is_binance else "Bybit Futures"
            raise HTTPException(status_code=502, detail=f"{source} 暫時無法提供 {symbol} 的 K 線資料，請稍後再試。") from error
    
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

    structure = detect_structure(candles)
    level_candles = candles[-config["lookback"] - 1:-1]
    levels = {"resistance": round(max(candle["high"] for candle in level_candles), 4), "support": round(min(candle["low"] for candle in level_candles), 4)}
    ema_data = {"fast": [{"time": candle["time"], "value": round(fast_ema[index], 4)} for index, candle in enumerate(candles)], "slow": [{"time": candle["time"], "value": round(slow_ema[index], 4)} for index, candle in enumerate(candles)], "trend": [{"time": candle["time"], "value": round(trend_ema[index], 4)} for index, candle in enumerate(candles)]}
    return {
        "status": "success",
        "strategy_name": config["name"],
        "strategy_description": config["description"],
        "market_source": market_source,
        "direction": direction,
        "message": message,
        "current_price": round(price, 4),
        "tp": round(tp, 4) if tp is not None else "—",
        "sl": round(sl, 4) if sl is not None else "—",
        "reason": reason,
        "structure": structure,
        "levels": levels,
        "ema_data": ema_data,
        "chart_data": [{key: round(value, 4) if key != "time" else value for key, value in candle.items()} for candle in candles],
    }
