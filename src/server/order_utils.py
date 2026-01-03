from __future__ import annotations

from src.models import Order
from src.server.helpers import _to_int, _to_side


def normalize_open_orders(raw_orders: list[dict[str, object]]) -> list[Order]:
    def _order_id(o: dict[str, object]) -> str | None:
        for key in ("orderID", "orderId", "order_id", "id"):
            val = o.get(key)
            if isinstance(val, str) and val:
                return val
        return None

    def _norm(o: dict[str, object], oid: str) -> Order:
        size_val = o.get("size", "")
        if not size_val:
            size_val = o.get("original_size", "")
        return {
            "orderID": oid,
            "price": str(o.get("price", "")),
            "size": str(size_val),
            "side": _to_side(o.get("side", "")),
            "asset_id": str(o.get("asset_id") or o.get("assetId") or o.get("market") or ""),
            "market": str(o.get("market", "")),
            "outcome": str(o.get("outcome", "")),
            "expiration": _to_int(o.get("expiration", 0)),
            "timestamp": _to_int(o.get("timestamp", 0) or o.get("created_at", 0)),
            "owner": str(o.get("owner", "")),
            "hash": str(o.get("hash", "")),
        }

    out: list[Order] = []
    for raw in raw_orders:
        if not isinstance(raw, dict):
            continue
        oid = _order_id(raw)
        if not oid:
            continue
        out.append(_norm(raw, oid))
    return out
