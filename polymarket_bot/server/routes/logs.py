from __future__ import annotations

import csv
import math
from collections import deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from polymarket_bot.server.helpers import _safe_path_segment
from polymarket_bot.server.state import registry

router = APIRouter()


@router.get("/logs/market")
async def get_market_log(
    slug: str,
    question: str,
    limit: int = Query(default=2000, ge=100, le=200_000),
    stride: int = Query(default=1, ge=1, le=1000),
    max_rows: int = Query(default=2000, ge=100, le=5000),
) -> dict[str, object]:
    safe_slug = _safe_path_segment(slug)
    safe_q = _safe_path_segment(question)
    path = Path("logs") / safe_slug / f"{safe_q}.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Log file not found.")
    window: deque[dict[str, str]] = deque(maxlen=limit)
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            window.append(row)
    rows = list(window)
    total = len(rows)
    auto_stride = stride
    if total > max_rows:
        auto_stride = max(auto_stride, math.ceil(total / max_rows))
    if auto_stride > 1:
        rows = rows[::auto_stride]
    return {
        "ok": True,
        "path": path,
        "rows": rows,
        "limit": limit,
        "stride": auto_stride,
        "total": total,
        "max_rows": max_rows,
    }


@router.get("/logs/index")
def list_market_logs() -> list[dict[str, str]]:
    base = Path("logs")
    if not base.exists():
        return []
    entries: list[dict[str, str]] = []
    for slug_dir in base.iterdir():
        if not slug_dir.is_dir():
            continue
        for csv_path in slug_dir.glob("*.csv"):
            entries.append(
                {
                    "slug": slug_dir.name,
                    "question": csv_path.stem,
                }
            )
    entries.sort(key=lambda item: (item["slug"], item["question"]))
    return entries


@router.get("/logs/auto/status")
def get_auto_logging_status() -> dict[str, object]:
    return registry.get_auto_event_logging_status()
