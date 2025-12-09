import os
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
POLY_URL = "https://polymarket.com/event/lol-c9-fox1-2025-12-08"

def slug_from_url(u: str) -> str:
    path = urlparse(u).path.strip("/")
    return path.split("/")[-1]

def main():
    load_dotenv()
    private_key = os.getenv("POLY_KEY") or os.getenv("POLY_API") or os.getenv("PRIVATE_KEY")
    funder = os.getenv("POLY_FUNDER") or os.getenv("FUNDER")
    if not private_key or not funder:
        raise RuntimeError("Missing key/funder env vars")

    slug = slug_from_url(POLY_URL)

    ev_resp = requests.get(f"{GAMMA_BASE}/events/slug/{slug}", timeout=10)
    ev_resp.raise_for_status()
    event = ev_resp.json()
    markets = event.get("markets", [])
    if not markets:
        raise RuntimeError("No markets for this slug")

    for m in markets:
        cond = m.get("conditionId") or m.get("condition_id")
        if not cond:
            continue
        clob_resp = requests.get(f"{CLOB_BASE}/markets/{cond}", timeout=10)
        clob_resp.raise_for_status()
        mk = clob_resp.json()
        tokens = mk.get("tokens", [])
        print("condition_id:", cond)
        for t in tokens:
            print(" ", t.get("outcome"), t.get("token_id"))

    first = markets[0]
    cond = first.get("conditionId") or first.get("condition_id")
    clob_resp = requests.get(f"{CLOB_BASE}/markets/{cond}", timeout=10)
    clob_resp.raise_for_status()
    mk = clob_resp.json()
    tokens = mk["tokens"]
    token = tokens[0]
    token_id = token["token_id"]
    min_size = float(mk.get("minimum_order_size", "1"))
    print("Chosen:", token.get("outcome"), token_id)
    print("Minimum order size:", min_size)

    client = ClobClient(CLOB_BASE, key=private_key, chain_id=137, signature_type=1, funder=funder)
    client.set_api_creds(client.create_or_derive_api_creds())

    price = 0.05
    order = OrderArgs(token_id=token_id, price=price, size=min_size, side=BUY)
    try:
        signed = client.create_order(order)
        resp = client.post_order(signed)
        print("Order response:", resp)
    except Exception as e:
        print("Order error:", repr(e))

if __name__ == "__main__":
    main()
