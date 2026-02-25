from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from polymarket_bot.server.metrics import latency_monitor
from polymarket_bot.server.settings import (
    AUTO_SUBSCRIBE_ENABLED,
    AUTO_SUBSCRIBE_REFRESH_INTERVAL_S,
    AUTO_SUBSCRIBE_END_DATE_WINDOW_BEFORE_HOURS,
    AUTO_SUBSCRIBE_END_DATE_WINDOW_HOURS,
    AUTO_SUBSCRIBE_GAMESTART_WINDOW_BEFORE_HOURS,
    AUTO_SUBSCRIBE_GAMESTART_WINDOW_HOURS,
)
from polymarket_bot.server.state import registry

_mem_log_stop = threading.Event()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = raw.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


@asynccontextmanager
async def lifespan(app: FastAPI):
    def _start_mem_logger() -> None:
        def _loop() -> None:
            while not _mem_log_stop.is_set():
                try:
                    print(
                        "MEM_DEBUG "
                        f"active_books={len(registry.active_books)} "
                        # f"tracked_assets={len(registry._tracked_assets)} "
                        # f"subs={sum(len(v) for v in registry._subs.values())} "
                        # f"orders_subs={len(registry._order_subs)} "
                        f"market_threads={len(registry._market_threads)} "
                        f"market_assets={len(registry._market_assets)} "
                        f"user_events={registry._user_event_count}"
                    )
                except Exception as exc:
                    print(f"MEM_DEBUG failed: {exc}")
                _mem_log_stop.wait(30.0)

        thread = threading.Thread(target=_loop, name="mem_debug_logger", daemon=True)
        thread.start()

    registry.disable_auto_trading()
    try:
        registry.poly_client.warm_trading_client()
        print("Trading client warmed at startup.")
    except Exception as e:
        print(f"Trading client warmup failed: {e}")
    try:
        registry.ensure_user_socket()
    except Exception as e:
        print(f"User WS startup failed: {e}")
    threshold_raw = os.getenv("ORDERBOOK_MIN_VOLUME", os.getenv("AUTO_LOG_VOLUME_THRESHOLD", "10000"))
    include_more_markets = _env_bool("ORDERBOOK_INCLUDE_MORE_MARKETS", True)
    track_all_outcomes = _env_bool("ORDERBOOK_TRACK_ALL_OUTCOMES", True)
    try:
        threshold = float(threshold_raw)
    except ValueError:
        threshold = 50_000.0
    refresh_s = AUTO_SUBSCRIBE_REFRESH_INTERVAL_S
    game_start_window_before_h = AUTO_SUBSCRIBE_GAMESTART_WINDOW_BEFORE_HOURS
    game_start_window_after_h = AUTO_SUBSCRIBE_GAMESTART_WINDOW_HOURS
    end_date_window_before_h = AUTO_SUBSCRIBE_END_DATE_WINDOW_BEFORE_HOURS
    end_date_window_after_h = AUTO_SUBSCRIBE_END_DATE_WINDOW_HOURS
    if AUTO_SUBSCRIBE_ENABLED:
        registry.start_auto_subscribe(
            volume_threshold=threshold,
            refresh_interval_s=refresh_s,
            window_before_hours=game_start_window_before_h,
            window_hours=game_start_window_after_h,
            end_date_window_before_hours=end_date_window_before_h,
            end_date_window_hours=end_date_window_after_h,
            include_more_markets=include_more_markets,
            track_all_outcomes=track_all_outcomes,
        )
        print(
            "Auto subscribe started "
            f"(volume_threshold={threshold}, refresh_interval_s={refresh_s}, "
            f"game_start_window_before_hours={game_start_window_before_h}, "
            f"game_start_window_hours={game_start_window_after_h}, "
            f"end_date_window_before_hours={end_date_window_before_h}, "
            f"end_date_window_hours={end_date_window_after_h}, "
            f"include_more_markets={include_more_markets}, track_all_outcomes={track_all_outcomes})"
        )
    else:
        print("Auto subscribe disabled (AUTO_SUBSCRIBE_ENABLED=False).")
    _start_mem_logger()
    latency_monitor.start()
    yield
    print("Shutting down: Closing all WebSockets...")
    registry.disable_auto_trading()
    registry.stop_auto_subscribe()
    _mem_log_stop.set()
    latency_monitor.stop()
    asset_ids = list(registry.active_books.keys())
    for aid in asset_ids:
        registry.release(aid)
    with registry._user_lock:
        if registry._user_socket is not None:
            registry._user_socket.stop()
            registry._user_socket = None
