from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from py_clob_client.clob_types import OpenOrderParams  # type: ignore
from polymarket_bot.server.state import logger, registry

router = APIRouter()


@router.get("/debug/events_raw")
def debug_events_raw(tag_id: int = 1, limit: int = 500, volume_min: float = 1000) -> dict[str, object]:
    fetch_limit = min(max(limit, 1), 500)
    now = datetime.now(timezone.utc)
    end_date_min = (now - timedelta(hours=4)).isoformat()
    end_date_max = (now + timedelta(hours=24)).isoformat()
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
    return {"count": len(events), "tag_id": tag_id, "events": events}


@router.get("/debug/event_by_slug")
def debug_event_by_slug(slug: str, tag_id: int = 1, volume_min: float = 1000) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    end_date_min = (now - timedelta(hours=4)).isoformat()
    end_date_max = (now + timedelta(hours=24)).isoformat()
    params: dict[str, object] = {
        "limit": 1,
        "active": True,
        "closed": False,
        "order": "volume24hr",
        "ascending": False,
        "end_date_min": end_date_min,
        "end_date_max": end_date_max,
        "volume_min": volume_min,
        "tag_id": tag_id,
        "slug": slug,
    }
    events = registry.poly_client.get_gamma_events(**params)  # type: ignore[arg-type]
    ev = events[0] if events else None
    if not ev:
        return {
            "slug": slug,
            "found": False,
            "filters": {
                "tag_id": tag_id,
                "end_date_min": end_date_min,
                "end_date_max": end_date_max,
                "volume_min": volume_min,
            },
        }

    end_raw = ev.get("endDate")
    end_dt = None
    if end_raw:
        try:
            end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
        except ValueError:
            end_dt = None

    volume_val = ev.get("volume24hr")
    try:
        volume_num = float(volume_val) if volume_val is not None else None
    except (TypeError, ValueError):
        volume_num = None

    return {
        "slug": slug,
        "found": True,
        "event": ev,
        "filters": {
            "tag_id": tag_id,
            "end_date_min": end_date_min,
            "end_date_max": end_date_max,
            "volume_min": volume_min,
        },
        "checks": {
            "end_date": str(end_raw),
            "end_in_window": bool(end_dt and end_date_min <= end_dt.isoformat() <= end_date_max),
            "volume24hr": volume_num,
            "volume_ok": bool(volume_num is not None and volume_num >= volume_min),
        },
    }


@router.get("/debug/open_orders_raw")
def debug_open_orders_raw() -> dict[str, object]:
    try:
        client = registry.poly_client._get_trading_clob_client()
        raw = client.get_orders(OpenOrderParams())  # type: ignore
        print(f"DEBUG open_orders_raw type={type(raw)}")
        print(f"DEBUG open_orders_raw payload={raw}")
        return {"type": str(type(raw)), "payload": raw}
    except Exception as e:
        logger.exception("Debug open orders raw failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/auth_status")
def debug_auth_status() -> dict[str, object]:
    try:
        client = registry.poly_client._get_trading_clob_client()
        address = client.get_address()
        try:
            keys = client.get_api_keys()  # type: ignore
            keys_info: object = keys
        except Exception as e:
            keys_info = {"error": str(e)}
        print(f"DEBUG auth_status address={address}")
        print(f"DEBUG auth_status api_keys={keys_info}")
        return {"address": str(address), "api_keys": keys_info}
    except Exception as e:
        logger.exception("Debug auth status failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/user_ws")
def debug_user_ws() -> dict[str, object]:
    return registry.get_user_socket_status()


@router.post("/debug/user_ws/start")
def debug_user_ws_start() -> dict[str, object]:
    try:
        registry.ensure_user_socket()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return registry.get_user_socket_status()


@router.get("/debug/books")
def debug_books() -> dict[str, object]:
    active_asset_ids = sorted(registry.active_books.keys())
    slug_to_title: dict[str, str] = {}
    with registry._auto_subscribe_lock:
        for item in registry._auto_subscribe_items.values():
            slug = str(item.get("event_slug") or "").strip()
            title = str(item.get("event_title") or "").strip()
            if slug and title and slug not in slug_to_title:
                slug_to_title[slug] = title
    active_assets: list[dict[str, str]] = []
    for aid in active_asset_ids:
        meta = registry._asset_meta.get(aid, {})
        slug = str(meta.get("slug") or "")
        active_assets.append(
            {
                "asset_id": aid,
                "slug": slug,
                "event_title": slug_to_title.get(slug, ""),
                "question": str(meta.get("question") or ""),
                "outcome": str(meta.get("outcome") or ""),
                "game_start_time": (
                    datetime.fromtimestamp(float(meta.get("game_start_ts")), tz=timezone.utc)
                    .astimezone()
                    .strftime("%H:%M")
                    if meta.get("game_start_ts") is not None
                    else ""
                ),
            }
        )
    return {
        "active_books": len(registry.active_books),
        "active_asset_ids": active_asset_ids,
        "active_assets": active_assets,
        "tracked_assets": len(registry._tracked_assets),
        "market_threads": len(registry._market_threads),
        "market_assets": len(registry._market_assets),
        "subscriber_queues": sum(len(v) for v in registry._subs.values()),
    }
