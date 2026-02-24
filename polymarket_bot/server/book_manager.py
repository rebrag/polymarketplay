from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
from asyncio import AbstractEventLoop, Queue
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Literal, Set, TypedDict, cast

from polymarket_bot.book import OrderBook
from polymarket_bot.clients import PolyClient, PolySocket, UserSocket
from polymarket_bot.models import (
    Order,
    WsBookMessage,
    WsLastTrade,
    WsLastTradePriceMessage,
    WsPriceChangeMessage,
    WsTickSizeChangeMessage,
)
from polymarket_bot.server.helpers import _to_float, _to_int, _to_side
from polymarket_bot.server.models import AutoPairConfig
from polymarket_bot.server.strategies import OrderIntent, PairContext, get_strategy


class AssetMeta(TypedDict):
    slug: str
    question: str
    outcome: str
    game_start_ts: float | None


class BookManager:
    def __init__(self) -> None:
        self.active_books: Dict[str, OrderBook] = {}
        self.client_counts: Dict[str, int] = {}
        self.poly_client = PolyClient()
        self._subs: Dict[str, Set[Queue[None]]] = {}
        self._loops: Dict[str, AbstractEventLoop] = {}
        self._tracked_assets: set[str] = set()
        # Upstream market data socket (server -> Polymarket CLOB WS).
        self._market_feed_socket: PolySocket | None = None
        self._market_feed_socket_lock = threading.Lock()
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
        self._asset_meta: Dict[str, AssetMeta] = {}
        self._market_assets: Dict[str, set[str]] = {}
        self._market_threads: Dict[str, threading.Thread] = {}
        self._market_stops: Dict[str, threading.Event] = {}
        self._last_trades: Dict[str, WsLastTrade] = {}
        self._auto_pairs: Dict[str, AutoPairConfig] = {}
        self._auto_lock = threading.Lock()
        self._auto_stop = threading.Event()
        self._auto_thread: threading.Thread | None = None
        self._positions_lock = threading.Lock()
        self._positions_cache: Dict[str, float] = {}
        self._positions_last_fetch = 0.0
        self._positions_refresh_interval_s = 60.0
        self._auto_last_submit_ts: Dict[tuple[str, str], float] = {}
        self._auto_submit_cooldown_s = 3.0
        self._auto_pending_submits: Dict[tuple[str, str], tuple[float, float]] = {}
        self._auto_pending_timeout_s = 20.0
        self._auto_pair_last_fill_ts: Dict[str, float] = {}
        self._auto_fill_repost_cooldown_s = 4.0
        self._open_orders_lock = threading.Lock()
        self._open_orders_by_id: Dict[str, Order] = {}
        self._open_orders_initialized = False
        self._auto_subscribe_lock = threading.Lock()
        self._auto_subscribe_stop = threading.Event()
        self._auto_subscribe_thread: threading.Thread | None = None
        self._auto_subscribe_enabled = False
        self._auto_subscribe_volume_threshold = 10_000.0
        self._auto_subscribe_refresh_interval_s = 30.0
        self._auto_subscribe_window_before_h = 1.0
        self._auto_subscribe_window_after_h = 1.0
        self._auto_subscribe_include_more_markets = True
        self._auto_subscribe_track_all_outcomes = True
        self._auto_subscribe_managed_assets: set[str] = set()
        self._auto_subscribe_items: dict[str, dict[str, object]] = {}
        self._auto_subscribe_last_run_ts: float | None = None
        self._auto_subscribe_last_error: str | None = None

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

        for q in tuple(subs):
            def _put_one(q_local: Queue[None] = q) -> None:
                try:
                    q_local.put_nowait(None)
                except Exception:
                    pass

            loop.call_soon_threadsafe(_put_one)

    def subscribe_to_asset(self, asset_id: str) -> OrderBook:
        if asset_id in self.active_books:
            self.client_counts[asset_id] += 1
            return self.active_books[asset_id]

        book = OrderBook(asset_id)
        self.active_books[asset_id] = book
        self.client_counts[asset_id] = 1
        self._ensure_logger(asset_id)

        with self._market_feed_socket_lock:
            self._tracked_assets.add(asset_id)
            if self._market_feed_socket is None:
                self._market_feed_socket = PolySocket(list(self._tracked_assets))

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
                        print(f"Book snapshot received (market_id={asset_id_str})")
                    self.notify_updated(asset_id_str)

                def _on_price(msg: WsPriceChangeMessage) -> None:
                    changes = msg.get("price_changes", [])
                    assets = {str(ch.get("asset_id")) for ch in changes if ch.get("asset_id")}
                    for market_id in assets:
                        target = self.active_books.get(market_id)
                        if not target:
                            continue
                        target.on_price_change(msg)
                        if market_id not in self._logged_price_changes:
                            self._logged_price_changes.add(market_id)
                            print(f"Price change received (market_id={market_id})")
                        self.notify_updated(market_id)

                def _on_tick(msg: WsTickSizeChangeMessage) -> None:
                    msg_asset = msg.get("asset_id")
                    if not msg_asset:
                        return
                    asset_id_str = str(msg_asset)
                    target = self.active_books.get(asset_id_str)
                    if not target:
                        return
                    target.on_tick_size_change(msg)
                    print(f"Tick size change received (market_id={asset_id_str})")
                    self.notify_updated(asset_id_str)

                def _on_last_trade(msg: WsLastTradePriceMessage) -> None:
                    msg_asset = msg.get("market_id")
                    if not msg_asset:
                        return
                    asset_id_str = str(msg_asset)
                    try:
                        price_val = float(msg.get("price", "0") or 0)
                    except (TypeError, ValueError):
                        price_val = 0.0
                    try:
                        size_val = float(msg.get("size", "0") or 0)
                    except (TypeError, ValueError):
                        size_val = 0.0
                    try:
                        ts_val = int(float(msg.get("timestamp", "0") or 0))
                    except (TypeError, ValueError):
                        ts_val = 0
                    side_val = str(msg.get("side", "")).upper() or "BUY"
                    self._last_trades[asset_id_str] = {
                        "price": price_val,
                        "size": size_val,
                        "side": cast(Literal["BUY", "SELL"], side_val),
                        "timestamp": ts_val,
                    }
                    # print(
                    #     "Last trade received (asset_id=%s side=%s price=%s size=%s ts=%s)",
                    #     asset_id_str,
                    #     side_val,
                    #     price_val,
                    #     size_val,
                    #     ts_val,
                    # )
                    self.notify_updated(asset_id_str)

                self._market_feed_socket.on_book = _on_book
                self._market_feed_socket.on_price_change = _on_price
                self._market_feed_socket.on_tick_size_change = _on_tick
                self._market_feed_socket.on_last_trade = _on_last_trade
                self._market_feed_socket.start()
            else:
                self._market_feed_socket.update_assets(list(self._tracked_assets), force_reconnect=True)

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
        self._stop_logger(asset_id)

        with self._market_feed_socket_lock:
            self._tracked_assets.discard(asset_id)
            if self._market_feed_socket is not None:
                if not self._tracked_assets:
                    self._market_feed_socket.stop()
                    self._market_feed_socket = None
                else:
                    self._market_feed_socket.update_assets(list(self._tracked_assets))

    def register_order_subscriber(self, q: Queue[dict[str, object]], loop: AbstractEventLoop) -> None:
        print(f"Registering order subscriber (pre_count={len(self._order_subs)})")
        self._order_subs.add(q)
        self._order_loops[q] = loop
        print(f"Order subscriber registered (count={len(self._order_subs)})")
        self._last_order_ws_register_ts = time.time()
        self.ensure_user_socket()

    def set_auto_pair(self, config: AutoPairConfig) -> None:
        with self._auto_lock:
            self._auto_pairs[config.pair_key] = config
        if config.enabled:
            try:
                self.ensure_user_socket()
            except Exception:
                pass
            self._ensure_open_orders_index()
            for asset in config.assets:
                try:
                    self.subscribe_to_asset(asset)
                except Exception:
                    pass
            self._ensure_auto_loop()

    def clear_auto_pair(self, pair_key: str) -> None:
        with self._auto_lock:
            self._auto_pairs.pop(pair_key, None)

    def disable_auto_trading(self) -> None:
        with self._auto_lock:
            self._auto_pairs.clear()
        self._auto_stop.set()
        self._auto_thread = None

    def _ensure_auto_loop(self) -> None:
        if self._auto_thread and self._auto_thread.is_alive():
            return
        self._auto_stop.clear()
        self._auto_thread = threading.Thread(target=self._run_auto_loop, daemon=True)
        self._auto_thread.start()

    def _get_positions_cache(self) -> Dict[str, float]:
        now = time.time()
        with self._positions_lock:
            if self._positions_cache and (now - self._positions_last_fetch) < self._positions_refresh_interval_s:
                return dict(self._positions_cache)
        address = self.poly_client.get_positions_address()
        if not address:
            with self._positions_lock:
                return dict(self._positions_cache)
        positions = self.poly_client.get_positions(address, limit=200)
        cache: Dict[str, float] = {}
        for pos in positions:
            asset = str(pos.get("asset") or "")
            if not asset:
                continue
            try:
                size = float(pos.get("size") or 0)
            except (TypeError, ValueError):
                size = 0.0
            cache[asset] = size
        with self._positions_lock:
            self._positions_cache = cache
            self._positions_last_fetch = now
            return dict(self._positions_cache)

    def _apply_fill_to_positions(self, order_obj: dict[str, object]) -> None:
        asset = str(order_obj.get("asset_id") or "")
        if not asset:
            return
        side = str(order_obj.get("side", "")).upper()
        if side not in {"BUY", "SELL"}:
            return
        try:
            size = float(order_obj.get("size") or 0)
        except (TypeError, ValueError):
            size = 0.0
        if size <= 0:
            return
        delta = size if side == "BUY" else -size
        with self._positions_lock:
            current = float(self._positions_cache.get(asset, 0.0))
            next_size = current + delta
            if next_size <= 1e-9:
                self._positions_cache.pop(asset, None)
            else:
                self._positions_cache[asset] = next_size

    def _decimals_for_tick(self, tick: float) -> int:
        if not tick or tick <= 0:
            return 2
        raw = f"{tick:.10f}".rstrip("0")
        parts = raw.split(".")
        return len(parts[1]) if len(parts) > 1 else 0

    def _build_bid_placements(self, prices: list[float], tick: float) -> list[float]:
        out: list[float] = []
        prev: float | None = None
        decimals = self._decimals_for_tick(tick)

        def rounded(val: float) -> float:
            return round(val, decimals)

        def push_unique(val: float) -> None:
            if not out:
                out.append(val)
                return
            if abs(out[-1] - val) >= tick / 2:
                out.append(val)

        for price in prices:
            if prev is not None and prev - price > tick:
                push_unique(rounded(price + tick))
                push_unique(rounded(price))
            else:
                push_unique(rounded(price))
            prev = price
        return out

    def _build_ask_placements(self, prices: list[float], tick: float) -> list[float]:
        out: list[float] = []
        prev: float | None = None
        decimals = self._decimals_for_tick(tick)

        def rounded(val: float) -> float:
            return round(val, decimals)

        def push_unique(val: float) -> None:
            if not out:
                out.append(val)
                return
            if abs(out[-1] - val) >= tick / 2:
                out.append(val)

        for price in prices:
            if prev is not None and price - prev > tick:
                push_unique(rounded(prev + tick))
                push_unique(rounded(price))
            else:
                push_unique(rounded(price))
            prev = price
        return out

    def _price_for_level(self, book: OrderBook, side: str, level: int) -> float | None:
        bids, asks = book.get_snapshot(limit=100)
        if not bids or not asks:
            return None
        bid_prices = [p for p, _ in bids]
        ask_prices = [p for p, _ in asks]
        best_bid = bid_prices[0]
        best_ask = ask_prices[0]
        tick = book.tick_size or 0.01

        if level <= 0:
            idx = min(abs(level), max(len(bid_prices), len(ask_prices)) - 1)
            if side == "BUY":
                placements = self._build_bid_placements(bid_prices, tick)
                return placements[idx] if idx < len(placements) else best_bid
            placements = self._build_ask_placements(ask_prices, tick)
            return placements[idx] if idx < len(placements) else best_ask

        buy_price = min(best_ask - tick, best_bid + level * tick)
        sell_price = max(best_bid + tick, best_ask - level * tick)
        return buy_price if side == "BUY" else sell_price

    def get_price_for_level(self, token_id: str, side: str, level: int) -> float | None:
        book = self.active_books.get(token_id)
        if book is None or not getattr(book, "ready", False):
            return None
        return self._price_for_level(book, side, level)

    def _run_auto_loop(self) -> None:
        while not self._auto_stop.is_set():
            with self._auto_lock:
                configs = [cfg for cfg in self._auto_pairs.values() if cfg.enabled]
            if not configs:
                return
            positions = self._get_positions_cache()
            if not self._ensure_open_orders_index():
                # Fail closed to avoid duplicate placements when open-order state is unavailable.
                self._auto_stop.wait(1.0)
                continue
            open_assets, open_sell_sizes = self._get_open_orders_snapshot()
            # Clear pending markers once the corresponding side appears in open orders.
            for key in list(self._auto_pending_submits.keys()):
                asset, side = key
                if side in open_assets.get(asset, set()):
                    self._auto_pending_submits.pop(key, None)
            now = time.time()
            for config in configs:
                if len(config.assets) < 2:
                    continue
                assets = config.assets[:2]
                books: Dict[str, OrderBook] = {}
                prices: Dict[str, tuple[float, float]] = {}
                for asset in assets:
                    book = self.active_books.get(asset)
                    if not book or not book.ready:
                        books = {}
                        break
                    bids, asks = book.get_snapshot(limit=5)
                    best_bid = bids[0][0] if bids else None
                    best_ask = asks[0][0] if asks else None
                    if best_bid is None or best_ask is None:
                        books = {}
                        break
                    books[asset] = book
                    prices[asset] = (float(best_bid), float(best_ask))
                if len(books) != 2:
                    continue

                bid_sum = sum(prices[a][0] for a in assets)
                ask_sum = sum(prices[a][1] for a in assets)
                buy_allowed = bid_sum * 100 <= config.auto_buy_max_cents
                sell_allowed = ask_sum * 100 >= config.auto_sell_min_cents

                shares = {a: positions.get(a, 0.0) for a in assets}
                both_over = all(s >= config.auto_sell_min_shares for s in shares.values())
                best_bids = {a: prices[a][0] for a in assets}
                last_trades = {
                    a: (self._last_trades.get(a) or {}) for a in assets
                }
                ctx = PairContext(
                    assets=assets,
                    positions=shares,
                    buy_allowed=buy_allowed,
                    sell_allowed=sell_allowed,
                    both_over=both_over,
                    best_bids=best_bids,
                    last_trades=last_trades, #type: ignore
                )
                strategy = get_strategy(getattr(config, "strategy", "default"))
                pair_last_fill = self._auto_pair_last_fill_ts.get(config.pair_key, 0.0)

                for asset in assets:
                    if asset in config.disabled_assets:
                        continue
                    intents = strategy.decide(asset, config, ctx)
                    if not intents:
                        continue

                    settings = config.asset_settings.get(asset)
                    if settings is None or not settings.enabled:
                        continue
                    for intent in intents:
                        trade_side = intent.side
                        if trade_side in open_assets.get(asset, set()):
                            continue
                        submit_key = (asset, trade_side)
                        pending = self._auto_pending_submits.get(submit_key)
                        if pending is not None:
                            pending_ts, _pending_size = pending
                            if now - pending_ts < self._auto_pending_timeout_s:
                                continue
                            self._auto_pending_submits.pop(submit_key, None)
                        last_submit = self._auto_last_submit_ts.get(submit_key, 0.0)
                        if now - last_submit < self._auto_submit_cooldown_s:
                            continue
                        if now - pair_last_fill < self._auto_fill_repost_cooldown_s:
                            continue
                        size_multiplier = 1.0
                        if intent.size_multiplier:
                            size_multiplier = max(0.01, float(intent.size_multiplier))
                        level = settings.level
                        if trade_side == "SELL" and len(assets) >= 2:
                            other_asset = assets[1] if asset == assets[0] else assets[0]
                            other_settings = config.asset_settings.get(other_asset)
                            if other_settings is not None:
                                level = other_settings.level
                        if intent.level is not None:
                            level = intent.level
                        price = self._price_for_level(books[asset], trade_side, level)
                        if price is None:
                            continue
                        price = max(0.01, min(0.99, price))
                        ttl_val = max(0, settings.ttl_seconds)
                        ttl_seconds = None if ttl_val <= 0 else ttl_val + 60
                        order_size = settings.shares * size_multiplier
                        if trade_side == "SELL":
                            pending_sell_size = 0.0
                            for (pending_asset, pending_side), (_ts, pending_sz) in self._auto_pending_submits.items():
                                if pending_asset == asset and pending_side == "SELL":
                                    pending_sell_size += pending_sz
                            available_sell = max(
                                0.0,
                                float(positions.get(asset, 0.0)) - open_sell_sizes.get(asset, 0.0) - pending_sell_size,
                            )
                            if available_sell + 1e-9 < order_size:
                                continue
                        try:
                            self.poly_client.place_limit_order(
                                token_id=asset,
                                side=cast(Literal["BUY", "SELL"], trade_side),
                                size=order_size,
                                price=price,
                                ttl_seconds=ttl_seconds,
                            )
                            self._auto_last_submit_ts[submit_key] = now
                            self._auto_pending_submits[submit_key] = (now, order_size)
                            open_assets.setdefault(asset, set()).add(trade_side)
                            if trade_side == "SELL":
                                open_sell_sizes[asset] = open_sell_sizes.get(asset, 0.0) + order_size
                        except Exception as e:
                            meta = self._asset_meta.get(asset, {})
                            question = meta.get("question") or "unknown"
                            outcome = meta.get("outcome") or "unknown"
                            slug = meta.get("slug") or "unknown"
                            print(
                                "Auto order failed "
                                f"(market={question} outcome={outcome} slug={slug} asset={asset} side={trade_side}): {e}"
                            )

    def _parse_game_start_ts(self, game_start_time: str | None) -> float | None:
        if not game_start_time:
            return None
        text = game_start_time.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def set_asset_meta(
        self,
        asset_id: str,
        slug: str | None,
        question: str | None,
        outcome: str | None,
        game_start_time: str | None = None,
    ) -> None:
        if not slug or not question:
            return
        meta: AssetMeta = {
            "slug": slug,
            "question": question,
            "outcome": outcome or "",
            "game_start_ts": self._parse_game_start_ts(game_start_time),
        }
        self._asset_meta[asset_id] = meta
        key = self._market_key(slug, question)
        self._market_assets.setdefault(key, set()).add(asset_id)
        self._ensure_market_logger(key, slug, question)

    def _safe_slug(self, slug: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", slug).strip("_")
        return cleaned or "unknown"

    def _market_key(self, slug: str, question: str) -> str:
        return f"{self._safe_slug(slug)}::{self._safe_slug(question)}"

    def _ensure_logger(self, asset_id: str) -> None:
        meta = self._asset_meta.get(asset_id)
        if not meta:
            return
        key = self._market_key(meta["slug"], meta["question"])
        if key not in self._market_assets:
            self._market_assets[key] = {asset_id}
        self._ensure_market_logger(key, meta["slug"], meta["question"])

    def _ensure_market_logger(self, key: str, slug: str, question: str) -> None:
        if key in self._market_threads:
            return
        stop_event = threading.Event()
        self._market_stops[key] = stop_event

        def _log_loop() -> None:
            base_dir = Path("logs")
            folder = base_dir / self._safe_slug(slug)
            path = folder / f"{self._safe_slug(question)}.csv"

            def _fmt(val: str) -> str:
                if val == "":
                    return ""
                try:
                    num = float(val)
                except (TypeError, ValueError):
                    return ""
                return f"{num:.6f}".rstrip("0").rstrip(".")

            def _fmt_elapsed(seconds: float | None) -> str:
                if seconds is None:
                    return ""
                return f"{seconds:.3f}".rstrip("0").rstrip(".")

            def _headerize(label: str) -> str:
                cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (label or "").strip()).strip("_").lower()
                return cleaned or "unknown"

            seen_non_empty = False
            last_snapshot: tuple[float | None, float | None, float | None, float | None] | None = None
            last_logged_snapshot: tuple[float | None, float | None, float | None, float | None] | None = None
            last_change_ts = 0.0
            while not stop_event.is_set():
                loop_start = time.time()
                assets = list(self._market_assets.get(key, set()))
                rows: list[tuple[str, str, str]] = []
                raw_rows: list[tuple[str, float | None, float | None]] = []
                game_start_ts: float | None = None
                for aid in assets:
                    meta = self._asset_meta.get(aid)
                    if not meta:
                        continue
                    if game_start_ts is None:
                        game_start_ts = meta.get("game_start_ts")
                    outcome = meta.get("outcome", "")
                    book = self.active_books.get(aid)
                    best_bid = ""
                    best_ask = ""
                    bid_val: float | None = None
                    ask_val: float | None = None
                    if book:
                        bids, asks = book.get_snapshot(limit=1)
                        if bids:
                            bid_val = float(bids[0][0])
                            best_bid = str(bids[0][0])
                        if asks:
                            ask_val = float(asks[0][0])
                            best_ask = str(asks[0][0])
                    rows.append((outcome, _fmt(best_bid), _fmt(best_ask)))
                    raw_rows.append((outcome, bid_val, ask_val))
                rows.sort(key=lambda r: r[0])
                raw_rows.sort(key=lambda r: r[0])
                first = rows[0] if len(rows) > 0 else ("", "", "")
                second = rows[1] if len(rows) > 1 else ("", "", "")
                first_raw = raw_rows[0] if len(raw_rows) > 0 else ("", None, None)
                second_raw = raw_rows[1] if len(raw_rows) > 1 else ("", None, None)
                current_non_empty = (
                    first[1] != ""
                    and first[2] != ""
                    and second[1] != ""
                    and second[2] != ""
                )
                if not seen_non_empty and not current_non_empty:
                    stop_event.wait(1.0)
                    continue
                if current_non_empty:
                    seen_non_empty = True
                if seen_non_empty and not current_non_empty:
                    stop_event.set()
                    break
                changed = False
                current_snapshot = (first_raw[1], first_raw[2], second_raw[1], second_raw[2])
                if current_non_empty:
                    if last_snapshot is not None:
                        for prev, curr in zip(last_snapshot, current_snapshot):
                            if prev is None or curr is None:
                                if prev != curr:
                                    last_change_ts = loop_start
                                    changed = True
                                continue
                            if curr != prev:
                                last_change_ts = loop_start
                                changed = True
                    last_snapshot = current_snapshot
                    if last_logged_snapshot is None or current_snapshot != last_logged_snapshot:
                        changed = True
                volatile = last_change_ts and (loop_start - last_change_ts) <= 10.0
                if current_non_empty and changed:
                    is_new = not path.exists()
                    if is_new:
                        folder.mkdir(parents=True, exist_ok=True)
                    with path.open("a", newline="") as fh:
                        writer = csv.writer(fh)
                        ask_1 = first_raw[2]
                        ask_2 = second_raw[2]
                        spread: float | None = None
                        if ask_1 is not None and ask_2 is not None:
                            spread = float(ask_1) + float(ask_2) - 1.0
                        cond1 = _headerize(first[0])
                        cond2 = _headerize(second[0])
                        if is_new:
                            writer.writerow(
                                [
                                    "time_since_gameStartTime",
                                    f"best_ask_{cond1}",
                                    f"best_ask_{cond2}",
                                    "spread",
                                ]
                            )
                        writer.writerow(
                            [
                                _fmt_elapsed(loop_start - game_start_ts if game_start_ts is not None else None),
                                first[2],
                                second[2],
                                _fmt(str(spread) if spread is not None else ""),
                            ]
                        )
                    last_logged_snapshot = current_snapshot
                stop_event.wait(1.0 if volatile else 4.0)
            self._market_threads.pop(key, None)
            self._market_stops.pop(key, None)

        thread = threading.Thread(target=_log_loop, name=f"market_logger_{key}", daemon=True)
        self._market_threads[key] = thread
        thread.start()

    def _stop_logger(self, asset_id: str) -> None:
        meta = self._asset_meta.pop(asset_id, None)
        if not meta:
            return
        key = self._market_key(meta["slug"], meta["question"])
        assets = self._market_assets.get(key)
        if assets is not None:
            assets.discard(asset_id)
            if not assets:
                self._market_assets.pop(key, None)
                stop = self._market_stops.get(key)
                if stop:
                    stop.set()

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
            pass
        # else:
        #     print(f"User WS event received (type={self._last_user_event_type})")
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
                "side": _to_side(ev.get("side", "")),
                "asset_id": str(ev.get("asset_id", "")),
                "market": str(ev.get("market", "")),
                "outcome": str(ev.get("outcome", "")),
                "expiration": _to_int(ev.get("expiration", 0)),
                "timestamp": _to_int(ev.get("timestamp", 0)),
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
                api_key = self.poly_client.get_api_creds().api_key
            except Exception:
                api_key = ""

            taker_order_id = str(ev.get("taker_order_id", ""))
            trade_owner = str(ev.get("trade_owner", "")) or str(ev.get("owner", ""))
            if api_key and taker_order_id and trade_owner == api_key:
                order: Order = {
                    "orderID": taker_order_id,
                    "price": str(ev.get("price", "")),
                    "size": str(ev.get("size", "")),
                    "side": _to_side(ev.get("side", "")),
                    "asset_id": str(ev.get("asset_id", "")),
                    "market": str(ev.get("market", "")),
                    "outcome": str(ev.get("outcome", "")),
                    "expiration": 0,
                    "timestamp": _to_int(ev.get("timestamp", 0)),
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
                    order = {
                        "orderID": oid,
                        "price": str(maker.get("price", "")),
                        "size": str(maker.get("matched_amount", "")),
                        "side": _to_side(maker.get("side", "")) if maker.get("side") else _to_side(ev.get("side", "")),
                        "asset_id": str(maker.get("asset_id", "")) or str(ev.get("asset_id", "")),
                        "market": str(ev.get("market", "")),
                        "outcome": str(maker.get("outcome", "")) or str(ev.get("outcome", "")),
                        "expiration": 0,
                        "timestamp": _to_int(ev.get("timestamp", 0)),
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
        self._apply_order_payload_to_index(payload)
        if not self._order_subs:
            print("User WS event dropped (no subscribers)")
        for q in tuple(self._order_subs):
            loop = self._order_loops.get(q)
            if loop is None:
                continue

            def _put_one(
                q_local: Queue[dict[str, object]] = q,
                payload_local: dict[str, object] = payload,
            ) -> None:
                try:
                    q_local.put_nowait(payload_local)
                except Exception:
                    pass

            loop.call_soon_threadsafe(_put_one)

    def _ensure_open_orders_index(self) -> bool:
        with self._open_orders_lock:
            if self._open_orders_initialized:
                return True
        try:
            orders = self.poly_client.get_open_orders_strict()
        except Exception as exc:
            print(f"Auto order open-orders bootstrap failed: {exc}")
            return False
        with self._open_orders_lock:
            self._open_orders_by_id = {}
            for order in orders:
                oid = str(order.get("orderID") or "")
                if not oid:
                    continue
                self._open_orders_by_id[oid] = order
            self._open_orders_initialized = True
        return True

    def _get_open_orders_snapshot(self) -> tuple[Dict[str, set[str]], Dict[str, float]]:
        with self._open_orders_lock:
            orders = list(self._open_orders_by_id.values())
        open_assets: Dict[str, set[str]] = {}
        open_sell_sizes: Dict[str, float] = {}
        for order in orders:
            asset = str(order.get("asset_id") or "")
            if not asset:
                continue
            side = str(order.get("side", "")).upper()
            if side not in {"BUY", "SELL"}:
                continue
            open_assets.setdefault(asset, set()).add(side)
            if side == "SELL":
                try:
                    sz = float(order.get("size") or 0)
                except (TypeError, ValueError):
                    sz = 0.0
                if sz > 0:
                    open_sell_sizes[asset] = open_sell_sizes.get(asset, 0.0) + sz
        return open_assets, open_sell_sizes

    def _apply_order_payload_to_index(self, payload: dict[str, object]) -> None:
        order_obj = payload.get("order")
        if not isinstance(order_obj, dict):
            return
        oid = str(order_obj.get("orderID") or "")
        if not oid:
            return
        msg_type = str(payload.get("type", "")).lower()
        event_type = str(payload.get("event", "")).upper()
        if event_type == "TRADE" and msg_type == "closed":
            asset = str(order_obj.get("asset_id") or "")
            side = str(order_obj.get("side", "")).upper()
            if asset and side in {"BUY", "SELL"}:
                now = time.time()
                with self._auto_lock:
                    for pair_key, cfg in self._auto_pairs.items():
                        if asset in cfg.assets:
                            self._auto_pair_last_fill_ts[pair_key] = now
                self._apply_fill_to_positions(order_obj)
        with self._open_orders_lock:
            if msg_type in {"opened", "update"}:
                self._open_orders_by_id[oid] = cast(Order, order_obj)
            elif msg_type == "closed":
                self._open_orders_by_id.pop(oid, None)
            self._open_orders_initialized = True

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

    def get_last_trade(self, asset_id: str) -> WsLastTrade | None:
        return self._last_trades.get(asset_id)

    def _prime_book_from_rest(self, asset_id: str) -> None:
        book = self.active_books.get(asset_id)
        if not book or getattr(book, "ready", False):
            return
        snapshot = self.poly_client.get_order_book_snapshot(asset_id)
        if not snapshot:
            return
        try:
            book.on_book_snapshot(snapshot)
            self.notify_updated(asset_id)
        except Exception:
            pass

    def _parse_string_or_list(self, raw: object) -> list[str]:
        if isinstance(raw, list):
            return [str(x) for x in raw]
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except Exception:
                return []
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        return []

    def start_auto_subscribe(
        self,
        volume_threshold: float = 50_000.0,
        refresh_interval_s: float = 30.0,
        window_before_hours: float = 1.0,
        window_hours: float = 1.0,
        include_more_markets: bool = True,
        track_all_outcomes: bool = True,
    ) -> None:
        with self._auto_subscribe_lock:
            self._auto_subscribe_volume_threshold = max(0.0, float(volume_threshold))
            self._auto_subscribe_refresh_interval_s = max(5.0, float(refresh_interval_s))
            self._auto_subscribe_window_before_h = max(0.0, float(window_before_hours))
            self._auto_subscribe_window_after_h = max(0.0, float(window_hours))
            self._auto_subscribe_include_more_markets = bool(include_more_markets)
            self._auto_subscribe_track_all_outcomes = bool(track_all_outcomes)
            self._auto_subscribe_enabled = True
            if self._auto_subscribe_thread and self._auto_subscribe_thread.is_alive():
                return
            self._auto_subscribe_stop.clear()

        def _loop() -> None:
            while not self._auto_subscribe_stop.is_set():
                try:
                    self._refresh_auto_subscribe_once()
                    with self._auto_subscribe_lock:
                        self._auto_subscribe_last_error = None
                except Exception as exc:
                    with self._auto_subscribe_lock:
                        self._auto_subscribe_last_error = str(exc)
                    print(f"Auto subscribe refresh failed: {exc}")
                wait_s = self._auto_subscribe_refresh_interval_s
                self._auto_subscribe_stop.wait(wait_s)

        self._auto_subscribe_thread = threading.Thread(target=_loop, name="auto_subscriber", daemon=True)
        self._auto_subscribe_thread.start()

    def stop_auto_subscribe(self) -> None:
        self._auto_subscribe_stop.set()
        with self._auto_subscribe_lock:
            self._auto_subscribe_enabled = False
            managed = list(self._auto_subscribe_managed_assets)
            self._auto_subscribe_managed_assets.clear()
            self._auto_subscribe_items = {}
        for aid in managed:
            try:
                self.release(aid)
            except Exception:
                pass

    def _refresh_auto_subscribe_once(self) -> None:
        with self._auto_subscribe_lock:
            threshold = self._auto_subscribe_volume_threshold
            include_more_markets = self._auto_subscribe_include_more_markets
            track_all_outcomes = self._auto_subscribe_track_all_outcomes
            window_before_h = self._auto_subscribe_window_before_h
            window_after_h = self._auto_subscribe_window_after_h
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=3)
        window_end = now + timedelta(hours=12)
        fetch_limit = 500
        fetch_params: dict[str, object] = {
            "limit": fetch_limit,
            "active": True,
            "closed": False,
            "order": "volume24hr",
            "ascending": False,
            "volume_min": threshold,
            # Match events/list source-of-truth windowing at fetch-time.
            "end_date_min": window_start.isoformat(),
            "end_date_max": window_end.isoformat(),
        }
        events = self.poly_client.get_gamma_events(**fetch_params)  # type: ignore[arg-type]
        total_markets = 0
        for ev in events:
            markets_obj = ev.get("markets", [])
            if isinstance(markets_obj, list):
                total_markets += len(markets_obj)
        print(f"Gamma events fetched: {len(events)} events, {total_markets} markets")
        desired_assets: set[str] = set()
        items: dict[str, dict[str, object]] = {}
        for ev in events:
            slug = str(ev.get("slug") or "").strip()
            title = str(ev.get("title") or "").strip()
            event_volume = _to_float(ev.get("volume24hr", 0.0))
            if not include_more_markets and "more-markets" in slug.lower():
                continue
            markets = ev.get("markets", [])
            if not slug or not isinstance(markets, list):
                continue
            for m in markets:
                if not isinstance(m, dict):
                    continue
                question = str(m.get("question") or "").strip()
                if not question:
                    continue
                market_vol = _to_float(m.get("volume", 0.0))
                game_start_time_raw = str(m.get("gameStartTime") or "").strip()
                if not game_start_time_raw:
                    # Keep backend tracking aligned with live event discovery:
                    # no market gameStartTime => do not auto-subscribe.
                    continue
                market_start_text = game_start_time_raw
                if market_start_text.endswith("Z"):
                    market_start_text = f"{market_start_text[:-1]}+00:00"
                try:
                    game_start_dt = datetime.fromisoformat(market_start_text)
                except ValueError:
                    continue
                if game_start_dt.tzinfo is None:
                    game_start_dt = game_start_dt.replace(tzinfo=timezone.utc)
                else:
                    game_start_dt = game_start_dt.astimezone(timezone.utc)
                if game_start_dt < window_start or game_start_dt > window_end:
                    continue
                game_start_time = game_start_time_raw
                outcomes = self._parse_string_or_list(m.get("outcomes"))
                token_ids = self._parse_string_or_list(m.get("clobTokenIds"))
                if len(outcomes) < 2 or len(token_ids) < 2:
                    continue
                valid_assets: list[str] = []
                pair_assets: list[str] = []
                pair_outcomes: list[str] = []
                max_len = min(len(outcomes), len(token_ids))
                for idx in range(max_len):
                    aid = str(token_ids[idx] or "").strip()
                    outcome = str(outcomes[idx] or "").strip()
                    if not aid:
                        continue
                    valid_assets.append(aid)
                    if len(pair_assets) < 2:
                        pair_assets.append(aid)
                        pair_outcomes.append(outcome)
                if not valid_assets:
                    continue

                if track_all_outcomes:
                    for aid in valid_assets:
                        desired_assets.add(aid)

                # Keep CSV logger metadata strictly pair-oriented for backward compatibility.
                if len(pair_assets) == 2 and len(outcomes) == 2 and len(token_ids) == 2:
                    for idx in range(2):
                        aid = pair_assets[idx]
                        outcome = pair_outcomes[idx] if idx < len(pair_outcomes) else ""
                        desired_assets.add(aid)
                        self.set_asset_meta(
                            aid,
                            slug=slug,
                            question=question,
                            outcome=outcome,
                            game_start_time=game_start_time,
                        )
                    key = self._market_key(slug, question)
                    items[key] = {
                        "event_slug": slug,
                        "event_title": title,
                        "event_volume": event_volume,
                        "question": question,
                        "market_volume": market_vol,
                        "assets": pair_assets,
                        "game_start_time": game_start_time,
                    }
                elif not track_all_outcomes:
                    # If all-outcome tracking is disabled, still track the first pair.
                    for idx in range(len(pair_assets)):
                        aid = pair_assets[idx]
                        desired_assets.add(aid)
                    if len(pair_assets) == 2:
                        for idx in range(2):
                            aid = pair_assets[idx]
                            outcome = pair_outcomes[idx] if idx < len(pair_outcomes) else ""
                            self.set_asset_meta(
                                aid,
                                slug=slug,
                                question=question,
                                outcome=outcome,
                                game_start_time=game_start_time,
                            )
                        key = self._market_key(slug, question)
                        items[key] = {
                            "event_slug": slug,
                            "event_title": title,
                            "event_volume": event_volume,
                            "question": question,
                            "market_volume": market_vol,
                            "assets": pair_assets,
                            "game_start_time": game_start_time,
                        }

        with self._auto_subscribe_lock:
            current = set(self._auto_subscribe_managed_assets)
        to_add = desired_assets - current
        to_remove = current - desired_assets
        for aid in to_add:
            try:
                self.subscribe_to_asset(aid)
                self._prime_book_from_rest(aid)
            except Exception as exc:
                meta = self._asset_meta.get(aid, {})
                question = str(meta.get("question") or "unknown")
                outcome = str(meta.get("outcome") or "unknown")
                print(
                    "Auto subscribe failed "
                    f"(question={question} outcome={outcome}): {exc}"
                )
        for aid in to_remove:
            try:
                self.release(aid)
            except Exception as exc:
                print(f"Auto subscribe release failed (asset={aid}): {exc}")
        with self._auto_subscribe_lock:
            self._auto_subscribe_managed_assets = desired_assets
            self._auto_subscribe_items = items
            self._auto_subscribe_last_run_ts = time.time()

    def get_auto_subscribe_status(self) -> dict[str, object]:
        with self._auto_subscribe_lock:
            items = list(self._auto_subscribe_items.values())
            items.sort(key=lambda x: float(x.get("market_volume") or 0.0), reverse=True)
            return {
                "enabled": self._auto_subscribe_enabled,
                "volume_threshold": self._auto_subscribe_volume_threshold,
                "refresh_interval_s": self._auto_subscribe_refresh_interval_s,
                "window_before_hours": self._auto_subscribe_window_before_h,
                "window_hours": self._auto_subscribe_window_after_h,
                "include_more_markets": self._auto_subscribe_include_more_markets,
                "track_all_outcomes": self._auto_subscribe_track_all_outcomes,
                "last_run_ts": self._auto_subscribe_last_run_ts,
                "last_error": self._auto_subscribe_last_error,
                "managed_assets_count": len(self._auto_subscribe_managed_assets),
                "markets_count": len(items),
                "markets": items,
            }

    # Backward-compatible aliases while callers migrate from "auto_event_logging" naming.
    def start_auto_event_logging(
        self,
        volume_threshold: float = 50_000.0,
        refresh_interval_s: float = 30.0,
        window_before_hours: float = 1.0,
        window_hours: float = 1.0,
        include_more_markets: bool = True,
        track_all_outcomes: bool = True,
    ) -> None:
        self.start_auto_subscribe(
            volume_threshold=volume_threshold,
            refresh_interval_s=refresh_interval_s,
            window_before_hours=window_before_hours,
            window_hours=window_hours,
            include_more_markets=include_more_markets,
            track_all_outcomes=track_all_outcomes,
        )

    def stop_auto_event_logging(self) -> None:
        self.stop_auto_subscribe()

    def get_auto_event_logging_status(self) -> dict[str, object]:
        return self.get_auto_subscribe_status()

