import os
import time
import requests
from typing import Dict, Set

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
from py_clob_client.exceptions import PolyApiException

load_dotenv()

GIAYN_WALLET =  "0x9d84ce0306f8551e02efef1680475fc0f1dc1344" #"0x507e52ef684ca2dd91f90a9d26d149dd3288beae" 2nd one is giang, 1st one is imjustken
DATA_API_BASE = "https://data-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
HOST = CLOB_BASE
CHAIN_ID = 137
PRIVATE_KEY = os.getenv("POLY_KEY")
FUNDER = os.getenv("POLY_FUNDER")
POLL_SECONDS = 4
MIN_USD_GIAYN_TO_COPY = 70.0
MIN_USD_PER_COPY = 1.00
MAX_USD_PER_COPY = 5.01
MAX_OPEN_MARKETS = 50

seen_hashes: Set[str] = set()
my_positions: Dict[str, float] = {}
min_size_cache: Dict[str, float] = {}

def init_client() -> ClobClient:
    if not PRIVATE_KEY or not FUNDER:
        raise RuntimeError("POLY_KEY or POLY_FUNDER missing from .env")

    client = ClobClient(
        HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=1,
        funder=FUNDER,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def fetch_giayn_activity(limit: int = 100):
    params = {
        "user": GIAYN_WALLET,
        "type": "TRADE",
        "limit": limit,
        "offset": 0,
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC",
    }
    resp = requests.get(f"{DATA_API_BASE}/activity", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", data.get("data", []))

    import json as _json
    try:
        parsed = _json.loads(data)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return parsed.get("results", parsed.get("data", []))
    except Exception:
        pass

    print("[WARN] Unexpected /activity payload type:", type(data))
    return []


def get_min_order_size(asset_id: str, condition_id: str) -> float:
    if asset_id in min_size_cache:
        return min_size_cache[asset_id]

    try:
        resp = requests.get(
            f"{CLOB_BASE}/markets/{condition_id}",
            timeout=10,
        )
        resp.raise_for_status()
        market = resp.json()
    except Exception as e:
        print("[WARN] Failed to fetch market for", condition_id, ":", e)
        min_size_cache[asset_id] = 1.0
        return 1.0

    min_size = 0.0
    if isinstance(market, dict):
        try:
            min_size = float(market.get("minimum_order_size", 0.0))
        except (TypeError, ValueError):
            min_size = 0.0

    if min_size <= 0:
        min_size = 1.0

    min_size_cache[asset_id] = min_size
    return min_size


def get_best_bid_ask(asset_id: str):
    try:
        resp = requests.get(
 f"{CLOB_BASE}/orderbook",
       params={"asset_id": asset_id},
            timeout=10,
        )
        resp.raise_for_status()
        ob = resp.json()
    except Exception as e:
        print("[WARN] Failed to fetch orderbook for", asset_id, ":", e)
        return None, None

    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    best_bid = (
        max((float(level["price"]) for level in bids), default=None)
        if bids
        else None
    )
    best_ask = (
        min((float(level["price"]) for level in asks), default=None)
        if asks
        else None
    )
    return best_bid, best_ask


def compute_copy_shares(price: float, min_size: float) -> float:
    if price <= 0:
        return 0.0
    target_usd = MIN_USD_PER_COPY
    shares = target_usd / price
    shares = max(shares, min_size)
    max_shares = MAX_USD_PER_COPY / max(price, 1e-6)
    shares = min(shares, max_shares)
    return round(shares, 4)


def place_order(client: ClobClient, token_id: str, side: str, price: float, size: float):
    if size <= 0:
        return

    order = OrderArgs(token_id=token_id, price=price, size=size, side=side)

    try:
        signed = client.create_order(order)
        resp = client.post_order(signed)
        print("[ORDER]", side, "token=", token_id, "price=", price, "size=", size)
        print("[RESPONSE]", resp)
    except PolyApiException as e:
        msg = str(e)
        if "lower than the minimum" in msg:
            print("[SKIP] Exchange rejected order: below minimum_size. Msg:", msg)
        else:
            print("[ERROR] PolyApiException:", msg)
    except Exception as e:
        print("[ERROR] place_order exception:", repr(e))


def handle_giayn_buy(ev: dict, client: ClobClient):
    token_id = ev["asset"]
    condition_id = ev["conditionId"]
    price = float(ev["price"])
    usdc = float(ev["usdcSize"])
    title = ev.get("title", "")
    outcome = ev.get("outcome", "")

    if len({k for k, v in my_positions.items() if v > 0}) >= MAX_OPEN_MARKETS:
        print("[SKIP BUY] Already at MAX_OPEN_MARKETS; skipping new market.")
        return

    min_size = get_min_order_size(token_id, condition_id)
    shares = compute_copy_shares(price, min_size)

    if shares * price > MAX_USD_PER_COPY + 1e-9:
        print(
            f"[SKIP BUY] GIAYN usdc≈{usdc:.2f} {token_id}, "
            f"min_size {min_size:.4f} would risk {shares * price:.2f} > MAX_USD_PER_COPY; skipping."
        )
        return

    best_bid, best_ask = get_best_bid_ask(token_id)

    if best_ask is not None and best_ask <= price:
        limit_price = best_ask
    else:
        limit_price = price

    print(
        f"[FOLLOW BUY] GIAYN BUY usdc≈{usdc:.2f} in '{title}' ({outcome}), "
        f"we BUY {shares:.4f} @ {limit_price:.3f} "
        f"(GIAYN price {price:.3f}, min_size {min_size:.2f})"
    )

    place_order(client, token_id, BUY, limit_price, shares)

    prev = my_positions.get(token_id, 0.0)
    my_positions[token_id] = prev + shares
    print(f"[POSITION] token {token_id} now {my_positions[token_id]:.4f} shares")


def handle_giayn_sell(ev: dict, client: ClobClient):
    token_id = ev["asset"]
    condition_id = ev["conditionId"]
    price = float(ev["price"])
    usdc = float(ev["usdcSize"])
    title = ev.get("title", "")
    outcome = ev.get("outcome", "")

    current_pos = my_positions.get(token_id, 0.0)
    if current_pos <= 0:
        print(
            f"[SKIP SELL] GIAYN SELL usdc≈{usdc:.2f} in '{title}' ({outcome}), "
            "but we have no position."
        )
        return

    min_size = get_min_order_size(token_id, condition_id)
    shares_to_sell = round(current_pos, 4)

    if shares_to_sell < min_size:
        print(
            f"[SKIP SELL] We only have {shares_to_sell:.4f} shares but "
            f"min_size is {min_size:.4f}; skipping close."
        )
        return

    best_bid, best_ask = get_best_bid_ask(token_id)
    if best_bid is not None and best_bid >= price:
        limit_price = best_bid
    else:
        limit_price = price

    print(
        f"[FOLLOW SELL] GIAYN SELL usdc≈{usdc:.2f} in '{title}' ({outcome}), "
        f"we SELL {shares_to_sell:.4f} @ {limit_price:.3f} "
        f"(GIAYN price {price:.3f}, min_size {min_size:.2f})"
    )

    place_order(client, token_id, SELL, limit_price, shares_to_sell)

    my_positions[token_id] = 0.0
    print(f"[POSITION] token {token_id} now 0.0000 shares")


def process_activity_event(ev: dict, client: ClobClient):
    if not isinstance(ev, dict):
        print("[WARN] Unexpected event type in process_activity_event:", type(ev), ev)
        return

    if ev.get("type") != "TRADE":
        return

    txh = ev.get("transactionHash")
    if not txh:
        return
    if txh in seen_hashes:
        return
    seen_hashes.add(txh)

    usdc = float(ev.get("usdcSize", 0.0))
    if usdc < MIN_USD_GIAYN_TO_COPY:
        return

    side = ev.get("side")
    if side == "BUY":
        handle_giayn_buy(ev, client)
    elif side == "SELL":
        handle_giayn_sell(ev, client)
    else:
        print("[WARN] Unknown side in activity:", side)


def bootstrap_seen_hashes():
    global seen_hashes
    events = fetch_giayn_activity(limit=200)
    seen_hashes = {e["transactionHash"] for e in events}
    print(f"Bootstrapped {len(seen_hashes)} existing activity events as seen.")


def main_loop():
    client = init_client()
    bootstrap_seen_hashes()

    print(
        f"Starting GIAYN copy-trader (improved):\n"
        f" - Only trades with usdcSize >= ${MIN_USD_GIAYN_TO_COPY}\n"
        f" - We risk about ${MIN_USD_PER_COPY}-${MAX_USD_PER_COPY} per BUY\n"
        f" - Use per-market minimum_order_size to avoid 400 errors\n"
        f" - Use live orderbook to try for price improvement vs GIAYN's price\n"
    )

    while True:
        try:
            events = fetch_giayn_activity(limit=50)

            if not isinstance(events, list):
                print("[WARN] fetch_giayn_activity did not return list, got:", type(events))
                time.sleep(POLL_SECONDS)
                continue

            for ev in reversed(events):
                process_activity_event(ev, client)

            if len(seen_hashes) > 10_000:
                latest = list(seen_hashes)[-5000:]
                seen_hashes.clear()
                seen_hashes.update(latest)

        except Exception as e:
            print("[ERROR in main_loop]", repr(e))

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main_loop()
