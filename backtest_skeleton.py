from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Protocol, Sequence, Tuple
import json


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class BookSnapshot:
    ts: float
    asset: str
    bids: Sequence[BookLevel]
    asks: Sequence[BookLevel]

    @property
    def best_bid(self) -> Optional[BookLevel]:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[BookLevel]:
        return self.asks[0] if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        bid = self.best_bid
        ask = self.best_ask
        if bid is None or ask is None:
            return None
        return 0.5 * (bid.price + ask.price)

    @property
    def spread(self) -> Optional[float]:
        bid = self.best_bid
        ask = self.best_ask
        if bid is None or ask is None:
            return None
        return ask.price - bid.price


@dataclass(frozen=True)
class BookEvent:
    ts: float
    asset: str
    bids: List[BookLevel]
    asks: List[BookLevel]


@dataclass
@dataclass
class ActiveOrder:
    id: int
    asset: str
    side: Side
    price: float
    remaining: float  # > 0
    created_ts: float



@dataclass(frozen=True)
class Order:
    asset: str
    side: Side
    price: float
    size: float  # > 0


@dataclass(frozen=True)
class Fill:
    ts: float
    asset: str
    side: Side
    price: float
    size: float  # > 0


@dataclass
class Portfolio:
    cash: float
    positions: Dict[str, float]  # asset -> qty


@dataclass
class BacktestResult:
    final_value: float
    portfolio: Portfolio
    fills: List[Fill]


class Strategy(Protocol):
    def on_book(
        self,
        snapshot: BookSnapshot,
        position_qty: float,
        cash: float,
    ) -> Sequence[Order]:
        ...


class MidpointMarketMaker(Strategy):
    def __init__(
        self,
        max_notional_per_asset: float,
        quote_spread_fraction: float,
        clip_size_usd: float,
    ) -> None:
        self.max_notional_per_asset = max_notional_per_asset
        self.quote_spread_fraction = quote_spread_fraction
        self.clip_size_usd = clip_size_usd

    def on_book(
        self,
        snapshot: BookSnapshot,
        position_qty: float,
        cash: float,
    ) -> Sequence[Order]:
        mid = snapshot.mid
        spread = snapshot.spread
        if mid is None or mid <= 0.0:
            return []
        if spread is None or spread <= 0.0:
            return []

        # No buying if no cash; no selling if no position
        if cash <= 0.0 and position_qty <= 0.0:
            return []

        notional = abs(position_qty) * mid
        if notional >= self.max_notional_per_asset:
            return []

        clip_size = self.clip_size_usd / mid
        if clip_size <= 0.0:
            return []

        max_affordable_size = cash / mid if cash > 0.0 else 0.0
        effective_buy_clip = min(clip_size, max_affordable_size)

        half_quote_spread = 0.5 * spread * self.quote_spread_fraction
        bid_price = max(0.0, mid - half_quote_spread)
        ask_price = min(1.0, mid + half_quote_spread)

        desired: List[Order] = []

        # BUY only if we have cash and we’re not heavily long already
        if effective_buy_clip > 0.0 and position_qty <= 0.0:
            desired.append(
                Order(
                    asset=snapshot.asset,
                    side=Side.BUY,
                    price=bid_price,
                    size=effective_buy_clip,
                )
            )

        # SELL only if we have a long position; cap size to what we own
        if position_qty > 0.0:
            max_sell_size = min(clip_size, position_qty)
            if max_sell_size > 0.0:
                desired.append(
                    Order(
                        asset=snapshot.asset,
                        side=Side.SELL,
                        price=ask_price,
                        size=max_sell_size,
                    )
                )

        return desired



class Backtester:
    def __init__(
        self,
        initial_cash: float,
        strategy: Strategy,
        max_order_lifetime_s: float = 30.0,
    ) -> None:
        self.initial_cash = initial_cash
        self.strategy = strategy
        self._next_order_id: int = 1
        self.max_order_lifetime_s = max_order_lifetime_s


    def _new_order_id(self) -> int:
        oid = self._next_order_id
        self._next_order_id += 1
        return oid

    def run(self, events: Iterable[BookEvent]) -> BacktestResult:
        portfolio = Portfolio(cash=self.initial_cash, positions={})
        active_orders: Dict[str, List[ActiveOrder]] = {}
        fills: List[Fill] = []
        last_mid: Dict[str, float] = {}

        for event in events:
            snapshot = BookSnapshot(
                ts=event.ts,
                asset=event.asset,
                bids=event.bids,
                asks=event.asks,
            )

            mid = snapshot.mid
            if mid is not None and mid > 0.0:
                last_mid[event.asset] = mid

            qty = portfolio.positions.get(event.asset, 0.0)
            existing_orders = active_orders.get(event.asset, [])

            # --- 1) Cancel orders older than max_order_lifetime_s ---
            still_live: List[ActiveOrder] = []
            for o in existing_orders:
                if snapshot.ts - o.created_ts <= self.max_order_lifetime_s:
                    still_live.append(o)
                # else: order expired, drop it

            # --- 2) Ask strategy for *new* orders at this snapshot ---
            new_orders = self.strategy.on_book(snapshot, qty, portfolio.cash)
            for order in new_orders:
                still_live.append(
                    ActiveOrder(
                        id=self._new_order_id(),
                        asset=order.asset,
                        side=order.side,
                        price=order.price,
                        remaining=order.size,
                        created_ts=snapshot.ts,
                    )
                )

            # --- 3) Match using current qty & cash (no short, no neg cash) ---
            new_fills, remaining_orders = self._match_orders(
                snapshot, still_live, qty, portfolio.cash
            )
            active_orders[event.asset] = remaining_orders

            for fill in new_fills:
                fills.append(fill)
                if fill.side is Side.BUY:
                    portfolio.cash -= fill.price * fill.size
                    portfolio.positions[fill.asset] = (
                        portfolio.positions.get(fill.asset, 0.0) + fill.size
                    )
                else:
                    portfolio.cash += fill.price * fill.size
                    portfolio.positions[fill.asset] = (
                        portfolio.positions.get(fill.asset, 0.0) - fill.size
                    )

        final_value = portfolio.cash
        for asset, qty in portfolio.positions.items():
            mid = last_mid.get(asset)
            if mid is not None:
                final_value += qty * mid

        return BacktestResult(
            final_value=final_value,
            portfolio=portfolio,
            fills=fills,
        )



    def _match_orders(
        self,
        snapshot: BookSnapshot,
        orders: List[ActiveOrder],
        current_qty: float,
        current_cash: float,
    ) -> Tuple[List[Fill], List[ActiveOrder]]:
        fills: List[Fill] = []
        remaining: List[ActiveOrder] = []

        best_bid = snapshot.best_bid
        best_ask = snapshot.best_ask

        qty_available_to_sell = max(current_qty, 0.0)
        cash_available = max(current_cash, 0.0)

        for order in orders:
            if order.remaining <= 0.0:
                continue

            if order.side is Side.BUY:
                if (
                    best_ask is not None
                    and best_ask.price <= order.price
                    and best_ask.size > 0.0
                    and cash_available > 0.0
                ):
                    max_buy_by_cash = cash_available / best_ask.price
                    if max_buy_by_cash > 0.0:
                        size = min(order.remaining, best_ask.size, max_buy_by_cash)
                    else:
                        size = 0.0

                    if size > 0.0:
                        order.remaining -= size
                        cash_available -= size * best_ask.price
                        fills.append(
                            Fill(
                                ts=snapshot.ts,
                                asset=order.asset,
                                side=Side.BUY,
                                price=best_ask.price,
                                size=size,
                            )
                        )

            else:  # SELL
                if (
                    best_bid is not None
                    and best_bid.price >= order.price
                    and best_bid.size > 0.0
                    and qty_available_to_sell > 0.0
                ):
                    max_sell_here = min(order.remaining, qty_available_to_sell)
                    size = min(max_sell_here, best_bid.size)
                    if size > 0.0:
                        order.remaining -= size
                        qty_available_to_sell -= size
                        fills.append(
                            Fill(
                                ts=snapshot.ts,
                                asset=order.asset,
                                side=Side.SELL,
                                price=best_bid.price,
                                size=size,
                            )
                        )

            if order.remaining > 0.0:
                remaining.append(order)

        return fills, remaining



def parse_book_events_from_jsonl(path: str) -> Iterable[BookEvent]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("type") != "book":
                continue

            # Adjust keys if your JSON uses different names
            asset = str(obj["asset"])
            ts = float(obj["ts"])

            bids_raw = obj.get("bids", [])
            asks_raw = obj.get("asks", [])

            bids: List[BookLevel] = [
                BookLevel(price=float(level["price"]), size=float(level["size"]))
                for level in bids_raw
            ]
            asks: List[BookLevel] = [
                BookLevel(price=float(level["price"]), size=float(level["size"]))
                for level in asks_raw
            ]

            yield BookEvent(ts=ts, asset=asset, bids=bids, asks=asks)


if __name__ == "__main__":
    events = parse_book_events_from_jsonl("giayn_trades_and_books.jsonl")

    strategy = MidpointMarketMaker(
        max_notional_per_asset=10.0,
        quote_spread_fraction=0.5,
        clip_size_usd=1.0,
    )

    backtester = Backtester(initial_cash=5000.0, strategy=strategy)
    result = backtester.run(events)

    print("Final portfolio value:", result.final_value)
    print("Cash:", result.portfolio.cash)
    for asset, qty in result.portfolio.positions.items():
        print("Asset:", asset, "Qty:", round(float(qty),3))
    print("Total fills:", len(result.fills))
    for fill in result.fills[:10]:
        print(fill)

