import json
import threading
import time
import requests
import websocket
from typing import List, Optional, cast, Protocol, Dict, Any

from src.config import GAMMA_URL, WSS_URL, REST_URL
from src.models import (
    GammaEvent, 
    WsBookMessage, 
    WsPriceChangeMessage,
    WebSocketAppProto,
    TradeActivity,
    Order
)

# External Lib Imports
from py_clob_client.client import ClobClient # type: ignore
from py_clob_client.clob_types import OpenOrderParams # type: ignore

class BookCallback(Protocol):
    def __call__(self, msg: WsBookMessage) -> None: ...

class PriceChangeCallback(Protocol):
    def __call__(self, msg: WsPriceChangeMessage) -> None: ...

class PolyClient:
    """
    Handles HTTP (Gamma & Data API) Requests and CLOB Helpers
    """
    def __init__(self, timeout: float = 10.0):
        self.session = requests.Session()
        self.timeout = timeout

    def _parse_string_or_list(self, raw: object) -> List[str]:
        match raw:
            case str():
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return []
                if isinstance(parsed, list):
                    return [str(x) for x in cast(List[object], parsed)]
            case list():
                return [str(x) for x in cast(List[object], raw)]
            case _:
                return []
        return []

    def find_asset_id(self, slug: str, outcome_keyword: str) -> Optional[str]:
        try:
            resp = self.session.get(GAMMA_URL, params={"slug": slug}, timeout=self.timeout)
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
    
    def get_gamma_events(self, tag_id: int) -> List[GammaEvent]:
        params = {
            "limit": "500", "active": "true", "closed": "false",
            "order": "volume24hr", "ascending": "false", 
            "tag_id": str(tag_id)
        }
        try:
            resp = self.session.get(GAMMA_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return cast(List[GammaEvent], resp.json())
        except Exception as e:
            print(f"❌ Poly API Error: {e}")
            return []

    def get_trades(self, user_address: str, limit: int = 20) -> List[TradeActivity]:
        params = {
            "user": user_address,
            "type": "TRADE",
            "limit": str(limit),
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC"
        }
        try:
            resp = self.session.get(REST_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return cast(List[TradeActivity], resp.json())
        except Exception as e:
            print(f"❌ Trade Fetch Error: {e}")
            return []

    def check_orders(self, client: ClobClient) -> List[Order]:
        """
        Fetches open orders and casts them to the strict 'Order' structure.
        """
        try:
            # We fetch the raw data. Pylance doesn't know what this library returns...
            raw_orders = client.get_orders(OpenOrderParams()) #type: ignore
            
            # ...So we validate it's a list...
            if isinstance(raw_orders, list):
                return cast(List[Order], raw_orders)
            return []
        except Exception as e:
            print(f"❌ Check Orders Error: {e}")
            return []


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

    def get_sport_keys(self) -> List[Dict[str, Any]]:
        """
        Fetches all available sports and their keys (e.g., 'americanfootball_nfl').
        """
        if not self.api_key:
            print("⚠️ No API Key provided")
            return []

        url = "https://api.the-odds-api.com/v4/sports"
        params = {
            "apiKey": self.api_key,
            "all": "true" 
        }
        
        try:
            resp = self.session.get(url, params=params, timeout=10.0)
            resp.raise_for_status()
            return cast(List[Dict[str, Any]], resp.json())
        except Exception as e:
            print(f"❌ Fetch Sports Error: {e}")
            return []

    def get_odds(self, regions: str = "eu", markets: str = "h2h,totals") -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
            
        params = {
            "api_key": self.api_key,
            "regions": regions,
            "markets": markets,
            "bookmakers": "pinnacle",
            "oddsFormat": "decimal"
        }
        try:
            resp = self.session.get(self.base_url, params=params, timeout=10.0)
            resp.raise_for_status()
            return cast(List[Dict[str, Any]], resp.json())
        except Exception as e:
            print(f"❌ Odds API Error: {e}")
            return []

class PolySocket:
    """
    Handles WebSocket (CLOB) Connections
    """
    def __init__(self, asset_ids: List[str]):
        self.asset_ids = asset_ids
        self.ws: Optional[websocket.WebSocketApp] = None
        self.thread: Optional[threading.Thread] = None
        self.keep_running = True
        
        self.on_book: Optional[BookCallback] = None
        self.on_price_change: Optional[PriceChangeCallback] = None

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
                on_error=self._on_error
            )
            cast(WebSocketAppProto, self.ws).run_forever()
            
            if self.keep_running:
                print("⚠️ WebSocket disconnected. Reconnecting in 2s...")
                time.sleep(2.0)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        print(f"✅ Connected. Subscribing to {len(self.asset_ids)} assets...")
        sub_msg: Dict[str, Any] = {
            "assets_ids": self.asset_ids,
            "type": "market"
        }
        ws.send(json.dumps(sub_msg))

    def _on_message(self, ws: websocket.WebSocketApp, msg_str: str) -> None:
        try:
            data: Any = json.loads(msg_str)
        except json.JSONDecodeError:
            return

        events: List[Dict[str, Any]] = []
        
        if isinstance(data, list):
            events = cast(List[Dict[str, Any]], data)
        elif isinstance(data, dict):
            events = [cast(Dict[str, Any], data)]
        else:
            return

        for ev in events:
            etype = str(ev.get("event_type", ""))
            
            if etype == "book" and self.on_book:
                book_msg = cast(WsBookMessage, ev)
                self.on_book(book_msg)
                
            elif etype == "price_change" and self.on_price_change:
                pc_msg = cast(WsPriceChangeMessage, ev)
                self.on_price_change(pc_msg)

    def _on_error(self, ws: websocket.WebSocketApp, error: object) -> None:
        print(f"❌ WebSocket Error: {error}")