# get_token_id_from_url.py
import requests
from urllib.parse import urlparse

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
POLY_URL = "https://polymarket.com/event/cbb-buf-umbc-2025-12-09" # Put your Polymarket event/market URL here:


def get_slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    return parts[-1]  # handles /event/<slug> or /market/<slug>

def get_condition_id_from_slug(slug: str) -> str:
    resp = requests.get(f"{GAMMA_BASE}/events/slug/{slug}", timeout=10)
    resp.raise_for_status()
    event = resp.json()
    markets = event.get("markets", [])
    if not markets:
        raise RuntimeError("No markets found for this slug")
    m = markets[0]
    condition_id = m.get("conditionId") or m.get("condition_id")
    if not condition_id:
        raise RuntimeError(f"No conditionId on first market: {m}")
    return condition_id


def get_tokens_from_condition_id(condition_id: str):
    resp = requests.get(f"{CLOB_BASE}/markets/{condition_id}", timeout=10)
    resp.raise_for_status()
    market = resp.json()

    tokens = market.get("tokens", [])
    if not tokens:
        raise RuntimeError("No tokens field found on CLOB market response")

    print(f"Condition ID: {condition_id}")
    for t in tokens:
        outcome = t.get("outcome", "?")
        token_id = t.get("token_id")
        print(f"- {outcome}: {token_id}")


if __name__ == "__main__":
    slug = get_slug_from_url(POLY_URL)
    cond = get_condition_id_from_slug(slug)
    get_tokens_from_condition_id(cond)
