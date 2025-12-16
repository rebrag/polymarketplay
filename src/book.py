import threading
from typing import Dict, List, Tuple, cast
from src.models import WsBookMessage, WsPriceChangeMessage

type PriceSize = Tuple[float, float]

class OrderBook:
    """
    Thread-safe Order Book. 
    Maintains Bids/Asks state from WebSocket events.
    """
    def __init__(self, asset_id: str) -> None:
        # 1. FIX: Standardized variable name (was target_asset_id)
        self.asset_id = asset_id 
        self.lock = threading.Lock()
        
        # State
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.ready = False
        self.msg_count = 0

    def _safe_float(self, val: object) -> float:
        try:
            return float(cast(float | str, val))
        except (ValueError, TypeError):
            return 0.0

    def _quantize(self, price: float) -> float:
        """
        2. FIX: Force prices to 2 decimals to prevent 'Ghost Orders'.
        0.33000001 becomes 0.33, ensuring dict keys match exactly.
        """
        return round(price, 2)

    def on_book_snapshot(self, msg: WsBookMessage) -> None:
        """Callback for 'book' (Snapshot) events"""
        with self.lock:
            # 3. FIX: Ensure we only process the snapshot for THIS asset
            if msg.get("asset_id") != self.asset_id:
                return

            self.msg_count += 1
            if self.ready: return

            self.bids.clear()
            self.asks.clear()

            raw_bids = msg.get("bids", [])
            raw_asks = msg.get("asks", [])

            for level in raw_bids:
                p = self._safe_float(level.get("price"))
                s = self._safe_float(level.get("size"))
                if s > 0: 
                    self.bids[self._quantize(p)] = s

            for level in raw_asks:
                p = self._safe_float(level.get("price"))
                s = self._safe_float(level.get("size"))
                if s > 0: 
                    self.asks[self._quantize(p)] = s

            self.ready = True

    def on_price_change(self, msg: WsPriceChangeMessage) -> None:
        """Callback for 'price_change' (Delta) events"""
        with self.lock:
            self.msg_count += 1
            
            changes = msg.get("price_changes", [])
            for ch in changes:
                # 4. FIX: Use self.asset_id (not target_asset_id)
                if ch.get("asset_id") != self.asset_id:
                    continue

                side = str(ch.get("side", "")).upper()
                p = self._quantize(self._safe_float(ch.get("price"))) # <--- Round key!
                s = self._safe_float(ch.get("size"))

                target_dict = self.bids if side == "BUY" else self.asks
                
                if s == 0.0:
                    # Safe pop: If key doesn't exist (ghost), do nothing
                    target_dict.pop(p, None)
                else:
                    target_dict[p] = s

    def get_snapshot(self, limit: int = 50) -> Tuple[List[PriceSize], List[PriceSize]]:
        """Returns sorted (Bids, Asks) for UI display"""
        with self.lock:
            # Sort Bids Descending (Highest buy first)
            bids_sorted = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)
            # Sort Asks Ascending (Lowest sell first)
            asks_sorted = sorted(self.asks.items(), key=lambda x: x[0])
            
            return bids_sorted[:limit], asks_sorted[:limit]