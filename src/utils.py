import json
import requests
from typing import List, Any, Dict, cast, Optional
from urllib.parse import urlparse # <--- New Import
from src.config import GAMMA_URL
from src.models import GammaEvent, GammaMarket

def normalize_point(point: float | str | None) -> str:
    if point is None:
        return ""
    try:
        f_point = float(point)
        if f_point.is_integer():
            return str(int(f_point))
        return str(f_point)
    except (ValueError, TypeError):
        return str(point)

def get_fair_prob(*odds: float) -> List[float]:
    implied = [1 / o for o in odds if o > 1.0]
    if not implied:
        return [0.0] * len(odds)
    juice = sum(implied)
    return [i / juice for i in implied]

def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) # type: ignore
    except (ValueError, TypeError):
        return default

def get_game_data(user_input: str) -> Optional[GammaEvent]:
    user_input = user_input.strip()
    slug = user_input
    if "polymarket.com" in user_input:
        path = urlparse(user_input).path.rstrip('/')
        slug = path.split('/')[-1]
    print(f"🔎 Looking up slug: '{slug}'")
    resp = requests.get(GAMMA_URL, params={"slug": slug}, timeout=10.0)
    resp.raise_for_status()
    data = cast(List[Dict[str, Any]], resp.json())
    if not data:
        return None
        
    event = cast(GammaEvent, data[0])
    raw_markets = event["markets"]
    cleaned_markets: List[Dict[str, GammaEvent]] = []

    for m in raw_markets:
        clean_m = m.copy()
        clean_m["volumeNum"] = float(m["volume"]) if "volume" in m else 0.0
        out_raw = m["outcomes"]
        clob_raw = m["clobTokenIds"]
        
        clean_m["outcomes"] = json.loads(out_raw) if isinstance(out_raw, str) else out_raw
        clean_m["clobTokenIds"] = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw

        cleaned_markets.append(clean_m)

    event["markets"] = cleaned_markets
    return event

def filter_markets_by_asset(
    raw_markets: List[GammaMarket], 
    valid_assets: set[str], 
    min_volume: float
) -> List[GammaMarket]:
    """
    Returns a list of markets where only the specific 'valid_assets' 
    (tokens the user traded) are kept in 'clobTokenIds' and 'outcomes'.
    """
    filtered_output: List[GammaMarket] = []

    for m in raw_markets:
        # 1. Check Volume First
        vol = float(m.get("volumeNum", 0.0))
        if vol < min_volume:
            continue

        # 2. Identify which indices (0=Yes, 1=No) match the user's trades
        keep_indices = [
            i for i, token_id in enumerate(m["clobTokenIds"]) 
            if token_id in valid_assets
        ]

        if not keep_indices:
            continue

        # 3. Create a clean copy with ONLY those tokens
        clean_m = m.copy()
        
        # Filter lists using the indices we found
        clean_m["clobTokenIds"] = [m["clobTokenIds"][i] for i in keep_indices]
        clean_m["outcomes"] = [m["outcomes"][i] for i in keep_indices]

        filtered_output.append(clean_m)

    return filtered_output