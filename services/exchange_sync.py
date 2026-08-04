import requests


def sync_binance_futures():
    """Compatibility name: load live OKX USDT perpetual and spot instruments."""
    headers = {"User-Agent": "SmartNavigator/1.0"}
    instruments = []
    for instrument_type in ("SWAP", "SPOT"):
        response = requests.get(
            "https://www.okx.com/api/v5/public/instruments",
            params={"instType": instrument_type},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        for item in response.json().get("data", []):
            if (
                item.get("state") != "live"
                or (instrument_type == "SWAP" and item.get("settleCcy") != "USDT")
                or (instrument_type == "SPOT" and item.get("quoteCcy") != "USDT")
            ):
                continue
            label = "Perpetual" if instrument_type == "SWAP" else "Spot"
            instruments.append(
                {
                    "symbol": f"OKX:{item['instId']}",
                    "name": f"{item.get('baseCcy', item['instId'])} {label}",
                    "type": (
                        "Perpetual Futures" if instrument_type == "SWAP" else "Spot"
                    ),
                    "exchange": "OKX",
                    "keywords": [
                        item["instId"],
                        f"OKX:{item['instId']}",
                        item.get("uly", ""),
                        item.get("baseCcy", ""),
                    ],
                }
            )
    return instruments
