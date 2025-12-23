import threading
import asyncio
from typing import Dict, List, Tuple, cast
from src.models import WsBookMessage, WsPriceChangeMessage

type PriceSize = Tuple[float, float]

class OrderBook:
    """
    Thread-safe Event-Driven Order Book.
    """
    def __init__(self, asset_id: str) -> None:
        self.asset_id = asset_id
        self.lock = threading.Lock()
        
        # Event used to wake up the server websocket immediately on change
        self.updated_event = asyncio.Event()
        self.loop = asyncio.get_event_loop()
        
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.ready = False
        self.msg_count = 0
        self._queue: List[WsPriceChangeMessage] = []

    def _trigger_update(self) -> None:
        """Schedules the event trigger on the main event loop."""
        self.loop.call_soon_threadsafe(self.updated_event.set)

    def _safe_float(self, val: object) -> float:
        try:
            return float(cast(float | str, val))
        except (ValueError, TypeError):
            return 0.0

    def _quantize(self, price: float) -> float:
        return round(price, 2)

    def _apply_price_change(self, msg: WsPriceChangeMessage) -> None:
        changes = msg.get("price_changes", [])
        for ch in changes:
            if ch.get("asset_id") != self.asset_id:
                continue
            side = str(ch.get("side", "")).upper()
            p = self._quantize(self._safe_float(ch.get("price")))
            s = self._safe_float(ch.get("size"))
            target_dict = self.bids if side == "BUY" else self.asks
            if s < 1e-9:
                target_dict.pop(p, None)
            else:
                target_dict[p] = s

    def on_book_snapshot(self, msg: WsBookMessage) -> None:
        with self.lock:
            if msg.get("asset_id") != self.asset_id:
                return
            self.msg_count += 1
            self.bids.clear()
            self.asks.clear()
            for level in msg.get("bids", []):
                self.bids[self._quantize(self._safe_float(level.get("price")))] = self._safe_float(level.get("size"))
            for level in msg.get("asks", []):
                self.asks[self._quantize(self._safe_float(level.get("price")))] = self._safe_float(level.get("size"))
            if self._queue:
                for pending_msg in self._queue:
                    self._apply_price_change(pending_msg)
                self._queue.clear()
            self.ready = True
        self._trigger_update()

    def on_price_change(self, msg: WsPriceChangeMessage) -> None:
        with self.lock:
            self.msg_count += 1
            if not self.ready:
                self._queue.append(msg)
                return
            self._apply_price_change(msg)
        self._trigger_update()

    def get_snapshot(self, limit: int = 50) -> Tuple[List[PriceSize], List[PriceSize]]:
        with self.lock:
            bids_sorted = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)
            asks_sorted = sorted(self.asks.items(), key=lambda x: x[0])
            return bids_sorted[:limit], asks_sorted[:limit]

    def get_cumulative_values(self, levels: List[PriceSize]) -> List[float]:
        out: List[float] = []
        total = 0.0
        for price, size in levels:
            total += price * size
            out.append(total)
        return out