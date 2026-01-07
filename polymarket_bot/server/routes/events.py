from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from polymarket_bot.models import GammaEvent, GammaMarket
from polymarket_bot.server.state import registry
from polymarket_bot.utils import get_game_data

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
    tag_id: int = 0,
    limit: int = 20,
    window_hours: int = 24,
    window_before_hours: int = 0,
    volume_min: float = 1000,
) -> list[GammaEvent]:
    now = datetime.now(timezone.utc)
    fetch_limit = max(limit, 500)
    base_params: dict[str, object] = {
        "limit": fetch_limit,
        "active": True,
        "closed": False,
        "order": "volume24hr",
        "ascending": False,
        "volume_min": volume_min,
    }

    def _fetch(tag: int | None, hours_after: int) -> list[GammaEvent]:
        params = dict(base_params)
        params["end_date_min"] = (now - timedelta(hours=window_before_hours)).isoformat()
        params["end_date_max"] = (now + timedelta(hours=hours_after)).isoformat()
        if tag:
            params["tag_id"] = tag
        return registry.poly_client.get_gamma_events(**params)  # type: ignore[arg-type]

    events: list[GammaEvent] = []
    if tag_id in (1, 450):
        combined: dict[object, GammaEvent] = {}
        for ev in _fetch(1, window_hours):
            key = ev.get("id", ev.get("slug", id(ev)))
            combined[key] = ev
        for ev in _fetch(450, 72):
            key = ev.get("id", ev.get("slug", id(ev)))
            combined[key] = ev
        events = list(combined.values())
    else:
        events = _fetch(tag_id if tag_id and tag_id > 0 else None, window_hours)
    total_markets = 0
    for ev in events:
        markets = ev.get("markets", [])
        if isinstance(markets, list):
            total_markets += len(markets)
    print(f"Gamma events fetched: {len(events)} events, {total_markets} markets")
    window_start = now - timedelta(hours=window_before_hours)
    window_end = now + timedelta(hours=window_hours)
    nfl_end_extend = timedelta(hours=48)

    def _parse(dt_str: str | None) -> datetime | None:
        if not dt_str:
            return None
        cleaned = dt_str.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None

    def _candidate_times(ev: GammaEvent) -> list[datetime]:
        times: list[datetime] = []
        end_raw = ev.get("endDate")
        start_raw = ev.get("startDate")
        end_dt = _parse(str(end_raw)) if end_raw else None
        start_dt = _parse(str(start_raw)) if start_raw else None
        if end_dt:
            times.append(end_dt)
        if start_dt:
            times.append(start_dt)
        markets = ev.get("markets", [])
        if isinstance(markets, list):
            for m in markets:
                if not isinstance(m, dict):
                    continue
                game_raw = m.get("gameStartTime")
                game_dt = _parse(str(game_raw)) if game_raw else None
                if game_dt:
                    times.append(game_dt)
        return times

    filtered: list[GammaEvent] = []
    for ev in events:
        candidates = _candidate_times(ev)
        event_tags = str(ev.get("tags") or "")
        is_nfl = "450" in event_tags.split(",") or event_tags.strip() == "450"
        effective_end = window_end + nfl_end_extend if is_nfl else window_end
        if any(window_start <= dt <= effective_end for dt in candidates):
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
