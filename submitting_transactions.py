#submitting_transactions.py
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

# SETUP: You need your Private Key (from Metamask/Phantom)
# WARNING: Use a fresh "Burner Wallet" with $50 in it, not your main savings.
load_dotenv()
host = "https://clob.polymarket.com"
key: str = str(os.getenv('POLY_KEY'))
funder: str = str(os.getenv('POLY_FUNDER'))
chain_id = 137 # Polygon Mainnet

# Initialize Client
client = ClobClient(
    "https://clob.polymarket.com",
    key=key,
    chain_id=137,
    signature_type=1,  # <--- CRITICAL: '1' means "Magic/Email Wallet"
    funder=funder      # <--- CRITICAL: You must explicitly provide this for Proxy wallets #
)

client.set_api_creds(client.create_or_derive_api_creds())

# 1. Get a Market (Example: specific Token ID for a game/election)
# You can find these IDs in the URL or via the API's "get_markets"
token_id = "42351579455604873042957090441032286075880144797259231030267680078160718556927"

# 2. Check the Order Book
orderbook = client.get_order_book(token_id)
best_bid = orderbook.bids[-1].price if orderbook.bids else 0
best_ask = orderbook.asks[-1].price if orderbook.asks else 0

print(f"Market Status:")
print(f"Best person willing to BUY: {best_bid}")
print(f"Best person willing to SELL: {best_ask}")
spread = round(float(best_ask) - float(best_bid), 2)
print(f"Spread: {spread}")

# 3. (Optional) Place a Limit Order
# This places a BID to buy 10 shares at 50 cents.
resp = client.create_and_post_order(
    OrderArgs(
        price=0.01,
        size=5.0,
        side=BUY,
        token_id=token_id
    )
)
print(resp)