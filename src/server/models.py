from __future__ import annotations

from typing import Dict, Literal

from pydantic import BaseModel, Field


class AutoAssetConfig(BaseModel):
    asset_id: str
    shares: float = Field(gt=0)
    ttl_seconds: int = Field(default=0, ge=0)
    level: int = 0
    enabled: bool = True


class AutoPairConfig(BaseModel):
    pair_key: str
    assets: list[str]
    asset_settings: Dict[str, AutoAssetConfig]
    disabled_assets: list[str] = []
    auto_buy_max_cents: float = 97
    auto_sell_min_cents: float = 103
    auto_sell_min_shares: float = 20
    strategy: str = "default"
    enabled: bool = True


class AutoPairPayload(BaseModel):
    pair_key: str
    assets: list[str]
    asset_settings: list[AutoAssetConfig]
    disabled_assets: list[str] = []
    auto_buy_max_cents: float = 97
    auto_sell_min_cents: float = 103
    auto_sell_min_shares: float = 20
    strategy: str = "default"
    enabled: bool = True


class LimitOrderRequest(BaseModel):
    token_id: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    size: float = Field(gt=0)
    ttl_seconds: int = Field(default=0)
    price_offset_cents: int = Field(default=0, ge=-50, le=50)


class MarketOrderRequest(BaseModel):
    token_id: str = Field(min_length=1)
    side: Literal["BUY", "SELL"]
    amount: float = Field(gt=0)
    fok_only: bool = False


class CancelOrderRequest(BaseModel):
    order_id: str = Field(min_length=1)
