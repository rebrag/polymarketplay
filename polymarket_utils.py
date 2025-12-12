# polymarket_utils.py
import json
import time
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from typing import Dict, Any
import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


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

def get_assets_from_event(poly_url: str) -> Dict[str, str]:
    slug = get_slug(poly_url)
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


def safe_filename(label: str) -> str:
    cleaned = "".join(
        c if c.isalnum() or c in (" ", "-", "_") else "_"
        for c in label
    ).strip()
    return f"{cleaned}.jsonl" if cleaned else "asset.jsonl"


def r3(x: Optional[float]) -> Optional[float]:
    return round(float(x), 3) if x is not None else None


def log_quote_to_file(
    fname: str,
    bid: Optional[float],
    ask: Optional[float],
    mid: Optional[float],
    bid_size: Optional[float],
    ask_size: Optional[float],
) -> None:
    rec = {
        "ts": time.time(),
        "bid": r3(bid),
        "ask": r3(ask),
        "mid": r3(mid),
        "spread": r3(ask - bid) if bid is not None and ask is not None else None,
        "bid_size": r3(bid_size),
        "ask_size": r3(ask_size),
    }
    with open(fname, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")

def get_tokens_for_main_market(url: str) -> Dict[str, str]:
    slug = get_slug(url)
    event = get_event(slug)
    main = pick_main_market(event)

    question = main.get("question") or "Unknown Event"
    cond = main.get("conditionId") or main.get("condition_id")
    if not isinstance(cond, str):
        raise RuntimeError(f"Main market missing conditionId: {cond}")

    r = requests.get(f"{CLOB_BASE}/markets/{cond}", timeout=10)
    r.raise_for_status()
    market = r.json()
    tokens = market.get("tokens") or []
    if not tokens:
        raise RuntimeError("No tokens in CLOB market response")

    out: Dict[str, str] = {}
    for t in tokens:
        token_id = t.get("token_id")
        outcome = t.get("outcome") or "?"
        if isinstance(token_id, str):
            out[token_id] = f"{question} - {outcome}"
    if not out:
        raise RuntimeError("No valid token_ids found")
    return out
