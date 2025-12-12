# websocket_demo.py
import json
import threading
import time
from typing import Dict, Any, Optional
from websocket import WebSocketApp
from polymarket_utils import (GAMMA_BASE,CLOB_BASE,get_assets_from_event,safe_filename,r3,log_quote_to_file,)

WSS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
POLY_URL = "https://polymarket.com/sports/nhl-2026/games/week/10/nhl-col-nsh-2025-12-10"

MIN_PRICE_CHANGE = 0.001

ASSETS: Dict[str, str] = {}
ASSET_IDS = []

last_quotes: Dict[str, Dict[str, Optional[float]]] = {}
orderbooks: Dict[str, Dict[str, Dict[float, float]]] = {}

book_count = 0
price_change_count = 0
trade_count = 0


def norm_price(p: float) -> float:
    return round(p, 2)


def on_open(ws: WebSocketApp):
    print("[WS] Connected. Subscribing to market channel for asset_ids:")
    for aid in ASSET_IDS:
        print("   -", aid, "->", ASSETS.get(aid, aid))
    sub_msg = {"assets_ids": ASSET_IDS, "type": "market"}
    ws.send(json.dumps(sub_msg))
    t = threading.Thread(target=ping_loop, args=(ws,), daemon=True)
    t.start()


def on_message(ws: WebSocketApp, message: str):
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        if message != "PONG":
            print("[WS] Non-JSON message:", message)
        return

    if isinstance(data, list):
        for ev in data:
            process_single_event(ev)
    elif isinstance(data, dict):
        process_single_event(data)


def process_single_event(event: Any):
    if not isinstance(event, dict):
        return
    et = event.get("event_type")
    if et == "book":
        handle_book_event(event)
    elif et == "price_change":
        handle_price_change_event(event)
    elif et == "last_trade_price":
        handle_last_trade_event(event)


def on_error(ws: WebSocketApp, error: Any):
    print("[WS ERROR]", error)


def on_close(ws: WebSocketApp, close_status_code, close_msg):
    print("[WS CLOSED]", close_status_code, close_msg)
    print(
        "[STATS] book:",
        book_count,
        "price_change:",
        price_change_count,
        "last_trade_price:",
        trade_count,
    )


def handle_book_event(event: Dict[str, Any]):
    global book_count
    book_count += 1

    asset_id = event.get("asset_id")
    if asset_id not in last_quotes:
        return

    bids = event.get("bids") or []
    asks = event.get("asks") or []

    bid_levels: Dict[float, float] = {}
    ask_levels: Dict[float, float] = {}

    for b in bids:
        p = norm_price(float(b["price"]))
        s = float(b.get("size", 0))
        bid_levels[p] = bid_levels.get(p, 0.0) + s

    for a in asks:
        p = norm_price(float(a["price"]))
        s = float(a.get("size", 0))
        ask_levels[p] = ask_levels.get(p, 0.0) + s

    orderbooks[asset_id] = {"bids": bid_levels, "asks": ask_levels}

    best_bid = max(bid_levels.keys()) if bid_levels else None
    best_ask = min(ask_levels.keys()) if ask_levels else None

    bid_size = bid_levels.get(best_bid) if best_bid is not None else None
    ask_size = ask_levels.get(best_ask) if best_ask is not None else None

    maybe_log_top_of_book(asset_id, best_bid, best_ask, bid_size, ask_size)


def handle_price_change_event(event: Dict[str, Any]):
    global price_change_count
    price_change_count += 1

    pcs = event.get("price_changes") or []
    for pc in pcs:
        asset_id = pc.get("asset_id")
        if asset_id not in last_quotes:
            continue

        side = pc.get("side")
        raw_price = pc.get("price")
        raw_size = pc.get("size")

        if raw_price is None or raw_size is None or side not in ("BUY", "SELL"):
            continue

        price = norm_price(float(raw_price))
        size = float(raw_size)

        ob = orderbooks.setdefault(
            asset_id, {"bids": {}, "asks": {}}
        )
        book_side = "bids" if side == "BUY" else "asks"

        if size <= 0:
            ob[book_side].pop(price, None)
        else:
            ob[book_side][price] = size

        notional = price * size
        label = ASSETS.get(asset_id, asset_id)
        level_side = "BID" if side == "BUY" else "ASK"
        print(
            f"[LEVEL] {label} | {level_side} level updated: "
            f"price={r3(price)} size={r3(size)} notional={r3(notional)}"
        )

        bb = pc.get("best_bid")
        ba = pc.get("best_ask")
        best_bid = norm_price(float(bb)) if bb is not None else None
        best_ask = norm_price(float(ba)) if ba is not None else None

        bid_size = (
            ob["bids"].get(best_bid)
            if best_bid is not None
            else None
        )
        ask_size = (
            ob["asks"].get(best_ask)
            if best_ask is not None
            else None
        )

        maybe_log_top_of_book(asset_id, best_bid, best_ask, bid_size, ask_size)


def handle_last_trade_event(event: Dict[str, Any]):
    global trade_count
    trade_count += 1

    asset_id = event.get("asset_id")
    if asset_id not in last_quotes:
        return
    price = event.get("price")
    price = float(price) if price is not None else None
    print(
        f"[TRADE] {ASSETS.get(asset_id, asset_id)} "
        f"price={r3(price)} size={event.get('size')} side={event.get('side')}"
    )


def maybe_log_top_of_book(
    asset_id: str,
    bid: Optional[float],
    ask: Optional[float],
    bid_size: Optional[float],
    ask_size: Optional[float],
):
    prev = last_quotes.setdefault(
        asset_id,
        {"bid": None, "ask": None, "bid_size": None, "ask_size": None},
    )
    prev_bid = prev["bid"]
    prev_ask = prev["ask"]

    if bid_size is None:
        bid_size = prev.get("bid_size")
    if ask_size is None:
        ask_size = prev.get("ask_size")

    mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None

    def changed(old: Optional[float], new: Optional[float]) -> bool:
        if old is None or new is None:
            return True
        return abs(new - old) >= MIN_PRICE_CHANGE

    if not (changed(prev_bid, bid) or changed(prev_ask, ask)):
        return

    label = ASSETS.get(asset_id, asset_id)
    print(
        f"[QUOTE] {label} "
        f"bid={r3(bid)} ask={r3(ask)} mid={r3(mid)} "
        f"bid_size={r3(bid_size)} ask_size={r3(ask_size)}"
    )

    fname = safe_filename(label)
    log_quote_to_file(fname, bid, ask, mid, bid_size, ask_size)

    prev["bid"] = bid
    prev["ask"] = ask
    prev["bid_size"] = bid_size
    prev["ask_size"] = ask_size


def ping_loop(ws: WebSocketApp):
    while True:
        try:
            ws.send("PING")
        except Exception as e:
            print("[WS PING ERROR]", e)
            break
        time.sleep(10)


def main():
    global ASSETS, ASSET_IDS, last_quotes, orderbooks

    print("[INIT] Resolving assets from event:", POLY_URL)
    ASSETS = get_assets_from_event(POLY_URL)
    ASSET_IDS = list(ASSETS.keys())
    last_quotes = {
        aid: {"bid": None, "ask": None, "bid_size": None, "ask_size": None}
        for aid in ASSET_IDS
    }
    orderbooks = {
        aid: {"bids": {}, "asks": {}}
        for aid in ASSET_IDS
    }

    print("[INIT] Tracking tokens:")
    for aid, label in ASSETS.items():
        print("   -", aid, "->", label)

    print("[WS] Connecting to:", WSS_URL)
    ws = WebSocketApp(
        WSS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever()


if __name__ == "__main__":
    main()
