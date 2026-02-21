from __future__ import annotations

import asyncio
import os
import time
from asyncio import Queue
from collections import deque
from typing import Final, Iterable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from polymarket_bot.models import GammaMarket, WsBidAsk, WsPayload
from polymarket_bot.server.order_utils import normalize_open_orders
from polymarket_bot.server.state import registry
from polymarket_bot.utils import filter_markets_by_asset, get_game_data

router = APIRouter()

ORDER_WS_PING_SECONDS: Final[float] = 15.0

# Hard cap on how fast we push book updates to the browser per-asset socket.
BOOK_MAX_HZ: Final[float] = 2.0
BOOK_MIN_SEND_INTERVAL_S: Final[float] = 1.0 / BOOK_MAX_HZ

# If your registry doesn't support book subscriber queues, we fall back to polling.
BOOK_POLL_FALLBACK_S: Final[float] = 0.02

# Prevent unbounded memory growth for long-running watch sessions.
WATCH_USER_MAX_SEEN_ASSETS: Final[int] = 20_000
WATCH_USER_INTERVAL_S: Final[float] = 2.0


async def _safe_close(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except Exception:
        return


def _coerce_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _now_s() -> int:
    return int(time.time())


@router.websocket("/ws/watch/user/{address}")
async def watch_user_endpoint(websocket: WebSocket, address: str, min_volume: float = 0.0) -> None:
    await websocket.accept()

    # Use an order-preserving bounded structure so this can't grow forever.
    sent_asset_ids: deque[str] = deque(maxlen=WATCH_USER_MAX_SEEN_ASSETS)
    sent_set: set[str] = set()

    print(f"Watching user {address} (Scan interval: {WATCH_USER_INTERVAL_S:.0f}s)")

    try:
        while True:
            # Avoid blocking the event loop with sync HTTP calls.
            trades_obj = await asyncio.to_thread(registry.poly_client.get_trades, address, 20)

            trades: list[dict[str, object]]
            if isinstance(trades_obj, list):
                trades = [t for t in trades_obj if isinstance(t, dict)] # type: ignore
            else:
                trades = []

            if trades:
                await websocket.send_json({"type": "recent_trades", "trades": trades})

            new_asset_ids: set[str] = set()
            new_event_slugs: set[str] = set()

            for t in trades:
                asset = _coerce_str(t.get("asset"))
                if not asset or asset in sent_set:
                    continue

                new_asset_ids.add(asset)

                evt_slug = _coerce_str(t.get("eventSlug"))
                if evt_slug:
                    new_event_slugs.add(evt_slug)

            if new_asset_ids and new_event_slugs:
                print(f"Found {len(new_asset_ids)} new traded tokens. Resolving...")

                batch_markets: list[GammaMarket] = []

                # Resolve each event slug (potentially network-heavy); do it off the loop.
                for evt_slug in new_event_slugs:
                    event_data = await asyncio.to_thread(get_game_data, evt_slug)
                    if not event_data:
                        continue

                    markets_obj = event_data.get("markets")
                    if not isinstance(markets_obj, list):
                        continue

                    filtered = filter_markets_by_asset(markets_obj, new_asset_ids, min_volume)
                    if filtered:
                        batch_markets.extend(filtered)

                if batch_markets:
                    await websocket.send_json({"type": "new_markets", "markets": batch_markets})

                # Record what we’ve seen (bounded).
                for asset in new_asset_ids:
                    if asset in sent_set:
                        continue
                    sent_asset_ids.append(asset)
                    sent_set.add(asset)

                # If the deque evicted something, clean the set too.
                while len(sent_set) > len(sent_asset_ids):
                    # Rare, but keep them consistent.
                    sent_set = set(sent_asset_ids)

            await asyncio.sleep(WATCH_USER_INTERVAL_S)

    except WebSocketDisconnect:
        print(f"Stopped watching user: {address}")
    except Exception as e:
        print(f"Error watching user: {e}")
        await _safe_close(websocket)


@router.websocket("/ws/orders")
@router.websocket("/ws/user")
async def orders_websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    print(f"Orders WS accepted (pid={os.getpid()})")
    registry._last_order_ws_accept_ts = time.time()

    q: Queue[dict[str, object]] = Queue(maxsize=200)

    try:
        registry.register_order_subscriber(q, asyncio.get_running_loop())
        print(f"Orders WS registered (subscribers={len(registry._order_subs)})")

        await websocket.send_json(
            {"type": "status", "status": "subscribed", "pid": os.getpid(), "server_now": _now_s()}
        )

        # Initial snapshot.
        try:
            open_orders = await asyncio.to_thread(registry.poly_client.get_open_orders)
            normalized = normalize_open_orders(open_orders)  # type: ignore[arg-type]
            await websocket.send_json({"type": "snapshot", "orders": normalized, "server_now": _now_s()})
        except Exception as e:
            await websocket.send_json({"type": "error", "error": str(e), "server_now": _now_s()})

        # Loop: either forward an order event, or periodically ping so we detect dead clients.
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=ORDER_WS_PING_SECONDS)
                msg["server_now"] = _now_s()
                await websocket.send_json(msg)
            except asyncio.TimeoutError:
                # If the client is gone, this send will raise and we’ll fall out to finally/unregister.
                await websocket.send_json({"type": "ping", "server_now": _now_s()})

    except WebSocketDisconnect:
        print("Orders WS disconnected")
    except Exception as e:
        print(f"Orders WS error: {e}")
    finally:
        registry.unregister_order_subscriber(q)
        await _safe_close(websocket)


def _build_book_payload(
    asset_id: str,
    book: object,
    msg_count: int,
    last_trade: dict[str, object] | None,
) -> WsPayload:
    # Registry book interface expected:
    # - get_snapshot(limit=15) -> (bids, asks) as list[tuple[float,float]] or similar
    # - get_cumulative_values(levels) -> list[float]
    bids, asks = getattr(book, "get_snapshot")(limit=15)
    bid_cum = getattr(book, "get_cumulative_values")(bids)
    ask_cum = getattr(book, "get_cumulative_values")(asks)

    bids_list: list[WsBidAsk] = [{"price": p, "size": s, "cum": c} for (p, s), c in zip(bids, bid_cum)]
    asks_list: list[WsBidAsk] = [{"price": p, "size": s, "cum": c} for (p, s), c in zip(asks, ask_cum)]

    payload: WsPayload = {
        "asset_id": asset_id,
        "ready": True,
        "msg_count": msg_count,
        "bids": bids_list,
        "asks": asks_list,
        "tick_size": float(getattr(book, "tick_size", 0.01)),
    }
    if last_trade:
        payload["last_trade"] = last_trade  # type: ignore[assignment]
    return payload


@router.websocket("/ws/{asset_id}")
async def websocket_endpoint(websocket: WebSocket, asset_id: str) -> None:
    await websocket.accept()

    try:
        # metadata setup...
        book = registry.get_or_create(asset_id)
    except Exception:
        await _safe_close(websocket)
        return

    try:
        # We no longer need update_q to trigger sends. 
        # We only need to know when to pull from the book.
        while True:
            # 1. State Check: If book isn't ready, throttle and wait.
            if not getattr(book, "ready", True):
                await websocket.send_json({"status": "loading", "asset_id": asset_id})
                await asyncio.sleep(0.5) # Heavy throttle during loading
                continue

            # 2. Extract current state from the "hot" BookManager
            msg_count = int(getattr(book, "msg_count", 0))
            last_trade = registry.get_last_trade(asset_id)
            
            # 3. Build the payload (This is the CPU-intensive part for the browser)
            payload = _build_book_payload(asset_id, book, msg_count, last_trade) #type: ignore
            
            # 4. Send to Frontend
            await websocket.send_json(payload)
            
            # 5. THE FIX: Strict Fixed Interval
            # By using a flat sleep, you guarantee the React Scheduler (Scheduler.js) 
            # has exactly 100ms of "Quiet Time" to perform Garbage Collection 
            # and clear the JS Heap between every single update.
            await asyncio.sleep(0.1) 

    except WebSocketDisconnect:
        return
    except Exception as e:
        print(f"Socket Error: {e}")
    finally:
        registry.release(asset_id)
        await _safe_close(websocket)


@router.websocket("/ws/books/stream")
async def websocket_books(websocket: WebSocket) -> None:
    await websocket.accept()

    subscribed: set[str] = set()
    update_q: Queue[None] = Queue(maxsize=1)
    loop = asyncio.get_running_loop()
    last_sent_msg_count: dict[str, int] = {}
    last_sent_trade_ts: dict[str, int] = {}

    async def _receive_messages() -> None:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                continue
            msg_type = payload.get("type")
            if msg_type == "subscribe":
                items = payload.get("assets")
                if not isinstance(items, list):
                    continue
                for item in items:
                    game_start_time = None
                    if isinstance(item, str):
                        asset_id = item
                        slug = question = outcome = None
                    elif isinstance(item, dict):
                        asset_id = item.get("asset_id")
                        slug = item.get("slug")
                        question = item.get("question")
                        outcome = item.get("outcome")
                        game_start_time = item.get("gameStartTime")
                    else:
                        continue
                    if not isinstance(asset_id, str) or not asset_id:
                        continue
                    if asset_id in subscribed:
                        continue
                    subscribed.add(asset_id)
                    if isinstance(slug, str) and isinstance(question, str):
                        registry.set_asset_meta(
                            asset_id,
                            slug,
                            question,
                            outcome if isinstance(outcome, str) else None,
                            game_start_time if isinstance(game_start_time, str) else None,
                        )
                    try:
                        registry.get_or_create(asset_id)
                        registry.register_subscriber(asset_id, update_q, loop)
                    except Exception:
                        continue
            elif msg_type == "unsubscribe":
                items = payload.get("assets")
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, str) or not item:
                        continue
                    if item not in subscribed:
                        continue
                    subscribed.remove(item)
                    registry.unregister_subscriber(item, update_q)
                    last_sent_msg_count.pop(item, None)
                    last_sent_trade_ts.pop(item, None)

    receiver_task = asyncio.create_task(_receive_messages())

    try:
        while True:
            if not subscribed:
                await asyncio.sleep(BOOK_MIN_SEND_INTERVAL_S)
                continue

            try:
                await asyncio.wait_for(update_q.get(), timeout=BOOK_MIN_SEND_INTERVAL_S)
            except asyncio.TimeoutError:
                pass

            updates: list[WsPayload] = []
            for asset_id in tuple(subscribed):
                book = registry.active_books.get(asset_id)
                if book is None:
                    book = registry.get_or_create(asset_id)
                if not getattr(book, "ready", True):
                    continue
                msg_count = int(getattr(book, "msg_count", 0))
                last_trade = registry.get_last_trade(asset_id)
                last_trade_ts = int(last_trade.get("timestamp", 0)) if last_trade else 0
                if (
                    last_sent_msg_count.get(asset_id) == msg_count
                    and last_sent_trade_ts.get(asset_id) == last_trade_ts
                ):
                    continue
                last_sent_msg_count[asset_id] = msg_count
                last_sent_trade_ts[asset_id] = last_trade_ts
                updates.append(_build_book_payload(asset_id, book, msg_count, last_trade)) #type: ignore

            if updates:
                await websocket.send_json({"type": "books", "updates": updates})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        print(f"Books WS Error: {exc}")
    finally:
        receiver_task.cancel()
        for asset_id in tuple(subscribed):
            registry.unregister_subscriber(asset_id, update_q)
        await _safe_close(websocket)
