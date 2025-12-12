# trades_logger.py
import json
import time
from typing import Any, Dict, List, Optional

import requests

DATA_API_TRADES = "https://data-api.polymarket.com/trades"

# 0x wallet of the user you want to track
USER_ADDRESS = "0x507e52ef684ca2dd91f90a9d26d149dd3288beae"

# Optional: filter to specific conditionIds; leave empty to track all
MARKETS: List[str] = [
    # "0xconditionId1",
    # "0xconditionId2",
]

OUTFILE = "giayn_trades.jsonl"
POLL_SECONDS = 0.5
LIMIT = 500

seen_hashes: set[str] = set()
last_ts_ms: Optional[int] = None  # ms since epoch of latest trade we've seen


def fetch_trades() -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "user": USER_ADDRESS,
        "limit": LIMIT,
    }
    if MARKETS:
        params["market"] = ",".join(MARKETS)

    r = requests.get(DATA_API_TRADES, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected /trades response type: {type(data)}")
    return data


def bootstrap_from_now() -> None:
    global last_ts_ms
    print("[BOOTSTRAP] Fetching current trades to set starting point...")
    try:
        trades = fetch_trades()
    except Exception as e:
        print("[BOOTSTRAP ERROR]", e)
        # if bootstrap fails, we just start with last_ts_ms=None and log everything
        return

    if not trades:
        print("[BOOTSTRAP] No trades returned; starting from empty history.")
        return

    max_ts = None
    for t in trades:
        ts = t.get("timestamp")
        tx = t.get("transactionHash")
        if isinstance(ts, int):
            if max_ts is None or ts > max_ts:
                max_ts = ts
        if isinstance(tx, str):
            seen_hashes.add(tx)

    last_ts_ms = max_ts
    print(f"[BOOTSTRAP] Starting from timestamp={last_ts_ms} (ms). Past trades ignored.")


def log_new_trades(trades: List[Dict[str, Any]]) -> None:
    global last_ts_ms

    if not trades:
        return

    trades_sorted = sorted(trades, key=lambda t: t.get("timestamp", 0))
    new_records: List[Dict[str, Any]] = []

    for t in trades_sorted:
        tx = t.get("transactionHash")
        ts = t.get("timestamp")  # ms since epoch
        if not isinstance(tx, str):
            continue
        if tx in seen_hashes:
            continue

        # Only log trades AFTER our starting point
        if isinstance(ts, int) and last_ts_ms is not None and ts <= last_ts_ms:
            # older or equal to last seen timestamp; skip
            continue

        seen_hashes.add(tx)
        if isinstance(ts, int):
            if last_ts_ms is None or ts > last_ts_ms:
                last_ts_ms = ts

        price = t.get("price")
        size = t.get("size")

        rec = {
            "ts_ms": ts,
            "ts": (ts / 1000.0) if isinstance(ts, (int, float)) else None,
            "side": t.get("side"),
            "price": round(float(price), 3) if price is not None else None,
            "size": round(float(size), 3) if size is not None else None,
            "asset": t.get("asset"),
            "conditionId": t.get("conditionId"),
            "outcome": t.get("outcome"),
            "title": t.get("title"),
            "eventSlug": t.get("eventSlug"),
            "tx": tx,
        }
        new_records.append(rec)

    if not new_records:
        return

    with open(OUTFILE, "a", encoding="utf-8") as f:
        for rec in new_records:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")

    print(f"[LOG] {len(new_records)} new trades. last_ts_ms={last_ts_ms}")


def main() -> None:
    if not USER_ADDRESS.startswith("0x") or len(USER_ADDRESS) != 42:
        print("Set USER_ADDRESS to the 0x wallet you want to track.")
        return

    print("=== trades_logger ===")
    print("User:", USER_ADDRESS)
    if MARKETS:
        print("Markets filter:", MARKETS)
    print("Output file:", OUTFILE)
    print("Poll interval:", POLL_SECONDS, "seconds")

    # Start from "now": ignore any past trades the API returns on first fetch
    bootstrap_from_now()

    while True:
        try:
            trades = fetch_trades()
            log_new_trades(trades)
        except requests.HTTPError as he:
            print("[HTTP ERROR]", he)
            # if it's a 5xx, just back off a bit and retry
            resp = getattr(he, "response", None)
            code = getattr(resp, "status_code", None)
            if isinstance(code, int) and 500 <= code < 600:
                time.sleep(2.0)
            else:
                time.sleep(1.0)
        except Exception as e:
            print("[ERROR]", e)
            time.sleep(1.0)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
