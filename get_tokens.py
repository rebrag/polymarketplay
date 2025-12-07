import requests

# 1. The "Slug" from the URL
# URL: https://polymarket.com/event/russia-x-ukraine-ceasefire-in-2025
slug = "russia-x-ukraine-ceasefire-in-2025"

def get_market_tokens(slug):
    print(f"🔎 Fetching data for: {slug}...")
    
    # We hit the "Gamma" API (Polymarket's Data Layer) directly
    # This is more reliable than the python client for lookups
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print("❌ No event found. Check the slug spelling.")
            return

        # Polymarket events can have multiple markets (e.g., "Will it rain?" has "Yes" and "No")
        # usually data[0] is the main event wrapper
        event = data[0]
        markets = event.get('markets', [])
        
        print(f"\n📅 Event: {event.get('title')}")
        
        for market in markets:
            print(f"\n  Market Question: {market.get('question')}")
            print(f"  Condition ID: {market.get('conditionId')}")
            
            # Use 'clobTokenIds' to get the actual IDs for the bot
            # usually index 0 is YES (or first outcome), index 1 is NO
            outcomes = JSON_outcomes = eval(market.get('outcomes')) # outcomes are stored as string "['Yes', 'No']"
            token_ids = eval(market.get('clobTokenIds')) 
            
            for i, outcome in enumerate(outcomes):
                print(f"    👉 OUTCOME: {outcome}")
                print(f"       Token ID: {token_ids[i]}") # <--- COPY THIS ID FOR YOUR BOT

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_market_tokens(slug)