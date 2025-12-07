from py_clob_client.client import ClobClient
from dotenv import load_dotenv
import os


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
# ... setup your client with keys as before ...

# Fetch open orders
# You can pass the specific 'token_id' to filter, or leave it blank to see all
resp = client.get_orders()

print("--- MY OPEN ORDERS ---")
for order in resp:
    print(f"ID: {order['orderID']}")
    print(f"Side: {order['side']} (BUY/SELL)")
    print(f"Price: {order['price']}")
    print(f"Size: {order['size']}")
    print("----------------------")