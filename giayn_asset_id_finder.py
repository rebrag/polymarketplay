#This file/script will print to terminal some of the asset_id(s) that GIAYN is currently/recently trading
import requests

GIAYN = "0x507e52ef684ca2dd91f90a9d26d149dd3288beae"

resp = requests.get(
    "https://data-api.polymarket.com/trades",
    params={"user": GIAYN, "limit": 5, "takerOnly": "true"},
    timeout=10,
)
resp.raise_for_status()
trades = resp.json()

for t in trades:
    print(t["title"], "-> asset:", t["asset"])
