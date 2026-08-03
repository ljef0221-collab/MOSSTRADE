import requests


def _bybit_contracts():
    response = requests.get(
        "https://api.bybit.com/v5/market/instruments-info",
        params={"category": "linear", "limit": 1000},
        headers={"User-Agent": "SmartNavigator/1.0"}, timeout=10,
    )
    response.raise_for_status()
    return [{
        "symbol": f"BYBIT:{item['symbol']}",
        "name": f"{item.get('baseCoin', item['symbol'])}/{item.get('quoteCoin', '')} Perpetual",
        "type": "Perpetual Futures", "exchange": "Bybit Futures",
        "keywords": [item["symbol"], f"BYBIT:{item['symbol']}", item.get("baseCoin", "")],
    } for item in response.json().get("result", {}).get("list", []) if item.get("status") == "Trading"]


def sync_binance_futures():
    """Prefer Binance; transparently use Bybit when Render is geo-blocked."""
    try:
        response = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo", headers={"User-Agent": "SmartNavigator/1.0"}, timeout=10)
        response.raise_for_status()
        return [{
            "symbol": f"BINANCE:{item['symbol']}",
            "name": f"{item.get('baseAsset', item['symbol'])}/{item.get('quoteAsset', '')} Perpetual",
            "type": "Perpetual Futures", "exchange": "Binance Futures",
            "keywords": [item["symbol"], f"BINANCE:{item['symbol']}", item.get("baseAsset", "")],
        } for item in response.json().get("symbols", []) if item.get("contractType") == "PERPETUAL" and item.get("status") == "TRADING"]
    except requests.RequestException:
        return _bybit_contracts()
