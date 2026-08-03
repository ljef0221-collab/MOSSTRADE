import time
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import yfinance as yf
import pandas as pd

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE = {
    "spot": None,
    "futures": None,
    "spot_last_updated": 0,
    "futures_last_updated": 0
}
CACHE_TTL = 60

@app.get("/", response_class=HTMLResponse)
def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/rankings")
def get_rankings(type: str = Query("futures")):
    current_time = time.time()
    
    if type == "futures" and CACHE["futures"] and (current_time - CACHE["futures_last_updated"] < CACHE_TTL):
        return CACHE["futures"]
    if type == "spot" and CACHE["spot"] and (current_time - CACHE["spot_last_updated"] < CACHE_TTL):
        return CACHE["spot"]

    try:
        if type == "futures":
            url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            res = requests.get(url, timeout=5).json()
            data_list = [x for x in res if x['symbol'].endswith('USDT')]
        else:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            res = requests.get(url, timeout=5).json()
            data_list = [x for x in res if x['symbol'].endswith('USDT')]

        top_volume_raw = sorted(data_list, key=lambda x: float(x['quoteVolume']), reverse=True)[:10]
        top_gainers_raw = sorted(data_list, key=lambda x: float(x['priceChangePercent']), reverse=True)[:10]

        top_volume = [{"symbol": x['symbol'], "price": round(float(x['lastPrice']), 4), "volume": round(float(x['quoteVolume'])), "change": round(float(x['priceChangePercent']), 2)} for x in top_volume_raw]
        top_gainers = [{"symbol": x['symbol'], "price": round(float(x['lastPrice']), 4), "volume": round(float(x['quoteVolume'])), "change": round(float(x['priceChangePercent']), 2)} for x in top_gainers_raw]

        result = {"top_volume": top_volume, "top_gainers": top_gainers}

        if type == "futures":
            CACHE["futures"] = result
            CACHE["futures_last_updated"] = current_time
        else:
            CACHE["spot"] = result
            CACHE["spot_last_updated"] = current_time

        return result
    except Exception as e:
        if CACHE[type]:
            return CACHE[type]
        return {"top_volume": [], "top_gainers": []}

@app.get("/api/klines")
def get_klines(symbol: str = "BTCUSDT"):
    symbol_upper = symbol.upper().strip()
    ohlc = []
    signals = []

    # 1. 常見傳統金融商品對照表 (黃金, 原油, 股票, 指數)
    commodity_map = {
        "GOLD": "GC=F",     # 黃金期貨
        "SILVER": "SI=F",   # 白銀期貨
        "OIL": "CL=F",      # 原油期貨
        "AAPL": "AAPL",     # 蘋果
        "TSLA": "TSLA",     # 特斯拉
        "NVDA": "NVDA",     # 輝達
        "2330": "2330.TW",  # 台積電
        "QQQ": "QQQ",       # 納斯達克ETF
        "SPY": "SPY"        # 標普500ETF
    }

    yf_symbol = commodity_map.get(symbol_upper)

    # 2. 如果是傳統金融商品 (黃金、股票等) -> 用 yfinance 抓取
    if yf_symbol or "." in symbol_upper or symbol_upper.endswith("=F"):
        target = yf_symbol if yf_symbol else symbol_upper
        try:
            ticker = yf.Ticker(target)
            df = ticker.history(period="1mo", interval="1h")
            
            if not df.empty:
                df = df.reset_index()
                for i, row in df.iterrows():
                    open_time = int(row['Datetime'].timestamp())
                    open_p = float(row['Open'])
                    high_p = float(row['High'])
                    low_p = float(row['Low'])
                    close_p = float(row['Close'])

                    ohlc.append({
                        "time": open_time,
                        "open": round(open_p, 2),
                        "high": round(high_p, 2),
                        "low": round(low_p, 2),
                        "close": round(close_p, 2)
                    })

                    # SMC 買賣訊號邏輯範例
                    if i > 5 and i % 20 == 0:
                        signals.append({"time": open_time, "position": "aboveBar", "color": "#f23645", "shape": "arrowDown", "text": "SMC Sell"})
                    elif i > 5 and i % 15 == 0:
                        signals.append({"time": open_time, "position": "belowBar", "color": "#089981", "shape": "arrowUp", "text": "SMC Buy"})

                return {"ohlc": ohlc, "signals": signals}
        except Exception as e:
            print(f"yfinance 抓取失敗: {e}")

    # 3. 若非傳統商品 -> 預設走幣安加密貨幣 API
    clean_symbol = symbol_upper.replace("-", "").replace("/", "")
    if not clean_symbol.endswith("USDT") and not clean_symbol.endswith("BTC"):
        clean_symbol += "USDT"

    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={clean_symbol}&interval=1h&limit=100"
        res = requests.get(url, timeout=5)
        
        if res.status_code != 200:
            url = f"https://api.binance.com/api/v3/klines?symbol={clean_symbol}&interval=1h&limit=100"
            res = requests.get(url, timeout=5)

        if res.status_code == 200:
            raw_klines = res.json()
            for i, k in enumerate(raw_klines):
                open_time = int(k[0] / 1000)
                open_p, high_p, low_p, close_p = float(k[1]), float(k[2]), float(k[3]), float(k[4])
                
                ohlc.append({"time": open_time, "open": open_p, "high": high_p, "low": low_p, "close": close_p})

                if i > 5 and i % 25 == 0:
                    signals.append({"time": open_time, "position": "aboveBar", "color": "#f23645", "shape": "arrowDown", "text": "SMC Sell"})
                elif i > 5 and i % 18 == 0:
                    signals.append({"time": open_time, "position": "belowBar", "color": "#089981", "shape": "arrowUp", "text": "SMC Buy"})

            return {"ohlc": ohlc, "signals": signals}
    except Exception as e:
        print(f"幣安 API 抓取失敗: {e}")

    return {"error": "找不到數據", "ohlc": [], "signals": []}