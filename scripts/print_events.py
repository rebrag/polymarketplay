import sys
from pathlib import Path

# Setup root path to find src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.clients import PolyClient

def main():
    client = PolyClient()
    
    # 👇 STEP 1: Paste the specific slug you want here
    target_slug = "lol-lgd-edg-2025-12-21" 
    
    print(f"🔎 Fetching specific event: {target_slug}...")
    
    # 👇 STEP 2: Pass the slug to your client
    # The Gamma API returns a list, even if searching for one event
    events = client.get_gamma_events(slug=target_slug)
    
    if not events:
        print(f"❌ Event '{target_slug}' not found.")
        print("Tip: Double-check the URL. Are you using the Event slug (e.g. 'nfl-games') or the Market slug?")
        return

    # Grab the first market from the returned event
    first_event = events[0]
    
    # ... rest of your script remains the same ...
    first_event = events[0]
    markets = first_event.get("markets", [])
    
    if not markets:
        print("❌ Event has no markets.")
        return

    market = markets[0]

    print(f"\n✅ INSPECTING MARKET: {market.get('question', 'Unknown')}")
    print(f"🆔 ID: {market.get('id')}\n")
    print("-" * 50)
    print(f"{'KEY':<25} {'TYPE':<15} {'VALUE (Truncated)'}")
    print("-" * 50)

    # Loop through every single key returned by the API
    for key in sorted(market.keys()):
        val = market[key]
        val_type = type(val).__name__
        
        # Truncate long strings for readability
        val_str = str(val)
        if len(val_str) > 50:
            val_str = val_str[:47] + "..."
            
        print(f"{key:<25} {val_type:<15} {val_str}")

if __name__ == "__main__":
    main()