import requests


def sync_binance_futures():
    """Load tradeable USDT perpetual contracts from Binance Futures."""
    response = requests.get(
        "https://fapi.binance.com/fapi/v1/exchangeInfo",
        headers={"User-Agent": "SmartNavigator/1.0"},
        timeout=10,
    )
    response.raise_for_status()

    contracts = []
    for item in response.json().get("symbols", []):
        if item.get("contractType") != "PERPETUAL" or item.get("status") != "TRADING":
            continue
        symbol = item.get("symbol", "")
        if not symbol:
            continue
        contracts.append({
            "symbol": f"BINANCE:{symbol}",
            "name": f"{item.get('baseAsset', symbol)}/{item.get('quoteAsset', '')} Perpetual",
            "type": "Perpetual Futures",
            "exchange": "Binance Futures",
            "keywords": [symbol, f"BINANCE:{symbol}", item.get("baseAsset", "")],
        })
    return contracts
