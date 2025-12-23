from __future__ import annotations
from asyncio import AbstractEventLoop, Queue
from typing import Set

import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()


from src.book import OrderBook
from src.clients import PolyClient, PolySocket
from src.models import WsPriceChangeMessage, GammaEvent, GammaMarket, Order, UserActivityResponse, WsBidAsk, WsPayload, WsBookMessage
from src.utils import filter_markets_by_asset, get_game_data


class MarketRegistry:
    def __init__(self) -> None:
        self.active_books: Dict[str, OrderBook] = {}
        self.active_sockets: Dict[str, PolySocket] = {}
        self.client_counts: Dict[str, int] = {}
        self.poly_client = PolyClient()

        # NEW: subscriber queues per asset + the loop they belong to
        self._subs: Dict[str, Set[Queue[None]]] = {}
        self._loops: Dict[str, AbstractEventLoop] = {}

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
        socket = PolySocket([asset_id])

        # CHANGED: wrap callbacks so we can notify websocket subscribers *on real updates*
        def _on_book(msg: WsBookMessage) -> None:  # msg type matches your WsBookMessage at runtime
            book.on_book_snapshot(msg)
            self.notify_updated(asset_id)

        def _on_price(msg: WsPriceChangeMessage) -> None:
            book.on_price_change(msg)
            self.notify_updated(asset_id)

        socket.on_book = _on_book
        socket.on_price_change = _on_price
        socket.start()

        self.active_books[asset_id] = book
        self.active_sockets[asset_id] = socket
        self.client_counts[asset_id] = 1
        return book
    
    def release(self, asset_id: str) -> None:
        count = self.client_counts.get(asset_id)
        if count is None:
            return

        count -= 1
        if count > 0:
            self.client_counts[asset_id] = count
            return

        sock = self.active_sockets.pop(asset_id, None)
        if sock is not None:
            sock.stop()

        self.active_books.pop(asset_id, None)
        self.client_counts.pop(asset_id, None)



registry = MarketRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    print("Shutting down: Closing all WebSockets...")
    asset_ids = list(registry.active_sockets.keys())
    for aid in asset_ids:
        registry.release(aid)


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


class LimitOrderRequest(BaseModel):
    token_id: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    size: float = Field(gt=0)
    ttl_seconds: int = Field(default=0)
    price_offset_cents: int = Field(default=0, ge=-50, le=50)


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
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/orders/open", response_model=list[Order])
def get_open_orders() -> list[Order]:
    try:
        return registry.poly_client.get_open_orders()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            }
            await websocket.send_json(payload)

    except WebSocketDisconnect:
        registry.release(asset_id)
    except Exception as e:
        print(f"Socket Error: {e}")
        registry.release(asset_id)

