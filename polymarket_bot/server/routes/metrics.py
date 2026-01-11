from __future__ import annotations

from fastapi import APIRouter

from polymarket_bot.server.metrics import latency_monitor

router = APIRouter()


@router.get("/metrics/latency")
def get_latency() -> dict[str, object]:
    return latency_monitor.snapshot()
