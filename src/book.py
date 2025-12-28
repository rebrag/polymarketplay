import threading
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple, cast
from src.models import WsBookMessage, WsPriceChangeMessage, WsTickSizeChangeMessage

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
        self.tick_size = 0.01
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
        tick = Decimal(str(self.tick_size))
        if tick <= 0:
            return float(price)
        quant = (Decimal(str(price)) / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
        return float(quant)

    def on_tick_size_change(self, msg: WsTickSizeChangeMessage) -> None:
        if msg.get("asset_id") != self.asset_id:
            return
        raw = msg.get("tick_size")
        try:
            next_tick = float(raw) if raw is not None else None
        except (ValueError, TypeError):
            next_tick = None
        if not next_tick or next_tick <= 0:
            return
        with self.lock:
            if self.tick_size == next_tick:
                return
            self.tick_size = next_tick
            bids: Dict[float, float] = {}
            asks: Dict[float, float] = {}
            for p, s in self.bids.items():
                qp = self._quantize(p)
                bids[qp] = bids.get(qp, 0.0) + s
            for p, s in self.asks.items():
                qp = self._quantize(p)
                asks[qp] = asks.get(qp, 0.0) + s
            self.bids = bids
            self.asks = asks
        self._trigger_update()

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
            bids_raw = msg.get("bids", [])
            asks_raw = msg.get("asks", [])
            inferred = self._infer_tick_size(bids_raw, asks_raw)
            if inferred is not None and inferred > 0 and inferred != self.tick_size:
                self.tick_size = inferred
            self.bids.clear()
            self.asks.clear()
            for level in bids_raw:
                self.bids[self._quantize(self._safe_float(level.get("price")))] = self._safe_float(level.get("size"))
            for level in asks_raw:
                self.asks[self._quantize(self._safe_float(level.get("price")))] = self._safe_float(level.get("size"))
            if self._queue:
                for pending_msg in self._queue:
                    self._apply_price_change(pending_msg)
                self._queue.clear()
            self.ready = True
        self._trigger_update()

    def _infer_tick_size(
        self,
        bids: list[dict[str, object]],
        asks: list[dict[str, object]],
    ) -> float | None:
        prices: list[float] = []
        for level in bids:
            p = self._safe_float(level.get("price"))
            if p > 0:
                prices.append(p)
        for level in asks:
            p = self._safe_float(level.get("price"))
            if p > 0:
                prices.append(p)
        if len(prices) < 2:
            return None
        prices = sorted(set(prices))
        min_diff = None
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            if diff <= 0:
                continue
            min_diff = diff if min_diff is None else min(min_diff, diff)
        if min_diff is None:
            return None
        # normalize to common tick sizes
        for tick in (0.0001, 0.001, 0.01, 0.1):
            if abs(min_diff - tick) < tick / 10:
                return tick
        return min_diff

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
