from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np
import os

app = FastAPI(title="Financial Navigation System API", version="1.0.0")

@app.get("/")
async def read_root():
    """
    根目錄：返回前端的 index.html 畫面，解決 Render Not Found 問題
    """
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"detail": "index.html not found in server directory"}

# 設定 CORS 允許前端跨域呼叫
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def calculate_strategy(df: pd.DataFrame):
    """
    量化策略邏輯：
    1. 趨勢判定：50 EMA > 200 EMA (多頭) / 50 EMA < 200 EMA (空頭)
    2. 突破捕捉：突破 50 週期唐奇安通道 ± (0.15 * ATR)
    3. 盤整過濾：14 ATR > 50 SMA(ATR) * 0.85
    4. 風控計算：停損 2.0 * ATR, 停利 3.8 * ATR (風報比 1.9)
    """
    if len(df) < 200:
        return {"signal": "HOLD", "reason": "數據長度不足以計算 200 EMA"}

    # 均線計算
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()

    # ATR 計算
    df['TR'] = np.maximum(
        df['High'] - df['Low'],
        np.maximum(
            abs(df['High'] - df['Close'].shift(1)),
            abs(df['Low'] - df['Close'].shift(1))
        )
    )
    df['ATR_14'] = df['TR'].rolling(window=14).mean()
    df['ATR_SMA_50'] = df['ATR_14'].rolling(window=50).mean()

    # 唐奇安通道
    df['Donchian_High'] = df['High'].shift(1).rolling(window=50).max()
    df['Donchian_Low'] = df['Low'].shift(1).rolling(window=50).min()

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # 盤整過濾檢查
    is_volatile = latest['ATR_14'] > (latest['ATR_SMA_50'] * 0.85)

    signal = "HOLD"
    stop_loss = 0.0
    take_profit = 0.0
    reason = "無明確突破訊號"

    if is_volatile:
        # 多頭訊號：大趨勢向上 + 突破唐奇安通道上軌
        if (latest['EMA_50'] > latest['EMA_200']) and (latest['Close'] > (latest['Donchian_High'] + 0.15 * latest['ATR_14'])):
            signal = "BUY"
            stop_loss = round(latest['Close'] - (2.0 * latest['ATR_14']), 2)
            take_profit = round(latest['Close'] + (3.8 * latest['ATR_14']), 2)
            reason = "多頭趨勢成立，向上突破唐奇安通道上軌"

        # 空頭訊號：大趨勢向下 + 跌破唐奇安通道下軌
        elif (latest['EMA_50'] < latest['EMA_200']) and (latest['Close'] < (latest['Donchian_Low'] - 0.15 * latest['ATR_14'])):
            signal = "SELL"
            stop_loss = round(latest['Close'] + (2.0 * latest['ATR_14']), 2)
            take_profit = round(latest['Close'] - (3.8 * latest['ATR_14']), 2)
            reason = "空頭趨勢成立，向下跌破唐奇安通道下軌"
    else:
        reason = "波動度不足（14 ATR 過低），判定為低效盤整"

    return {
        "symbol": latest.name if hasattr(latest, 'name') else "UNKNOWN",
        "close_price": round(latest['Close'], 2),
        "signal": signal,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "atr": round(latest['ATR_14'], 2),
        "reason": reason
    }

@app.get("/api/v1/analyze/{symbol}")
async def analyze_symbol(symbol: str, interval: str = "1h"):
    """
    抓取多品類數據 (股票、加密貨幣、外匯、原油、黃金) 並執行策略分析
    """
    try:
        # yfinance 格式處理 (例如 BTCUSD -> BTC-USD)
        formatted_symbol = symbol.upper()
        if formatted_symbol in ["BTC", "ETH", "SOL"]:
            formatted_symbol += "-USD"

        ticker = yf.Ticker(formatted_symbol)
        df = ticker.history(period="1mo", interval=interval)

        if df.empty:
            raise HTTPException(status_code=404, detail=f"找不到商品標的: {symbol}")

        result = calculate_strategy(df)
        result["requested_symbol"] = symbol
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)