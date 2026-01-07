from __future__ import annotations

import os
import time
from typing import cast

from polymarket_bot.clients import OddsApiClient
from polymarket_bot.config import ODDS_SPORT_KEY

_odds_cache: dict[str, tuple[float, list[dict[str, object]]]] = {}
_odds_clients: dict[str, OddsApiClient] = {}
_ODDS_CACHE_TTL_SECONDS = int(cast(str, os.getenv("ODDS_CACHE_TTL_SECONDS", "3600")))
_odds_sports_cache: tuple[float, list[dict[str, object]]] | None = None
_ODDS_SPORTS_TTL_SECONDS = int(cast(str, os.getenv("ODDS_SPORTS_TTL_SECONDS", "3600")))


def _get_odds_client(sport: str) -> OddsApiClient:
    client = _odds_clients.get(sport)
    if client is not None:
        return client
    api_key = os.getenv("ODDS_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing ODDS_KEY in environment.")
    client = OddsApiClient(api_key=api_key, sport=sport)
    _odds_clients[sport] = client
    return client


def get_cached_odds(sport: str, ttl_seconds: int = _ODDS_CACHE_TTL_SECONDS) -> list[dict[str, object]]:
    cached = _odds_cache.get(sport)
    now = time.time()
    if cached and now - cached[0] < ttl_seconds:
        return cached[1]
    client = _get_odds_client(sport)
    data = client.get_odds(markets="h2h")
    try:
        used, remaining = client.get_usage()
        print(f"Odds API usage: used={used} remaining={remaining}")
    except Exception as e:
        print(f"Odds API usage check failed: {e}")
    _odds_cache[sport] = (now, data)
    return data


def get_cached_odds_sports() -> list[dict[str, object]]:
    global _odds_sports_cache
    now = time.time()
    if _odds_sports_cache and now - _odds_sports_cache[0] < _ODDS_SPORTS_TTL_SECONDS:
        return _odds_sports_cache[1]
    client = _get_odds_client(ODDS_SPORT_KEY)
    data = client.get_sport_keys()
    _odds_sports_cache = (now, data)
    return data
