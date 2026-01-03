from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from src.models import GammaEvent, GammaMarket
from src.server.state import registry
from src.utils import get_game_data

router = APIRouter()


@router.get("/events/resolve", response_model=GammaEvent)
def resolve_event(query: str, min_volume: float = 0.0) -> GammaEvent:
    data = get_game_data(query)
    if not data:
        raise HTTPException(status_code=404, detail="Event not found")

    filtered_markets: list[GammaMarket] = []
    raw_markets = data.get("markets", [])

    for m in raw_markets:
        vol = float(m.get("volumeNum", 0.0))
        if vol >= min_volume:
            filtered_markets.append(m)

    data["markets"] = filtered_markets
    return data


@router.get("/events/list", response_model=list[GammaEvent])
def list_events(
    tag_id: int = 1,
    limit: int = 20,
    window_hours: int = 24,
    window_before_hours: int = 0,
    volume_min: float = 1000,
) -> list[GammaEvent]:
    now = datetime.now(timezone.utc)
    end_date_min = (now - timedelta(hours=4)).isoformat()
    end_date_max = (now + timedelta(hours=24)).isoformat()
    fetch_limit = max(limit, 500)
    params: dict[str, object] = {
        "limit": fetch_limit,
        "active": True,
        "closed": False,
        "order": "volume24hr",
        "ascending": False,
        "end_date_min": end_date_min,
        "end_date_max": end_date_max,
        "volume_min": volume_min,
    }
    if tag_id and tag_id > 0:
        params["tag_id"] = tag_id
    events = registry.poly_client.get_gamma_events(**params)  # type: ignore[arg-type]
    total_markets = 0
    for ev in events:
        markets = ev.get("markets", [])
        if isinstance(markets, list):
            total_markets += len(markets)
    print(f"Gamma events fetched: {len(events)} events, {total_markets} markets")
    window_start = now - timedelta(hours=window_before_hours)
    window_end = now + timedelta(hours=window_hours)

    def _parse(dt_str: str | None) -> datetime | None:
        if not dt_str:
            return None
        cleaned = dt_str.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None

    filtered: list[GammaEvent] = []
    for ev in events:
        end_raw = ev.get("endDate")
        end_dt = _parse(str(end_raw)) if end_raw else None
        if end_dt and window_start <= end_dt <= window_end:
            filtered.append(ev)

    def _sort_key(ev: GammaEvent) -> datetime:
        end_raw = ev.get("endDate")
        end_dt = _parse(str(end_raw)) if end_raw else None
        if end_dt:
            return end_dt
        return now

    filtered.sort(key=_sort_key)
    print(f"Gamma events in window: {len(filtered)} (fetch_limit={fetch_limit})")
    return filtered[:limit]
