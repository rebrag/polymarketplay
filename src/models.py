from enum import Enum
from typing import TypedDict, Protocol, Literal, Required, List, Any, NotRequired, Optional

class AssetType(str, Enum):
    COLLATERAL = "COLLATERAL"
    CONDITIONAL = "CONDITIONAL"

class BalanceAllowanceParams(TypedDict):
    asset_type: AssetType
    token_id: Optional[str]

# The method accepts a List of these params
type BalanceAllowanceParamsList = List[BalanceAllowanceParams]

class BalanceAllowanceResponse(TypedDict):
    balance: str
    allowance: str

class UserValueEntry(TypedDict):
    user: str
    value: float

type UserValueResponse = list[UserValueEntry]

class WebSocketAppProto(Protocol):
    def run_forever(self, ping_interval: int, ping_timeout: int) -> bool: ...
    def send(self, data: str | bytes) -> None: ...
    def close(self) -> None: ...

class GammaMarket(TypedDict, total=False):
    id: str
    question: str
    slug: str
    active: bool
    closed: bool
    liquidity: str
    volume: float
    outcomes: Required[List[str]]
    clobTokenIds:Required [List[str]]

class GammaEvent(TypedDict, total=False):
    id: Required[str]
    slug: Required[str]
    title: Required[str]
    markets: Required[List[Any]]  # Should ideally be List[Market] later
    description: str
    ticker: str
    resolutionSource: str
    image: str
    icon: str
    startDate: str
    endDate: str
    creationDate: str
    updatedAt: str
    volume: float
    volume24hr: float
    liquidity: float
    openInterest: float
    commentCount: int
    active: bool
    closed: bool
    archived: bool
    new: bool
    featured: bool
    restricted: bool
    enableOrderBook: bool
    enableNegRisk: bool
    tags: List[Any]

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
    asset: Required[str]
    side: TradeSide
    outcomeIndex: int
    title: str
    slug: Required[str]
    icon: str
    eventSlug: Required[str]
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

class MarketWithVolume(GammaMarket):
    # Extends GammaMarket to include the volumeNum we added in utils
    volumeNum: float

class UserActivityResponse(TypedDict):
    title: str
    markets: List[GammaMarket] # We use Any here to avoid circular imports, or use GammaMarket if order permits

class WsBidAsk(TypedDict):
    price: float
    size: float
    cum: float

class WsPayload(TypedDict):
    asset_id: str
    ready: bool
    msg_count: int
    bids: List[WsBidAsk]
    asks: List[WsBidAsk]
    status: NotRequired[str] # Use NotRequired if this key is optional