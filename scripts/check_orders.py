import os
import sys
from dotenv import load_dotenv
from py_clob_client.client import ClobClient # type: ignore
from src.clients import PolyClient
from src.config import CLOB_URL

def main():
    load_dotenv()
    key = os.getenv("POLY_KEY") or sys.exit("❌ No POLY_KEY found in .env")
    funder = os.getenv("POLY_KEY") or sys.exit("❌ No POLY_FUNDER found in .env")

    print("🔑 Authenticating ClobClient...")
    client = ClobClient(
        host=CLOB_URL, 
        key=key, 
        chain_id=137,
        funder=funder
    )

    try:
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
    except Exception as e:
        print(f"❌ Auth Error: {e}")
        return

    poly = PolyClient()
    
    print("📡 Fetching Open Orders...")
    orders = poly.check_orders(client)

    print("\n--- MY OPEN ORDERS ---")
    if not orders:
        print("No open orders found.")
    
    for order in orders:
        # Pylance is happy because 'order' is strictly typed as 'Order'
        oid = order.get("orderID", "N/A")
        side = order.get("side", "UNKNOWN")
        price = order.get("price", "0.00")
        size = order.get("size", "0.00")
        
        print(f"ID:    {oid}")
        print(f"Side:  {side}")
        print(f"Price: {price}")
        print(f"Size:  {size}")
        print("-" * 22)

if __name__ == "__main__":
    main()