from __future__ import annotations

from fastapi import APIRouter, HTTPException
import time

from polymarket_bot.server.helpers import _to_float
from polymarket_bot.server.models import (
    AutoPairConfig,
    AutoPairPayload,
    CancelOrderRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)
from polymarket_bot.server.state import logger, registry
from polymarket_bot.server.strategies import get_strategy_names

router = APIRouter()


def _log_submit_latency(action: str, token_id: str, side: str, duration_ms: float) -> None:
    print(
        "ORDER_LATENCY "
        f"action={action} side={side} latency_ms={duration_ms:.2f}"
    )


def _best_price_from_book(token_id: str, side: str) -> float | None:
    book = registry.active_books.get(token_id)
    if book is None or not getattr(book, "ready", False):
        return None
    bids, asks = book.get_snapshot(limit=1)
    if side == "BUY":
        return bids[0][0] if bids else None
    return asks[0][0] if asks else None


@router.post("/orders/limit")
def post_limit_order(req: LimitOrderRequest) -> dict[str, object]:
    """
    Places a limit order at best_bid (BUY) or best_ask (SELL), optionally offset by cents.

    Notes:
    - For BUY, positive offset makes your bid more aggressive (bid higher).
    - For SELL, negative offset makes your ask more aggressive (ask lower).
    """
    try:
        best_price = _best_price_from_book(req.token_id, req.side)
        if best_price is None:
            try:
                best_price = registry.poly_client.get_best_price(req.token_id, req.side)
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"error": "best_price unavailable", "upstream": str(exc)},
                )
        price: float | None = None
        if req.level is not None:
            price = registry.get_price_for_level(req.token_id, req.side, req.level)
        if price is None:
            price_offset = req.price_offset_cents or 0
            price = best_price + (price_offset / 100.0)
        price = max(0.01, min(0.99, price))

        ttl = req.ttl_seconds
        if ttl < 0:
            raise HTTPException(status_code=400, detail="ttl_seconds must be >= 0 (or omitted for GTC)")

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                start = time.perf_counter()
                result = registry.poly_client.place_limit_order(
                    token_id=req.token_id,
                    side=req.side,
                    size=req.size,
                    price=price,
                    ttl_seconds=ttl + 60,
                )
                _log_submit_latency(
                    "limit",
                    req.token_id,
                    req.side,
                    (time.perf_counter() - start) * 1000.0,
                )
                return {"ok": True, "placed_price": price, "result": result}
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and "Request exception" in str(exc):
                    time.sleep(0.25)
                    continue
                raise
        raise last_exc  # type: ignore[misc]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Order Error (token_id=%s side=%s)", req.token_id, req.side)

        status = getattr(e, "status_code", 500)
        if not isinstance(status, int):
            try:
                status = int(status)
            except (TypeError, ValueError):
                status = 500
        err_msg = getattr(e, "error_message", None)

        detail: object = {"error": str(e)}
        if err_msg is not None:
            detail = {"error": str(e), "upstream": err_msg}

        raise HTTPException(status_code=status, detail=detail)


@router.post("/auto/pair")
def set_auto_pair(req: AutoPairPayload) -> dict[str, object]:
    asset_settings = {s.asset_id: s for s in req.asset_settings}
    config = AutoPairConfig(
        pair_key=req.pair_key,
        assets=req.assets,
        asset_settings=asset_settings,
        disabled_assets=req.disabled_assets,
        auto_buy_max_cents=req.auto_buy_max_cents,
        auto_sell_min_cents=req.auto_sell_min_cents,
        auto_sell_min_shares=req.auto_sell_min_shares,
        strategy=req.strategy,
        enabled=req.enabled,
    )
    if req.enabled:
        registry.set_auto_pair(config)
        return {"ok": True, "enabled": True}
    registry.clear_auto_pair(req.pair_key)
    return {"ok": True, "enabled": False}


@router.get("/auto/pair")
def get_auto_pair(pair_key: str) -> dict[str, object]:
    with registry._auto_lock:
        config = registry._auto_pairs.get(pair_key)
    if config is None:
        raise HTTPException(status_code=404, detail="Auto pair not found")
    settings = [
        {
            "asset_id": s.asset_id,
            "shares": s.shares,
            "ttl_seconds": s.ttl_seconds,
            "level": s.level,
            "enabled": s.enabled,
        }
        for s in config.asset_settings.values()
    ]
    return {
        "ok": True,
        "pair": {
            "pair_key": config.pair_key,
            "assets": config.assets,
            "disabled_assets": config.disabled_assets,
            "auto_buy_max_cents": config.auto_buy_max_cents,
            "auto_sell_min_cents": config.auto_sell_min_cents,
            "auto_sell_min_shares": config.auto_sell_min_shares,
            "strategy": config.strategy,
            "enabled": config.enabled,
            "asset_settings": settings,
        },
    }


@router.get("/auto/status")
def get_auto_status() -> dict[str, object]:
    with registry._auto_lock:
        pairs = [
            {
                "pair_key": cfg.pair_key,
                "assets": cfg.assets,
                "disabled_assets": cfg.disabled_assets,
                "auto_buy_max_cents": cfg.auto_buy_max_cents,
                "auto_sell_min_cents": cfg.auto_sell_min_cents,
                "auto_sell_min_shares": cfg.auto_sell_min_shares,
                "strategy": getattr(cfg, "strategy", "default"),
                "enabled": cfg.enabled,
            }
            for cfg in registry._auto_pairs.values()
        ]
    return {"ok": True, "count": len(pairs), "pairs": pairs}


@router.post("/auto/kill")
def kill_auto_trading() -> dict[str, object]:
    registry.disable_auto_trading()
    return {"ok": True}


@router.get("/auto/strategies")
def list_auto_strategies() -> dict[str, object]:
    return {"strategies": get_strategy_names()}


@router.post("/orders/market")
def post_market_order(req: MarketOrderRequest) -> dict[str, object]:
    try:
        if req.fok_only:
            start = time.perf_counter()
            result = registry.poly_client.place_market_order(
                token_id=req.token_id,
                side=req.side,
                size=req.amount,
            )
            _log_submit_latency(
                "market_fok",
                req.token_id,
                req.side,
                (time.perf_counter() - start) * 1000.0,
            )
            logger.info(
                "Market order response (mode=fok token_id=%s side=%s amount=%s)",
                req.token_id,
                req.side,
                req.amount,
            )
            return {"ok": True, "mode": "fok", "result": result}

        snapshot = registry.poly_client.get_order_book_snapshot(req.token_id)
        best_price: float | None = None
        total_liquidity = 0.0
        size_shares = req.amount
        if snapshot:
            asks = snapshot.get("asks", []) if isinstance(snapshot, dict) else []
            bids = snapshot.get("bids", []) if isinstance(snapshot, dict) else []
            if req.side == "BUY" and not asks:
                raise HTTPException(status_code=400, detail="No asks available for market buy.")
            if req.side == "SELL" and not bids:
                raise HTTPException(status_code=400, detail="No bids available for market sell.")
            if req.side == "BUY":
                if isinstance(asks[0], dict):
                    best_price = _to_float(asks[0].get("price", 0))
                total_liquidity = sum(_to_float(a.get("size", 0)) for a in asks if isinstance(a, dict))
                if best_price is not None and best_price > 0:
                    size_shares = req.amount / best_price
            else:
                if isinstance(bids[0], dict):
                    best_price = _to_float(bids[0].get("price", 0))
                total_liquidity = sum(_to_float(b.get("size", 0)) for b in bids if isinstance(b, dict))

        if best_price is not None and total_liquidity < size_shares:
            start = time.perf_counter()
            result = registry.poly_client.place_limit_order(
                token_id=req.token_id,
                side=req.side,
                size=size_shares,
                price=best_price,
                ttl_seconds=None,
            )
            _log_submit_latency(
                "market_limit_fallback",
                req.token_id,
                req.side,
                (time.perf_counter() - start) * 1000.0,
            )
            return {
                "ok": True,
                "mode": "limit_fallback",
                "note": "Insufficient immediate liquidity for market order; placed aggressive limit.",
                "placed_price": best_price,
                "result": result,
            }

        start = time.perf_counter()
        result = registry.poly_client.place_market_order(
            token_id=req.token_id,
            side=req.side,
            size=req.amount,
        )
        _log_submit_latency(
            "market",
            req.token_id,
            req.side,
            (time.perf_counter() - start) * 1000.0,
        )
        logger.info(
            "Market order response (token_id=%s side=%s amount=%s)",
            req.token_id,
            req.side,
            req.amount,
        )
        return {"ok": True, "result": result}
    except Exception as e:
        error_text = str(e)
        if "no orders found to match" in error_text or "couldn't be fully filled" in error_text:
            try:
                best_price = _to_float(
                    registry.poly_client.get_best_price(
                        req.token_id, "SELL" if req.side == "BUY" else "BUY"
                    )
                )
                size_shares = req.amount
                if req.side == "BUY" and best_price > 0:
                    size_shares = req.amount / best_price
                start = time.perf_counter()
                result = registry.poly_client.place_limit_order(
                    token_id=req.token_id,
                    side=req.side,
                    size=size_shares,
                    price=best_price,
                    ttl_seconds=None,
                )
                _log_submit_latency(
                    "market_limit_fallback",
                    req.token_id,
                    req.side,
                    (time.perf_counter() - start) * 1000.0,
                )
                print(
                    f"Market order fallback response (token_id={req.token_id} side={req.side} amount={req.amount}): {result}"
                )
                return {
                    "ok": True,
                    "mode": "limit_fallback",
                    "note": "Market order had no immediate match; placed aggressive limit.",
                    "placed_price": best_price,
                    "result": result,
                }
            except Exception:
                pass
        logger.exception("Market Order Error (token_id=%s side=%s amount=%s)", req.token_id, req.side, req.amount)
        status = getattr(e, "status_code", 500)
        err_msg = getattr(e, "error_message", None)
        detail: object = {"error": str(e)}
        if err_msg is not None:
            detail = {"error": str(e), "upstream": err_msg}
        raise HTTPException(status_code=int(status), detail=detail)


@router.post("/orders/cancel")
def cancel_order(req: CancelOrderRequest) -> dict[str, object]:
    try:
        result = registry.poly_client.cancel_order(req.order_id)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
