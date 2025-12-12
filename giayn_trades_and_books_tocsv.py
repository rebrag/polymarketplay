from __future__ import annotations

import csv
import json
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, TypedDict, Literal, Tuple, TextIO
from pathlib import Path

import requests
from websocket import WebSocketApp


# ---------- Config ----------

GIAYN_ADDRESS: str = "0x507e52ef684ca2dd91f90a9d26d149dd3288beae"

EVENT_SLUG: str = "cs2-furia-navi-2025-12-12"

DATA_API_ACTIVITY: str = "https://data-api.polymarket.com/activity"
GAMMA_EVENT_URL_TEMPLATE: str = "https://gamma-api.polymarket.com/events/slug/{slug}"
WSS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

OUTPUT_DIR = Path("output") / EVENT_SLUG
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TRADES_CSV_PATH: str = str(OUTPUT_DIR / "giayn_trades.csv")
BOOK_FILE_TEMPLATE: str = str(OUTPUT_DIR / "giayn_book_{placeholder}.csv")

POLL_SECONDS: float = 0.5
LIMIT: int = 500

BOOK_LOG_MIN_INTERVAL: float = 0.4  # currently not used for throttling


# ---------- CSV schemas ----------

BOOK_FIELDNAMES: List[str] = [
    "t_rel_s",
    "asset",
    "spread",
    "bid1_price",
    "bid1_size",
    "bid2_price",
    "bid2_size",
    "bid3_price",
    "bid3_size",
    "ask1_price",
    "ask1_size",
    "ask2_price",
    "ask2_size",
    "ask3_price",
    "ask3_size",
    "reason",
]

TRADES_FIELDNAMES: List[str] = [
    "t_rel_s",
    "local_ts",
    "remote_ts_ms",
    "side",
    "price",
    "size",
    "usdc",
    "asset",
    "conditionId",
    "outcome",
    "title",
    "eventSlug",
    "tx",
    "spread",
]


# ---------- Typed domain models ----------

Side = Literal["BUY", "SELL"]


class TradeActivityBase(TypedDict):
    type: str
    timestamp: int
    transactionHash: str


class TradeActivity(TradeActivityBase, total=False):
    asset: str
    side: str
    price: float
    size: float
    usdcSize: float
    conditionId: str
    outcome: str
    title: str
    eventSlug: str


class GammaMarket(TypedDict, total=False):
    conditionId: str
    clobTokenIds: str


class GammaEvent(TypedDict, total=False):
    id: str
    slug: str
    markets: List[GammaMarket]


@dataclass
class MarketMetadata:
    event_id: str
    event_slug: str
    asset_ids: List[str]
    condition_ids: Dict[str, str]


@dataclass
class BookState:
    bids: Dict[float, float]
    asks: Dict[float, float]


@dataclass
class Level:
    price: float
    size: float


# ---------- Global state ----------

start_ts: float = 0.0

orderbooks: Dict[str, BookState] = {}
orderbook_lock = threading.Lock()

asset_labels: Dict[str, str] = {}
asset_placeholders: Dict[str, str] = {}
placeholder_counter: int = 0

seen_hashes: Set[str] = set()

book_file_lock = threading.Lock()
trades_file_lock = threading.Lock()

# Per-asset book writers and file handles
book_writers: Dict[str, csv.DictWriter] = {}
book_files: Dict[str, TextIO] = {}

trades_writer: Optional[csv.DictWriter] = None


# ---------- Utility ----------

def r3(x: float) -> float:
    return round(x, 3)


def norm_price(p: float) -> float:
    return round(p, 2)


def get_or_create_placeholder(asset_id: str) -> str:
    global placeholder_counter
    if asset_id in asset_placeholders:
        return asset_placeholders[asset_id]
    placeholder = f"A{placeholder_counter}"
    placeholder_counter += 1
    asset_placeholders[asset_id] = placeholder
    base_label = asset_labels.get(asset_id, "").strip()
    short_id = asset_id[:10] + "..." if len(asset_id) > 13 else asset_id
    if base_label:
        display = f"{base_label} ({short_id})"
    else:
        display = short_id
    print(f"[ASSET MAP] {placeholder} -> {display}")
    return placeholder

def init_csv_writers() -> None:
    global trades_writer

    # Trades: single combined CSV
    trades_f = open(TRADES_CSV_PATH, "w", newline="", encoding="utf-8")
    trades_writer_local = csv.DictWriter(trades_f, fieldnames=TRADES_FIELDNAMES)
    trades_writer_local.writeheader()
    trades_writer = trades_writer_local

    init_csv_writers.trades_f_handle = trades_f 


def close_csv_writers() -> None:
    # Close all per-asset book files
    for f in book_files.values():
        f.close()
    book_files.clear()
    book_writers.clear()

    # Close trades file
    trades_f_handle = getattr(init_csv_writers, "trades_f_handle", None)
    if trades_f_handle is not None:
        trades_f_handle.close()


def fetch_market_metadata_for_event_slug(slug: str) -> MarketMetadata:
    url = GAMMA_EVENT_URL_TEMPLATE.format(slug=slug)
    resp = requests.get(url, timeout=10.0)
    resp.raise_for_status()
    data_obj = resp.json()

    if not isinstance(data_obj, dict):
        raise RuntimeError("Gamma event response is not a dict")

    data: GammaEvent = data_obj  # type: ignore[assignment]

    event_id_val = data.get("id")
    if not isinstance(event_id_val, str):
        raise RuntimeError("Gamma event 'id' missing or not string")

    markets_obj = data.get("markets")
    if not isinstance(markets_obj, list):
        raise RuntimeError("Gamma event 'markets' missing or not list")

    asset_ids: List[str] = []
    condition_ids: Dict[str, str] = {}

    for m_obj in markets_obj:
        if not isinstance(m_obj, dict):
            continue
        m: GammaMarket = m_obj

        cond = m.get("conditionId")
        clob_raw = m.get("clobTokenIds")
        if not isinstance(cond, str) or not isinstance(clob_raw, str):
            continue

        try:
            token_list = json.loads(clob_raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(token_list, list):
            continue

        title_val = (
            str(m.get("question"))
            if m.get("question") is not None
            else str(m.get("title") or m.get("slug") or "")
        ).strip()

        outcomes_raw = m.get("outcomes") or m.get("shortOutcomes") or m.get("outcomeNames")
        outcomes: List[str] = []
        if isinstance(outcomes_raw, list):
            outcomes = [str(o) for o in outcomes_raw]
        elif isinstance(outcomes_raw, str):
            try:
                parsed = json.loads(outcomes_raw)
                if isinstance(parsed, list):
                    outcomes = [str(o) for o in parsed]
            except json.JSONDecodeError:
                pass

        for idx, token in enumerate(token_list):
            token_str = str(token)
            asset_ids.append(token_str)
            condition_ids[token_str] = cond

            # Build label: "Title - Outcome" if both known, else just title
            outcome_part = outcomes[idx] if idx < len(outcomes) else ""
            if title_val and outcome_part:
                label = f"{title_val} - {outcome_part}"
            elif title_val:
                label = title_val
            else:
                label = ""

            if label:
                asset_labels.setdefault(token_str, label)

    if not asset_ids:
        raise RuntimeError("No asset_ids found for event")

    return MarketMetadata(
        event_id=event_id_val,
        event_slug=slug,
        asset_ids=asset_ids,
        condition_ids=condition_ids,
    )



def top_levels_for_asset(asset_id: str) -> Tuple[List[Level], List[Level]]:
    with orderbook_lock:
        state = orderbooks.get(asset_id)
        if state is None:
            return [], []

        bid_items = sorted(state.bids.items(), key=lambda kv: kv[0], reverse=True)
        ask_items = sorted(state.asks.items(), key=lambda kv: kv[0], reverse=False)

    bids = [Level(price=price, size=size) for price, size in bid_items[:3]]
    asks = [Level(price=price, size=size) for price, size in ask_items[:3]]
    return bids, asks


def get_book_writer_for_placeholder(placeholder: str) -> csv.DictWriter:
    if placeholder in book_writers:
        return book_writers[placeholder]

    filename = BOOK_FILE_TEMPLATE.format(placeholder=placeholder)
    f = open(filename, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=BOOK_FIELDNAMES)
    writer.writeheader()

    book_files[placeholder] = f
    book_writers[placeholder] = writer
    return writer


def log_book_snapshot(asset_id: str, reason: str) -> None:
    now = time.time()
    t_rel = r3(now - start_ts)

    bids, asks = top_levels_for_asset(asset_id)
    if not bids and not asks:
        return

    best_bid_price: Optional[float] = bids[0].price if bids else None
    best_ask_price: Optional[float] = asks[0].price if asks else None

    spread: Optional[float] = None
    if best_bid_price is not None and best_ask_price is not None:
        spread_raw = best_ask_price - best_bid_price
        spread = r3(spread_raw)

    def lvl(levels: List[Level], idx: int) -> Tuple[float, float]:
        if 0 <= idx < len(levels):
            return levels[idx].price, levels[idx].size
        return 0.0, 0.0

    b1p, b1s = lvl(bids, 0)
    b2p, b2s = lvl(bids, 1)
    b3p, b3s = lvl(bids, 2)
    a1p, a1s = lvl(asks, 0)
    a2p, a2s = lvl(asks, 1)
    a3p, a3s = lvl(asks, 2)

    placeholder = get_or_create_placeholder(asset_id)
    writer = get_book_writer_for_placeholder(placeholder)

    row = {
        "t_rel_s": t_rel,
        "asset": placeholder,
        "spread": spread if spread is not None else "",
        "bid1_price": b1p,
        "bid1_size": b1s,
        "bid2_price": b2p,
        "bid2_size": b2s,
        "bid3_price": b3p,
        "bid3_size": b3s,
        "ask1_price": a1p,
        "ask1_size": a1s,
        "ask2_price": a2p,
        "ask2_size": a2s,
        "ask3_price": a3p,
        "ask3_size": a3s,
        "reason": reason,
    }

    with book_file_lock:
        writer.writerow(row)
        book_files[placeholder].flush()


def log_trade(trade: TradeActivity) -> None:
    global trades_writer
    writer = trades_writer
    if writer is None:
        return

    now = time.time()
    t_rel = r3(now - start_ts)

    remote_ts_ms = trade["timestamp"]
    side = trade.get("side", "")
    price_val = trade.get("price")
    size_val = trade.get("size")
    usdc_val = trade.get("usdcSize")
    asset_id = trade.get("asset", "")
    condition_id = trade.get("conditionId", "")
    outcome = trade.get("outcome", "")
    title = trade.get("title", "")
    event_slug = trade.get("eventSlug", "")
    txh = trade.get("transactionHash", "")

    price = r3(price_val) if price_val is not None else None
    size = r3(size_val) if size_val is not None else None
    usdc = r3(usdc_val) if usdc_val is not None else None

    raw_asset_id = asset_id if isinstance(asset_id, str) else ""
    placeholder = get_or_create_placeholder(raw_asset_id) if raw_asset_id else ""

    bids, asks = top_levels_for_asset(raw_asset_id) if raw_asset_id else ([], [])

    best_bid_price: Optional[float] = bids[0].price if bids else None
    best_ask_price: Optional[float] = asks[0].price if asks else None

    spread: Optional[float] = None
    if best_bid_price is not None and best_ask_price is not None:
        spread_raw = best_ask_price - best_bid_price
        spread = r3(spread_raw)

    row = {
        "t_rel_s": t_rel,
        "local_ts": r3(now),
        "remote_ts_ms": remote_ts_ms,
        "side": side,
        "price": price if price is not None else "",
        "size": size if size is not None else "",
        "usdc": usdc if usdc is not None else "",
        "asset": placeholder,
        "conditionId": condition_id,
        "outcome": outcome,
        "title": title,
        "eventSlug": event_slug,
        "tx": txh,
        "spread": spread if spread is not None else "",
    }

    with trades_file_lock:
        writer.writerow(row)
        trades_f = getattr(init_csv_writers, "trades_f_handle", None)
        if trades_f is not None:
            trades_f.flush()


# ---------- Trades (REST) ----------

def fetch_giayn_trades() -> List[TradeActivity]:
    params: Dict[str, str] = {
        "user": GIAYN_ADDRESS,
        "type": "TRADE",
        "limit": str(LIMIT),
        "offset": "0",
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC",
    }
    resp = requests.get(DATA_API_ACTIVITY, params=params, timeout=10.0)
    resp.raise_for_status()
    data_obj = resp.json()

    raw_list: List[Dict[str, object]] = []

    if isinstance(data_obj, list):
        for item in data_obj:
            if isinstance(item, dict):
                raw_list.append(item)
    elif isinstance(data_obj, dict):
        maybe = data_obj.get("results") or data_obj.get("data") or []
        if isinstance(maybe, list):
            for item in maybe:
                if isinstance(item, dict):
                    raw_list.append(item)

    trades: List[TradeActivity] = []

    for obj in raw_list:
        t_type = obj.get("type")
        if t_type != "TRADE":
            continue

        slug_val = obj.get("eventSlug")
        if EVENT_SLUG and slug_val != EVENT_SLUG:
            continue

        ts_val = obj.get("timestamp")
        txh_val = obj.get("transactionHash")

        if not isinstance(ts_val, int):
            continue
        if not isinstance(txh_val, str):
            continue

        trade: TradeActivity = {
            "type": "TRADE",
            "timestamp": ts_val,
            "transactionHash": txh_val,
        }

        asset_val = obj.get("asset")
        if isinstance(asset_val, str):
            trade["asset"] = asset_val
        side_val = obj.get("side")
        if isinstance(side_val, str):
            trade["side"] = side_val
        price_val = obj.get("price")
        if isinstance(price_val, (int, float)):
            trade["price"] = float(price_val)
        size_val = obj.get("size")
        if isinstance(size_val, (int, float)):
            trade["size"] = float(size_val)
        usdc_val = obj.get("usdcSize")
        if isinstance(usdc_val, (int, float)):
            trade["usdcSize"] = float(usdc_val)
        cond_val = obj.get("conditionId")
        if isinstance(cond_val, str):
            trade["conditionId"] = cond_val
        outcome_val = obj.get("outcome")
        if isinstance(outcome_val, str):
            trade["outcome"] = outcome_val
        title_val = obj.get("title")
        if isinstance(title_val, str):
            trade["title"] = title_val
        slug_val2 = obj.get("eventSlug")
        if isinstance(slug_val2, str):
            trade["eventSlug"] = slug_val2

        trades.append(trade)

    trades_sorted = sorted(trades, key=lambda t: t["timestamp"])
    return trades_sorted


def bootstrap_seen_trades() -> None:
    events = fetch_giayn_trades()
    count = 0
    for t in events:
        txh = t["transactionHash"]
        if txh not in seen_hashes:
            seen_hashes.add(txh)
            count += 1
    print(f"[BOOTSTRAP] Marked {count} existing trades as seen (not logged).")


def trades_loop() -> None:
    bootstrap_seen_trades()

    while True:
        try:
            events = fetch_giayn_trades()
            new_count = 0
            for t in events:
                txh = t["transactionHash"]
                if txh in seen_hashes:
                    continue
                seen_hashes.add(txh)

                asset = t.get("asset")
                if isinstance(asset, str) and asset:
                    title_val = t.get("title") or ""
                    outcome_val = t.get("outcome") or ""
                    label = f"{title_val} - {outcome_val}".strip(" -")
                    if label:
                        asset_labels.setdefault(asset, label)

                log_trade(t)
                new_count += 1
            if new_count:
                print(f"[TRADES] Logged {new_count} new trades.")
        except Exception as exc:
            print("[TRADES ERROR]", exc)
            time.sleep(1.0)

        time.sleep(POLL_SECONDS)


# ---------- WebSocket handling ----------

def ping_loop(ws: WebSocketApp) -> None:
    while True:
        try:
            ws.send("PING")
        except Exception as exc:
            msg = str(exc).lower()
            if "closed" not in msg:
                print("[WS PING ERROR]", exc)
            break
        time.sleep(10.0)


def handle_book_event(event: Dict[str, object], metadata: MarketMetadata) -> None:
    asset_obj = event.get("asset_id")
    if not isinstance(asset_obj, str):
        return
    asset_id = asset_obj
    if asset_id not in metadata.asset_ids:
        return

    bids_obj = event.get("bids")
    asks_obj = event.get("asks")

    bids_list: List[Dict[str, object]] = []
    asks_list: List[Dict[str, object]] = []

    if isinstance(bids_obj, list):
        for b in bids_obj:
            if isinstance(b, dict):
                bids_list.append(b)
    if isinstance(asks_obj, list):
        for a in asks_obj:
            if isinstance(a, dict):
                asks_list.append(a)

    bid_map: Dict[float, float] = {}
    ask_map: Dict[float, float] = {}

    for b in bids_list:
        price_obj = b.get("price")
        size_obj = b.get("size")

        if not isinstance(price_obj, (int, float, str)):
            continue
        if not isinstance(size_obj, (int, float, str)):
            continue

        try:
            price = norm_price(float(price_obj))
            size = float(size_obj)
        except (TypeError, ValueError):
            continue

        if size <= 0.0:
            continue
        bid_map[price] = bid_map.get(price, 0.0) + size

    for a in asks_list:
        price_obj = a.get("price")
        size_obj = a.get("size")

        if not isinstance(price_obj, (int, float, str)):
            continue
        if not isinstance(size_obj, (int, float, str)):
            continue

        try:
            price = norm_price(float(price_obj))
            size = float(size_obj)
        except (TypeError, ValueError):
            continue

        if size <= 0.0:
            continue
        ask_map[price] = ask_map.get(price, 0.0) + size

    with orderbook_lock:
        orderbooks[asset_id] = BookState(bids=bid_map, asks=ask_map)

    log_book_snapshot(asset_id, reason="book")


def handle_price_change_event(event: Dict[str, object], metadata: MarketMetadata) -> None:
    pcs_obj = event.get("price_changes")
    if not isinstance(pcs_obj, list):
        return

    for pc in pcs_obj:
        if not isinstance(pc, dict):
            continue

        asset_obj = pc.get("asset_id")
        if not isinstance(asset_obj, str):
            continue
        asset_id = asset_obj
        if asset_id not in metadata.asset_ids:
            continue

        side_obj = pc.get("side")
        if side_obj not in ("BUY", "SELL"):
            continue

        price_obj = pc.get("price")
        size_obj = pc.get("size")

        if not isinstance(price_obj, (int, float, str)):
            continue
        if not isinstance(size_obj, (int, float, str)):
            continue

        try:
            price = norm_price(float(price_obj))
            size = float(size_obj)
        except (TypeError, ValueError):
            continue

        with orderbook_lock:
            state = orderbooks.get(asset_id)
            if state is None:
                state = BookState(bids={}, asks={})
                orderbooks[asset_id] = state

            side_dict = state.bids if side_obj == "BUY" else state.asks

            if size <= 0.0:
                if price in side_dict:
                    side_dict.pop(price)
            else:
                side_dict[price] = size

        log_book_snapshot(asset_id, reason="price_change")


def process_ws_event(event: Dict[str, object], metadata: MarketMetadata) -> None:
    etype_obj = event.get("event_type")
    if not isinstance(etype_obj, str):
        return
    if etype_obj == "book":
        handle_book_event(event, metadata)
    elif etype_obj == "price_change":
        handle_price_change_event(event, metadata)


def ws_loop(metadata: MarketMetadata) -> None:
    def on_open(ws: WebSocketApp) -> None:
        print("[WS] Connected.")
        sub_msg = {"assets_ids": metadata.asset_ids, "type": "market"}
        try:
            ws.send(json.dumps(sub_msg))
            print("[WS] Subscribed with assets_ids:", metadata.asset_ids)
        except Exception as exc:
            print("[WS SUBSCRIBE ERROR]", exc)
        t = threading.Thread(target=ping_loop, args=(ws,), daemon=True)
        t.start()

    def on_message(ws: WebSocketApp, message: str) -> None:
        try:
            data_obj = json.loads(message)
        except json.JSONDecodeError:
            if message != "PONG":
                print("[WS] Non-JSON message:", message)
            return

        if isinstance(data_obj, list):
            for ev in data_obj:
                if isinstance(ev, dict):
                    process_ws_event(ev, metadata)
        elif isinstance(data_obj, dict):
            process_ws_event(data_obj, metadata)

    def on_error(ws: WebSocketApp, error: object) -> None:
        print("[WS ERROR]", error)

    def on_close(ws: WebSocketApp, close_status_code: int, close_msg: str) -> None:
        print("[WS CLOSED]", close_status_code, close_msg)

    while True:
        print("[WS] Connecting to:", WSS_URL)
        ws = WebSocketApp(
            WSS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        ws.run_forever()
        print("[WS] Disconnected, retrying in 2s...")
        time.sleep(2.0)


# ---------- Main ----------

def main() -> None:
    global start_ts

    start_ts = time.time()

    print("=== GIAYN trades + book logger (CSV) ===")
    print("User:", GIAYN_ADDRESS)
    print("Event slug:", EVENT_SLUG)

    metadata = fetch_market_metadata_for_event_slug(EVENT_SLUG)
    print("Event ID:", metadata.event_id)
    print("Assets:", metadata.asset_ids)

    init_csv_writers()

    ws_thread = threading.Thread(target=ws_loop, args=(metadata,), daemon=True)
    ws_thread.start()

    try:
        trades_loop()
    finally:
        close_csv_writers()


if __name__ == "__main__":
    main()
