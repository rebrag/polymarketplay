from __future__ import annotations

import json
import os
import threading
import time

import requests
import websocket
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Literal, Protocol, TypedDict, cast

from polymarket_bot.config import GAMMA_URL, REST_URL, WSS_URL, WSS_USER_URL
from polymarket_bot.models import (
    BalanceAllowanceResponse,
    GammaEvent,
    Order,
    TradeActivity,
    WebSocketAppProto,
    WsBookMessage,
    WsPriceChangeMessage,
    WsLastTradePriceMessage,
    WsTickSizeChangeMessage,
)

# External Lib Imports
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds,
    BalanceAllowanceParams as ClobBalanceAllowanceParams,
    AssetType as ClobAssetType,
    MarketOrderArgs,
    OpenOrderParams,
    OrderArgs,
    OrderType,
)  # type: ignore
from py_clob_client.order_builder.constants import BUY, SELL

class BookCallback(Protocol):
    def __call__(self, msg: WsBookMessage) -> None: ...


class PriceChangeCallback(Protocol):
    def __call__(self, msg: WsPriceChangeMessage) -> None: ...

class TickSizeCallback(Protocol):
    def __call__(self, msg: WsTickSizeChangeMessage) -> None: ...

class LastTradeCallback(Protocol):
    def __call__(self, msg: WsLastTradePriceMessage) -> None: ...


Side = Literal["BUY", "SELL"]


class Position(TypedDict, total=False):
    proxyWallet: str
    asset: str
    conditionId: str
    size: float
    avgPrice: float
    initialValue: float
    currentValue: float
    cashPnl: float
    percentPnl: float
    totalBought: float
    realizedPnl: float
    percentRealizedPnl: float
    curPrice: float
    redeemable: bool
    mergeable: bool
    title: str
    slug: str
    icon: str
    eventSlug: str
    outcome: str
    outcomeIndex: int
    oppositeOutcome: str
    oppositeAsset: str
    endDate: str
    negativeRisk: bool


class PolyClient:
    """
    Handles HTTP (Gamma & Data API) Requests and CLOB Helpers.

    Notes:
    - Read-only CLOB calls can be made without credentials.
    - Trading / order management requires env vars (see _get_trading_clob_client()).
    """

    def __init__(self, timeout: float = 10.0):
        self.session = requests.Session()
        self.timeout = timeout

        self._public_clob: ClobClient | None = None
        self._trading_clob: ClobClient | None = None
        self._api_creds: ApiCreds | None = None

    def _parse_string_or_list(self, raw: object) -> list[str]:
        match raw:
            case str():
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return []
                if isinstance(parsed, list):
                    return [str(x) for x in cast(list[object], parsed)]
            case list():
                return [str(x) for x in cast(list[object], raw)]
            case _:
                return []
        return []

    def find_asset_id(self, slug: str, outcome_keyword: str) -> str | None:
        try:
            resp = self.session.get(
                GAMMA_URL, params={"slug": slug}, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        if not isinstance(data, list) or not data:
            return None

        event = cast(GammaEvent, data[0])
        keyword_lower = outcome_keyword.lower()

        for market in event.get("markets", []):
            outcomes = self._parse_string_or_list(market.get("outcomes", "[]"))
            token_ids = self._parse_string_or_list(market.get("clobTokenIds", "[]"))

            for i, outcome in enumerate(outcomes):
                if i >= len(token_ids):
                    break
                if keyword_lower in outcome.lower():
                    return token_ids[i]
        return None

    def get_gamma_events(
        self,
        tag_id: int | None = None,
        slug: str | None = None,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        order: str = "volume24hr",
        ascending: bool = False,
        end_date_min: str | None = None,
        end_date_max: str | None = None,
        volume_min: float | None = None,
    ) -> list[GammaEvent]:
        """
        Fetches events from Gamma API. Supports:
        1) By Slug: client.get_gamma_events(slug="nfl-game")
        2) By Tag:  client.get_gamma_events(tag_id=1002)
        3) Bulk:    client.get_gamma_events()
        """
        params: dict[str, str] = {
            "limit": str(limit),
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "order": order,
            "ascending": str(ascending).lower(),
        }

        if tag_id is not None:
            params["tag_id"] = str(tag_id)

        if slug:
            params["slug"] = slug
        if end_date_min:
            params["end_date_min"] = end_date_min
        if end_date_max:
            params["end_date_max"] = end_date_max
        if volume_min is not None:
            params["volume_min"] = str(volume_min)

        try:
            resp = self.session.get(GAMMA_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return cast(list[GammaEvent], resp.json())
        except Exception as e:
            print(f"❌ Poly API Error: {e}")
            return []

    def get_trades(self, user_address: str, limit: int = 20) -> list[TradeActivity]:
        params: dict[str, str] = {
            "user": user_address,
            "type": "TRADE",
            "limit": str(limit),
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
        }
        try:
            resp = self.session.get(REST_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return cast(list[TradeActivity], resp.json())
        except Exception as e:
            print(f"❌ Trade Fetch Error: {e}")
            return []

    def get_positions(self, user_address: str, limit: int = 100) -> list[Position]:
        url = os.getenv("POLY_POSITIONS_URL", "https://data-api.polymarket.com/positions")
        params: dict[str, str] = {"user": user_address, "limit": str(limit)}
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()

            data_obj: object = resp.json()
            if not isinstance(data_obj, list):
                return []

            out: list[Position] = []
            for item_obj in data_obj: # type: ignore
                if isinstance(item_obj, dict):
                    out.append(cast(Position, cast(dict[str, object], item_obj)))
            return out
        except Exception as e:
            print(f"❌ Positions Fetch Error: {e}")
            return []


    def get_balance_allowance(
        self,
        asset_type: str = "COLLATERAL",
        token_id: str | None = None,
        signature_type: int | None = None,
    ) -> BalanceAllowanceResponse:
        """
        Fetches balance + allowance for the authenticated wallet.

        Notes:
        - Requires Level 2 auth (API creds) from _get_trading_clob_client().
        - For COLLATERAL, token_id must be None or omitted.
        """
        client = self._get_trading_clob_client()

        asset_enum = (
            ClobAssetType.COLLATERAL
            if asset_type.upper() == "COLLATERAL"
            else ClobAssetType.CONDITIONAL
        )
        params = ClobBalanceAllowanceParams(asset_type=asset_enum, token_id=token_id) # type: ignore
        if signature_type is not None:
            params.signature_type = signature_type
        else:
            # -1 works with most wallet types (avoids 400 for collateral balance calls).
            params.signature_type = -1

        def _to_amount(val: object) -> Decimal:
            try:
                if isinstance(val, Decimal):
                    return val
                if isinstance(val, (int, float)):
                    return Decimal(str(val))
                if isinstance(val, str):
                    return Decimal(val)
            except InvalidOperation:
                return Decimal(0)
            return Decimal(0)

        def _format_amount(dec: Decimal) -> str:
            if asset_type.upper() == "COLLATERAL" and dec == dec.to_integral_value():
                dec = dec / Decimal("1000000")
            return format(dec, "f")

        raw = client.get_balance_allowance(params)  # type: ignore
        if isinstance(raw, dict) and "balance" in raw:
            balance_dec = _to_amount(raw.get("balance"))

            allowance_val: object | None = raw.get("allowance")
            if allowance_val is None:
                allowances = raw.get("allowances")
                if isinstance(allowances, dict) and allowances:
                    allowance_vals = [_to_amount(v) for v in allowances.values()]
                    allowance_val = max(allowance_vals) if allowance_vals else Decimal(0)

            allowance_dec = _to_amount(allowance_val) if allowance_val is not None else Decimal(0)
            return {
                "balance": _format_amount(balance_dec),
                "allowance": _format_amount(allowance_dec),
            }

        raise RuntimeError(f"Unexpected balance response: {raw!r}")

    def get_authenticated_address(self) -> str | None:
        client = self._get_trading_clob_client()
        addr = client.get_address()
        return str(addr) if addr else None

    def get_positions_address(self) -> str | None:
        funder = os.getenv("POLY_FUNDER")
        if funder and funder.strip():
            return funder.strip()
        return self.get_authenticated_address()

    def _get_public_clob_client(self) -> ClobClient:
        if self._public_clob is not None:
            return self._public_clob
        host = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
        self._public_clob = ClobClient(host)  # Level 0 (no auth)
        return self._public_clob

    def get_best_price(self, token_id: str, side: Side) -> float:
        """
        Returns the best bid (BUY) or best ask (SELL) price for a token_id.

        Uses the CLOB REST price endpoint under the hood.
        """
        client = self._get_public_clob_client()
        side_param = "buy" if side == "BUY" else "sell"
        raw = client.get_price(token_id, side=side_param)  # type: ignore
        if isinstance(raw, dict):
            price_val: float = raw["price"] # type: ignore
            return float(price_val) if isinstance(price_val, str) else float(price_val) # type: ignore
        return float(raw) #type:ignore

    def get_order_book_snapshot(self, token_id: str) -> WsBookMessage | None:
        """
        Fetches a point-in-time order book snapshot via REST.
        """
        try:
            client = self._get_public_clob_client()
            raw = client.get_order_book(token_id)  # type: ignore
        except Exception as e:
            print(f"⚠️ Order book REST fetch failed: {e}")
            return None

        book: dict[str, Any] | None
        if isinstance(raw, dict):
            book = cast(dict[str, Any], raw)
        else:
            book = getattr(raw, "__dict__", None)
            if not isinstance(book, dict):
                return None

        def _levels(key: str) -> list[dict[str, str]]:
            levels = book.get(key, [])
            if not isinstance(levels, list):
                return []
            out: list[dict[str, str]] = []
            for lvl in levels:
                if isinstance(lvl, dict):
                    price = str(lvl.get("price", "0"))
                    size = str(lvl.get("size", "0"))
                    out.append({"price": price, "size": size})
                else:
                    price = str(getattr(lvl, "price", "0"))
                    size = str(getattr(lvl, "size", "0"))
                    out.append({"price": price, "size": size})
            return out

        return {
            "event_type": "book",
            "asset_id": token_id,
            "bids": _levels("bids"),
            "asks": _levels("asks"),
        } # type: ignore

    def _require_env(self, name: str) -> str:
        val = os.getenv(name)
        if not val:
            raise RuntimeError(
                f"Missing environment variable '{name}'. "
                "Trading endpoints require explicit credentials."
            )
        return val

    def _get_trading_clob_client(self) -> ClobClient:
        """
        Lazily initializes an authenticated CLOB client for order placement/cancel.

        Required env vars:
          - POLY_PRIVATE_KEY: private key used to sign orders
        Optional / commonly needed:
          - POLY_CLOB_HOST (default https://clob.polymarket.com)
          - POLY_CHAIN_ID (default 137)
          - POLY_SIGNATURE_TYPE (default 0; set 1 for Magic/email wallets)
          - POLY_FUNDER (required if POLY_SIGNATURE_TYPE != 0)
        """
        if self._trading_clob is not None:
            return self._trading_clob

        host = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
        def _env_int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None or raw.strip() == "":
                return default
            try:
                return int(raw)
            except ValueError as e:
                raise RuntimeError(f"{name} must be an integer, got {raw!r}") from e

        chain_id = _env_int("POLY_CHAIN_ID", 137)
        signature_type = _env_int("POLY_SIGNATURE_TYPE", 1)

        private_key = self._require_env("POLY_KEY")

        funder = os.getenv("POLY_FUNDER")
        if signature_type != 0 and not funder:
            raise RuntimeError(
                "POLY_FUNDER is required when POLY_SIGNATURE_TYPE != 0 "
                "(proxy/email wallets)."
            )

        if funder:
            client = ClobClient(
                host,
                key=private_key,
                chain_id=chain_id,
                signature_type=signature_type,
                funder=funder,
            )
        else:
            client = ClobClient(
                host,
                key=private_key,
                chain_id=chain_id,
                signature_type=signature_type,
            )

        creds = client.create_or_derive_api_creds()  # type: ignore
        client.set_api_creds(creds)  # type: ignore
        self._api_creds = creds
        self._trading_clob = client
        return client

    def get_api_creds(self) -> ApiCreds:
        if self._api_creds is not None:
            return self._api_creds
        client = self._get_trading_clob_client()
        creds = client.create_or_derive_api_creds()  # type: ignore
        self._api_creds = creds
        return creds

    def get_user_ws_auth(self) -> dict[str, str]:
        api_key = os.getenv("CLOB_API_KEY", "").strip()
        api_secret = os.getenv("CLOB_API_SECRET", "").strip()
        api_passphrase = os.getenv("CLOB_API_PASSPHRASE", "").strip()
        if not api_key or not api_secret or not api_passphrase:
            raise RuntimeError(
                "Missing CLOB_API_KEY/CLOB_API_SECRET/CLOB_API_PASSPHRASE for user websocket auth."
            )
        return {
            "apiKey": api_key,
            "secret": api_secret,
            "passphrase": api_passphrase,
        }

    def check_orders(self, client: ClobClient) -> list[Order]:
        """
        Fetches open orders and casts them to the strict 'Order' structure.
        """
        try:
            raw_orders = client.get_orders(OpenOrderParams())  # type: ignore
            if isinstance(raw_orders, list):
                return cast(list[Order], raw_orders)
            return []
        except Exception as e:
            print(f"❌ Check Orders Error: {e}")
            return []

    def get_open_orders(self) -> list[Order]:
        """
        Convenience wrapper around check_orders() using the authenticated client.
        """
        client = self._get_trading_clob_client()
        return self.check_orders(client)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        client = self._get_trading_clob_client()
        resp = client.cancel(order_id)  # type: ignore
        if isinstance(resp, dict):
            return cast(dict[str, Any], resp)
        return {"result": resp}

    def cancel_all_orders(self) -> dict[str, Any]:
        client = self._get_trading_clob_client()
        resp = client.cancel_all()  # type: ignore
        if isinstance(resp, dict):
            return cast(dict[str, Any], resp)
        return {"result": resp}

    def place_limit_order(
        self,
        token_id: str,
        side: Side,
        size: float,
        price: float,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        """
        Places a LIMIT order.

        - size is in shares
        - price is in dollars [0.00, 1.00]
        - ttl_seconds:
            * None -> GTC (Good-Til-Cancelled)
            * >= 60 -> GTD (Good-Til-Date) with expiration unix timestamp (UTC seconds)
        """
        if size <= 0:
            raise ValueError("size must be > 0")
        if price <= 0 or price >= 1:
            raise ValueError("price must be between 0 and 1 (exclusive)")

        side_const = BUY if side == "BUY" else SELL

        if ttl_seconds is None:
            order = OrderArgs(token_id=token_id, price=price, size=size, side=side_const)
            client = self._get_trading_clob_client()
            signed = client.create_order(order)  # type: ignore
            resp = client.post_order(signed, OrderType.GTC)  # type: ignore
        else:
            if ttl_seconds < 0:
                raise ValueError("ttl_seconds must be >= 0 due to GTD security threshold")
            expiration_ts = int(time.time()) + ttl_seconds
            order = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side_const,
                expiration=expiration_ts,
            )
            client = self._get_trading_clob_client()
            signed = client.create_order(order)  # type: ignore
            resp = client.post_order(signed, OrderType.GTD)  # type: ignore

        if isinstance(resp, dict):
            return cast(dict[str, Any], resp)
        return {"result": resp}

    def place_market_order(
        self,
        token_id: str,
        side: Side,
        size: float,
        order_type: OrderType = OrderType.FOK,
    ) -> dict[str, Any]:
        """
        Places a MARKET order using a FOK order type.
        """
        if size <= 0:
            raise ValueError("size must be > 0")

        side_const = BUY if side == "BUY" else SELL
        client = self._get_trading_clob_client()
        try:
            creds = client.create_or_derive_api_creds()  # type: ignore
            client.set_api_creds(creds)  # type: ignore
            self._api_creds = creds
        except Exception:
            # Fallback to existing creds if re-derive fails.
            pass

        order = MarketOrderArgs(
            token_id=token_id,
            amount=size,
            side=side_const,
            order_type=order_type,
        )
        signed = client.create_market_order(order)  # type: ignore
        resp = client.post_order(signed, order_type)  # type: ignore

        if isinstance(resp, dict):
            return cast(dict[str, Any], resp)
        return {"result": resp}


class OddsApiClient:
    def __init__(self, api_key: str, sport: str = "soccer_epl"):
        self.api_key = api_key
        self.sport = sport
        self.session = requests.Session()
        self.base_url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"

    def get_usage(self) -> tuple[int, int]:
        try:
            url = "https://api.the-odds-api.com/v4/sports"
            resp = self.session.get(url, params={"api_key": self.api_key})
            resp.raise_for_status()

            used = int(resp.headers.get("x-requests-used", 0))
            rem = int(resp.headers.get("x-requests-remaining", 0))
            return used, rem
        except Exception as e:
            print(f"❌ Quota Check Error: {e}")
            return 0, 0

    def get_sport_keys(self) -> list[dict[str, Any]]:
        """
        Fetches all available sports and their keys (e.g., 'americanfootball_nfl').
        """
        if not self.api_key:
            print("⚠️ No API Key provided")
            return []

        url = "https://api.the-odds-api.com/v4/sports"
        params = {"apiKey": self.api_key, "all": "true"}

        try:
            resp = self.session.get(url, params=params, timeout=10.0)
            resp.raise_for_status()
            return cast(list[dict[str, Any]], resp.json())
        except Exception as e:
            print(f"❌ Fetch Sports Error: {e}")
            return []

    def get_odds(self, regions: str = "eu", markets: str = "h2h,totals") -> list[dict[str, Any]]:
        if not self.api_key:
            return []

        params = {
            "api_key": self.api_key,
            "regions": regions,
            "markets": markets,
            "bookmakers": "pinnacle",
            "oddsFormat": "decimal",
        }
        try:
            resp = self.session.get(self.base_url, params=params, timeout=10.0)
            resp.raise_for_status()
            return cast(list[dict[str, Any]], resp.json())
        except Exception as e:
            print(f"❌ Odds API Error: {e}")
            return []


class PolySocket:
    """
    Handles WebSocket (CLOB) Connections
    """

    def __init__(self, asset_ids: list[str]):
        self.asset_ids = asset_ids
        self.ws: websocket.WebSocketApp | None = None
        self.thread: threading.Thread | None = None
        self.keep_running = True
        self._asset_lock = threading.Lock()

        self.on_book: BookCallback | None = None
        self.on_price_change: PriceChangeCallback | None = None
        self.on_tick_size_change: TickSizeCallback | None = None
        self.on_last_trade: LastTradeCallback | None = None

    def start(self) -> None:
        self.keep_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.keep_running = False
        if self.ws:
            cast(WebSocketAppProto, self.ws).close()

    def _run_loop(self) -> None:
        while self.keep_running:
            self.ws = websocket.WebSocketApp(
                WSS_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
            )
            cast(WebSocketAppProto, self.ws).run_forever(ping_interval=30, ping_timeout=10)

            if self.keep_running:
                print("⚠️ WebSocket disconnected. Reconnecting in 2s...")
                time.sleep(2.0)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        with self._asset_lock:
            assets = list(self.asset_ids)
        print(f"✅ Connected. Subscribing to {len(assets)} assets...")
        sub_msg: dict[str, Any] = {"assets_ids": assets, "type": "market"}
        ws.send(json.dumps(sub_msg))

    def update_assets(self, asset_ids: list[str], force_reconnect: bool = False) -> None:
        with self._asset_lock:
            self.asset_ids = asset_ids
            ws = self.ws
            assets = list(self.asset_ids)
        if ws and force_reconnect:
            try:
                ws.close()
            except Exception as e:
                print(f"⚠️ WebSocket Reconnect Error: {e}")
            return
        if ws:
            try:
                ws.send(json.dumps({"assets_ids": assets, "type": "market"}))
            except Exception as e:
                print(f"⚠️ WebSocket Subscribe Error: {e}")

    def _on_message(self, ws: websocket.WebSocketApp, msg_str: str) -> None:
        try:
            data: Any = json.loads(msg_str)
        except json.JSONDecodeError:
            return

        events: list[dict[str, Any]]
        if isinstance(data, list):
            events = cast(list[dict[str, Any]], data)
        elif isinstance(data, dict):
            events = [cast(dict[str, Any], data)]
        else:
            return

        for ev in events:
            etype = str(ev.get("event_type", ""))

            if etype == "book" and self.on_book:
                self.on_book(cast(WsBookMessage, ev))

            elif etype == "price_change" and self.on_price_change:
                self.on_price_change(cast(WsPriceChangeMessage, ev))

            elif etype == "tick_size_change" and self.on_tick_size_change:
                self.on_tick_size_change(cast(WsTickSizeChangeMessage, ev))
            elif etype == "last_trade_price" and self.on_last_trade:
                self.on_last_trade(cast(WsLastTradePriceMessage, ev))

    def _on_error(self, ws: websocket.WebSocketApp, error: object) -> None:
        print(f"❌ WebSocket Error: {error}")

class UserSocket:
    """
    Handles authenticated user WebSocket events (orders, trades).
    """

    def __init__(self, auth: dict[str, str]):
        self.auth = auth
        self.ws: websocket.WebSocketApp | None = None
        self.thread: threading.Thread | None = None
        self.keep_running = True
        self.connected = False
        self.markets = self._parse_markets(os.getenv("POLY_USER_WS_MARKETS", ""))
        self._last_payload: dict[str, Any] | None = None
        self.last_message_ts: float | None = None
        self.last_error: str | None = None

        self.on_event: Callable[[dict[str, Any]], None] | None = None

    def start(self) -> None:
        self.keep_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.keep_running = False
        if self.ws:
            cast(WebSocketAppProto, self.ws).close()

    def _run_loop(self) -> None:
        while self.keep_running:
            print("User WS connecting...")
            self.ws = websocket.WebSocketApp(
                WSS_USER_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            cast(WebSocketAppProto, self.ws).run_forever(ping_interval=30, ping_timeout=10)

            if self.keep_running:
                time.sleep(2.0)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        self.connected = True
        print("User WS connected, sending auth...")
        auth_msg: dict[str, Any] = {
            "type": "user",
            "auth": self.auth,
        }
        if self.markets:
            auth_msg["markets"] = self.markets
        self._last_payload = auth_msg
        print(f"User WS subscribe payload (redacted): {self._redact(auth_msg)}")
        ws.send(json.dumps(auth_msg))

    def _on_message(self, ws: websocket.WebSocketApp, msg_str: str) -> None:
        self.last_message_ts = time.time()
        # print(f"User WS message: {msg_str}")
        try:
            data: Any = json.loads(msg_str)
        except json.JSONDecodeError:
            return

        if isinstance(data, dict) and self.on_event:
            self.on_event(cast(dict[str, Any], data))
        elif isinstance(data, list) and self.on_event:
            for item in data:
                if isinstance(item, dict):
                    self.on_event(cast(dict[str, Any], item))

    def _on_error(self, ws: websocket.WebSocketApp, error: object) -> None:
        self.connected = False
        self.last_error = str(error)
        print(f"User WS Error: {error}")

    def _on_close(
        self,
        ws: websocket.WebSocketApp,
        status_code: int | None,
        msg: str | None,
    ) -> None:
        self.connected = False
        print(f"User WS closed: code={status_code} msg={msg}")

    def is_connected(self) -> bool:
        return self.connected

    def get_status(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "last_message_ts": self.last_message_ts,
            "last_error": self.last_error,
            "last_payload": self._redact(self._last_payload) if self._last_payload else None,
        }

    def _parse_markets(self, raw: str) -> list[str]:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return parts

    def _redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _mask(value: object) -> object:
            if isinstance(value, str) and value:
                return "*****"
            return value
        out: dict[str, Any] = {}
        for key, val in payload.items():
            if key == "auth" and isinstance(val, dict):
                out[key] = {k: _mask(v) for k, v in val.items()}
            else:
                out[key] = val
        return out
