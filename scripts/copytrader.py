from __future__ import annotations

import sys
import os
import time
from pathlib import Path
from typing import Set, Dict, Any, cast
from dotenv import load_dotenv
from py_clob_client.client import ClobClient # type: ignore
from py_clob_client.clob_types import OrderArgs # type: ignore

# Path Fix
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from polymarket_bot.clients import PolyClient
from polymarket_bot.config import GIAYN_ADDRESS, CLOB_URL
from polymarket_bot.models import TradeActivity

# --- CONFIG ---
load_dotenv()
PK = os.getenv("POLY_KEY", "") # Your Polygon Private Key
POLL_INTERVAL = 2.0
FIXED_SIZE = 5.0 # Amount of USDC to bet per copy
MAX_SLIPPAGE = 0.05 # 5% Slippage tolerance

def main() -> None:
    if not PK:
        print("❌ Missing PRIVATE_KEY in .env")
        return

    # 1. Setup Clients
    reader = PolyClient()
    executor = ClobClient(
        host=CLOB_URL, 
        key=PK, 
        chain_id=137 # Polygon Mainnet
    )
    
    # 2. State
    seen_txs: Set[str] = set()
    
    # Bootstrap: Mark existing trades as seen
    print(f"📡 Bootstrapping history for {GIAYN_ADDRESS}...")
    initial_trades = reader.get_trades(GIAYN_ADDRESS, limit=50)
    for t in initial_trades:
        tx = t.get("transactionHash")
        if isinstance(tx, str):
            seen_txs.add(tx)
            
    print(f"✅ Synced. Watching for NEW trades (Fixed Size: ${FIXED_SIZE})...")

    while True:
        try:
            trades = reader.get_trades(GIAYN_ADDRESS, limit=10)
            
            # Process newest first (reverse chronological list)
            for trade in reversed(trades):
                tx_hash = trade.get("transactionHash")
                
                # Strict check for string type before using
                if not isinstance(tx_hash, str) or not tx_hash or tx_hash in seen_txs:
                    continue
                
                seen_txs.add(tx_hash)
                
                # Execute Copy
                execute_copy(executor, trade)

        except KeyboardInterrupt:
            print("\n🛑 Stopping CopyTrader.")
            break
        except Exception as e:
            print(f"⚠️ Loop Error: {e}")
        
        time.sleep(POLL_INTERVAL)

def execute_copy(client: ClobClient, trade: TradeActivity) -> None:
    # 1. Safe Extraction
    asset_raw = trade.get("asset")
    side_raw = trade.get("side")
    price_raw = trade.get("price")
    title_raw = trade.get("title", "Unknown")

    # 2. Type Checking
    if not asset_raw or not isinstance(side_raw, str):
        return
    if not isinstance(price_raw, (float, int)):
        return

    asset_id: str = asset_raw
    side: str = side_raw.upper()
    price: float = float(price_raw)
    title: str = str(title_raw)

    if price <= 0:
        return

    # 3. Slippage Calculation
    limit_price = round(price * (1 + MAX_SLIPPAGE) if side == "BUY" else price * (1 - MAX_SLIPPAGE), 2)
    
    # Sanity Check
    if limit_price >= 1.0 or limit_price <= 0.0:
        print(f"⚠️ Skipping: Price {limit_price} out of bounds")
        return

    print(f"🚀 COPYING: {side} {title} @ {limit_price} (Target: {price})")

    try:
        # 4. Execute Order & Fix Typing
        resp_any = client.create_and_post_order(
            OrderArgs(
                price=limit_price,
                size=FIXED_SIZE,
                side=side,
                token_id=asset_id
            )
        )
        
        # FIX: Explicit cast so Pylance knows this is a Dictionary, not a String
        resp = cast(Dict[str, Any], resp_any)
        
        order_id = resp.get("orderID", "Unknown")
        print(f"✅ Order Placed: {order_id}")
        
    except Exception as e:
        print(f"❌ Execution Failed: {e}")

if __name__ == "__main__":
    main()
