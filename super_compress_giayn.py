# super_compress_giayn.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, TypedDict, Union

INPUT_FILE = "giayn_trades_and_books.jsonl"
OUTPUT_FILE = "giayn_supercompact.csv"

NumberLike = Union[int, float, str]


def _to_float(value: object) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def r3(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    return round(x, 3)


def to_str(x: object) -> str:
    if x is None:
        return ""
    if isinstance(x, (int, float)):
        rounded = r3(float(x))
        return "" if rounded is None else str(rounded)
    return str(x)


@dataclass
class DepthSnapshot:
    bb: Optional[float]
    bb_sz: Optional[float]
    ba: Optional[float]
    ba_sz: Optional[float]
    spread: Optional[float]
    b1p: Optional[float]
    b1s: Optional[float]
    b2p: Optional[float]
    b2s: Optional[float]
    b3p: Optional[float]
    b3s: Optional[float]
    a1p: Optional[float]
    a1s: Optional[float]
    a2p: Optional[float]
    a2s: Optional[float]
    a3p: Optional[float]
    a3s: Optional[float]


class CompactEvent(TypedDict):
    k: str
    t_abs: float
    a: str
    s: Optional[str]
    px: Optional[float]
    sz: Optional[float]
    usd: Optional[float]
    bb: Optional[float]
    bbSz: Optional[float]
    ba: Optional[float]
    baSz: Optional[float]
    spread: Optional[float]
    b1p: Optional[float]
    b1s: Optional[float]
    b2p: Optional[float]
    b2s: Optional[float]
    b3p: Optional[float]
    b3s: Optional[float]
    a1p: Optional[float]
    a1s: Optional[float]
    a2p: Optional[float]
    a2s: Optional[float]
    a3p: Optional[float]
    a3s: Optional[float]
    eAsk: Optional[float]
    eBid: Optional[float]
    cid: Optional[str]
    slug: Optional[str]


def _extract_level(levels: List[dict], index: int) -> DepthSnapshot | None:
    # This helper isn't actually needed; we inline handling in _top3_from_book.
    return None


def _top3_from_book(book: Dict[str, object]) -> DepthSnapshot:
    bids_obj = book.get("bids")
    asks_obj = book.get("asks")

    bids: List[Dict[str, object]] = bids_obj if isinstance(bids_obj, list) else []
    asks: List[Dict[str, object]] = asks_obj if isinstance(asks_obj, list) else []

    def get_level(levels: List[Dict[str, object]], idx: int) -> tuple[Optional[float], Optional[float]]:
        if 0 <= idx < len(levels):
            lvl = levels[idx]
            raw_p = lvl.get("price")
            raw_s = lvl.get("size")
            p = _to_float(raw_p)
            s = _to_float(raw_s)
            return p, s
        return None, None

    b1p, b1s = get_level(bids, 0)
    b2p, b2s = get_level(bids, 1)
    b3p, b3s = get_level(bids, 2)
    a1p, a1s = get_level(asks, 0)
    a2p, a2s = get_level(asks, 1)
    a3p, a3s = get_level(asks, 2)

    best_bid_obj = book.get("best_bid")
    best_ask_obj = book.get("best_ask")

    bb_price: Optional[float] = None
    bb_size: Optional[float] = None
    ba_price: Optional[float] = None
    ba_size: Optional[float] = None

    if isinstance(best_bid_obj, dict):
        bb_price = _to_float(best_bid_obj.get("price"))
        bb_size = _to_float(best_bid_obj.get("size"))

    if isinstance(best_ask_obj, dict):
        ba_price = _to_float(best_ask_obj.get("price"))
        ba_size = _to_float(best_ask_obj.get("size"))

    spread: Optional[float] = None
    if bb_price is not None and ba_price is not None:
        spread = ba_price - bb_price

    return DepthSnapshot(
        bb=bb_price,
        bb_sz=bb_size,
        ba=ba_price,
        ba_sz=ba_size,
        spread=spread,
        b1p=b1p,
        b1s=b1s,
        b2p=b2p,
        b2s=b2s,
        b3p=b3p,
        b3s=b3s,
        a1p=a1p,
        a1s=a1s,
        a2p=a2p,
        a2s=a2s,
        a3p=a3p,
        a3s=a3s,
    )


def main() -> None:
    events: List[CompactEvent] = []
    last_book_by_asset: Dict[str, Dict[str, object]] = {}

    # 1) Read JSONL and build events
    with open(INPUT_FILE, "r", encoding="utf-8") as fin:
        for raw_line in fin:
            line = raw_line.strip()
            if not line:
                continue

            try:
                rec_obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(rec_obj, dict):
                continue

            rtype_obj = rec_obj.get("type")
            if not isinstance(rtype_obj, str):
                continue
            rtype = rtype_obj

            # --- BOOK EVENTS ---
            if rtype == "book":
                asset_obj = rec_obj.get("asset")
                if not isinstance(asset_obj, str):
                    continue
                asset = asset_obj

                ts_obj = rec_obj.get("ts")
                t_abs = _to_float(ts_obj)
                if t_abs is None:
                    continue

                last_book_by_asset[asset] = rec_obj
                depth = _top3_from_book(rec_obj)

                ev: CompactEvent = {
                    "k": "b",
                    "t_abs": t_abs,
                    "a": asset,
                    "s": None,
                    "px": None,
                    "sz": None,
                    "usd": None,
                    "bb": depth.bb,
                    "bbSz": depth.bb_sz,
                    "ba": depth.ba,
                    "baSz": depth.ba_sz,
                    "spread": depth.spread,
                    "b1p": depth.b1p,
                    "b1s": depth.b1s,
                    "b2p": depth.b2p,
                    "b2s": depth.b2s,
                    "b3p": depth.b3p,
                    "b3s": depth.b3s,
                    "a1p": depth.a1p,
                    "a1s": depth.a1s,
                    "a2p": depth.a2p,
                    "a2s": depth.a2s,
                    "a3p": depth.a3p,
                    "a3s": depth.a3s,
                    "eAsk": None,
                    "eBid": None,
                    "cid": None,
                    "slug": None,
                }
                events.append(ev)
                continue

            # --- TRADE EVENTS ---
            if rtype == "trade":
                asset_obj = rec_obj.get("asset")
                if not isinstance(asset_obj, str):
                    continue
                asset = asset_obj

                ts_obj = rec_obj.get("ts")
                t_abs = _to_float(ts_obj)
                if t_abs is None:
                    continue

                side_obj = rec_obj.get("side")
                side: Optional[str] = side_obj if isinstance(side_obj, str) else None

                price = _to_float(rec_obj.get("price"))
                size = _to_float(rec_obj.get("size"))
                usdc = _to_float(rec_obj.get("usdc"))

                book = last_book_by_asset.get(asset)
                if book is not None:
                    depth = _top3_from_book(book)
                else:
                    depth = DepthSnapshot(
                        bb=None,
                        bb_sz=None,
                        ba=None,
                        ba_sz=None,
                        spread=None,
                        b1p=None,
                        b1s=None,
                        b2p=None,
                        b2s=None,
                        b3p=None,
                        b3s=None,
                        a1p=None,
                        a1s=None,
                        a2p=None,
                        a2s=None,
                        a3p=None,
                        a3s=None,
                    )

                eAsk: Optional[float] = None
                eBid: Optional[float] = None
                if price is not None:
                    if depth.ba is not None and side == "BUY":
                        eAsk = depth.ba - price
                    if depth.bb is not None and side == "SELL":
                        eBid = price - depth.bb

                cid_obj = rec_obj.get("conditionId")
                cid = cid_obj if isinstance(cid_obj, str) else None
                slug_obj = rec_obj.get("eventSlug")
                slug = slug_obj if isinstance(slug_obj, str) else None

                ev: CompactEvent = {
                    "k": "t",
                    "t_abs": t_abs,
                    "a": asset,
                    "s": side,
                    "px": price,
                    "sz": size,
                    "usd": usdc,
                    "bb": depth.bb,
                    "bbSz": depth.bb_sz,
                    "ba": depth.ba,
                    "baSz": depth.ba_sz,
                    "spread": depth.spread,
                    "b1p": depth.b1p,
                    "b1s": depth.b1s,
                    "b2p": depth.b2p,
                    "b2s": depth.b2s,
                    "b3p": depth.b3p,
                    "b3s": depth.b3s,
                    "a1p": depth.a1p,
                    "a1s": depth.a1s,
                    "a2p": depth.a2p,
                    "a2s": depth.a2s,
                    "a3p": depth.a3p,
                    "a3s": depth.a3s,
                    "eAsk": eAsk,
                    "eBid": eBid,
                    "cid": cid,
                    "slug": slug,
                }
                events.append(ev)
                continue

    if not events:
        print("No events found in input.")
        return

    # 2) Compute t0
    valid_times: List[float] = [
        ev["t_abs"] for ev in events if ev["t_abs"] > 1_000_000_000.0
    ]
    if not valid_times:
        valid_times = [ev["t_abs"] for ev in events if ev["t_abs"] > 0.0]

    if not valid_times:
        print("No valid (non-zero) time values found in input.")
        return

    t0 = min(valid_times)
    print(f"Loaded {len(events)} events from {INPUT_FILE}")
    print("t0 (first valid timestamp) =", t0)

    # 3) Asset map A0, A1, ...
    asset_map: Dict[str, str] = {}
    for ev in events:
        a_val = ev["a"]
        if a_val not in asset_map:
            asset_map[a_val] = f"A{len(asset_map)}"

    print("Found", len(asset_map), "distinct assets")

    # 4) Sort events by time
    events.sort(key=lambda ev: ev["t_abs"])

    # 5) Write CSV
    header = [
        "kind",
        "time_since_start_s",
        "asset_code",
        "side",
        "trade_price",
        "trade_size_shares",
        "trade_size_usd",
        "best_bid_price",
        "best_bid_size_shares",
        "best_ask_price",
        "best_ask_size_shares",
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
        "edge_vs_best_ask",
        "edge_vs_best_bid",
        "giayn_asset_code",
        "event_slug",
    ]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fout:
        fout.write(",".join(header) + "\n")

        for ev in events:
            dt = r3(ev["t_abs"] - t0)

            a_val = ev["a"]
            a_short = asset_map.get(a_val, "")

            row = [
                to_str(ev["k"]),
                to_str(dt),
                to_str(a_short),
                to_str(ev["s"]),
                to_str(ev["px"]),
                to_str(ev["sz"]),
                to_str(ev["usd"]),
                to_str(ev["bb"]),
                to_str(ev["bbSz"]),
                to_str(ev["ba"]),
                to_str(ev["baSz"]),
                to_str(ev["spread"]),
                to_str(ev["b1p"]),
                to_str(ev["b1s"]),
                to_str(ev["b2p"]),
                to_str(ev["b2s"]),
                to_str(ev["b3p"]),
                to_str(ev["b3s"]),
                to_str(ev["a1p"]),
                to_str(ev["a1s"]),
                to_str(ev["a2p"]),
                to_str(ev["a2s"]),
                to_str(ev["a3p"]),
                to_str(ev["a3s"]),
                to_str(ev["eAsk"]),
                to_str(ev["eBid"]),
                to_str(a_short),
                to_str(ev["slug"]),
            ]
            fout.write(",".join(row) + "\n")

    print("Wrote super-compact CSV to", OUTPUT_FILE)
    print("Asset mapping (paste into your LLM prompt if useful):")
    for full, short in asset_map.items():
        print(short, "=", full)


if __name__ == "__main__":
    main()
