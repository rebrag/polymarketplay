from __future__ import annotations

import sys
import csv
import json
import time
import re
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple, cast

# --- PATH FIX ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# --- IMPORTS FROM SRC ---
from src.config import GIAYN_ADDRESS,REST_URL,GAMMA_URL,OUTPUT_ROOT,TRADES_CSV_PATH
from src.models import TradeActivity,GammaEvent,WsBookMessage,WsPriceChangeMessage
from src.clients import PolyClient, PolySocket
from src.book import OrderBook

# --- CONSTANTS ---
POLL_SECONDS = 2.0
LIMIT = 500
BOOK_FILENAME = "giayn_book_{placeholder}.csv"

BOOK_FIELDNAMES = [
    "t_rel_s", "spread", 
    "bid1_price", "bid2_price", "bid3_price", 
    "ask1_price", "ask2_price", "ask3_price", 
    "bid1_size", "bid2_size", "bid3_size", 
    "ask1_size", "ask2_size", "ask3_size", 
    "reason"
]

TRADES_FIELDNAMES = [
    "t_rel_s", "local_ts", "remote_ts_ms", "side", "price", "size", 
    "usdc", "asset", "conditionId", "outcome", "title", "eventSlug", 
    "tx", "spread"
]

# --- STATE ---
start_ts: float = time.time()
seen_hashes: Set[str] = set()
active_events: Dict[str, 'TrackedEvent'] = {}
asset_map: Dict[str, str] = {}
placeholder_count: int = 0

# --- UTILS ---
def r3(x: float | None) -> float | str:
    return round(x, 3) if isinstance(x, (float, int)) else ""

def get_placeholder(asset_id: str) -> str:
    global placeholder_count
    if asset_id not in asset_map:
        asset_map[asset_id] = f"A{placeholder_count}"
        placeholder_count += 1
    return asset_map[asset_id]

# --- CLASS: EVENT MANAGER ---
class TrackedEvent:
    def __init__(self, slug: str, assets: List[str]):
        self.slug = slug
        self.assets = assets
        self.books: Dict[str, OrderBook] = {}
        self.writers: Dict[str, Any] = {}
        self.files: Dict[str, Any] = {}
        
        safe_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", slug)
        event_dir = OUTPUT_ROOT / safe_slug
        event_dir.mkdir(parents=True, exist_ok=True)

        for asset_id in assets:
            # 1. Init Logic
            book = OrderBook(asset_id)
            self.books[asset_id] = book
            
            # 2. Init Logging
            ph = get_placeholder(asset_id)
            path = event_dir / BOOK_FILENAME.format(placeholder=ph)
            f = open(path, "w", newline="", encoding="utf-8")
            w = csv.DictWriter(f, fieldnames=BOOK_FIELDNAMES)
            w.writeheader()
            
            self.files[asset_id] = f
            self.writers[asset_id] = w

        # 3. Init Socket
        self.socket = PolySocket(asset_ids=assets)
        self.socket.on_book = self.on_book
        self.socket.on_price_change = self.on_price_change
        self.socket.start()
        print(f"✅ Started tracking event: {slug} ({len(assets)} assets)")

    def log_snapshot(self, asset_id: str, reason: str) -> None:
        book = self.books.get(asset_id)
        writer = self.writers.get(asset_id)
        if not book or not writer: return

        bids, asks = book.get_snapshot(limit=3)
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        
        spread = r3(best_ask - best_bid) if (best_bid is not None and best_ask is not None) else ""
        
        # Strictly typed helper
        def get_lvl(lst: List[Tuple[float, float]], idx: int) -> Tuple[float, float]: 
            return (lst[idx][0], lst[idx][1]) if idx < len(lst) else (0.0, 0.0)

        b1p, b1s = get_lvl(bids, 0)
        b2p, b2s = get_lvl(bids, 1)
        b3p, b3s = get_lvl(bids, 2)
        
        a1p, a1s = get_lvl(asks, 0)
        a2p, a2s = get_lvl(asks, 1)
        a3p, a3s = get_lvl(asks, 2)

        row: Dict[str, Any] = {
            "t_rel_s": r3(time.time() - start_ts),
            "spread": spread,
            "bid1_price": b1p, "bid1_size": b1s,
            "bid2_price": b2p, "bid2_size": b2s,
            "bid3_price": b3p, "bid3_size": b3s,
            "ask1_price": a1p, "ask1_size": a1s,
            "ask2_price": a2p, "ask2_size": a2s,
            "ask3_price": a3p, "ask3_size": a3s,
            "reason": reason
        }
        writer.writerow(row)
        self.files[asset_id].flush()

    def on_book(self, msg: WsBookMessage) -> None:
        aid = msg.get("asset_id", "")
        if aid in self.books:
            self.books[aid].on_book_snapshot(msg)
            self.log_snapshot(aid, "book")

    def on_price_change(self, msg: WsPriceChangeMessage) -> None:
        changes = msg.get("price_changes", [])
        touched_assets: Set[str] = set()
        
        for ch in changes:
            aid = ch.get("asset_id", "")
            if aid in self.books:
                self.books[aid].on_price_change(msg)
                touched_assets.add(aid)
        
        for aid in touched_assets:
            self.log_snapshot(aid, "price_change")

    def stop(self) -> None:
        self.socket.stop()
        for f in self.files.values():
            f.close()

# --- MAIN LOGIC ---

def get_event_assets(client: PolyClient, slug: str) -> List[str]:
    try:
        url = f"{GAMMA_URL}?slug={slug}" 
        resp = client.session.get(url)
        resp.raise_for_status()
        data = resp.json()
        
        if not data or not isinstance(data, list): return []
        
        event = cast(GammaEvent, data[0])
        assets: List[str] = []
        
        for m in event.get("markets", []):
            token_str = m.get("clobTokenIds", "[]")
            try:
                tokens_any = json.loads(token_str)
                if isinstance(tokens_any, list):
                    # FIX: Strict cast to List[Any] to ensure 't' is recognized
                    tokens_list = cast(List[Any], tokens_any)
                    assets.extend([str(t) for t in tokens_list])
            except json.JSONDecodeError: 
                pass
            
        return assets
    except Exception as e:
        print(f"❌ Meta Error {slug}: {e}")
        return []

def trade_logger_loop() -> None:
    client = PolyClient()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    f_trades = open(TRADES_CSV_PATH, "w", newline="", encoding="utf-8")
    w_trades = csv.DictWriter(f_trades, fieldnames=TRADES_FIELDNAMES)
    w_trades.writeheader()

    print("📡 Waiting for trades...")

    while True:
        try:
            params = {
                "user": GIAYN_ADDRESS,
                "type": "TRADE",
                "limit": "50",
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC"
            }
            resp = client.session.get(REST_URL, params=params)
            trades_raw = resp.json()
            trades: List[TradeActivity] = cast(List[TradeActivity], trades_raw)

            new_count = 0
            sorted_trades = sorted(trades, key=lambda x: x.get("timestamp", 0))
            
            for t in sorted_trades:
                tx = t.get("transactionHash", "")
                if tx in seen_hashes: continue
                seen_hashes.add(tx)
                
                slug = t.get("eventSlug", "")
                asset = t.get("asset", "")
                
                row: Dict[str, Any] = {
                    "t_rel_s": r3(time.time() - start_ts),
                    "local_ts": r3(time.time()),
                    "remote_ts_ms": t.get("timestamp"),
                    "side": t.get("side"),
                    "price": t.get("price"),
                    "size": t.get("size"),
                    "usdc": t.get("usdcSize"),
                    "asset": get_placeholder(asset) if asset else "",
                    "conditionId": t.get("conditionId"),
                    "outcome": t.get("outcome"),
                    "title": t.get("title"),
                    "eventSlug": slug,
                    "tx": tx,
                    "spread": "" 
                }
                w_trades.writerow(row)
                f_trades.flush()
                new_count += 1

                if slug and slug not in active_events:
                    print(f"🆕 New Event Detected: {slug}")
                    assets = get_event_assets(client, slug)
                    if assets:
                        tracker = TrackedEvent(slug, assets)
                        active_events[slug] = tracker
                    else:
                        print(f"⚠️ No assets found for {slug}")

            if new_count > 0:
                print(f"📝 Logged {new_count} trades.")

        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(POLL_SECONDS)

def main() -> None:
    try:
        trade_logger_loop()
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
        for t in active_events.values():
            t.stop()

if __name__ == "__main__":
    main()