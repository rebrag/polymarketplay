from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.server.state import registry

_mem_log_stop = threading.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    def _start_mem_logger() -> None:
        def _loop() -> None:
            while not _mem_log_stop.is_set():
                try:
                    print(
                        "MEM_DEBUG "
                        f"active_books={len(registry.active_books)} "
                        f"tracked_assets={len(registry._tracked_assets)} "
                        f"subs={sum(len(v) for v in registry._subs.values())} "
                        f"orders_subs={len(registry._order_subs)} "
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
        registry.ensure_user_socket()
    except Exception as e:
        print(f"User WS startup failed: {e}")
    _start_mem_logger()
    yield
    print("Shutting down: Closing all WebSockets...")
    registry.disable_auto_trading()
    _mem_log_stop.set()
    asset_ids = list(registry.active_books.keys())
    for aid in asset_ids:
        registry.release(aid)
    with registry._user_lock:
        if registry._user_socket is not None:
            registry._user_socket.stop()
            registry._user_socket = None
