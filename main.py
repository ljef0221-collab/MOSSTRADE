from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import yfinance as yf
import pandas as pd
import numpy as np
import os

app = FastAPI(title="SmartNavigator API", version="1.0.0")

# 設定 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. 根目錄回傳前端 index.html
@app.get("/")
async def read_root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"detail": "index.html not found"}

# 2. 前端需要的榜單 API (/api/rankings)
@app.get("/api/rankings")
async def get_rankings():
    try:
        # 預設熱門觀察標的
        symbols = ["NVDA", "TSLA", "AAPL", "AMD", "BTC-USD"]
        data = []
        for sym in symbols:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="2d")
            if len(hist) >= 1:
                latest_price = round(hist['Close'].iloc[-1], 2)
                volume = int(hist['Volume'].iloc[-1])
                change = 0.0
                if len(hist) >= 2:
                    prev_close = hist['Close'].iloc[-2]
                    change = round(((latest_price - prev_close) / prev_close) * 100, 2)
                
                data.append({
                    "symbol": sym,
                    "price": latest_price,
                    "volume": volume,
                    "change": change
                })
        
        # 分別依照成交量與漲跌幅排序
        top_volume = sorted(data, key=lambda x: x['volume'], reverse=True)
        top_gainers = sorted(data, key=lambda x: x['change'], reverse=True)
        
        return {
            "top_volume": top_volume,
            "top_gainers": top_gainers
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. 前端 Lightweight Charts 需要的 K 線 API (/api/klines)
@app.get("/api/klines")
async def get_klines(symbol: str, interval: str = "1d"):
    try:
        formatted_symbol = symbol.upper()
        if formatted_symbol in ["BTC", "ETH", "SOL"]:
            formatted_symbol += "-USD"

        ticker = yf.Ticker(formatted_symbol)
        df = ticker.history(period="3mo", interval=interval)

        if df.empty:
            raise HTTPException(status_code=404, detail=f"找不到標的: {symbol}")

        # 轉換成 Lightweight Charts 需要的格式 ({time: 'YYYY-MM-DD', open, high, low, close})
        ohlc = []
        for index, row in df.iterrows():
            time_str = index.strftime('%Y-%m-%d')
            ohlc.append({
                "time": time_str,
                "open": round(row['Open'], 2),
                "high": round(row['High'], 2),
                "low": round(row['Low'], 2),
                "close": round(row['Close'], 2)
            })

        # 簡單產生買賣訊號點範例 (可搭配策略邏輯調整)
        signals = []
        if len(ohlc) > 5:
            last_item = ohlc[-1]
            signals.append({
                "time": last_item["time"],
                "position": "aboveBar",
                "color": "#089981",
                "shape": "arrowDown",
                "text": "BUY Signal"
            })

        return {
            "symbol": symbol,
            "ohlc": ohlc,
            "signals": signals
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)