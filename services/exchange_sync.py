import requests
import json
import os


BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)


CACHE_DIR = os.path.join(
    BASE_DIR,
    "cache"
)


os.makedirs(
    CACHE_DIR,
    exist_ok=True
)


CACHE_FILE = os.path.join(
    CACHE_DIR,
    "binance_symbols.json"
)



def sync_binance_futures():

    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"


    response = requests.get(
        url,
        timeout=10
    )


    data = response.json()


    symbols = []


    for item in data["symbols"]:

        if item["status"] != "TRADING":
            continue


        symbols.append({

            "symbol": item["symbol"],

            "name":
                item["baseAsset"]
                + "/"
                + item["quoteAsset"],

            "type": "crypto",

            "exchange": "BINANCE",

            "market": "FUTURES"

        })


    with open(
        CACHE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            symbols,
            f,
            ensure_ascii=False,
            indent=2
        )


    print(
        "Binance symbols:",
        len(symbols)
    )


    return symbols