from urllib.parse import quote
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import sqlite3
import json
import time
import threading
import xml.etree.ElementTree as ET
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
        "name": "1分策略說明",
        "description": "1分鐘短線進出",
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
        "name": "3分策略說明",
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
        "name": "5分策略說明",
        "description": "5分鐘短線進出",
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
        "name": "10分策略說明",
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
        "name": "15分策略說明",
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
        "name": "30分策略說明",
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
        "name": "45分策略說明",
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
        "name": "1小時策略說明",
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
        "name": "2小時策略說明",
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
        "name": "3小時策略說明",
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
        "name": "4小時策略說明",
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
        "name": "日線策略說明",
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
        "name": "週線策略說明",
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
        "name": "月線策略說明",
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
TELEGRAM_WATCHLIST = os.getenv("TELEGRAM_WATCHLIST", "OKX:BTC-USDT-SWAP:1h").strip()
TELEGRAM_POLL_SECONDS = int(os.getenv("TELEGRAM_POLL_SECONDS", "60"))
_telegram_started = False
_telegram_last_signal = {}


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


def telegram_allowed(chat_id) -> bool:
    return bool(TELEGRAM_CHAT_ID and str(chat_id) == str(TELEGRAM_CHAT_ID))


def format_analysis_message(symbol: str, interval: str, data: dict) -> str:
    direction = {"BUY": "多方／買入", "SELL": "空方／賣出"}.get(data.get("direction"), "觀望")
    return (
        f"MOSSTRADE 策略查詢\n\n商品：{symbol.upper()}\n時間線：{interval}\n"
        f"方向：{direction}\n目前價格：{data.get('current_price', '--')}\n"
        f"參考進場：{data.get('current_price', '--')}\n停利：{data.get('tp', '--')}\n"
        f"停損：{data.get('sl', '--')}\n\n{data.get('reason', '')}"
    )


def telegram_symbol_suggestions(keyword: str) -> list[dict]:
    query = keyword.strip().lower()
    if not query:
        return []
    matches = []
    for item in SYMBOL_DATABASE:
        symbol = str(item.get("symbol", "")).upper()
        name = str(item.get("name", ""))
        haystack = " ".join([symbol, name, *[str(k) for k in item.get("keywords", [])]]).lower()
        if query in haystack:
            matches.append({"symbol": symbol, "name": name})
    # Allow any exchange symbol even when it is not in the local catalogue.
    if not matches and ("-" in keyword or "." in keyword or query.isalnum()):
        matches.append({"symbol": keyword.strip().upper(), "name": "直接查詢此代號"})
    unique = {}
    for item in matches:
        unique[item["symbol"]] = item
    return list(unique.values())[:8]


def telegram_keyboard_for_symbols(matches: list[dict]) -> dict:
    return {"inline_keyboard": [[{"text": f"{item['symbol']}｜{item['name'][:24]}", "callback_data": f"sym|{item['symbol']}"}] for item in matches]}


def telegram_keyboard_for_intervals(symbol: str) -> dict:
    intervals = [("10 分鐘", "10m"), ("1 小時", "1h"), ("4 小時", "4h"), ("日線", "1d")]
    return {"inline_keyboard": [[{"text": label, "callback_data": f"scan|{symbol}|{value}"} for label, value in intervals]]}


def _telegram_api(method: str, payload: dict | None = None) -> dict:
    response = HTTP.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        json=payload or {}, timeout=25,
    )
    response.raise_for_status()
    return response.json()


def _telegram_worker() -> None:
    """Telegram 查詢與背景訊號監控；只接受設定的管理者 Chat ID。"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    offset = 0
    last_monitor = 0.0
    while True:
        try:
            updates = _telegram_api("getUpdates", {"offset": offset, "timeout": 20}).get("result", [])
            for update in updates:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                message = update.get("message") or {}
                chat_id = (message.get("chat") or {}).get("id")
                text = (message.get("text") or "").strip()
                if text.startswith("/start") or text == "/help":
                    _telegram_api("sendMessage", {"chat_id": chat_id, "text": "MOSSTRADE Bot\n查詢格式：/scan 商品 時間線\n例如：/scan BTC-USD 1h"})
                elif text.startswith("/scan"):
                    parts = text.split()
                    if len(parts) != 3:
                        reply = "格式錯誤，請使用：/scan BTC-USD 1h"
                    else:
                        try:
                            symbol, interval = parts[1].upper(), parts[2].lower()
                            result = analyze_market(symbol=symbol, interval=interval)
                            reply = format_analysis_message(symbol, interval, result)
                        except Exception as error:
                            reply = f"查詢失敗：{getattr(error, 'detail', str(error))}"
                    _telegram_api("sendMessage", {"chat_id": chat_id, "text": reply})
                elif text.startswith("/search") or text:
                    keyword = text.split(maxsplit=1)[1] if " " in text else text.lstrip("/")
                    matches = telegram_symbol_suggestions(keyword)
                    if matches:
                        _telegram_api("sendMessage", {"chat_id": chat_id, "text": "請選擇商品：", "reply_markup": telegram_keyboard_for_symbols(matches)})
                    else:
                        _telegram_api("sendMessage", {"chat_id": chat_id, "text": "找不到商品，請輸入代號或名稱，例如：BTC、台積電、AAPL"})
            for callback in [item.get("callback_query") for item in updates]:
                if not callback:
                    continue
                callback_id = callback.get("id")
                chat_id = (callback.get("message", {}).get("chat") or {}).get("id")
                data = callback.get("data", "")
                _telegram_api("answerCallbackQuery", {"callback_query_id": callback_id})
                if data.startswith("sym|"):
                    symbol = data.split("|", 1)[1]
                    _telegram_api("sendMessage", {"chat_id": chat_id, "text": f"已選擇 {symbol}，請選擇時間線：", "reply_markup": telegram_keyboard_for_intervals(symbol)})
                elif data.startswith("scan|"):
                    _, symbol, interval = data.split("|", 2)
                    try:
                        result = analyze_market(symbol=symbol, interval=interval)
                        reply = format_analysis_message(symbol, interval, result)
                    except Exception as error:
                        reply = f"查詢失敗：{getattr(error, 'detail', str(error))}"
                    _telegram_api("sendMessage", {"chat_id": chat_id, "text": reply})
            now = time.time()
            if now - last_monitor >= max(TELEGRAM_POLL_SECONDS, 30):
                last_monitor = now
                for item in TELEGRAM_WATCHLIST.split(","):
                    if ":" not in item:
                        continue
                    symbol, interval = [part.strip() for part in item.rsplit(":", 1)]
                    try:
                        result = analyze_market(symbol=symbol, interval=interval)
                        direction = result.get("direction")
                        key = f"{symbol.upper()}:{interval}:{result.get('signal_time')}:{direction}"
                        if direction in ("BUY", "SELL") and _telegram_last_signal.get(f"{symbol}:{interval}") != key:
                            _telegram_last_signal[f"{symbol}:{interval}"] = key
                            _telegram_api("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "text": format_analysis_message(symbol, interval, result)})
                    except Exception as error:
                        print(f"Telegram monitor error ({symbol}:{interval}): {error}")
        except Exception as error:
            print(f"Telegram worker error: {error}")
            time.sleep(10)


@app.on_event("startup")
def start_telegram_worker():
    global _telegram_started
    if not _telegram_started and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        _telegram_started = True
        threading.Thread(target=_telegram_worker, name="telegram-worker", daemon=True).start()

# MOSSTRADE 預設布林通道參數：20 根 K 線、上下軌各 2 個標準差。
# 圖表顯示與策略判斷共用，避免兩邊使用不同參數造成判讀落差。
BB_PERIOD = 20
BB_DEVIATIONS = 2.0
API_CACHE = {}
API_CACHE_LOCK = threading.Lock()
API_INFLIGHT = {}
RESPONSE_CACHE = {}
RESPONSE_CACHE_LOCK = threading.Lock()
RESPONSE_INFLIGHT = {}
# 端點級 TTL：重整與輪詢共用，避免每次請求都打上游。
RANKING_TTL_SECONDS = {
    "futures": 45,
    "taiwan": 120,
    "us": 120,
    "metals": 120,
}
NEWS_RESPONSE_TTL_SECONDS = 180
NEWS_ITEM_TTL_SECONDS = 180
ANALYZE_TTL_SECONDS = 20

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _wait_for_inflight(event: threading.Event, timeout: float = 30) -> None:
    event.wait(timeout=timeout)


def cached_endpoint(cache_key: str, ttl: float, producer):
    """快取完整 API 回應，並以 single-flight 合併同 key 的併發重建。"""
    now = time.time()
    with RESPONSE_CACHE_LOCK:
        entry = RESPONSE_CACHE.get(cache_key)
        if entry and now - entry[0] < ttl:
            return entry[1]
        event = RESPONSE_INFLIGHT.get(cache_key)
        if event is None:
            event = threading.Event()
            RESPONSE_INFLIGHT[cache_key] = event
            owner = True
        else:
            owner = False
    if not owner:
        _wait_for_inflight(event)
        with RESPONSE_CACHE_LOCK:
            entry = RESPONSE_CACHE.get(cache_key)
            if entry:
                return entry[1]
        # 等待後仍無資料時才自行重建，避免整頁卡住。
        return producer()
    try:
        payload = producer()
        with RESPONSE_CACHE_LOCK:
            RESPONSE_CACHE[cache_key] = (time.time(), payload)
        return payload
    except Exception:
        with RESPONSE_CACHE_LOCK:
            entry = RESPONSE_CACHE.get(cache_key)
        if entry:
            return entry[1]
        raise
    finally:
        with RESPONSE_CACHE_LOCK:
            RESPONSE_INFLIGHT.pop(cache_key, None)
            event.set()


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
        event = API_INFLIGHT.get(key)
        if event is None:
            event = threading.Event()
            API_INFLIGHT[key] = event
            owner = True
        else:
            owner = False
    if not owner:
        _wait_for_inflight(event)
        with API_CACHE_LOCK:
            cached = API_CACHE.get(key)
            if cached:
                return cached[1]
        # 等待逾時仍無結果：若無人重建則接手；否則再等一次。
        with API_CACHE_LOCK:
            event = API_INFLIGHT.get(key)
            if event is None:
                event = threading.Event()
                API_INFLIGHT[key] = event
                owner = True
            else:
                owner = False
        if not owner:
            _wait_for_inflight(event)
            with API_CACHE_LOCK:
                cached = API_CACHE.get(key)
                if cached:
                    return cached[1]
            raise requests.RequestException(f"上游快取重建逾時: {url}")
    try:
        response = HTTP.get(url, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        with API_CACHE_LOCK:
            cached = API_CACHE.get(key)
            API_INFLIGHT.pop(key, None)
            event.set()
        if cached:
            return cached[1]
        raise
    with API_CACHE_LOCK:
        API_CACHE[key] = (time.time(), payload)
        API_INFLIGHT.pop(key, None)
        event.set()
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


INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "45m": 2700,
    "1h": 3600,
    "2h": 7200,
    "3h": 10800,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
}


def candle_is_forming(candle, interval, now=None) -> bool:
    """K 線開始時間加上週期長度還沒到，就代表這根還沒收線。"""
    now = time.time() if now is None else now
    if interval == "1mo":
        start = datetime.fromtimestamp(candle["time"], tz=timezone.utc)
        current = datetime.fromtimestamp(now, tz=timezone.utc)
        return (start.year, start.month) == (current.year, current.month)
    return candle["time"] + INTERVAL_SECONDS.get(interval, 0) > now


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


SEARCH_CATALOG_REFRESH_SECONDS = 21600
SEARCH_CATALOG = []
SEARCH_CATALOG_LOCK = threading.Lock()
_search_catalog_started = False


def _compact(text) -> str:
    """只留英數與中日韓文字並轉小寫，讓 btcusdt 能對上 BTC-USDT。"""
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def _catalog_entry(
    symbol, name, type_, exchange, source, keywords=(), category=None
) -> dict:
    raw_symbol = str(symbol).split(":", 1)[-1]
    is_exchange = str(symbol).upper().startswith(("OKX:", "BINANCE:", "BYBIT:"))
    compact_symbol = _compact(raw_symbol)
    if compact_symbol.endswith("swap"):
        compact_symbol = compact_symbol[: -len("swap")]
    base = _compact(re.split(r"[-./]", raw_symbol)[0])
    terms = {_compact(name)}
    terms.update(_compact(word) for word in str(name or "").split())
    terms.update(_compact(keyword) for keyword in keywords if keyword)
    terms.discard("")
    return {
        "item": {
            "symbol": symbol,
            "name": name or symbol,
            "type": type_,
            "exchange": exchange,
            "source": source,
        },
        "symbol_key": compact_symbol,
        "base_key": base,
        "terms": tuple(terms),
        "is_crypto": is_exchange and category in (None, "1"),
        "is_tokenized": is_exchange and category not in (None, "1"),
        "is_perpetual": str(symbol).upper().endswith("-SWAP"),
    }


def _local_catalog_entries() -> list[dict]:
    return [
        _catalog_entry(
            item["symbol"],
            item.get("name", item["symbol"]),
            item.get("type", "ASSET"),
            item.get("exchange", "LOCAL"),
            "Local",
            item.get("keywords", []),
            item.get("category"),
        )
        for item in SYMBOL_DATABASE
        if item.get("symbol")
    ]


def _remote_catalog_entries() -> list[dict]:
    entries = []
    sources = [
        (
            "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
            {},
            lambda payload: [
                (f"{row.get('公司代號', '').strip()}.TW", row.get("公司簡稱", "").strip(),
                 "Taiwan Stock", "TWSE", "TWSE")
                for row in payload
                if str(row.get("公司代號", "")).strip()
            ],
        ),
        (
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
            {},
            lambda payload: [
                (f"{row.get('SecuritiesCompanyCode', '').strip()}.TWO",
                 row.get("CompanyAbbreviation", "").strip(),
                 "Taiwan OTC Stock", "TPEx", "TPEx")
                for row in payload
                if str(row.get("SecuritiesCompanyCode", "")).strip()
            ],
        ),
        (
            "https://openapi.twse.com.tw/v1/opendata/t187ap47_L",
            {},
            lambda payload: [
                (f"{row.get('基金代號', '').strip()}.TW", row.get("基金簡稱", "").strip(),
                 "Taiwan ETF", "TWSE", "TWSE")
                for row in payload
                if str(row.get("基金代號", "")).strip()
            ],
        ),
        (
            "https://api.nasdaq.com/api/screener/stocks",
            {"tableonly": "true", "limit": 10000, "offset": 0},
            lambda payload: [
                (row.get("symbol", "").strip(), row.get("name", "").strip(),
                 "US Stock", "NASDAQ/NYSE", "Nasdaq")
                for row in (payload.get("data") or {}).get("table", {}).get("rows", [])
                if str(row.get("symbol", "")).strip()
            ],
        ),
        (
            "https://api.nasdaq.com/api/screener/etf",
            {"tableonly": "true", "limit": 10000, "offset": 0},
            lambda payload: [
                (row.get("symbol", "").strip(), row.get("companyName", "").strip(),
                 "US ETF", "US ETF", "Nasdaq")
                for row in (
                    ((payload.get("data") or {}).get("records") or {}).get("data") or {}
                ).get("rows", [])
                if str(row.get("symbol", "")).strip()
            ],
        ),
    ]
    for url, params, parse in sources:
        try:
            payload = cached_json(url, params, SEARCH_CATALOG_REFRESH_SECONDS)
            entries.extend(_catalog_entry(*row) for row in parse(payload))
        except Exception as error:
            print(f"Search catalog error ({url}): {error}")
    return entries


def _rebuild_search_catalog() -> None:
    entries = _local_catalog_entries() + _remote_catalog_entries()
    with SEARCH_CATALOG_LOCK:
        SEARCH_CATALOG[:] = entries


def _search_catalog_worker() -> None:
    while True:
        try:
            _rebuild_search_catalog()
        except Exception as error:
            print(f"Search catalog worker error: {error}")
        time.sleep(SEARCH_CATALOG_REFRESH_SECONDS)


@app.on_event("startup")
def start_search_catalog_worker():
    global _search_catalog_started
    with SEARCH_CATALOG_LOCK:
        SEARCH_CATALOG[:] = _local_catalog_entries()
    if not _search_catalog_started:
        _search_catalog_started = True
        threading.Thread(
            target=_search_catalog_worker, name="search-catalog", daemon=True
        ).start()


def _match_score(entry: dict, query: str) -> int | None:
    """數字越小越相關：完全符合 > 代號開頭 > 名稱開頭 > 任意包含。"""
    symbol_key, base_key = entry["symbol_key"], entry["base_key"]
    if query in (symbol_key, base_key):
        return 0
    if symbol_key.startswith(query):
        return 1
    if any(term.startswith(query) for term in entry["terms"]):
        return 2
    if query in symbol_key or any(query in term for term in entry["terms"]):
        return 3
    return None


def search_catalog(keyword: str, limit: int = 30) -> list[dict]:
    query = _compact(keyword)
    if not query:
        return []
    with SEARCH_CATALOG_LOCK:
        catalog = SEARCH_CATALOG or _local_catalog_entries()
    scored = []
    for entry in catalog:
        score = _match_score(entry, query)
        if score is not None:
            scored.append(
                (
                    score,
                    not entry["is_crypto"],
                    entry["is_tokenized"],
                    not entry["is_perpetual"],
                    len(entry["symbol_key"]),
                    entry["item"]["symbol"],
                    entry["item"],
                )
            )
    scored.sort(key=lambda row: row[:6])
    unique = {}
    for row in scored:
        unique.setdefault(row[-1]["symbol"], row[-1])
        if len(unique) >= limit:
            break
    return list(unique.values())


@app.get("/api/search")
def search_symbol(keyword: str):
    keyword = keyword.strip()
    if not keyword:
        return {"status": "success", "results": []}

    # 1. 記憶體內商品清單：背景預先載入，搜尋時不等外部網站。
    results = search_catalog(keyword)

    # 2. 清單內找不到時，才問 Nasdaq 即時查詢。
    if not results:
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
                    results.append(
                        {
                            "symbol": ticker,
                            "name": name,
                            "type": str(item.get("asset", "US Asset")),
                            "exchange": item.get("exchange") or "US Market",
                            "source": "Nasdaq",
                        }
                    )
        except Exception:
            pass

    # 3. TradingView 全球大數據搜尋
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

    # 4. Yahoo Search 備用；使用快取避免 Render 共用 IP 被限流。
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


NEWS_QUERIES = {
    "TW": "台股 台灣股市",
    "US": "US stocks market",
    "CRYPTO": "crypto bitcoin cryptocurrency market",
}
NEWS_CACHE = {}
NEWS_CACHE_LOCK = threading.Lock()


def _read_news_cache(market: str, *, allow_stale: bool = False) -> list[dict] | None:
    with NEWS_CACHE_LOCK:
        entry = NEWS_CACHE.get(market)
        if not entry:
            return None
        timestamp, items = entry
        if allow_stale or time.time() - timestamp < NEWS_ITEM_TTL_SECONDS:
            return list(items)
    return None


def _write_news_cache(market: str, items: list[dict]) -> None:
    with NEWS_CACHE_LOCK:
        NEWS_CACHE[market] = (time.time(), list(items))


def _news_items_for_market(market: str) -> list[dict]:
    fresh = _read_news_cache(market)
    if fresh is not None:
        return fresh
    query = NEWS_QUERIES[market]
    try:
        payload = yahoo_json(
            "/v1/finance/search",
            {"q": query, "quotesCount": 0, "newsCount": 12},
            300,
        )
    except Exception:
        payload = {}
    items = []
    for news in payload.get("news", []):
        title = (news.get("title") or "").strip()
        url = news.get("link") or news.get("url")
        if not title or not url or urlparse(url).scheme not in {"http", "https"}:
            continue
        timestamp = news.get("providerPublishTime") or news.get("published_at")
        try:
            published = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat() if timestamp else None
        except (TypeError, ValueError, OSError):
            published = None
        if not published:
            continue
        items.append({
            "id": news.get("uuid") or url,
            "market": market,
            "title": title,
            "summary": news.get("summary") or "",
            "symbol": news.get("relatedTickers", [""])[0] if news.get("relatedTickers") else "",
            "source": news.get("publisher") or "Yahoo Finance",
            "url": url,
            "published_at": published,
            "importance": "medium",
        })
    if items:
        _write_news_cache(market, items)
        return items
    # Fallback to Google News RSS so the page can still show sourced headlines
    # when Yahoo Finance is rate-limited or unavailable.
    rss = HTTP.get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"},
        timeout=8,
    )
    rss.raise_for_status()
    root = ET.fromstring(rss.text)
    for entry in root.findall("./channel/item")[:12]:
        title = (entry.findtext("title") or "").strip()
        link = (entry.findtext("link") or "").strip()
        if not title or not link or urlparse(link).scheme not in {"http", "https"}:
            continue
        pub_date = entry.findtext("pubDate")
        try:
            published = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc).isoformat() if pub_date else None
        except ValueError:
            published = None
        if not published:
            continue
        items.append({
            "id": link,
            "market": market,
            "title": title,
            "summary": "",
            "symbol": "",
            "source": "Google News RSS",
            "url": link,
            "published_at": published,
            "importance": "medium",
        })
    if items:
        _write_news_cache(market, items)
    return items


@app.get("/api/news")
def market_news(market: str = "ALL"):
    market = market.upper().strip()
    markets = list(NEWS_QUERIES) if market == "ALL" else [market]
    if any(item not in NEWS_QUERIES for item in markets):
        raise HTTPException(status_code=400, detail="不支援的消息市場分類。")

    def build_news_payload():
        items = []
        errors = []
        for item_market in markets:
            try:
                current_items = _news_items_for_market(item_market)
                if current_items:
                    items.extend(current_items)
                else:
                    stale = _read_news_cache(item_market, allow_stale=True) or []
                    items.extend(stale)
            except Exception as error:
                errors.append(item_market)
                print(f"News provider error ({item_market}): {error}")
                stale = _read_news_cache(item_market, allow_stale=True) or []
                items.extend(stale)
        unique = {}
        for item in items:
            dedupe_key = "|".join([
                item.get("market", ""),
                " ".join(item.get("title", "").lower().split()),
                item.get("source", "").lower(),
            ])
            unique[dedupe_key] = item
        ordered = sorted(
            unique.values(), key=lambda item: item.get("published_at") or "", reverse=True
        )[:30]
        return {
            "status": "partial" if errors and ordered else "error" if errors else "success",
            "results": ordered,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "failed_markets": errors,
            "cache_ttl_seconds": NEWS_RESPONSE_TTL_SECONDS,
        }

    return cached_endpoint(f"news:{market}", NEWS_RESPONSE_TTL_SECONDS, build_news_payload)


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
    ttl = RANKING_TTL_SECONDS[market]

    def build_ranking_payload():
        rows = []
        try:
            if market == "futures":
                payload = cached_json(
                    "https://www.okx.com/api/v5/market/tickers",
                    {"instType": "SWAP"},
                    ttl,
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
            sort_key = "volume" if ranking == "volume" else "change"
            reverse = ranking != "losers"
            return {
                "status": "success",
                "market": market,
                "ranking": ranking,
                "results": sorted(
                    rows, key=lambda item: item[sort_key], reverse=reverse
                )[:10],
                "cache_ttl_seconds": ttl,
            }
        except Exception as error:
            raise HTTPException(
                status_code=502, detail="目前選擇的排行榜資料暫時無法取得。"
            ) from error

    return cached_endpoint(f"ranking:{market}:{ranking}", ttl, build_ranking_payload)


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
    cache_key = f"analyze:{symbol.strip().upper()}:{interval.strip().lower()}"
    return cached_endpoint(
        cache_key, ANALYZE_TTL_SECONDS, lambda: _compute_analyze_market(symbol, interval)
    )


def _compute_analyze_market(symbol: str, interval: str = "1h"):
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

    all_candles = aggregate_candles(candles, config["bucket"])
    if not all_candles:
        raise HTTPException(status_code=422, detail="沒有可用的 K 線資料。")
    live_price = all_candles[-1]["close"]
    # 策略只看已收線的 K 線：盤中插針或暫時突破，收線前不會亮訊號。
    forming = candle_is_forming(all_candles[-1], interval)
    candles = all_candles[:-1] if forming else all_candles
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

    # 插針／假突破過濾：看收線後的影線長度與收盤位置。
    candle_range = current["high"] - current["low"]
    upper_wick = current["high"] - max(current["open"], current["close"])
    lower_wick = min(current["open"], current["close"]) - current["low"]
    filter_notes = []
    if long_signal and candle_range > 0:
        if upper_wick >= candle_range * 0.6:
            long_signal = False
            filter_notes.append("上影線過長（插針），多單不成立")
        elif current["high"] > recent_high and price <= recent_high:
            long_signal = False
            filter_notes.append("盤中突破但收線跌回區間（假突破），多單不成立")
    if short_signal and candle_range > 0:
        if lower_wick >= candle_range * 0.6:
            short_signal = False
            filter_notes.append("下影線過長（插針），空單不成立")
        elif current["low"] < recent_low and price >= recent_low:
            short_signal = False
            filter_notes.append("盤中跌破但收線站回區間（假跌破），空單不成立")
    if filter_notes:
        reason += "｜" + "；".join(filter_notes)
    if forming:
        reason += "｜以上一根已收線 K 線判斷"

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
    # 圖表線條仍畫到最新一根（含未收線），讓畫面跟著即時價格走。
    chart_closes = [candle["close"] for candle in all_candles]
    chart_fast = calculate_ema(chart_closes, config["fast"])
    chart_slow = calculate_ema(chart_closes, config["slow"])
    chart_trend = calculate_ema(chart_closes, config["trend"])
    chart_bb_middle, chart_bb_upper, chart_bb_lower = calculate_bollinger(
        chart_closes, period=BB_PERIOD, deviations=BB_DEVIATIONS
    )
    ema_data = {
        "fast": [
            {"time": candle["time"], "value": round(chart_fast[index], 4)}
            for index, candle in enumerate(all_candles)
        ],
        "slow": [
            {"time": candle["time"], "value": round(chart_slow[index], 4)}
            for index, candle in enumerate(all_candles)
        ],
        "trend": [
            {"time": candle["time"], "value": round(chart_trend[index], 4)}
            for index, candle in enumerate(all_candles)
        ],
    }
    bollinger_data = {
        "middle": [
            {"time": candle["time"], "value": round(chart_bb_middle[index], 4)}
            for index, candle in enumerate(all_candles)
            if chart_bb_middle[index] is not None
        ],
        "upper": [
            {"time": candle["time"], "value": round(chart_bb_upper[index], 4)}
            for index, candle in enumerate(all_candles)
            if chart_bb_upper[index] is not None
        ],
        "lower": [
            {"time": candle["time"], "value": round(chart_bb_lower[index], 4)}
            for index, candle in enumerate(all_candles)
            if chart_bb_lower[index] is not None
        ],
    }
    return {
        "status": "success",
        "strategy_name": config["name"],
        "strategy_description": config["description"],
        "market_source": market_source,
        "direction": direction,
        "message": message,
        "current_price": round(live_price, 4),
        # 訊號依據的已收線收盤價，止損／止盈也以此計算。
        "entry_price": round(price, 4),
        "signal_time": current["time"],
        "signal_candle_closed": True,
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
            for candle in all_candles
        ],
    }
