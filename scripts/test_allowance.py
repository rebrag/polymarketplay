import os
from typing import cast, Dict
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

load_dotenv()

def quick_test() -> None:
    try:
        # 1. Initialize Client (Using the derivation logic that worked)
        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=str(os.getenv("POLY_KEY", "")).strip(),
            funder=str(os.getenv("POLY_FUNDER", "")).strip(),
            signature_type=1
        )

        # 2. Re-load the credentials that were successful
        creds = client.derive_api_key()
        if not creds:
            print("❌ Failed to derive creds.")
            return
        client.set_api_creds(creds)

        # 3. FIX: For COLLATERAL, token_id must be None or omitted
        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            token_id=None # Setting this to None fixes the 400 error
        )
        params.signature_type = -1 

        print(f"📡 Requesting balance for {client.get_address()}...")
        
        # 4. Fetch
        raw_resp = client.get_balance_allowance(params)
        data = cast(Dict[str, str], raw_resp)

        print("\n✅ SUCCESS!")
        print(f"💰 Cash Balance: ${data['balance']}")
        print(f"🔓 Allowance:    ${data['allowance']}")

    except Exception as e:
        print(f"❌ Critical Error: {e}")

if __name__ == "__main__":
    quick_test()