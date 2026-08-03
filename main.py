import time
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import requests

app = FastAPI()

# 60秒記憶體快取
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
    
    # 讀取快取
    if type == "futures" and CACHE["futures"] and (current_time - CACHE["futures_last_updated"] < CACHE_TTL):
        return CACHE["futures"]
    if type == "spot" and CACHE["spot"] and (current_time - CACHE["spot_last_updated"] < CACHE_TTL):
        return CACHE["spot"]

    try:
        if type == "futures":
            # 幣安 USDT 永續合約 API
            url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            res = requests.get(url, timeout=5).json()
            data_list = [x for x in res if x['symbol'].endswith('USDT')]
        else:
            # 幣安 現貨 API
            url = "https://api.binance.com/api/v3/ticker/24hr"
            res = requests.get(url, timeout=5).json()
            data_list = [x for x in res if x['symbol'].endswith('USDT')]

        # 成交量排序 前 10 名
        top_volume_raw = sorted(data_list, key=lambda x: float(x['quoteVolume']), reverse=True)[:10]
        # 漲跌幅排序 前 10 名
        top_gainers_raw = sorted(data_list, key=lambda x: float(x['priceChangePercent']), reverse=True)[:10]

        top_volume = []
        for item in top_volume_raw:
            top_volume.append({
                "symbol": item['symbol'],
                "price": round(float(item['lastPrice']), 4),
                "volume": round(float(item['quoteVolume'])),
                "change": round(float(item['priceChangePercent']), 2)
            })

        top_gainers = []
        for item in top_gainers_raw:
            top_gainers.append({
                "symbol": item['symbol'],
                "price": round(float(item['lastPrice']), 4),
                "volume": round(float(item['quoteVolume'])),
                "change": round(float(item['priceChangePercent']), 2)
            })

        result = {"top_volume": top_volume, "top_gainers": top_gainers}

        # 更新快取
        if type == "futures":
            CACHE["futures"] = result
            CACHE["futures_last_updated"] = current_time
        else:
            CACHE["spot"] = result
            CACHE["spot_last_updated"] = current_time

        return result

    except Exception as e:
        print(f"API 抓取失敗: {e}")
        # 如果失敗且有快取就用快取，否則給備用數據
        if CACHE[type]:
            return CACHE[type]
        return {"top_volume": [], "top_gainers": []}

@app.get("/api/klines")
def get_klines(symbol: str = "BTCUSDT"):
    try:
        # 預設抓取幣安合約 K 線，若查不到自動轉現貨
        clean_symbol = symbol.upper().replace("-", "").replace("/", "")
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={clean_symbol}&interval=1h&limit=100"
        res = requests.get(url, timeout=5)
        
        if res.status_code != 200:
            url = f"https://api.binance.com/api/v3/klines?symbol={clean_symbol}&interval=1h&limit=100"
            res = requests.get(url, timeout=5)
            
        raw_klines = res.json()
        
        ohlc = []
        signals = []
        
        for i, k in enumerate(raw_klines):
            open_time = int(k[0] / 1000)
            open_p, high_p, low_p, close_p = float(k[1]), float(k[2]), float(k[3]), float(k[4])
            
            ohlc.append({
                "time": open_time,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p
            })
            
            # 簡單模擬 SMC 買賣點與標記點測試 (示意訊號)
            if i > 5 and i % 25 == 0:
                signals.append({
                    "time": open_time,
                    "position": "aboveBar",
                    "color": "#f23645",
                    "shape": "arrowDown",
                    "text": "SMC Sell"
                })
            elif i > 5 and i % 18 == 0:
                signals.append({
                    "time": open_time,
                    "position": "belowBar",
                    "color": "#089981",
                    "shape": "arrowUp",
                    "text": "SMC Buy"
                })

        return {"ohlc": ohlc, "signals": signals}
    except Exception as e:
        return {"error": str(e), "ohlc": [], "signals": []}