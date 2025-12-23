import requests
import json
from typing import Dict, Any

def test_balance_fetch(address: str) -> None:
    url: str = f"https://data-api.polymarket.com/value?user={address}"
    print(f"📡 Fetching data from: {url}...")
    
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data: Dict[str, Any] = resp.json()
        
        # Pretty print the raw response to inspect the structure
        print("\n📝 Raw JSON Response:")
        print(json.dumps(data, indent=4))
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    # Using the address from your recent queries
    test_balance_fetch("0x507e52ef684ca2dd91f90a9d26d149dd3288beae")