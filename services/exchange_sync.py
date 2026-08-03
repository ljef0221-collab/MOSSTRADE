import requests


def sync_binance_futures():
    """Compatibility name: load active OKX USDT perpetual contracts."""
    response = requests.get(
        "https://www.okx.com/api/v5/public/instruments",
        params={"instType": "SWAP"},
        headers={"User-Agent": "SmartNavigator/1.0"}, timeout=10,
    )
    response.raise_for_status()
    return [{
        "symbol": f"OKX:{item['instId']}",
        "name": f"{item.get('ctValCcy', item['instId'])} Perpetual",
        "type": "Perpetual Futures", "exchange": "OKX",
        "keywords": [item["instId"], f"OKX:{item['instId']}", item.get("uly", "")],
    } for item in response.json().get("data", []) if item.get("state") == "live" and item.get("settleCcy") == "USDT"]
