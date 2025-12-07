#!/usr/bin/env python3

import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
PRICE_THRESHOLD = 0.98
SECONDS_TO_EXPIRY = 23 * 60 * 60  # 1 hour


def parse_iso8601(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None


def fetch_active_markets(limit: int = 500) -> List[Dict[str, Any]]:
    params = {
        "closed": "false",     # only open markets :contentReference[oaicite:3]{index=3}
        "limit": str(limit),
        "order": "id",
        "ascending": "false",
    }
    resp = requests.get(GAMMA_MARKETS_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("Unexpected response format from Gamma /markets API")
    return data


def seconds_until(dt: datetime) -> float:
    """Return seconds from now until dt (can be negative if already expired)."""
    now = datetime.now(timezone.utc)
    return (dt - now).total_seconds()


def find_near_expiry_high_price_markets(
    markets: List[Dict[str, Any]],
    price_threshold: float = PRICE_THRESHOLD,
    max_seconds_to_expiry: int = SECONDS_TO_EXPIRY,
) -> List[Dict[str, Any]]:
    """
    Filter markets to those that expire soon and have bestAsk > price_threshold.
    """
    results: List[Dict[str, Any]] = []

    for m in markets:
        end_str = m.get("endDate") or m.get("endDateIso")
        end_dt = parse_iso8601(end_str) if isinstance(end_str, str) else None
        if not end_dt:
            continue

        secs_left = seconds_until(end_dt)
        if secs_left <= 0 or secs_left > max_seconds_to_expiry:
            continue

        best_ask = m.get("bestAsk")
        # Some markets may not have bestAsk yet; skip them
        if best_ask is None:
            continue

        try:
            best_ask_float = float(best_ask)
        except (TypeError, ValueError):
            continue

        if best_ask_float <= price_threshold:
            continue

        # Build a convenient payload
        results.append(
            {
                "question": m.get("question", "").strip(),
                "slug": m.get("slug"),
                "bestAsk": best_ask_float,
                "endDate": end_dt,
                "seconds_left": secs_left,
                "event_title": None,
                "event_slug": None,
            }
        )

    # Sort by time remaining (soonest expiring first)
    results.sort(key=lambda r: r["seconds_left"])
    return results


def format_time_left(seconds_left: float) -> str:
    """Pretty-print remaining time in mm:ss."""
    if seconds_left < 0:
        return "expired"
    minutes = int(seconds_left // 60)
    seconds = int(seconds_left % 60)
    return f"{minutes:02d}m {seconds:02d}s"


def main() -> None:
    print("Fetching active Polymarket markets from Gamma API...")
    try:
        markets = fetch_active_markets()
    except Exception as e:
        print(f"Error fetching markets: {e}")
        return

    candidates = find_near_expiry_high_price_markets(markets)

    if not candidates:
        print(
            f"No markets found with < 1 hour to expiry and bestAsk > {PRICE_THRESHOLD:.2f}."
        )
        return

    print(
        f"\nFound {len(candidates)} near-expiry markets with bestAsk > {PRICE_THRESHOLD:.2f}:\n"
    )

    for i, c in enumerate(candidates, start=1):
        question = c["question"] or "(no question text)"
        slug = c["slug"]
        best_ask = c["bestAsk"]
        time_left = format_time_left(c["seconds_left"])
        end_dt = c["endDate"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

        # Construct a frontend URL (market slug)
        url = f"https://polymarket.com/market/{slug}" if slug else "(no slug)"

        print(f"{i}. {question}")
        print(f"   URL:        {url}")
        print(f"   Best ask:   {best_ask:.4f} (≈ {best_ask * 100:.2f}% implied)")
        print(f"   Ends at:    {end_dt} (UTC)")
        print(f"   Time left:  {time_left}")
        print("-" * 80)


if __name__ == "__main__":
    main()
