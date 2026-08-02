
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


# =====================================================================
# 改進後的 API 路由：搜尋與策略訊號完美整合
# =====================================================================

# =====================================================================
# 全球化自動擋搜尋 API：支援任何語言、任何名詞，免手寫 ALIASES 字典
# =====================================================================

@app.get("/api/search")
def search_symbol(keyword: str):
    keyword = keyword.strip()
    if not keyword:
        return {"status": "success", "results": []}

    results = []
    lower_keyword = keyword.lower()

    # --- 步驟 1：本地 symbols.json 搜尋 ---
    for item in SYMBOL_DATABASE:
        is_match = False
        for key in item.get("keywords", []):
            if lower_keyword in key.lower():
                is_match = True
                break
        
        if is_match:
            results.append({
                "symbol": item["symbol"],
                "name": item["name"],
                "type": item["type"],
                "exchange": item["exchange"],
                "source": "Local"
            })

    # --- 步驟 2：如果本地找不到，直接利用 yfinance 進行全球關鍵字（任何語言名詞）搜尋 ---
    if not results:
        try:
            import yfinance as yf
            # yfinance 的 yf.Search 可以傳入任意名稱（例如: 蘋果, Toyota, 2330）
            # 它會返回全球各大交易所最貼近的標準商品清單
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
            print("Yahoo 全球名詞搜尋失敗，改用 TradingView 備援:", e)

    # --- 步驟 3：如果 Yahoo 搜尋沒結果，轉向 TradingView 進行全球大數據搜尋 ---
    if not results:
        try:
            response = requests.get(
                "https://tradingview.com",
                params={"text": keyword, "hl": "1", "lang": "zh_TW"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                for item in data[:8]:  # 限制前 8 筆
                    if item.get("symbol"):
                        results.append({
                            "symbol": item.get("symbol"),
                            "name": item.get("description"),
                            "type": item.get("type"),
                            "exchange": item.get("exchange"),
                            "source": "TradingView"
                        })
        except Exception as e:
            print("TradingView 全球搜尋錯誤:", e)

    # --- 步驟 4：關鍵核心！安全的自動策略注入（防禦性保護） ---
    # 限制只計算前 3 筆，確保打字流暢度與避免後端卡死
    for res in results[:3]:
        try:
            # 這裡直接拿兩大引擎幫我們轉換出來的「標準國際代號」去算 K 線策略
            analysis = analyze_market(symbol=res["symbol"], interval="1d")
            res["strategy_signal"] = {
                "direction": analysis["direction"],      # "BUY", "SELL", or "HOLD"
                "message": analysis["message"],          # "多頭進場訊號" 等
                "price": analysis["current_price"],
                "tp": analysis["tp"],
                "sl": analysis["sl"],
                "reason": analysis["reason"]
            }
        except Exception as e:
            # 💡 核心防護機制：如果該代號在 Yahoo 無法取得 K 線（例如特殊的 TradingView 指數、外匯商品）
            # 後端絕對不會報錯崩潰，而是優雅地回傳基本商品資訊，讓使用者依然能點擊去看圖表
            print(f"背景策略計算跳過 ({res['symbol']}):", e)
            res["strategy_signal"] = {
                "direction": "HOLD",
                "message": "🔍 點擊查看詳細圖表",
                "price": "—", "tp": "—", "sl": "—",
                "reason": "此商品需要載入特定交易所 K 線，請直接點選商品啟動分析。"
            }

    return {
        "status": "success",
        "results": results
    }


# =====================================================================
# 你原本的核心分析與 K 線聚合邏輯（保留並修正特殊代號問題）
# =====================================================================

@app.get("/api/analyze")
def analyze_market(symbol: str, interval: str = "1h"):
    # 先做別名轉換，免得 analyze 帶入「台積電」會爆掉
    symbol_upper = symbol.strip().upper()
    if symbol_upper in ALIASES:
        symbol = ALIASES[symbol_upper]
        
    symbol = symbol.split(":")[-1]
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
        print("Yahoo K線錯誤:", error)
        raise HTTPException(
            status_code=502,
            detail=f"無法取得 {symbol} 的市場 K 線資料。"
        ) from error

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
