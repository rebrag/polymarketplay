from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException

from src.models import BalanceAllowanceResponse, GammaMarket, UserActivityResponse
from src.server.state import logger, registry
from src.utils import filter_markets_by_asset, get_game_data

router = APIRouter()


@router.get("/user/resolve", response_model=UserActivityResponse)
def resolve_user_activity(address: str, limit: int = 50, min_volume: float = 0.0) -> UserActivityResponse:
    trades = registry.poly_client.get_trades(address, limit=limit)
    if not trades:
        raise HTTPException(status_code=404, detail="No recent activity found")

    target_event_slugs: set[str] = set()
    traded_asset_ids: set[str] = set()

    for t in trades:
        if t.get("eventSlug"):
            target_event_slugs.add(t["eventSlug"])
        if t.get("asset"):
            traded_asset_ids.add(t["asset"])

    combined_markets: list[GammaMarket] = []
    for evt_slug in target_event_slugs:
        event_data = get_game_data(str(evt_slug))
        if not event_data:
            continue

        filtered = filter_markets_by_asset(event_data["markets"], traded_asset_ids, min_volume)
        combined_markets.extend(filtered)

    return {
        "title": f"Activity: {address[:6]}...{address[-4:]}",
        "markets": combined_markets,
    }


@router.get("/user/balance_allowance", response_model=BalanceAllowanceResponse)
def get_balance_allowance(
    asset_type: Literal["COLLATERAL", "CONDITIONAL"] = "COLLATERAL",
    token_id: str | None = None,
    signature_type: int | None = None,
) -> BalanceAllowanceResponse:
    try:
        return registry.poly_client.get_balance_allowance(
            asset_type=asset_type,
            token_id=token_id,
            signature_type=signature_type,
        )
    except Exception as e:
        logger.exception(
            "Balance/allowance fetch failed (asset_type=%s token_id=%s signature_type=%s)",
            asset_type,
            token_id,
            signature_type,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/balance")
def get_balance() -> dict[str, str]:
    try:
        data = registry.poly_client.get_balance_allowance()
        return {"balance": data["balance"]}
    except Exception as e:
        logger.exception("Balance fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/positions")
def get_positions(address: str, limit: int = 100) -> list[dict[str, object]]:
    try:
        raw = registry.poly_client.get_positions(address, limit=limit)
        filtered: list[dict[str, object]] = []
        for pos in raw:
            size = float(pos.get("size", 0) or 0)
            value = float(pos.get("currentValue", 0) or 0)
            if size > 0 and value > 0:
                filtered.append(pos)  # type: ignore
        return filtered
    except Exception as e:
        logger.exception("Positions fetch failed (address=%s limit=%s)", address, limit)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/positions/auth")
def get_positions_auth(limit: int = 100) -> list[dict[str, object]]:
    try:
        address = registry.poly_client.get_positions_address()
        if not address:
            raise RuntimeError("Authenticated address unavailable.")
        return registry.poly_client.get_positions(address, limit=limit)  # type: ignore
    except Exception as e:
        logger.exception("Auth positions fetch failed (limit=%s)", limit)
        raise HTTPException(status_code=500, detail=str(e))
