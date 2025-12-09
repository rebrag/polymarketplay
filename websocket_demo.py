"""
websocket_demo.py

Standalone script that illustrates the utility of using Polymarket's
market websocket channel:

- Connects to the 'market' websocket
- Subscribes to one or more asset_ids (outcomes)
- Streams live orderbook updates
- Prints best bid/ask + mid price whenever they change meaningfully

This is NOT placing orders or touching your wallet. It's purely a
market-data demo to show how websockets can power better exits,
monitoring, and strategies than naive polling.
"""

import json
import threading
import time
import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from websocket import WebSocketApp
load_dotenv()

WSS_BASE = "wss://ws-subscriptions-clob.polymarket.com/ws"

# Comma-separated list of asset_ids in your .env, e.g.:
# ASSET_IDS=123,456
ASSET_IDS_ENV = os.getenv("ASSET_IDS", "")

if ASSET_IDS_ENV.strip():
    ASSET_IDS = [s.strip() for s in ASSET_IDS_ENV.split(",") if s.strip()]
else:
    # If you don't want to use .env, hard-code one or two asset_ids here.
    ASSET_IDS = [
        "82263437028976937938917692119085850534298447420831840197176963793365472027050",
        "108933364589075777870940251520486797095591816136220472580701600373174470258002",
    ]

if not ASSET_IDS:
    print(
        "WARNING: No ASSET_IDS configured.\n"
        " - Set ASSET_IDS in your .env (comma-separated), or\n"
        " - Hard-code them in the ASSET_IDS list in this file.\n"
        "The websocket will still connect, but nothing meaningful will be streamed."
    )

# How big a price change counts as "interesting" for logging (0.005 = 0.5%)
MIN_PRICE_CHANGE = 0.005

# ---------------- STATE ----------------

# Track last seen best bid/ask for each asset so we only print real changes
last_quotes: Dict[str, Dict[str, Optional[float]]] = {
    aid: {"bid": None, "ask": None} for aid in ASSET_IDS
}


# ---------------- HANDLERS ----------------

def on_open(ws: WebSocketApp):
    """
    Called when the websocket connection is opened.
    We send a subscription message for our asset_ids.
    """
    print("[WS] Connected. Subscribing to market channel for asset_ids:")
    for aid in ASSET_IDS:
        print("   -", aid)

    sub_msg = {
        "assets_ids": ASSET_IDS,
        "type": "market",
    }
    ws.send(json.dumps(sub_msg))

    # Start a ping thread to keep the connection alive
    t = threading.Thread(target=ping_loop, args=(ws,), daemon=True)
    t.start()


def on_message(ws: WebSocketApp, message: str):
    """
    Called whenever the server sends us a message.
    Polymarket sometimes sends:
      - a single event as a dict
      - multiple events as a list of dicts
      - raw strings like 'PONG'
    """
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        # This is where 'PONG' lands, which is fine
        print("[WS] Received non-JSON message:", message)
        return

    # If it's a list, process each element as an event
    if isinstance(data, list):
        for ev in data:
            process_single_event(ev)
    elif isinstance(data, dict):
        process_single_event(data)
    else:
        print("[WS] Unexpected message type:", type(data), data)


def process_single_event(event: Any):
    """
    Handle a single decoded event dict from the websocket stream.
    """
    if not isinstance(event, dict):
        # safety guard
        print("[WS] Skipping non-dict event:", type(event), event)
        return

    event_type = event.get("event_type")

    if event_type == "book":
        handle_book_event(event)
    elif event_type == "price_change":
        handle_price_change_event(event)
    else:
        # For demo we ignore other events, but you could log occasionally
        # print("[WS] Unknown event:", event)
        pass


def on_error(ws: WebSocketApp, error: Any):
    print("[WS ERROR]", error)


def on_close(ws: WebSocketApp, close_status_code, close_msg):
    print("[WS CLOSED]", close_status_code, close_msg)


# ---------------- EVENT PROCESSING ----------------

def handle_book_event(event: Dict[str, Any]):
    asset_id = event.get("asset_id")
    if asset_id not in last_quotes:
        return
    bids = event.get("bids", [])
    asks = event.get("asks", [])
    best_bid = float(bids[-1]["price"]) if bids else None
    best_ask = float(asks[-1]["price"]) if asks else None
    maybe_log_quote_change(asset_id, best_bid, best_ask)


def handle_price_change_event(event: Dict[str, Any]):
    asset_id = event.get("asset_id")
    if asset_id not in last_quotes:
        return
    best_bid = event.get("best_bid")
    best_ask = event.get("best_ask")
    if best_bid is not None:
        best_bid = float(best_bid)
    if best_ask is not None:
        best_ask = float(best_ask)
    maybe_log_quote_change(asset_id, best_bid, best_ask)


def maybe_log_quote_change(asset_id: str, bid: Optional[float], ask: Optional[float]):
    """
    Compare new best bid/ask to the last seen ones and log only meaningful changes.

    This is where you *could* plug in logic like:
    - if bid < entry_price - stop_loss_threshold: trigger exit
    - if bid > entry_price + profit_take_threshold: take profit
    """
    prev = last_quotes.setdefault(asset_id, {"bid": None, "ask": None})
    prev_bid = prev["bid"]
    prev_ask = prev["ask"]

    mid = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2.0

    def changed_enough(old: Optional[float], new: Optional[float]) -> bool:
        if old is None or new is None:
            return True
        return abs(new - old) >= MIN_PRICE_CHANGE

    if not (changed_enough(prev_bid, bid) or changed_enough(prev_ask, ask)):
        return

    prev_desc = f"prev_bid={prev_bid} prev_ask={prev_ask}"
    now_desc = f"bid={bid} ask={ask} mid={mid}"

    print(f"[QUOTE] asset={asset_id}  {now_desc}  ({prev_desc})")

    prev["bid"] = bid
    prev["ask"] = ask


# ---------------- PING LOOP ----------------

def ping_loop(ws: WebSocketApp):
    """
    Send periodic PING frames so the connection stays alive.
    """
    while True:
        try:
            ws.send("PING")
        except Exception as e:
            print("[WS PING ERROR]", e)
            break
        time.sleep(10)


# ---------------- MAIN ----------------

def main():
    """
    Connects to the market websocket and starts streaming.
    """
    if not ASSET_IDS:
        print(
            "No ASSET_IDS configured; please set ASSET_IDS in .env or hard-code them "
            "in websocket_demo.py to see real data."
        )

    ws_url = WSS_BASE + "/market"  # /ws/market
    print("[WS] Connecting to:", ws_url)

    ws = WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    ws.run_forever()


if __name__ == "__main__":
    main()
