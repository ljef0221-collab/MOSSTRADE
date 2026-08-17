from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
import json
import time
import threading
import requests
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

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
SYMBOL_DATABASE.extend(
    [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "type": "US Stock",
            "exchange": "NASDAQ",
            "keywords": ["apple", "蘋果"],
        },
        {
            "symbol": "MSFT",
            "name": "Microsoft",
            "type": "US Stock",
            "exchange": "NASDAQ",
            "keywords": ["microsoft", "微軟"],
        },
        {
            "symbol": "NVDA",
            "name": "NVIDIA",
            "type": "US Stock",
            "exchange": "NASDAQ",
            "keywords": ["nvidia", "輝達"],
        },
        {
            "symbol": "TSLA",
            "name": "Tesla",
            "type": "US Stock",
            "exchange": "NASDAQ",
            "keywords": ["tesla", "特斯拉"],
        },
        {
            "symbol": "2330.TW",
            "name": "台積電",
            "type": "Taiwan Stock",
            "exchange": "TWSE",
            "keywords": ["2330", "tsmc"],
        },
        {
            "symbol": "2317.TW",
            "name": "鴻海",
            "type": "Taiwan Stock",
            "exchange": "TWSE",
            "keywords": ["2317", "foxconn"],
        },
        {
            "symbol": "2454.TW",
            "name": "聯發科",
            "type": "Taiwan Stock",
            "exchange": "TWSE",
            "keywords": ["2454", "mediatek"],
        },
        {
            "symbol": "0050.TW",
            "name": "元大台灣50",
            "type": "Taiwan ETF",
            "exchange": "TWSE",
            "keywords": ["0050", "台灣50"],
        },
        {
            "symbol": "GLD",
            "name": "SPDR Gold Shares",
            "type": "Precious Metals ETF",
            "exchange": "NYSEARCA",
            "keywords": ["gold", "黃金", "xau"],
        },
        {
            "symbol": "SLV",
            "name": "iShares Silver Trust",
            "type": "Precious Metals ETF",
            "exchange": "NYSEARCA",
            "keywords": ["silver", "白銀", "xag"],
        },
        {
            "symbol": "PPLT",
            "name": "abrdn Physical Platinum",
            "type": "Precious Metals ETF",
            "exchange": "NYSEARCA",
            "keywords": ["platinum", "鉑金"],
        },
        {
            "symbol": "PALL",
            "name": "abrdn Physical Palladium",
            "type": "Precious Metals ETF",
            "exchange": "NYSEARCA",
            "keywords": ["palladium", "鈀金"],
        },
    ]
)

# ALIASES 別名對照表
ALIASES = {"台積電": "2330.TW", "BTC": "BTC-USD", "ETH": "ETH-USD"}

# TIMEFRAME 策略預設配置表
TIMEFRAME_CONFIG = {
    "1m": {
        "source": "1m",
        "range": "7d",
        "bucket": 1,
        "mode": "cross",
        "fast": 5,
        "slow": 20,
        "trend": 60,
        "lookback": 20,
        "tp_atr": 1.5,
        "sl_atr": 1.0,
        "name": "1分極速衝浪",
        "description": "極短線動能策略",
    },
    "3m": {
        "source": "1m",
        "range": "7d",
        "bucket": 3,
        "mode": "cross",
        "fast": 5,
        "slow": 20,
        "trend": 60,
        "lookback": 20,
        "tp_atr": 1.5,
        "sl_atr": 1.0,
        "name": "3分極短線策略",
        "description": "微觀趨勢交叉策略",
    },
    "5m": {
        "source": "5m",
        "range": "60d",
        "bucket": 5,
        "mode": "cross",
        "fast": 5,
        "slow": 20,
        "trend": 60,
        "lookback": 20,
        "tp_atr": 1.5,
        "sl_atr": 1.0,
        "name": "5分動能策略",
        "description": "5分鐘極速衝浪",
    },
    "10m": {
        "source": "5m",
        "range": "60d",
        "bucket": 10,
        "mode": "cross",
        "fast": 5,
        "slow": 20,
        "trend": 60,
        "lookback": 20,
        "tp_atr": 1.8,
        "sl_atr": 1.0,
        "name": "10分動能策略",
        "description": "10分鐘聚合波段",
    },
    "15m": {
        "source": "15m",
        "range": "60d",
        "bucket": 15,
        "mode": "cross",
        "fast": 8,
        "slow": 21,
        "trend": 80,
        "lookback": 20,
        "tp_atr": 1.8,
        "sl_atr": 1.0,
        "name": "15分日內策略",
        "description": "當沖經典短線策略",
    },
    "30m": {
        "source": "15m",
        "range": "60d",
        "bucket": 30,
        "mode": "breakout",
        "fast": 10,
        "slow": 30,
        "trend": 100,
        "lookback": 20,
        "tp_atr": 2.0,
        "sl_atr": 1.2,
        "name": "30分區間突破",
        "description": "半小時區間突破策略",
    },
    "45m": {
        "source": "15m",
        "range": "60d",
        "bucket": 45,
        "mode": "breakout",
        "fast": 10,
        "slow": 30,
        "trend": 100,
        "lookback": 20,
        "tp_atr": 2.0,
        "sl_atr": 1.2,
        "name": "45分區間突破",
        "description": "波段進場過濾策略",
    },
    "1h": {
        "source": "1h",
        "range": "1y",
        "bucket": 60,
        "mode": "breakout",
        "fast": 10,
        "slow": 30,
        "trend": 100,
        "lookback": 20,
        "tp_atr": 2.0,
        "sl_atr": 1.2,
        "name": "1小時突破策略",
        "description": "趨勢區間突破策略",
    },
    "2h": {
        "source": "1h",
        "range": "1y",
        "bucket": 120,
        "mode": "breakout",
        "fast": 10,
        "slow": 30,
        "trend": 100,
        "lookback": 20,
        "tp_atr": 2.2,
        "sl_atr": 1.2,
        "name": "2小時亞盤/歐盤策略",
        "description": "跨時區區間突破策略",
    },
    "3h": {
        "source": "1h",
        "range": "1y",
        "bucket": 180,
        "mode": "breakout",
        "fast": 10,
        "slow": 30,
        "trend": 100,
        "lookback": 20,
        "tp_atr": 2.5,
        "sl_atr": 1.5,
        "name": "3小時趨勢策略",
        "description": "中長線區間突破",
    },
    "4h": {
        "source": "1h",
        "range": "1y",
        "bucket": 240,
        "mode": "breakout",
        "fast": 10,
        "slow": 30,
        "trend": 100,
        "lookback": 20,
        "tp_atr": 2.5,
        "sl_atr": 1.5,
        "name": "4小時四小時線策略",
        "description": "機構級波段突破策略",
    },
    "1d": {
        "source": "1d",
        "range": "5y",
        "bucket": 1,
        "mode": "macro",
        "fast": 20,
        "slow": 50,
        "trend": 200,
        "lookback": 60,
        "tp_atr": 3.0,
        "sl_atr": 1.5,
        "name": "日線趨勢結構策略",
        "description": "EMA 斜率、布林通道與波段回測綜合判讀",
    },
    "1w": {
        "source": "1wk",
        "range": "10y",
        "bucket": 1,
        "mode": "macro",
        "fast": 10,
        "slow": 30,
        "trend": 52,
        "lookback": 52,
        "tp_atr": 3.5,
        "sl_atr": 2.0,
        "name": "週線戰略趨勢策略",
        "description": "52 週趨勢、布林中軌與長波段結構",
    },
    "1mo": {
        "source": "1mo",
        "range": "10y",
        "bucket": 1,
        "mode": "macro",
        "fast": 6,
        "slow": 12,
        "trend": 24,
        "lookback": 24,
        "tp_atr": 4.0,
        "sl_atr": 2.0,
        "name": "月線宏觀週期策略",
        "description": "兩年趨勢、布林通道與主要回測區判讀",
    },
}

app = FastAPI(title="MOSSTRADE")
app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")
VISITS_DB = Path(os.getenv("VISITS_DB_PATH", BASE_DIR / "MOSSTRADE.db"))
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "MOSSTRADE/1.0"})

# Telegram 私人推播設定：敏感值只從後端環境變數讀取，不放進前端或 Git。
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
MOSSTRADE_ADMIN_KEY = os.getenv("MOSSTRADE_ADMIN_KEY", "").strip()


def require_admin(admin_key: str | None) -> None:
    if not MOSSTRADE_ADMIN_KEY or not admin_key or admin_key != MOSSTRADE_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="管理者驗證失敗")


def send_telegram_message(message: str) -> dict:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(status_code=503, detail="尚未設定 Telegram 推播環境變數")
    response = HTTP.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=10,
    )
    if not response.ok:
        raise HTTPException(status_code=502, detail="Telegram 推播失敗")
    return {"status": "sent"}

# MOSSTRADE 預設布林通道參數：20 根 K 線、上下軌各 2 個標準差。
# 圖表顯示與策略判斷共用，避免兩邊使用不同參數造成判讀落差。
BB_PERIOD = 20
BB_DEVIATIONS = 2.0
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
        true_ranges.append(
            max(
                candle["high"] - candle["low"],
                abs(candle["high"] - previous["close"]),
                abs(candle["low"] - previous["close"]),
            )
        )
    atr = sum(true_ranges[:period]) / period
    for value in true_ranges[period:]:
        atr = (atr * (period - 1) + value) / period
    return atr


def calculate_bollinger(prices, period=20, deviations=2):
    """Return aligned middle, upper and lower Bollinger-band arrays."""
    middle, upper, lower = [], [], []
    for index in range(len(prices)):
        if index + 1 < period:
            middle.append(None)
            upper.append(None)
            lower.append(None)
            continue
        window = prices[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        deviation = variance**0.5 * deviations
        middle.append(mean)
        upper.append(mean + deviation)
        lower.append(mean - deviation)
    return middle, upper, lower


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
    params = {
        "assetclass": "stocks",
        "fromdate": start.isoformat(),
        "todate": end.isoformat(),
        "limit": 5000,
    }
    url = (
        f"https://api.nasdaq.com/api/quote/{quote(symbol.lower(), safe='')}/historical"
    )
    payload = cached_json(url, params, 300)
    if not (payload.get("data") or {}).get("tradesTable", {}).get("rows"):
        params["assetclass"] = "etf"
        payload = cached_json(url, params, 300)
    rows = (payload.get("data") or {}).get("tradesTable", {}).get("rows", [])
    candles = []
    for row in reversed(rows):
        try:
            stamp = int(
                datetime.strptime(row["date"], "%m/%d/%Y")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            open_, high, low, close = (
                number_value(row.get(key)) for key in ("open", "high", "low", "close")
            )
            if None not in (open_, high, low, close):
                candles.append(
                    {
                        "time": stamp,
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": number_value(row.get("volume")) or 0,
                    }
                )
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
        payload = cached_json(
            "https://www.twse.com.tw/exchangeReport/STOCK_DAY",
            {"response": "json", "date": f"{year}{month:02d}01", "stockNo": stock_no},
            86400,
        )
        for row in payload.get("data", []):
            try:
                y, m, d = (int(part) for part in row[0].split("/"))
                stamp = int(datetime(y + 1911, m, d, tzinfo=timezone.utc).timestamp())
                open_, high, low, close = (
                    number_value(row[index]) for index in (3, 4, 5, 6)
                )
                if None not in (open_, high, low, close):
                    candles.append(
                        {
                            "time": stamp,
                            "open": open_,
                            "high": high,
                            "low": low,
                            "close": close,
                            "volume": number_value(row[1]) or 0,
                        }
                    )
            except (IndexError, ValueError):
                continue
    return sorted(
        {candle["time"]: candle for candle in candles}.values(),
        key=lambda candle: candle["time"],
    )


def twse_recent_candles(symbol, months=2):
    """Small TWSE request used by rankings; full history is only loaded for analysis."""
    stock_no = symbol.split(".")[0]
    now = datetime.now(timezone.utc)
    candles = []
    for offset in range(months):
        month = now.month - offset
        year = now.year
        if month <= 0:
            month += 12
            year -= 1
        payload = cached_json(
            "https://www.twse.com.tw/exchangeReport/STOCK_DAY",
            {"response": "json", "date": f"{year}{month:02d}01", "stockNo": stock_no},
            1800,
        )
        for row in payload.get("data", []):
            try:
                y, m, d = (int(part) for part in row[0].split("/"))
                open_, high, low, close = (
                    number_value(row[index]) for index in (3, 4, 5, 6)
                )
                if None not in (open_, high, low, close):
                    candles.append(
                        {
                            "time": int(
                                datetime(
                                    y + 1911, m, d, tzinfo=timezone.utc
                                ).timestamp()
                            ),
                            "open": open_,
                            "high": high,
                            "low": low,
                            "close": close,
                            "volume": number_value(row[1]) or 0,
                        }
                    )
            except (IndexError, ValueError):
                continue
    return sorted(
        {row["time"]: row for row in candles}.values(), key=lambda row: row["time"]
    )


def okx_history_candles(symbol, bar, pages=5):
    """Page OKX candles backwards so aggregated hourly strategies have history."""
    rows, after = [], None
    for _ in range(pages):
        params = {"instId": symbol, "bar": bar, "limit": 300}
        if after:
            params["after"] = after
        payload = cached_json(
            "https://www.okx.com/api/v5/market/history-candles", params, ttl=60
        )
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
            current_bucket = {
                "time": b_time,
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c.get("volume", 0),
            }
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
        window = candles[index - pivot_size : index + pivot_size + 1]
        if candles[index]["high"] == max(item["high"] for item in window):
            swing_highs.append(candles[index])
        if candles[index]["low"] == min(item["low"] for item in window):
            swing_lows.append(candles[index])

    events = []
    index_by_time = {item["time"]: index for index, item in enumerate(candles)}
    for swing in swing_highs[-24:]:
        start = index_by_time[swing["time"]] + 1
        for index in range(start, len(candles)):
            if candles[index - 1]["close"] <= swing["high"] < candles[index]["close"]:
                events.append(
                    {
                        "direction": "bullish",
                        "level": swing["high"],
                        "time": candles[index]["time"],
                    }
                )
                break
    for swing in swing_lows[-24:]:
        start = index_by_time[swing["time"]] + 1
        for index in range(start, len(candles)):
            if candles[index - 1]["close"] >= swing["low"] > candles[index]["close"]:
                events.append(
                    {
                        "direction": "bearish",
                        "level": swing["low"],
                        "time": candles[index]["time"],
                    }
                )
                break
    unique_events = {(event["time"], event["direction"]): event for event in events}
    recent_events = sorted(unique_events.values(), key=lambda event: event["time"])[-6:]
    markers = [
        {
            "time": event["time"],
            "position": "belowBar" if event["direction"] == "bullish" else "aboveBar",
            "color": "#26a69a" if event["direction"] == "bullish" else "#ef5350",
            "shape": "arrowUp" if event["direction"] == "bullish" else "arrowDown",
            "text": (
                "Bullish CHoCH" if event["direction"] == "bullish" else "Bearish CHoCH"
            ),
        }
        for event in recent_events
    ]
    choch = recent_events[-1] if recent_events else None

    zones = []
    recent_ranges = [item["high"] - item["low"] for item in candles[-50:]]
    # Ignore tiny three-candle gaps. A meaningful FVG must be at least 45% of
    # the recent average candle range; this prevents noisy micro-gaps from
    # flooding short timeframes.
    minimum_gap = (
        (sum(recent_ranges) / len(recent_ranges)) * 0.45 if recent_ranges else 0
    )
    for index in range(2, len(candles)):
        first, last = candles[index - 2], candles[index]
        if last["low"] - first["high"] >= minimum_gap and not any(
            item["low"] <= first["high"] for item in candles[index + 1 :]
        ):
            zones.append(
                {
                    "side": "bullish",
                    "low": first["high"],
                    "high": last["low"],
                    "time": last["time"],
                }
            )
        elif first["low"] - last["high"] >= minimum_gap and not any(
            item["high"] >= first["low"] for item in candles[index + 1 :]
        ):
            zones.append(
                {
                    "side": "bearish",
                    "low": last["high"],
                    "high": first["low"],
                    "time": last["time"],
                }
            )
    return {"markers": markers, "fvg_zones": zones[-1:], "choch": choch}


@app.get("/", response_class=HTMLResponse)
def read_index():
    with sqlite3.connect(VISITS_DB) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS site_stats (name TEXT PRIMARY KEY, value INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT OR IGNORE INTO site_stats (name, value) VALUES ('visits', 0)"
        )
        connection.execute(
            "UPDATE site_stats SET value = value + 1 WHERE name = 'visits'"
        )

    index_file = BASE_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html 檔案不存在")
    with open(index_file, "r", encoding="utf-8") as file:
        return file.read()


@app.get("/api/stats")
def site_stats():
    with sqlite3.connect(VISITS_DB) as connection:
        row = connection.execute(
            "SELECT value FROM site_stats WHERE name = 'visits'"
        ).fetchone()
    return {"visits": row[0] if row else 0}


@app.get("/api/sim/spec")
def simulation_instrument_spec(symbol: str):
    """Return public trading constraints used by the local simulator."""
    symbol = symbol.strip()
    upper = symbol.upper()
    if upper.startswith("OKX:") and upper.endswith("-SWAP"):
        inst_id = upper.removeprefix("OKX:")
        fallback = {
            "market": "contract",
            "currency": "USDT",
            "instrument": inst_id,
            "tick_size": 0.0001,
            "lot_size": 1.0,
            "min_size": 1.0,
            "contract_value": 1.0,
            "contract_value_currency": "",
            "max_leverage": 50.0,
            "tiers": [],
            "source": "OKX fallback limits",
        }
        try:
            instruments = cached_json(
                "https://www.okx.com/api/v5/public/instruments",
                {"instType": "SWAP", "instId": inst_id},
                ttl=3600,
            ).get("data", [])
            if not instruments:
                return fallback
            item = instruments[0]
            spec = {
                **fallback,
                "tick_size": float(item.get("tickSz") or fallback["tick_size"]),
                "lot_size": float(item.get("lotSz") or fallback["lot_size"]),
                "min_size": float(item.get("minSz") or fallback["min_size"]),
                "contract_value": float(
                    item.get("ctVal") or fallback["contract_value"]
                ),
                "contract_value_currency": item.get("ctValCcy", ""),
                "max_leverage": float(item.get("lever") or fallback["max_leverage"]),
                "source": "OKX public instruments",
            }
            try:
                tier_rows = cached_json(
                    "https://www.okx.com/api/v5/public/position-tiers",
                    {
                        "instType": "SWAP",
                        "tdMode": "isolated",
                        "instFamily": item.get("instFamily")
                        or item.get("uly")
                        or inst_id.removesuffix("-SWAP"),
                    },
                    ttl=3600,
                ).get("data", [])
                tiers = []
                for row in tier_rows:
                    tiers.append(
                        {
                            "tier": int(float(row.get("tier") or len(tiers) + 1)),
                            "min_size": float(row.get("minSz") or 0),
                            "max_size": float(row.get("maxSz") or 0),
                            "maintenance_margin_rate": float(row.get("mmr") or 0.005),
                            "initial_margin_rate": float(row.get("imr") or 0),
                            "max_leverage": float(
                                row.get("maxLever")
                                or row.get("maxLeverage")
                                or spec["max_leverage"]
                            ),
                        }
                    )
                if tiers:
                    spec["tiers"] = tiers
                    spec["max_leverage"] = max(tier["max_leverage"] for tier in tiers)
                    spec["source"] = "OKX public instruments and position tiers"
            except (requests.RequestException, ValueError, TypeError):
                pass
            return spec
        except (requests.RequestException, ValueError, TypeError):
            return fallback

    if upper.endswith((".TW", ".TWO")):
        return {
            "market": "stock",
            "currency": "TWD",
            "instrument": symbol,
            "max_leverage": 1,
            "source": "MOSSTRADE cash simulation",
        }
    return {
        "market": "stock",
        "currency": "USD",
        "instrument": symbol,
        "max_leverage": 1,
        "source": "MOSSTRADE cash simulation",
    }


@app.get("/api/search")
def search_symbol(keyword: str):
    keyword = keyword.strip()
    if not keyword:
        return {"status": "success", "results": []}

    results = []
    lower_keyword = keyword.lower()

    # 1. 本地資料庫搜尋（包含 Binance 永續合約）
    for item in SYMBOL_DATABASE:
        searchable = [
            item.get("symbol", ""),
            item.get("name", ""),
            *item.get("keywords", []),
        ]
        if any(lower_keyword in key.lower() for key in searchable):
            results.append(
                {
                    "symbol": item["symbol"],
                    "name": item.get("name", item["symbol"]),
                    "type": item.get("type", "ASSET"),
                    "exchange": item.get("exchange", "LOCAL"),
                    "source": "Local",
                }
            )

    # Official catalogs expand search beyond the small built-in seed list.
    try:
        for item in cached_json(
            "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", {}, 21600
        ):
            code, name = (
                str(item.get("公司代號", "")).strip(),
                str(item.get("公司簡稱", "")).strip(),
            )
            if lower_keyword in code.lower() or lower_keyword in name.lower():
                results.append(
                    {
                        "symbol": f"{code}.TW",
                        "name": name,
                        "type": "Taiwan Stock",
                        "exchange": "TWSE",
                        "source": "TWSE",
                    }
                )
    except Exception:
        pass
    try:
        for item in cached_json(
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", {}, 21600
        ):
            code, name = (
                str(item.get("SecuritiesCompanyCode", "")).strip(),
                str(item.get("CompanyAbbreviation", "")).strip(),
            )
            if lower_keyword in code.lower() or lower_keyword in name.lower():
                results.append(
                    {
                        "symbol": f"{code}.TWO",
                        "name": name,
                        "type": "Taiwan OTC Stock",
                        "exchange": "TPEx",
                        "source": "TPEx",
                    }
                )
    except Exception:
        pass
    try:
        for item in cached_json(
            "https://openapi.twse.com.tw/v1/opendata/t187ap47_L", {}, 21600
        ):
            code, name = (
                str(item.get("基金代號", "")).strip(),
                str(item.get("基金簡稱", "")).strip(),
            )
            if lower_keyword in code.lower() or lower_keyword in name.lower():
                results.append(
                    {
                        "symbol": f"{code}.TW",
                        "name": name,
                        "type": "Taiwan ETF",
                        "exchange": "TWSE",
                        "source": "TWSE",
                    }
                )
    except Exception:
        pass
    try:
        payload = cached_json(
            "https://api.nasdaq.com/api/screener/stocks",
            {"tableonly": "true", "limit": 10000, "offset": 0},
            21600,
        )
        for item in (payload.get("data") or {}).get("table", {}).get("rows", []):
            ticker, name = (
                str(item.get("symbol", "")).strip(),
                str(item.get("name", "")).strip(),
            )
            if lower_keyword in ticker.lower() or lower_keyword in name.lower():
                results.append(
                    {
                        "symbol": ticker,
                        "name": name,
                        "type": "US Stock",
                        "exchange": "NASDAQ/NYSE",
                        "source": "Nasdaq",
                    }
                )
    except Exception:
        pass
    try:
        payload = cached_json(
            "https://api.nasdaq.com/api/screener/etf",
            {"tableonly": "true", "limit": 10000, "offset": 0},
            21600,
        )
        rows = (
            ((payload.get("data") or {}).get("records") or {}).get("data") or {}
        ).get("rows", [])
        for item in rows:
            ticker, name = (
                str(item.get("symbol", "")).strip(),
                str(item.get("companyName", "")).strip(),
            )
            if lower_keyword in ticker.lower() or lower_keyword in name.lower():
                results.append(
                    {
                        "symbol": ticker,
                        "name": name,
                        "type": "US ETF",
                        "exchange": "US ETF",
                        "source": "Nasdaq",
                    }
                )
    except Exception:
        pass
    try:
        payload = cached_json(
            "https://api.nasdaq.com/api/autocomplete/slookup/10",
            {"search": keyword},
            3600,
        )
        for item in payload.get("data", []):
            ticker, name = (
                str(item.get("symbol", "")).strip(),
                str(item.get("name", "")).strip(),
            )
            if ticker:
                asset = str(item.get("asset", "US Asset"))
                results.append(
                    {
                        "symbol": ticker,
                        "name": name,
                        "type": asset,
                        "exchange": item.get("exchange") or "US Market",
                        "source": "Nasdaq",
                    }
                )
    except Exception:
        pass

    # 2. TradingView 全球大數據搜尋
    if not results:
        try:
            response = requests.get(
                "https://symbol-search.tradingview.com/symbol_search/",
                params={"text": keyword, "type": ""},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=2,
            )
            if response.status_code == 200:
                data = response.json()
                for item in data[:8]:
                    results.append(
                        {
                            "symbol": item.get("symbol"),
                            "name": item.get("description"),
                            "type": item.get("type"),
                            "exchange": item.get("exchange"),
                            "source": "TradingView",
                        }
                    )
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
                    results.append(
                        {
                            "symbol": q.get("symbol"),
                            "name": q.get("longname") or q.get("shortname") or keyword,
                            "type": q.get("quoteType", "STOCK"),
                            "exchange": q.get("exchDisp", "YAHOO"),
                            "source": "Yahoo",
                        }
                    )
        except Exception:
            pass

    unique_results = {item["symbol"]: item for item in results if item.get("symbol")}
    return {"status": "success", "results": list(unique_results.values())[:30]}


@app.get("/api/market-rankings")
def market_rankings():
    """OKX USDT perpetual 24-hour gain/loss and quote-volume leaders."""
    try:
        items = []
        try:
            payload = cached_json(
                "https://www.okx.com/api/v5/market/tickers",
                {"instType": "SWAP"},
                ttl=45,
            )
            for item in payload.get("data", []):
                if not item.get("instId", "").endswith("-USDT-SWAP"):
                    continue
                last, open_ = float(item.get("last") or 0), float(
                    item.get("open24h") or 0
                )
                if last > 0 and open_ > 0:
                    items.append(
                        {
                            "symbol": f"OKX:{item['instId']}",
                            "name": item["instId"],
                            "change": round((last - open_) / open_ * 100, 2),
                            "volume": round(float(item.get("volCcy24h") or 0), 2),
                            "price": last,
                        }
                    )
        except Exception as error:
            print("OKX ranking error:", error)
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
                    rows.append(
                        {
                            "symbol": ticker,
                            "name": f"{ticker} · {label}",
                            "change": round(
                                (latest["close"] - previous["close"])
                                / previous["close"]
                                * 100,
                                2,
                            ),
                            "volume": latest.get("volume", 0),
                            "price": latest["close"],
                        }
                    )
                except Exception:
                    continue
            return {
                "gainers": sorted(rows, key=lambda row: row["change"], reverse=True)[
                    :10
                ],
                "losers": sorted(rows, key=lambda row: row["change"])[:10],
                "volume": sorted(rows, key=lambda row: row["volume"], reverse=True)[
                    :10
                ],
            }

        stocks = ranked_symbols(
            [
                "AAPL",
                "MSFT",
                "NVDA",
                "TSLA",
                "AMZN",
                "META",
                "GOOGL",
                "AMD",
                "NFLX",
                "INTC",
            ],
            "US Stock",
        )
        metals = ranked_symbols(
            ["GLD", "IAU", "SLV", "SIVR", "PPLT", "PALL", "GDX", "GDXJ", "SIL", "COPX"],
            "Metals",
        )
        taiwan_rows = []
        for ticker in [
            "2330.TW",
            "2317.TW",
            "2454.TW",
            "2303.TW",
            "2881.TW",
            "2882.TW",
            "2308.TW",
            "3711.TW",
            "2382.TW",
            "0050.TW",
        ]:
            try:
                candles = twse_daily_candles(ticker)
                if len(candles) >= 2:
                    latest, previous = candles[-1], candles[-2]
                    taiwan_rows.append(
                        {
                            "symbol": ticker,
                            "name": ticker,
                            "change": round(
                                (latest["close"] - previous["close"])
                                / previous["close"]
                                * 100,
                                2,
                            ),
                            "volume": latest.get("volume", 0),
                            "price": latest["close"],
                        }
                    )
            except Exception:
                continue
        taiwan = {
            "gainers": sorted(taiwan_rows, key=lambda row: row["change"], reverse=True)[
                :10
            ],
            "losers": sorted(taiwan_rows, key=lambda row: row["change"])[:10],
            "volume": sorted(taiwan_rows, key=lambda row: row["volume"], reverse=True)[
                :10
            ],
        }
        return {
            "status": "success",
            "markets": {
                "futures": futures,
                "taiwan": taiwan,
                "us": stocks,
                "metals": metals,
            },
        }
    except Exception as error:
        raise HTTPException(
            status_code=502, detail="排行榜資料暫時無法載入，請稍後再試。"
        ) from error


@app.get("/api/market-ranking")
def market_ranking(market: str = "futures", ranking: str = "gainers"):
    """Load only the market and ranking currently selected by the user."""
    market, ranking = market.lower(), ranking.lower()
    if market not in {"futures", "taiwan", "us", "metals"} or ranking not in {
        "gainers",
        "losers",
        "volume",
    }:
        raise HTTPException(status_code=400, detail="不支援的排行榜類型。")
    rows = []
    try:
        if market == "futures":
            payload = cached_json(
                "https://www.okx.com/api/v5/market/tickers", {"instType": "SWAP"}, 60
            )
            for item in payload.get("data", []):
                if not item.get("instId", "").endswith("-USDT-SWAP"):
                    continue
                last, open_ = number_value(item.get("last")), number_value(
                    item.get("open24h")
                )
                if last and open_:
                    rows.append(
                        {
                            "symbol": f"OKX:{item['instId']}",
                            "name": item["instId"],
                            "price": last,
                            "change": round((last - open_) / open_ * 100, 2),
                            "volume": number_value(item.get("volCcy24h")) or 0,
                        }
                    )
        else:
            symbols = {
                "taiwan": [
                    "2330.TW",
                    "2317.TW",
                    "2454.TW",
                    "2303.TW",
                    "2881.TW",
                    "2882.TW",
                    "2308.TW",
                    "3711.TW",
                    "2382.TW",
                    "0050.TW",
                ],
                "us": [
                    "AAPL",
                    "MSFT",
                    "NVDA",
                    "TSLA",
                    "AMZN",
                    "META",
                    "GOOGL",
                    "AMD",
                    "QQQ",
                    "TLT",
                ],
                "metals": [
                    "GLD",
                    "IAU",
                    "SLV",
                    "SIVR",
                    "PPLT",
                    "PALL",
                    "GDX",
                    "GDXJ",
                    "SIL",
                    "COPX",
                ],
            }[market]
            for ticker in symbols:
                try:
                    candles = (
                        twse_recent_candles(ticker)
                        if market == "taiwan"
                        else nasdaq_daily_candles(ticker)
                    )
                    if len(candles) < 2:
                        continue
                    latest, previous = candles[-1], candles[-2]
                    rows.append(
                        {
                            "symbol": ticker,
                            "name": ticker,
                            "price": latest["close"],
                            "change": round(
                                (latest["close"] - previous["close"])
                                / previous["close"]
                                * 100,
                                2,
                            ),
                            "volume": latest.get("volume", 0),
                        }
                    )
                except Exception as error:
                    print(f"Ranking item error {ticker}:", error)
        key = "volume" if ranking == "volume" else "change"
        reverse = ranking != "losers"
        return {
            "status": "success",
            "market": market,
            "ranking": ranking,
            "results": sorted(rows, key=lambda item: item[key], reverse=reverse)[:10],
        }
    except Exception as error:
        raise HTTPException(
            status_code=502, detail="目前選擇的排行榜資料暫時無法取得。"
        ) from error


@app.post("/api/admin/telegram/test")
def telegram_test(x_mosstrade_admin_key: str | None = Header(default=None)):
    require_admin(x_mosstrade_admin_key)
    return send_telegram_message("MOSSTRADE 管理者推播測試成功")


@app.post("/api/admin/telegram/send")
def telegram_send(message: str, x_mosstrade_admin_key: str | None = Header(default=None)):
    require_admin(x_mosstrade_admin_key)
    cleaned = message.strip()
    if not cleaned or len(cleaned) > 4000:
        raise HTTPException(status_code=400, detail="推播內容不可為空或超過 4000 字")
    return send_telegram_message(cleaned)


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
    market_source = (
        "OKX Perpetual Futures"
        if is_okx_swap
        else "OKX Spot" if is_okx else "Yahoo Finance"
    )

    try:
        if is_okx:
            okx_bar = {
                "1m": "1m",
                "3m": "3m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1H",
                "1d": "1Dutc",
                "1wk": "1Wutc",
                "1mo": "1Mutc",
            }.get(config["source"])
            if not okx_bar:
                raise ValueError("OKX does not support this interval")
            rows = okx_history_candles(symbol, okx_bar)
            candles = [
                {
                    "time": int(row[0]) // 1000,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5] or 0),
                }
                for row in rows
            ]
        elif is_binance:
            binance_interval = {"1wk": "1w", "1mo": "1M"}.get(
                config["source"], config["source"]
            )
            rows = cached_json(
                "https://fapi.binance.com/fapi/v1/klines",
                {"symbol": symbol, "interval": binance_interval, "limit": 1500},
                ttl=30,
            )
            candles = [
                {
                    "time": row[0] // 1000,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5] or 0),
                }
                for row in rows
            ]
        elif is_bybit:
            bybit_interval = {
                "1m": "1",
                "3m": "3",
                "5m": "5",
                "15m": "15",
                "30m": "30",
                "1h": "60",
                "1d": "D",
                "1wk": "W",
                "1mo": "M",
            }.get(config["source"])
            if not bybit_interval:
                raise ValueError("Bybit does not support this interval")
            payload = cached_json(
                "https://api.bybit.com/v5/market/kline",
                {
                    "category": "linear",
                    "symbol": symbol,
                    "interval": bybit_interval,
                    "limit": 1000,
                },
                ttl=30,
            )
            rows = payload.get("result", {}).get("list", [])
            candles = [
                {
                    "time": int(row[0]) // 1000,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5] or 0),
                }
                for row in reversed(rows)
            ]
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
            for timestamp, open_, high, low, close, volume in zip(
                result["timestamp"],
                quote_data["open"],
                quote_data["high"],
                quote_data["low"],
                quote_data["close"],
                quote_data.get("volume", []),
            ):
                if None not in (open_, high, low, close):
                    candles.append(
                        {
                            "time": timestamp,
                            "open": open_,
                            "high": high,
                            "low": low,
                            "close": close,
                            "volume": volume or 0,
                        }
                    )
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
                raise HTTPException(
                    status_code=502,
                    detail=f"Yahoo 與備援資料來源暫時無法提供 {symbol} 的 K 線資料，請稍後再試。",
                ) from error
        else:
            source = (
                "OKX Perpetual Futures"
                if is_okx_swap
                else (
                    "OKX Spot"
                    if is_okx
                    else "Binance Futures" if is_binance else "Bybit Futures"
                )
            )
            raise HTTPException(
                status_code=502,
                detail=f"{source} 暫時無法提供 {symbol} 的 K 線資料，請稍後再試。",
            ) from error

    candles = aggregate_candles(candles, config["bucket"])
    lookback = config.get("lookback", 0)
    if len(candles) < max(config["trend"], lookback) + 2:
        raise HTTPException(
            status_code=422, detail=f"資料歷史不足，無法計算 {interval} 策略。"
        )

    closes = [candle["close"] for candle in candles]
    fast_ema = calculate_ema(closes, config["fast"])
    slow_ema = calculate_ema(closes, config["slow"])
    trend_ema = calculate_ema(closes, config["trend"])
    atr = calculate_atr(candles)
    bb_middle, bb_upper, bb_lower = calculate_bollinger(
        closes, period=BB_PERIOD, deviations=BB_DEVIATIONS
    )

    if atr is None or not fast_ema or not slow_ema or not trend_ema:
        raise HTTPException(status_code=422, detail="指標計算數據不足。")

    current = candles[-1]
    price = current["close"]
    trend_up = price > trend_ema[-1] and fast_ema[-1] > slow_ema[-1]
    trend_down = price < trend_ema[-1] and fast_ema[-1] < slow_ema[-1]
    direction, message = "HOLD", "目前沒有符合條件的訊號"
    reason = "等待下一根 K 線確認"

    if config["mode"] == "cross":
        long_signal = (
            trend_up and fast_ema[-2] <= slow_ema[-2] and fast_ema[-1] > slow_ema[-1]
        )
        short_signal = (
            trend_down and fast_ema[-2] >= slow_ema[-2] and fast_ema[-1] < slow_ema[-1]
        )
        reason = f"{interval} 策略：{config['fast']}／{config['slow']} EMA 交叉，{config['trend']} EMA 趨勢濾網"
    else:
        recent_high = max(
            candle["high"] for candle in candles[-config["lookback"] - 1 : -1]
        )
        recent_low = min(
            candle["low"] for candle in candles[-config["lookback"] - 1 : -1]
        )
        buffer = atr * 0.15
        long_signal = (
            trend_up and price > recent_high + buffer and price > current["open"]
        )
        short_signal = (
            trend_down and price < recent_low - buffer and price < current["open"]
        )
        reason = f"{interval} 策略：{config['fast']}／{config['slow']}／{config['trend']} EMA 趨勢；{config['lookback']} 根區間突破＋ATR 過濾"

    # Multi-factor score: trend, momentum, structure, FVG retest and volume spike.
    structure = detect_structure(candles)
    recent_high = max(
        candle["high"] for candle in candles[-config["lookback"] - 1 : -1]
    )
    recent_low = min(candle["low"] for candle in candles[-config["lookback"] - 1 : -1])
    volumes = [candle.get("volume", 0) for candle in candles]
    average_volume = sum(volumes[-21:-1]) / max(len(volumes[-21:-1]), 1)
    volume_spike = average_volume > 0 and volumes[-1] >= average_volume * 1.5
    long_score, short_score = 0, 0
    long_factors, short_factors = [], []
    if trend_up:
        long_score += 2
        long_factors.append("EMA 多頭趨勢")
    if trend_down:
        short_score += 2
        short_factors.append("EMA 空頭趨勢")
    if price > candles[-2]["close"] and fast_ema[-1] > fast_ema[-2]:
        long_score += 1
        long_factors.append("上漲動能")
    if price < candles[-2]["close"] and fast_ema[-1] < fast_ema[-2]:
        short_score += 1
        short_factors.append("下跌動能")
    if price >= recent_high - atr * 0.10:
        long_score += 1
        long_factors.append("接近區間突破")
    if price <= recent_low + atr * 0.10:
        short_score += 1
        short_factors.append("接近區間跌破")
    choch = structure.get("choch") or {}
    if choch.get("direction") == "bullish":
        long_score += 2
        long_factors.append("多頭 CHoCH")
    if choch.get("direction") == "bearish":
        short_score += 2
        short_factors.append("空頭 CHoCH")
    for zone in structure.get("fvg_zones", []):
        if (
            zone["side"] == "bullish"
            and current["low"] <= zone["high"]
            and price > zone["low"]
        ):
            long_score += 1
            long_factors.append("多頭 FVG 回補")
        elif (
            zone["side"] == "bearish"
            and current["high"] >= zone["low"]
            and price < zone["high"]
        ):
            short_score += 1
            short_factors.append("空頭 FVG 回補")
    if volume_spike and price > current["open"]:
        long_score += 2
        long_factors.append("上漲爆量")
    if volume_spike and price < current["open"]:
        short_score += 2
        short_factors.append("下跌爆量")

    # Bollinger regime and swing Fibonacci retracement confirmation.
    if bb_middle[-1] is not None:
        middle_rising = bb_middle[-1] > bb_middle[-2]
        if price > bb_middle[-1] and middle_rising:
            long_score += 1
            long_factors.append("布林中軌向上")
        if price < bb_middle[-1] and not middle_rising:
            short_score += 1
            short_factors.append("布林中軌向下")
        if price >= bb_upper[-1] and volume_spike:
            long_score += 1
            long_factors.append("布林上軌爆量突破")
        if price <= bb_lower[-1] and volume_spike:
            short_score += 1
            short_factors.append("布林下軌爆量跌破")

    swing_window = candles[-min(len(candles) - 1, max(config["lookback"], 20)) - 1 : -1]
    swing_high = max(candle["high"] for candle in swing_window)
    swing_low = min(candle["low"] for candle in swing_window)
    swing_range = swing_high - swing_low
    fibonacci = {}
    if swing_range > 0:
        fibonacci = {
            "high": swing_high,
            "low": swing_low,
            "bull_382": swing_high - swing_range * 0.382,
            "bull_500": swing_high - swing_range * 0.500,
            "bull_618": swing_high - swing_range * 0.618,
            "bear_382": swing_low + swing_range * 0.382,
            "bear_500": swing_low + swing_range * 0.500,
            "bear_618": swing_low + swing_range * 0.618,
        }
        tolerance = max(atr * 0.45, swing_range * 0.012)
        if trend_up and any(
            abs(price - fibonacci[key]) <= tolerance
            for key in ("bull_382", "bull_500", "bull_618")
        ):
            long_score += 1
            long_factors.append("多頭斐波那契回測區")
        if trend_down and any(
            abs(price - fibonacci[key]) <= tolerance
            for key in ("bear_382", "bear_500", "bear_618")
        ):
            short_score += 1
            short_factors.append("空頭斐波那契反彈區")

    macro_mode = config["mode"] == "macro"
    signal_threshold = 4 if macro_mode else 3
    macro_long_ok = not macro_mode or (
        trend_up and bb_middle[-1] is not None and bb_middle[-1] > bb_middle[-2]
    )
    macro_short_ok = not macro_mode or (
        trend_down and bb_middle[-1] is not None and bb_middle[-1] < bb_middle[-2]
    )
    long_signal = (
        long_score >= signal_threshold and long_score > short_score and macro_long_ok
    )
    short_signal = (
        short_score >= signal_threshold and short_score > long_score and macro_short_ok
    )
    reason = f"{interval} 多因子評分｜多方 {long_score} 分：{', '.join(long_factors) or '無'}｜空方 {short_score} 分：{', '.join(short_factors) or '無'}"

    if long_signal:
        direction, message = "BUY", "多頭進場訊號"
        tp, sl = (
            price + atr * max(config["tp_atr"], config["sl_atr"] * 1.6),
            price - atr * config["sl_atr"],
        )
        tp2 = price + atr * config["sl_atr"] * 2.5
    elif short_signal:
        direction, message = "SELL", "空頭進場訊號"
        tp, sl = (
            price - atr * max(config["tp_atr"], config["sl_atr"] * 1.6),
            price + atr * config["sl_atr"],
        )
        tp2 = price - atr * config["sl_atr"] * 2.5
    else:
        tp = tp2 = sl = None

    structure = detect_structure(candles)
    level_candles = candles[-config["lookback"] - 1 : -1]
    levels = {
        "resistance": round(max(candle["high"] for candle in level_candles), 4),
        "support": round(min(candle["low"] for candle in level_candles), 4),
    }
    ema_data = {
        "fast": [
            {"time": candle["time"], "value": round(fast_ema[index], 4)}
            for index, candle in enumerate(candles)
        ],
        "slow": [
            {"time": candle["time"], "value": round(slow_ema[index], 4)}
            for index, candle in enumerate(candles)
        ],
        "trend": [
            {"time": candle["time"], "value": round(trend_ema[index], 4)}
            for index, candle in enumerate(candles)
        ],
    }
    bollinger_data = {
        "middle": [
            {"time": candle["time"], "value": round(bb_middle[index], 4)}
            for index, candle in enumerate(candles)
            if bb_middle[index] is not None
        ],
        "upper": [
            {"time": candle["time"], "value": round(bb_upper[index], 4)}
            for index, candle in enumerate(candles)
            if bb_upper[index] is not None
        ],
        "lower": [
            {"time": candle["time"], "value": round(bb_lower[index], 4)}
            for index, candle in enumerate(candles)
            if bb_lower[index] is not None
        ],
    }
    return {
        "status": "success",
        "strategy_name": config["name"],
        "strategy_description": config["description"],
        "market_source": market_source,
        "direction": direction,
        "message": message,
        "current_price": round(price, 4),
        "tp": round(tp, 4) if tp is not None else "—",
        "tp2": round(tp2, 4) if tp2 is not None else "—",
        "sl": round(sl, 4) if sl is not None else "—",
        "reason": reason,
        "structure": structure,
        "levels": levels,
        "ema_data": ema_data,
        "bollinger_data": bollinger_data,
        "bollinger_params": {
            "period": BB_PERIOD,
            "deviations": BB_DEVIATIONS,
        },
        "fibonacci": {key: round(value, 4) for key, value in fibonacci.items()},
        "chart_data": [
            {
                key: round(value, 4) if key != "time" else value
                for key, value in candle.items()
            }
            for candle in candles
        ],
    }
