from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from polymarket_bot.server.state import registry

router = APIRouter()


class BooksBatchRequest(BaseModel):
    token_ids: list[str] = Field(default_factory=list, max_length=500)


def _best(levels: list[dict[str, str]], take_min: bool) -> float | None:
    vals: list[float] = []
    for lvl in levels:
        try:
            val = float(str(lvl.get("price", "")))
        except (TypeError, ValueError):
            continue
        if val >= 0:
            vals.append(val)
    if not vals:
        return None
    return min(vals) if take_min else max(vals)


@router.post("/books/batch")
def books_batch(req: BooksBatchRequest) -> dict[str, object]:
    unique_ids = [tid for tid in dict.fromkeys(req.token_ids) if isinstance(tid, str) and tid]
    books = registry.poly_client.get_order_book_snapshots(unique_ids)
    by_token: dict[str, dict[str, object]] = {}
    for book in books:
        token_id = str(book.get("asset_id") or "")
        if not token_id:
            continue
        bids = book.get("bids", []) if isinstance(book.get("bids"), list) else []
        asks = book.get("asks", []) if isinstance(book.get("asks"), list) else []
        by_token[token_id] = {
            "token_id": token_id,
            "best_bid": _best(bids, take_min=False),  # type: ignore[arg-type]
            "best_ask": _best(asks, take_min=True),   # type: ignore[arg-type]
        }
    items = [by_token.get(tid, {"token_id": tid, "best_bid": None, "best_ask": None}) for tid in unique_ids]
    return {"ok": True, "count": len(items), "items": items}


@router.get("/books/auto/status")
def books_auto_status() -> dict[str, object]:
    return registry.get_auto_subscribe_status()
