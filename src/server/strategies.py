from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Protocol

from src.server.models import AutoPairConfig


@dataclass(frozen=True)
class PairContext:
    assets: list[str]
    positions: Dict[str, float]
    buy_allowed: bool
    sell_allowed: bool
    both_over: bool
    best_bids: Dict[str, float]
    last_trades: Dict[str, dict[str, float | str | int]]


@dataclass(frozen=True)
class OrderIntent:
    side: str
    level: int | None = None
    size_multiplier: float | None = None


class AutoStrategy(Protocol):
    name: str

    def decide(self, asset_id: str, config: AutoPairConfig, ctx: PairContext) -> list[OrderIntent]:
        ...


class DefaultStrategy:
    name = "default"

    def decide(self, asset_id: str, config: AutoPairConfig, ctx: PairContext) -> list[OrderIntent]:
        other_asset = ctx.assets[1] if asset_id == ctx.assets[0] else ctx.assets[0]
        current_shares = ctx.positions.get(asset_id, 0.0)
        other_shares = ctx.positions.get(other_asset, 0.0)
        if current_shares >= 25:
            return []
        exposure_diff = current_shares - other_shares
        trade_side = "SELL" if ctx.both_over or exposure_diff >= config.auto_sell_min_shares else "BUY"
        if trade_side == "BUY" and not ctx.buy_allowed:
            return []
        if trade_side == "SELL" and not ctx.sell_allowed:
            return []
        return [OrderIntent(side=trade_side)]


class ConservativeStrategy:
    name = "conservative"

    def decide(self, asset_id: str, config: AutoPairConfig, ctx: PairContext) -> list[OrderIntent]:
        other_asset = ctx.assets[1] if asset_id == ctx.assets[0] else ctx.assets[0]
        current_shares = ctx.positions.get(asset_id, 0.0)
        other_shares = ctx.positions.get(other_asset, 0.0)
        if current_shares >= 25:
            return []
        exposure_diff = current_shares - other_shares
        if ctx.both_over and ctx.sell_allowed:
            return [OrderIntent(side="SELL")]
        if exposure_diff <= -config.auto_sell_min_shares and ctx.buy_allowed:
            return [OrderIntent(side="BUY")]
        return []


class AggressiveStrategy:
    name = "aggressive"

    def decide(self, asset_id: str, config: AutoPairConfig, ctx: PairContext) -> list[OrderIntent]:
        other_asset = ctx.assets[1] if asset_id == ctx.assets[0] else ctx.assets[0]
        current_shares = ctx.positions.get(asset_id, 0.0)
        other_shares = ctx.positions.get(other_asset, 0.0)
        if current_shares >= 25:
            return []
        exposure_diff = current_shares - other_shares
        preferred = "SELL" if ctx.both_over or exposure_diff >= config.auto_sell_min_shares else "BUY"
        if preferred == "BUY" and ctx.buy_allowed:
            return [OrderIntent(side="BUY")]
        if preferred == "SELL" and ctx.sell_allowed:
            return [OrderIntent(side="SELL")]
        if ctx.buy_allowed:
            return [OrderIntent(side="BUY")]
        if ctx.sell_allowed:
            return [OrderIntent(side="SELL")]
        return []


class AdaptiveStrategy:
    name: str = "adaptive"

    def decide(self, asset_id: str, config: AutoPairConfig, ctx: PairContext) -> list[OrderIntent]:
        # 1. Trigger Logic: Check for high-volume trades (>= $150)
        triggered: bool = False
        for aid in ctx.assets:
            last = ctx.last_trades.get(aid)
            if isinstance(last, dict):
                try:
                    price = float(last.get("price", 0) or 0)
                    size = float(last.get("size", 0) or 0)
                    if price * size >= 150:
                        triggered = True
                        break
                except (TypeError, ValueError):
                    continue

        if not triggered:
            return []

        other_id: str = ctx.assets[1] if asset_id == ctx.assets[0] else ctx.assets[0]
        bid_self: float = ctx.best_bids.get(asset_id, 0.0)
        bid_other: float = ctx.best_bids.get(other_id, 0.0)
        
        is_self_favorite: bool = bid_self >= bid_other + 0.05
        fav_id = asset_id if is_self_favorite else other_id
        shares_fav = float(ctx.positions.get(fav_id, 0.0))
        shares_self = float(ctx.positions.get(asset_id, 0.0))

        intents: list[OrderIntent] = []

        if ctx.buy_allowed:
            if shares_fav <= 5:
                if is_self_favorite:
                    intents.append(OrderIntent(side="BUY", level=0, size_multiplier=1.5))
                else:
                    intents.append(OrderIntent(side="BUY", level=-1))
            
            elif is_self_favorite and shares_fav > 5:
                intents.append(OrderIntent(side="BUY", level=0, size_multiplier=1.5))
                if ctx.sell_allowed:
                    intents.append(OrderIntent(side="SELL", level=-1, size_multiplier=1))

        if shares_self >= 25 and ctx.sell_allowed:
            return [OrderIntent(side="SELL", level=-1, size_multiplier=1)]

        return intents


_STRATEGIES: dict[str, AutoStrategy] = {
    "default": DefaultStrategy(),
    "conservative": ConservativeStrategy(),
    "aggressive": AggressiveStrategy(),
    "adaptive": AdaptiveStrategy(),
}


def get_strategy(name: str | None) -> AutoStrategy:
    key = (name or "default").strip().lower()
    return _STRATEGIES.get(key, _STRATEGIES["default"])


def get_strategy_names() -> list[str]:
    return sorted(_STRATEGIES.keys())
