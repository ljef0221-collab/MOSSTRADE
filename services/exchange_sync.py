import requests

def sync_binance_futures():
    """
    從 CoinGecko 取得全球所有加密貨幣清單，
    並轉換成與 Local Symbol Database 相容的格式。
    """
    url = "https://api.coingecko.com/api/v3/coins/list"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        # CoinGecko 免費 API，無 IP 封鎖問題
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            coins = response.json()
            crypto_database = []
            
            for coin in coins:
                symbol = coin.get("symbol", "").upper()
                name = coin.get("name", "")
                
                if symbol and name:
                    crypto_database.append({
                        "symbol": f"{symbol}-USD",  # 相容於搜尋與 Yahoo 畫圖格式
                        "name": f"{name} ({symbol})",
                        "type": "Crypto",
                        "exchange": "Crypto",
                        "keywords": [symbol, name, f"{symbol}USD", f"{symbol}-USD"]
                    })
                    
            print(f"✅ 成功同步全網加密貨幣共 {len(crypto_database)} 筆數據！")
            return crypto_database
        else:
            print(f"⚠️ CoinGecko 回傳異常: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ 加密貨幣全網同步失敗: {e}")
        return []