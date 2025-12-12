# websocket_demo.py
import json
import threading
import time
from typing import Dict, Any, Optional
from websocket import WebSocketApp

WSS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# asset_id -> human-readable label (edit/add as needed)
ASSETS: Dict[str, str] = {
    "14433630064846279767985835789711244696150988949614799880619450463696167114135": "Heat vs. Magic - Heat",
    # "..." : "Some Other Game - Outcome",
}

ASSET_IDS = list(ASSETS.keys())
MIN_PRICE_CHANGE = 0.005  # 0.5%

last_quotes: Dict[str, Dict[str, Optional[float]]] = {
    aid: {"bid": None, "ask": None} for aid in ASSET_IDS
}


def safe_filename(label: str) -> str:
    cleaned = "".join(
        c if c.isalnum() or c in (" ", "-", "_") else "_"
        for c in label
    ).strip()
    return f"{cleaned}.jsonl" if cleaned else "asset.jsonl"


def r(x: Optional[float]) -> Optional[float]:
    return round(x, 3) if x is not None else None


def log_quote(
    asset_id: str,
    bid: Optional[float],
    ask: Optional[float],
    mid: Optional[float],
    bid_size: Optional[float],
    ask_size: Optional[float],
) -> None:
    label = ASSETS.get(asset_id, asset_id)
    fname = safe_filename(label)
    rec = {
        "ts": time.time(),
        "bid": r(bid),
        "ask": r(ask),
        "mid": r(mid),
        "spread": r(ask - bid) if bid is not None and ask is not None else None,
        "bid_size": r(bid_size),
        "ask_size": r(ask_size),
    }
    with open(fname, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


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


def on_error(ws: WebSocketApp, error: Any):
    print("[WS ERROR]", error)


def on_close(ws: WebSocketApp, close_status_code, close_msg):
    print("[WS CLOSED]", close_status_code, close_msg)


def handle_book_event(event: Dict[str, Any]):
    asset_id = event.get("asset_id")
    if asset_id not in last_quotes:
        return

    bids = event.get("bids") or []
    asks = event.get("asks") or []

    best_bid = float(bids[-1]["price"]) if bids else None
    best_ask = float(asks[-1]["price"]) if asks else None
    bid_size = float(bids[-1].get("size", 0)) if bids else None
    ask_size = float(asks[-1].get("size", 0)) if asks else None

    maybe_log_quote_change(asset_id, best_bid, best_ask, bid_size, ask_size)


def handle_price_change_event(event: Dict[str, Any]):
    asset_id = event.get("asset_id")
    if asset_id not in last_quotes:
        return

    best_bid = event.get("best_bid")
    best_ask = event.get("best_ask")
    bid_size = event.get("best_bid_size")
    ask_size = event.get("best_ask_size")

    best_bid = float(best_bid) if best_bid is not None else None
    best_ask = float(best_ask) if best_ask is not None else None
    bid_size = float(bid_size) if bid_size is not None else None
    ask_size = float(ask_size) if ask_size is not None else None

    maybe_log_quote_change(asset_id, best_bid, best_ask, bid_size, ask_size)


def maybe_log_quote_change(
    asset_id: str,
    bid: Optional[float],
    ask: Optional[float],
    bid_size: Optional[float],
    ask_size: Optional[float],
):
    prev = last_quotes.setdefault(asset_id, {"bid": None, "ask": None})
    prev_bid = prev["bid"]
    prev_ask = prev["ask"]

    mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None

    def changed(old: Optional[float], new: Optional[float]) -> bool:
        if old is None or new is None:
            return True
        return abs(new - old) >= MIN_PRICE_CHANGE

    if not (changed(prev_bid, bid) or changed(prev_ask, ask)):
        return

    print(
        f"[QUOTE] {ASSETS.get(asset_id, asset_id)} "
        f"bid={r(bid)} ask={r(ask)} mid={r(mid)} "
        f"prev_bid={r(prev_bid)} prev_ask={r(prev_ask)} "
        f"bid_size={r(bid_size)} ask_size={r(ask_size)}"
    )

    log_quote(asset_id, bid, ask, mid, bid_size, ask_size)
    prev["bid"] = bid
    prev["ask"] = ask


def ping_loop(ws: WebSocketApp):
    while True:
        try:
            ws.send("PING")
        except Exception as e:
            print("[WS PING ERROR]", e)
            break
        time.sleep(10)


def main():
    if not ASSET_IDS:
        print("No ASSET_IDS configured in ASSETS dict.")
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
