# price_change_dump.py
import json
from typing import Dict, Any
from urllib.parse import urlparse

import requests
from websocket import WebSocketApp

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
WSS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

POLY_URL = "https://polymarket.com/sports/nhl-2026/games/week/10/nhl-col-nsh-2025-12-10"

ASSETS: Dict[str, str] = {}
ASSET_IDS = []
price_change_count = 0


def get_slug(url: str) -> str:
    return urlparse(url).path.strip("/").split("/")[-1]


def get_event(slug: str) -> Dict[str, Any]:
    r = requests.get(f"{GAMMA_BASE}/events/slug/{slug}", timeout=10)
    r.raise_for_status()
    return r.json()


def pick_main_market(event: Dict[str, Any]) -> Dict[str, Any]:
    markets = event.get("markets") or []
    if not markets:
        raise RuntimeError("No markets on this event")
    for m in markets:
        q = (m.get("question") or "").lower()
        if "assists" not in q and "o/u" not in q and "spread" not in q:
            return m
    return markets[0]


def get_assets_from_event(url: str) -> Dict[str, str]:
    slug = get_slug(url)
    event = get_event(slug)
    main_market = pick_main_market(event)

    question = main_market.get("question") or "Unknown Event"
    cond = main_market.get("conditionId") or main_market.get("condition_id")
    if not isinstance(cond, str):
        raise RuntimeError(f"Main market missing conditionId: {cond}")

    r = requests.get(f"{CLOB_BASE}/markets/{cond}", timeout=10)
    r.raise_for_status()
    market = r.json()
    tokens = market.get("tokens") or []
    if not tokens:
        raise RuntimeError("No tokens in CLOB market response")

    assets: Dict[str, str] = {}
    for t in tokens:
        token_id = t.get("token_id")
        outcome = t.get("outcome") or "?"
        if isinstance(token_id, str):
            label = f"{question} - {outcome}"
            assets[token_id] = label
    if not assets:
        raise RuntimeError("No valid token_ids found for main market")
    return assets


def on_open(ws: WebSocketApp):
    print("[WS] Connected.")
    print("[INIT] Tracking tokens:")
    for aid, label in ASSETS.items():
        print("   -", aid, "->", label)

    sub_msg = {"assets_ids": ASSET_IDS, "type": "market"}
    print("[WS] Subscribing with:", sub_msg)
    ws.send(json.dumps(sub_msg))


def on_message(ws: WebSocketApp, message: str):
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        if message != "PONG":
            print("[WS] Non-JSON:", message)
        return

    if isinstance(data, list):
        for ev in data:
            process_single_event(ev)
    elif isinstance(data, dict):
        process_single_event(data)


def process_single_event(event: Any):
    global price_change_count
    if not isinstance(event, dict):
        return
    if event.get("event_type") != "price_change":
        return

    price_change_count += 1
    print(f"\n=== PRICE_CHANGE EVENT #{price_change_count} ===")
    print("Top-level keys:", list(event.keys()))
    print(json.dumps(event, indent=2, sort_keys=True))

    pcs = event.get("price_changes") or []
    for i, pc in enumerate(pcs):
        print(f"\n  -- price_changes[{i}] --")
        print("  keys:", list(pc.keys()))
        print(json.dumps(pc, indent=2, sort_keys=True))


def on_error(ws: WebSocketApp, error: Any):
    print("[WS ERROR]", error)


def on_close(ws: WebSocketApp, close_status_code, close_msg):
    print("[WS CLOSED]", close_status_code, close_msg)
    print(f"[STATS] total price_change events: {price_change_count}")


def main():
    global ASSETS, ASSET_IDS

    print("[INIT] Resolving assets from event:", POLY_URL)
    ASSETS = get_assets_from_event(POLY_URL)
    ASSET_IDS = list(ASSETS.keys())

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
