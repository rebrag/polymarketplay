from typing import TypedDict, Protocol, Literal

class WebSocketAppProto(Protocol):
    def run_forever(self) -> bool: ...
    def send(self, data: str | bytes) -> None: ...
    def close(self) -> None: ...

class GammaMarket(TypedDict, total=False):
    id: str
    question: str
    slug: str
    active: bool
    closed: bool
    liquidity: str
    volume: str
    outcomes: str        
    clobTokenIds: str    

class GammaEvent(TypedDict, total=False):
    id: str
    slug: str
    active: bool
    markets: list[GammaMarket]

# --- WebSocket Message Types ---
class WsBookLevel(TypedDict, total=False):
    price: str
    size: str

class WsBookMessage(TypedDict, total=False):
    event_type: str
    asset_id: str
    buys: list[WsBookLevel]
    sells: list[WsBookLevel]
    bids: list[WsBookLevel]
    asks: list[WsBookLevel]

class WsPriceChange(TypedDict, total=False):
    asset_id: str
    side: str
    price: str
    size: str

class WsPriceChangeMessage(TypedDict, total=False):
    event_type: str
    price_changes: list[WsPriceChange]

class Token(TypedDict):
    token_id: str
    outcome: str
    price: float
    winner: bool

class Market(TypedDict):
    question: str
    condition_id: str
    slug: str
    tokens: list[Token]

TradeSide = Literal["BUY", "SELL"]
TradeType = Literal["TRADE"]

class TradeActivity(TypedDict, total=False):
    proxyWallet: str
    timestamp: int
    conditionId: str
    type: TradeType
    size: float
    usdcSize: float
    transactionHash: str
    price: float
    asset: str
    side: TradeSide
    outcomeIndex: int
    title: str
    slug: str
    icon: str
    eventSlug: str
    outcome: str
    name: str
    pseudonym: str
    bio: str
    profileImage: str
    profileImageOptimized: str

class Order(TypedDict):
    orderID: str
    price: str       # API returns decimal strings ("0.55")
    size: str        # API returns decimal strings ("10.0")
    side: Literal["BUY", "SELL"]
    asset_id: str
    expiration: int
    timestamp: int
    owner: str
    hash: str