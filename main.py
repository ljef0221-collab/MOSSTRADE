
from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(
    os.path.join(BASE_DIR,"assets","symbols.json"),
    encoding="utf-8"
) as f:
    SYMBOL_DATABASE = json.load(f)

print("第一筆：")
print(SYMBOL_DATABASE[0])

print("最後一筆：")
print(SYMBOL_DATABASE[-1])

from services.exchange_sync import sync_binance_futures


try:

    BINANCE_DATABASE = sync_binance_futures()


except Exception as e:

    print(
        "Binance sync error:",
        e
    )

    BINANCE_DATABASE = []


SYMBOL_DATABASE.extend(
    BINANCE_DATABASE
)


print(
    "Total symbols:",
    len(SYMBOL_DATABASE)
)

print("Loaded symbols:", len(SYMBOL_DATABASE))
print(SYMBOL_DATABASE[0])

# 補上別名對照表
ALIASES = {
    "台積電": "2330.TW",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD"
}

# 補上時間週期設定
# 補上完整時間週期設定（涵蓋前端所有選單選項，修正短時區無法計算的問題）
TIMEFRAME_CONFIG = {
    # 分鐘級別 (1m - 45m)
    "1m":  {"source": "1m",  "range": "7d",  "bucket": 1,  "mode": "cross", "fast": 5,  "slow": 20, "trend": 60,  "lookback": 20, "tp_atr": 1.5, "sl_atr": 1.0, "name": "1分極短線", "description": "極短線策略"},
    "3m":  {"source": "2m",  "range": "7d",  "bucket": 3,  "mode": "cross", "fast": 5,  "slow": 20, "trend": 60,  "lookback": 20, "tp_atr": 1.5, "sl_atr": 1.0, "name": "3分極速策略", "description": "極短線策略"},
    "5m":  {"source": "5m",  "range": "14d", "bucket": 1,  "mode": "cross", "fast": 5,  "slow": 20, "trend": 60,  "lookback": 20, "tp_atr": 1.5, "sl_atr": 1.0, "name": "5分短線策略", "description": "極短線策略,捕捉主要波段"},
    "10m": {"source": "5m",  "range": "14d", "bucket": 2,  "mode": "cross", "fast": 8,  "slow": 21, "trend": 80,  "lookback": 20, "tp_atr": 1.8, "sl_atr": 1.0, "name": "10分動能策略", "description": "短線動能追隨策略"},
    "15m": {"source": "15m", "range": "1mo", "bucket": 1,  "mode": "cross", "fast": 8,  "slow": 21, "trend": 80,  "lookback": 20, "tp_atr": 1.8, "sl_atr": 1.0, "name": "15m當沖主線", "description": "短線交易與趨勢確認"},
    "30m": {"source": "30m", "range": "1mo", "bucket": 1,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.0, "sl_atr": 1.2, "name": "30m波段突破", "description": "日內波段突破策略"},
    "45m": {"source": "15m", "range": "1mo", "bucket": 3,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.0, "sl_atr": 1.2, "name": "45m亞盤/歐盤波段", "description": "中短線區間突破策略"},
    
    # 小時級別 (1h - 4h)
    "1h":  {"source": "60m", "range": "2mo", "bucket": 1,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.0, "sl_atr": 1.2, "name": "1小時突破策略", "description": "趨勢區間突破策略"},
    "2h":  {"source": "60m", "range": "3mo", "bucket": 2,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.2, "sl_atr": 1.3, "name": "2小時趨勢策略", "description": "中線波段追蹤策略"},
    "3h":  {"source": "60m", "range": "3mo", "bucket": 3,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.5, "sl_atr": 1.4, "name": "3小時趨勢策略", "description": "跨日波段趨勢策略"},
    "4h":  {"source": "60m", "range": "6mo", "bucket": 4,  "mode": "breakout", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 2.5, "sl_atr": 1.5, "name": "4小時主力波段", "description": "機構主力波段策略"},
    
    # 長週期 (1d - 1mo)
    "1d":  {"source": "1d",  "range": "2y",  "bucket": 1,  "mode": "cross", "fast": 10, "slow": 30, "trend": 200, "lookback": 20, "tp_atr": 3.0, "sl_atr": 1.5, "name": "日線長線策略", "description": "大週期 EMA 交叉策略"},
    "1w":  {"source": "1wk", "range": "5y",  "bucket": 1,  "mode": "cross", "fast": 10, "slow": 30, "trend": 100, "lookback": 20, "tp_atr": 4.0, "sl_atr": 2.0, "name": "週線戰略策略", "description": "長期投資宏觀策略"},
    "1mo": {"source": "1mo", "range": "10y", "bucket": 1,  "mode": "cross", "fast": 5,  "slow": 15, "trend": 50,  "lookback": 12, "tp_atr": 5.0, "sl_atr": 2.5, "name": "月線週期策略", "description": "超長線景氣循環策略"}
}

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

# 🔽 新增 SMC / ICT 失衡缺口 (FVG) 計算函數 🔽
def detect_fvg(candles):
    """
    SMC 策略核心：尋找未被填補的失衡缺口 (Fair Value Gap)
    - 看多 FVG (Bullish FVG): Candle[i-2].high < Candle[i].low (中間第 i-1 根強勢衝高留空)
    - 看空 FVG (Bearish FVG): Candle[i-2].low > Candle[i].high
    """
    if len(candles) < 3:
        return None, 0, 0

    # 檢測最新 10 根 K 線內最具代表性的 FVG
    for i in range(len(candles) - 1, len(candles) - 10, -1):
        if i < 2:
            break
        c1, c3 = candles[i - 2], candles[i]
        
        # 多頭 FVG 缺口
        if c3["low"] > c1["high"]:
            fvg_bottom = c1["high"]
            fvg_top = c3["low"]
            return "BULLISH", fvg_top, fvg_bottom
            
        # 空頭 FVG 缺口
        elif c3["high"] < c1["low"]:
            fvg_top = c1["low"]
            fvg_bottom = c3["high"]
            return "BEARISH", fvg_top, fvg_bottom

    return None, 0, 0

# 🔽 新增在 calculate_atr 正下方的函數 🔽
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
    with open(BASE_DIR / "index.html", "r", encoding="utf-8") as file:
        return file.read()


@app.get("/api/stats")
def site_stats():
    with sqlite3.connect(VISITS_DB) as connection:
        row = connection.execute("SELECT value FROM site_stats WHERE name = 'visits'").fetchone()
    return {"visits": row[0] if row else 0}


# =====================================================================
# 改進後的 API 路由：搜尋與策略訊號完美整合
# =====================================================================

# =====================================================================
# 全球化自動擋搜尋 API：支援任何語言、任何名詞，免手寫 ALIASES 字典
# =====================================================================
import concurrent.futures

# 🔽 優化版：利用 ThreadPoolExecutor 進行多執行緒平行發包，極速載入首頁榜單 🔽
@app.get("/api/top_market")
def get_top_market():
    dynamic_symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "NVDA", "TSLA", "AAPL", "AMZN", "2330.TW", "2454.TW", "EURUSD=X"]
    
    def fetch_single(sym):
        try:
            encoded = quote(sym, safe=".-")
            res = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}",
                params={"interval": "1d", "range": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=2.5
            )
            data = res.json()["chart"]["result"][0]
            meta = data["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("chartPreviousClose", price)
            change_percent = ((price - prev_close) / prev_close * 100) if prev_close else 0
            volume = meta.get("regularMarketVolume", 0)
            
            return {
                "symbol": sym,
                "name": meta.get("shortName", sym),
                "price": round(price, 2),
                "change_percent": round(change_percent, 2),
                "volume": volume
            }
        except Exception:
            return None

    # ⚡ 使用 10 個核心執行緒同時抓取數據
    market_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_single, dynamic_symbols)
        for r in results:
            if r is not None:
                market_data.append(r)

    # 排序並截取前 5 名
    volume_rank = sorted(market_data, key=lambda x: x["volume"], reverse=True)[:5]
    gainers_rank = sorted(market_data, key=lambda x: x["change_percent"], reverse=True)[:5]

    return {
        "volume_rank": volume_rank,
        "gainers_rank": gainers_rank
    }
# =====================================================================
# 全球化極速搜尋 API：毫秒級回傳，絕不卡頓
# =====================================================================
@app.get("/api/search")
def search_symbol(keyword: str):
    keyword = keyword.strip()
    if not keyword:
        return {"status": "success", "results": []}

    results = []
    lower_keyword = keyword.lower()

    # 1. 本地資料庫比對
    for item in SYMBOL_DATABASE:
        if any(lower_keyword in key.lower() for key in item.get("keywords", [])):
            results.append({
                "symbol": item["symbol"],
                "name": item["name"],
                "type": item["type"],
                "exchange": item["exchange"],
                "source": "Local"
            })

    # 2. TradingView 全球大數據極速搜尋 (秒級回傳)
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

    # 3. 如果前兩者都沒有，備用 Yahoo Search
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

    return {
        "status": "success",
        "results": results
    }

# =====================================================================
# 你原本的核心分析與 K 線聚合邏輯（保留並修正特殊代號問題）
# =====================================================================

@app.get("/api/analyze")
def analyze_market(symbol: str, interval: str = "1h"):
    # 統一轉成小寫，避免前端傳入 '1H' 或 '1D' 抓不到
    interval = interval.strip().lower()
    
    # 先做別名轉換
    symbol_upper = symbol.strip().upper()
    if symbol_upper in ALIASES:
        symbol = ALIASES[symbol_upper]
        
    symbol = symbol.split(":")[-1]
    if not symbol:
        raise HTTPException(status_code=400, detail="請輸入商品代號。")
    if interval not in TIMEFRAME_CONFIG:
        # 如果遇到不認識的週期，預設退回 1h
        config = TIMEFRAME_CONFIG["1h"]
    else:
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
        timestamps = result.get("timestamp", [])
        quote_data = result["indicators"]["quote"][0]
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as error:
        print("Yahoo K線錯誤:", error)
        raise HTTPException(
            status_code=502,
            detail=f"無法取得 {symbol} 的市場 K 線資料。"
        ) from error

    candles = []
    for timestamp, open_, high, low, close in zip(
        timestamps, quote_data.get("open", []), quote_data.get("high", []), quote_data.get("low", []), quote_data.get("close", [])
    ):
        if None not in (open_, high, low, close):
            candles.append({"time": timestamp, "open": open_, "high": high, "low": low, "close": close})
    
    candles = aggregate_candles(candles, config["bucket"])
    lookback = config.get("lookback", 0)
    
    # ⚠️ 防禦優化：若數據稍有不足，自動彈性調降所需的最低 K 線數，防止直接 422 崩潰
    min_required = max(config["trend"], lookback) + 2
    if len(candles) < min_required:
        # 當資料不足時，動態縮小 trend EMA 週期以保證計算成功
        config["trend"] = max(10, len(candles) // 2)
        if len(candles) < 15:
            raise HTTPException(status_code=422, detail=f"【{symbol}】{interval} 歷史 K 線數據不足（僅 {len(candles)} 根），請切換至其他週期。")

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

    # ==========================================
    # 第二步位置 2：導入 SMC / ICT 策略與原本的 EMA 策略
    # ==========================================
    fvg_type, fvg_top, fvg_bottom = detect_fvg(candles)
    
    # 1m-15m 短時區自動啟動 SMC FVG 缺口策略
    if interval in ["1m", "3m", "5m", "10m", "15m"] and fvg_type is not None:
        if fvg_type == "BULLISH" and price >= fvg_bottom:
            long_signal, short_signal = True, False
            reason = f"SMC/ICT 策略：回測 {interval} 多頭失衡缺口 (FVG: {round(fvg_bottom,2)}-{round(fvg_top,2)})，機構買盤確立"
        elif fvg_type == "BEARISH" and price <= fvg_top:
            long_signal, short_signal = False, True
            reason = f"SMC/ICT 策略：觸碰 {interval} 空頭失衡缺口 (FVG: {round(fvg_bottom,2)}-{round(fvg_top,2)})，機構拋售賣壓"
        else:
            long_signal = short_signal = False
            reason = f"{interval} SMC 觀察中：捕捉到 FVG 缺口 ({round(fvg_bottom,2)} - {round(fvg_top,2)})，等待價格回測"
            
    # 中長時區維持原有的 EMA 交叉或區間突破邏輯
    elif config["mode"] == "cross":
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

    # ==========================================
    # 進出場訊號與風控 (TP/SL) 計算
    # ==========================================
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