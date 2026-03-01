from __future__ import annotations

# Books stream behavior:
# - True: push to frontend on each backend book event (subject to queue coalescing).
# - False: cap frontend push rate using BOOK_MAX_HZ in frontend_ws.py.
BOOKS_STREAM_FULL_EVENT_DRIVEN: bool = True

# PolySocket asset subscription behavior:
# - True: disable subscribe/unsubscribe flush delay for immediate updates.
# - False: keep a short debounce delay.
POLYSOCKET_DISABLE_ASSET_FLUSH_DELAY: bool = False

# default-smallest-size-level strategy tuning
# Negative level range evaluated for min-size selection (inclusive).
# Example: max=-1, min=-4 evaluates -1, -2, -3, -4.
DEFAULT_SMALLEST_SIZE_LEVEL_MAX_LEVEL: int = -1
DEFAULT_SMALLEST_SIZE_LEVEL_MIN_LEVEL: int = -4
DEFAULT_SMALLEST_SIZE_LEVEL_MIN_BUY_PRICE: float = 0.10
DEFAULT_SMALLEST_SIZE_LEVEL_MAX_SELL_PRICE: float = 0.85

# Single source of truth for auto-subscribe timing.
AUTO_SUBSCRIBE_ENABLED: bool = True
AUTO_SUBSCRIBE_REFRESH_INTERVAL_S: float = 200.0
AUTO_SUBSCRIBE_GAMESTART_WINDOW_BEFORE_HOURS: float = 3.0
AUTO_SUBSCRIBE_GAMESTART_WINDOW_HOURS: float = 2.0
AUTO_SUBSCRIBE_END_DATE_WINDOW_BEFORE_HOURS: float = 3.0
AUTO_SUBSCRIBE_END_DATE_WINDOW_HOURS: float = 24.0

# Backward-compatible aliases. Prefer the explicit GAMESTART/END_DATE constants above.
AUTO_SUBSCRIBE_WINDOW_BEFORE_HOURS: float = AUTO_SUBSCRIBE_GAMESTART_WINDOW_BEFORE_HOURS
AUTO_SUBSCRIBE_WINDOW_HOURS: float = AUTO_SUBSCRIBE_GAMESTART_WINDOW_HOURS
