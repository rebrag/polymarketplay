from __future__ import annotations
from asyncio import AbstractEventLoop, Queue
from typing import Set
import logging
import time

import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()
import os


from src.book import OrderBook
from src.clients import PolyClient, PolySocket, UserSocket
from src.models import (
    BalanceAllowanceResponse,
    WsPriceChangeMessage,
    WsTickSizeChangeMessage,
    GammaEvent,
    GammaMarket,
    Order,
    UserActivityResponse,
    WsBidAsk,
    WsPayload,
    WsBookMessage,
)
from py_clob_client.clob_types import OpenOrderParams  # type: ignore
from src.utils import filter_markets_by_asset, get_game_data
from src.config import POLY_TAG_ID


class MarketRegistry:
    def __init__(self) -> None:
        self.active_books: Dict[str, OrderBook] = {}
        self.client_counts: Dict[str, int] = {}
        self.poly_client = PolyClient()

        # NEW: subscriber queues per asset + the loop they belong to
        self._subs: Dict[str, Set[Queue[None]]] = {}
        self._loops: Dict[str, AbstractEventLoop] = {}
        self._tracked_assets: set[str] = set()
        self._socket: PolySocket | None = None
        self._socket_lock = threading.Lock()
        self._logged_books: set[str] = set()
        self._logged_price_changes: set[str] = set()
        self._order_subs: set[Queue[dict[str, object]]] = set()
        self._order_loops: Dict[Queue[dict[str, object]], AbstractEventLoop] = {}
        self._user_socket: UserSocket | None = None
        self._user_lock = threading.Lock()
        self._last_order_ws_accept_ts: float | None = None
        self._last_order_ws_register_ts: float | None = None
        self._last_user_event_ts: float | None = None
        self._last_user_event_type: str | None = None
        self._user_event_count = 0

    def register_subscriber(self, asset_id: str, q: Queue[None], loop: AbstractEventLoop) -> None:
        self._subs.setdefault(asset_id, set()).add(q)
        self._loops.setdefault(asset_id, loop)

    def unregister_subscriber(self, asset_id: str, q: Queue[None]) -> None:
        subs = self._subs.get(asset_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                self._subs.pop(asset_id, None)
                self._loops.pop(asset_id, None)

    def notify_updated(self, asset_id: str) -> None:
        subs = self._subs.get(asset_id)
        loop = self._loops.get(asset_id)
        if not subs or loop is None:
            return

        # Coalesce updates: if a queue is full, skip (it already has a pending “tick”)
        for q in tuple(subs):
            def _put_one(q_local: Queue[None] = q) -> None:
                try:
                    q_local.put_nowait(None)
                except Exception:
                    # QueueFull or loop shutdown; ignore
                    pass

            loop.call_soon_threadsafe(_put_one)

    def get_or_create(self, asset_id: str) -> OrderBook:
        if asset_id in self.active_books:
            self.client_counts[asset_id] += 1
            return self.active_books[asset_id]

        book = OrderBook(asset_id)
        self.active_books[asset_id] = book
        self.client_counts[asset_id] = 1

        with self._socket_lock:
            self._tracked_assets.add(asset_id)
            if self._socket is None:
                self._socket = PolySocket(list(self._tracked_assets))

                def _on_book(msg: WsBookMessage) -> None:
                    msg_asset = msg.get("asset_id")
                    if not msg_asset:
                        return
                    asset_id_str = str(msg_asset)
                    target = self.active_books.get(asset_id_str)
                    if not target:
                        return
                    target.on_book_snapshot(msg)
                    if asset_id_str not in self._logged_books:
                        self._logged_books.add(asset_id_str)
                        print(f"Book snapshot received (asset_id={asset_id_str})")
                    self.notify_updated(asset_id_str)

                def _on_price(msg: WsPriceChangeMessage) -> None:
                    changes = msg.get("price_changes", [])
                    assets = {str(ch.get("asset_id")) for ch in changes if ch.get("asset_id")}
                    for aid in assets:
                        target = self.active_books.get(aid)
                        if not target:
                            continue
                        target.on_price_change(msg)
                        if aid not in self._logged_price_changes:
                            self._logged_price_changes.add(aid)
                            print(f"Price change received (asset_id={aid})")
                        self.notify_updated(aid)

                def _on_tick(msg: WsTickSizeChangeMessage) -> None:
                    msg_asset = msg.get("asset_id")
                    if not msg_asset:
                        return
                    asset_id_str = str(msg_asset)
                    target = self.active_books.get(asset_id_str)
                    if not target:
                        return
                    target.on_tick_size_change(msg)
                    print(f"Tick size change received (asset_id={asset_id_str})")
                    self.notify_updated(asset_id_str)

                self._socket.on_book = _on_book
                self._socket.on_price_change = _on_price
                self._socket.on_tick_size_change = _on_tick
                self._socket.start()
            else:
                self._socket.update_assets(list(self._tracked_assets), force_reconnect=True)

        return book
    
    def release(self, asset_id: str) -> None:
        count = self.client_counts.get(asset_id)
        if count is None:
            return

        count -= 1
        if count > 0:
            self.client_counts[asset_id] = count
            return

        self.active_books.pop(asset_id, None)
        self.client_counts.pop(asset_id, None)

        with self._socket_lock:
            self._tracked_assets.discard(asset_id)
            if self._socket is not None:
                if not self._tracked_assets:
                    self._socket.stop()
                    self._socket = None
                else:
                    self._socket.update_assets(list(self._tracked_assets))

    def register_order_subscriber(self, q: Queue[dict[str, object]], loop: AbstractEventLoop) -> None:
        print(f"Registering order subscriber (pre_count={len(self._order_subs)})")
        self._order_subs.add(q)
        self._order_loops[q] = loop
        print(f"Order subscriber registered (count={len(self._order_subs)})")
        self._last_order_ws_register_ts = time.time()
        self.ensure_user_socket()

    def unregister_order_subscriber(self, q: Queue[dict[str, object]]) -> None:
        self._order_subs.discard(q)
        self._order_loops.pop(q, None)
        if not self._order_subs:
            with self._user_lock:
                if self._user_socket is not None:
                    print("Stopping user websocket (no order subscribers).")
                    self._user_socket.stop()
                    self._user_socket = None

    def ensure_user_socket(self) -> None:
        with self._user_lock:
            if self._user_socket is None:
                print(f"Starting user websocket for order updates... (pid={os.getpid()})")
                auth = self.poly_client.get_user_ws_auth()
                self._user_socket = UserSocket(auth)
                self._user_socket.on_event = self._handle_user_event
                self._user_socket.start()

    def _handle_user_event(self, ev: dict[str, object]) -> None:
        self._last_user_event_ts = time.time()
        self._last_user_event_type = str(ev.get("type", ""))
        self._user_event_count += 1
        if str(ev.get("event_type", "")) == "trade":
            # Trade events are expected; avoid noisy logging during normal operation.
            pass
        else:
            print(f"User WS event received (type={self._last_user_event_type})")
        event_type = str(ev.get("event_type", ""))
        if event_type == "order":
            order_type = str(ev.get("type", "")).upper()
            oid = str(ev.get("id", ""))
            if not oid:
                return
            order: Order = {
                "orderID": oid,
                "price": str(ev.get("price", "")),
                "size": str(ev.get("original_size", "")),
                "side": str(ev.get("side", "")),
                "asset_id": str(ev.get("asset_id", "")),
                "market": str(ev.get("market", "")),
                "outcome": str(ev.get("outcome", "")),
                "expiration": int(float(ev.get("expiration", 0) or 0)),
                "timestamp": int(ev.get("timestamp", 0) or 0),
                "owner": str(ev.get("owner", "")),
                "hash": "",
            }
            msg_type = "update"
            if order_type == "PLACEMENT":
                msg_type = "opened"
            elif order_type == "CANCELLATION":
                msg_type = "closed"
            payload: dict[str, object] = {"type": msg_type, "order": order, "event": order_type}
        elif event_type == "trade":
            maker_orders = ev.get("maker_orders", [])
            if not isinstance(maker_orders, list) or not maker_orders:
                return
            payloads: list[dict[str, object]] = []
            trade_id = str(ev.get("id", ""))
            trade_status = str(ev.get("status", ""))
            api_key = ""
            try:
                api_key = registry.poly_client.get_api_creds().api_key
            except Exception:
                api_key = ""

            taker_order_id = str(ev.get("taker_order_id", ""))
            trade_owner = str(ev.get("trade_owner", "")) or str(ev.get("owner", ""))
            if api_key and taker_order_id and trade_owner == api_key:
                order: Order = {
                    "orderID": taker_order_id,
                    "price": str(ev.get("price", "")),
                    "size": str(ev.get("size", "")),
                    "side": str(ev.get("side", "")),
                    "asset_id": str(ev.get("asset_id", "")),
                    "market": str(ev.get("market", "")),
                    "outcome": str(ev.get("outcome", "")),
                    "expiration": 0,
                    "timestamp": int(ev.get("timestamp", 0) or 0),
                    "owner": trade_owner,
                    "hash": "",
                }
                payloads.append(
                    {"type": "closed", "order": order, "event": "TRADE", "trade_id": trade_id, "trade_status": trade_status}
                )
            else:
                for maker in maker_orders:
                    if not isinstance(maker, dict):
                        continue
                    if api_key and str(maker.get("owner", "")) != api_key:
                        continue
                    oid = str(maker.get("order_id", ""))
                    if not oid:
                        continue
                    order: Order = {
                        "orderID": oid,
                        "price": str(maker.get("price", "")),
                        "size": str(maker.get("matched_amount", "")),
                        "side": str(maker.get("side", "")) or str(ev.get("side", "")),
                        "asset_id": str(maker.get("asset_id", "")) or str(ev.get("asset_id", "")),
                        "market": str(ev.get("market", "")),
                        "outcome": str(maker.get("outcome", "")) or str(ev.get("outcome", "")),
                        "expiration": 0,
                        "timestamp": int(ev.get("timestamp", 0) or 0),
                        "owner": str(maker.get("owner", "")),
                        "hash": "",
                    } 
                    payloads.append(
                        {"type": "closed", "order": order, "event": "TRADE", "trade_id": trade_id, "trade_status": trade_status}
                    )
            if not payloads:
                return
            for payload in payloads:
                self._dispatch_order_payload(payload)
            return
        else:
            return

        self._dispatch_order_payload(payload)

    def _dispatch_order_payload(self, payload: dict[str, object]) -> None:
        if not self._order_subs:
            print("User WS event dropped (no subscribers)")
        for q in tuple(self._order_subs):
            loop = self._order_loops.get(q)
            if loop is None:
                continue
            def _put_one(q_local: Queue[dict[str, object]] = q, payload_local: dict[str, object] = payload) -> None:
                try:
                    q_local.put_nowait(payload_local)
                except Exception:
                    pass
            loop.call_soon_threadsafe(_put_one)

    def get_user_socket_status(self) -> dict[str, object]:
        connected = False
        status: dict[str, object] = {}
        if self._user_socket is not None:
            status = self._user_socket.get_status()
            connected = bool(status.get("connected"))
        return {
            "has_socket": self._user_socket is not None,
            "connected": connected,
            "subscribers": len(self._order_subs),
            "pid": os.getpid(),
            "status": status,
            "last_order_ws_accept_ts": self._last_order_ws_accept_ts,
            "last_order_ws_register_ts": self._last_order_ws_register_ts,
            "last_user_event_ts": self._last_user_event_ts,
            "last_user_event_type": self._last_user_event_type,
            "user_event_count": self._user_event_count,
        }


registry = MarketRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        registry.ensure_user_socket()
    except Exception as e:
        print(f"User WS startup failed: {e}")
    yield
    print("Shutting down: Closing all WebSockets...")
    asset_ids = list(registry.active_books.keys())
    for aid in asset_ids:
        registry.release(aid)
    with registry._user_lock:
        if registry._user_socket is not None:
            registry._user_socket.stop()
            registry._user_socket = None


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/events/resolve", response_model=GammaEvent)
def resolve_event(query: str, min_volume: float = 0.0) -> GammaEvent:
    data = get_game_data(query)
    if not data:
        raise HTTPException(status_code=404, detail="Event not found")

    filtered_markets: list[GammaMarket] = []
    raw_markets = data.get("markets", [])

    for m in raw_markets:
        vol = float(m.get("volumeNum", 0.0))
        if vol >= min_volume:
            filtered_markets.append(m)

    data["markets"] = filtered_markets
    return data


@app.get("/events/list", response_model=list[GammaEvent])
def list_events(
    tag_id: int = 1,
    limit: int = 20,
    window_hours: int = 24,
    window_before_hours: int = 0,
    volume_min: float = 1000,
) -> list[GammaEvent]:
    now = datetime.now(timezone.utc)
    end_date_min = (now - timedelta(hours=4)).isoformat()
    end_date_max = (now + timedelta(hours=24)).isoformat()
    fetch_limit = max(limit, 500)
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
    total_markets = 0
    for ev in events:
        markets = ev.get("markets", [])
        if isinstance(markets, list):
            total_markets += len(markets)
    print(f"Gamma events fetched: {len(events)} events, {total_markets} markets")
    window_start = now - timedelta(hours=window_before_hours)
    window_end = now + timedelta(hours=window_hours)

    def _parse(dt_str: str | None) -> datetime | None:
        if not dt_str:
            return None
        cleaned = dt_str.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None

    filtered: list[GammaEvent] = []
    for ev in events:
        end_raw = ev.get("endDate")
        end_dt = _parse(str(end_raw)) if end_raw else None
        if end_dt and window_start <= end_dt <= window_end:
            filtered.append(ev)
    def _sort_key(ev: GammaEvent) -> datetime:
        end_raw = ev.get("endDate")
        end_dt = _parse(str(end_raw)) if end_raw else None
        if end_dt:
            return end_dt
        return now

    filtered.sort(key=_sort_key)
    print(f"Gamma events in window: {len(filtered)} (fetch_limit={fetch_limit})")
    return filtered[:limit]


@app.get("/debug/events_raw")
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


@app.get("/debug/event_by_slug")
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


@app.get("/user/resolve", response_model=UserActivityResponse)
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


@app.get("/user/balance_allowance", response_model=BalanceAllowanceResponse)
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


@app.get("/user/balance")
def get_balance() -> dict[str, str]:
    try:
        data = registry.poly_client.get_balance_allowance()
        return {"balance": data["balance"]}
    except Exception as e:
        logger.exception("Balance fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/open_orders_raw")
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


def _normalize_open_orders(raw_orders: list[dict[str, object]]) -> list[Order]:
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
            "side": str(o.get("side", "")),
            "asset_id": str(o.get("asset_id") or o.get("assetId") or o.get("market") or ""),
            "market": str(o.get("market", "")),
            "outcome": str(o.get("outcome", "")),
            "expiration": int(o.get("expiration", 0) or 0),
            "timestamp": int(o.get("timestamp", 0) or o.get("created_at", 0) or 0),
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


# @app.get("/orders/open", response_model=list[Order])
# def get_open_orders_endpoint() -> list[Order]:
#     try:
#         raw_orders = registry.poly_client.get_open_orders()
#         return _normalize_open_orders(raw_orders)  # type: ignore[arg-type]
#     except Exception as e:
#         logger.exception("Open orders fetch failed")
#         raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/auth_status")
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


@app.get("/debug/user_ws")
def debug_user_ws() -> dict[str, object]:
    return registry.get_user_socket_status()

@app.post("/debug/user_ws/start")
def debug_user_ws_start() -> dict[str, object]:
    try:
        registry.ensure_user_socket()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return registry.get_user_socket_status()

@app.get("/user/positions")
def get_positions(address: str, limit: int = 100) -> list[dict[str, object]]:
    try:
        raw = registry.poly_client.get_positions(address, limit=limit)
        filtered: list[dict[str, object]] = []
        for pos in raw:
            size = float(pos.get("size", 0) or 0)
            value = float(pos.get("currentValue", 0) or 0)
            if size > 0 and value > 0:
                filtered.append(pos) # type: ignore
        return filtered
    except Exception as e:
        logger.exception("Positions fetch failed (address=%s limit=%s)", address, limit)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/user/positions/auth")
def get_positions_auth(limit: int = 100) -> list[dict[str, object]]:
    try:
        address = registry.poly_client.get_positions_address()
        if not address:
            raise RuntimeError("Authenticated address unavailable.")
        return registry.poly_client.get_positions(address, limit=limit) # type: ignore
    except Exception as e:
        logger.exception("Auth positions fetch failed (limit=%s)", limit)
        raise HTTPException(status_code=500, detail=str(e))


class LimitOrderRequest(BaseModel):
    token_id: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    size: float = Field(gt=0)
    ttl_seconds: int = Field(default=0)
    price_offset_cents: int = Field(default=0, ge=-50, le=50)

logger = logging.getLogger("polymarket")

@app.post("/orders/limit")
def post_limit_order(req: LimitOrderRequest) -> dict[str, object]:
    """
    Places a limit order at best_bid (BUY) or best_ask (SELL), optionally offset by cents.

    Notes:
    - For BUY, positive offset makes your bid more aggressive (bid higher).
    - For SELL, negative offset makes your ask more aggressive (ask lower).
    """
    try:
        best_price = registry.poly_client.get_best_price(req.token_id, req.side)
        price = best_price + (req.price_offset_cents / 100.0)
        # Avoid nonsense prices
        price = max(0.01, min(0.99, price))

        ttl = req.ttl_seconds
        if  ttl < 0:
            raise HTTPException(status_code=400, detail="ttl_seconds must be >= 0 (or omitted for GTC)")

        result = registry.poly_client.place_limit_order(
            token_id=req.token_id,
            side=req.side,
            size=req.size,
            price=price,
            ttl_seconds=ttl+60,
        )
        return {"ok": True, "placed_price": price, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        # This prints the *actual* reason (403/401/cloudflare html/etc)
        logger.exception("Order Error (token_id=%s side=%s)", req.token_id, req.side)

        # Try to preserve useful structured fields if present (PolyApiException-like)
        status = getattr(e, "status_code", 500)
        err_msg = getattr(e, "error_message", None)

        detail: object = {"error": str(e)}
        if err_msg is not None:
            detail = {"error": str(e), "upstream": err_msg}

        raise HTTPException(status_code=int(status), detail=detail)

class MarketOrderRequest(BaseModel):
    token_id: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    amount: float = Field(gt=0)
    fok_only: bool = False


@app.post("/orders/market")
def post_market_order(req: MarketOrderRequest) -> dict[str, object]:
    try:
        if req.fok_only:
            result = registry.poly_client.place_market_order(
                token_id=req.token_id,
                side=req.side,
                size=req.amount,
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
                best_price = float(asks[0]["price"])
                total_liquidity = sum(float(a.get("size", 0)) for a in asks)
                if best_price > 0:
                    size_shares = req.amount / best_price
            else:
                best_price = float(bids[0]["price"])
                total_liquidity = sum(float(b.get("size", 0)) for b in bids)

        if best_price is not None and total_liquidity < size_shares:
            result = registry.poly_client.place_limit_order(
                token_id=req.token_id,
                side=req.side,
                size=size_shares,
                price=best_price,
                ttl_seconds=None,
            )
            return {
                "ok": True,
                "mode": "limit_fallback",
                "note": "Insufficient immediate liquidity for market order; placed aggressive limit.",
                "placed_price": best_price,
                "result": result,
            }

        result = registry.poly_client.place_market_order(
            token_id=req.token_id,
            side=req.side,
            size=req.amount,
        )
        return {"ok": True, "result": result}
    except Exception as e:
        error_text = str(e)
        if "no orders found to match" in error_text or "couldn't be fully filled" in error_text:
            try:
                best_price = registry.poly_client.get_best_price(req.token_id, "SELL" if req.side == "BUY" else "BUY")
                size_shares = req.amount
                if req.side == "BUY" and best_price > 0:
                    size_shares = req.amount / best_price
                result = registry.poly_client.place_limit_order(
                    token_id=req.token_id,
                    side=req.side,
                    size=size_shares,
                    price=best_price,
                    ttl_seconds=None,
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


# @app.get("/orders/open", response_model=list[Order])
# def get_open_orders() -> list[Order]:
#     try:
#         return registry.poly_client.get_open_orders()
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


class CancelOrderRequest(BaseModel):
    order_id: str = Field(min_length=1)


@app.post("/orders/cancel")
def cancel_order(req: CancelOrderRequest) -> dict[str, object]:
    try:
        result = registry.poly_client.cancel_order(req.order_id)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/watch/user/{address}")
async def watch_user_endpoint(websocket: WebSocket, address: str, min_volume: float = 0.0):
    await websocket.accept()
    sent_asset_ids: set[str] = set()
    print(f"👀 Watching user {address} (Scan interval: 2s)")
    try:
        while True:
            trades = registry.poly_client.get_trades(address, limit=20)
            if trades:
                await websocket.send_json({"type": "recent_trades", "trades": trades})

            new_asset_ids: set[str] = set()
            new_event_slugs: set[str] = set()

            for t in trades:
                asset = t.get("asset")
                if asset and asset not in sent_asset_ids:
                    new_asset_ids.add(asset)
                    if t.get("eventSlug"):
                        new_event_slugs.add(t["eventSlug"])

            if new_asset_ids:
                print(f"Found {len(new_asset_ids)} new traded tokens. Resolving...")

                batch_markets: list[GammaMarket] = []
                for evt_slug in new_event_slugs:
                    event_data = get_game_data(evt_slug)
                    if not event_data:
                        continue
                    filtered = filter_markets_by_asset(event_data["markets"], new_asset_ids, min_volume)
                    batch_markets.extend(filtered)

                if batch_markets:
                    await websocket.send_json({"type": "new_markets", "markets": batch_markets})
                    sent_asset_ids.update(new_asset_ids)

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        print(f"Stopped watching user: {address}")
    except Exception as e:
        print(f"Error watching user: {e}")
        await websocket.close()


@app.websocket("/ws/orders")
@app.websocket("/ws/user")
async def orders_websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    print(f"Orders WS accepted (pid={os.getpid()})")
    registry._last_order_ws_accept_ts = time.time()
    last_open: dict[str, Order] = {}
    q: Queue[dict[str, object]] = Queue(maxsize=200)
    ping_task: asyncio.Task[None] | None = None
    try:
        registry.register_order_subscriber(q, asyncio.get_running_loop())
        print(f"Orders WS registered (subscribers={len(registry._order_subs)})")
        await websocket.send_json(
            {"type": "status", "status": "subscribed", "pid": os.getpid(), "server_now": int(time.time())}
        )
        async def _ping_loop() -> None:
            while True:
                await asyncio.sleep(15)
                await websocket.send_json({"type": "ping", "server_now": int(time.time())})

        ping_task = asyncio.create_task(_ping_loop())
        # Initial snapshot from open orders
        try:
            open_orders = await asyncio.to_thread(registry.poly_client.get_open_orders)
            normalized = _normalize_open_orders(open_orders)  # type: ignore[arg-type]
            last_open = {o["orderID"]: o for o in normalized}
            await websocket.send_json(
                {"type": "snapshot", "orders": normalized, "server_now": int(time.time())}
            )
        except Exception as e:
            await websocket.send_json({"type": "error", "error": str(e)})

        while True:
            msg = await q.get()
            msg["server_now"] = int(time.time())
            try:
                await websocket.send_json(msg)
            except WebSocketDisconnect:
                break
            except Exception:
                break
    except WebSocketDisconnect:
        print("Orders WS disconnected")
    except Exception as e:
        print(f"Orders WS error: {e}")
    finally:
        registry.unregister_order_subscriber(q)
        if ping_task is not None:
            ping_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/{asset_id}")
async def websocket_endpoint(websocket: WebSocket, asset_id: str) -> None:
    await websocket.accept()
    try:
        book = registry.get_or_create(asset_id)
    except Exception:
        await websocket.close()
        return

    last_sent = -1
    try:
        while True:
            if not getattr(book, "ready", True):
                await websocket.send_json({"status": "loading", "asset_id": asset_id})
                await asyncio.sleep(0.05)
                continue

            msg_count = int(getattr(book, "msg_count", 0))
            if msg_count == last_sent:
                await asyncio.sleep(0.001)  # responsive, low CPU
                continue

            last_sent = msg_count

            bids, asks = book.get_snapshot(limit=15)
            bid_cum = book.get_cumulative_values(bids)
            ask_cum = book.get_cumulative_values(asks)

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
            await websocket.send_json(payload)

    except WebSocketDisconnect:
        registry.release(asset_id)
    except Exception as e:
        print(f"Socket Error: {e}")
        registry.release(asset_id)

