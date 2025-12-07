import requests
import os
from dotenv import load_dotenv

load_dotenv()

# Use your key
API_KEY = os.getenv('ODDS_KEY', 'YOUR_ODDS_API_KEY_HERE')

def get_keys():
    print("🔑 Fetching all available Sports Keys...")
    resp = requests.get(
        f"https://api.the-odds-api.com/v4/sports", 
        params={
            "apiKey": API_KEY,
            "all": "true" # <--- Forces it to show everything, not just popular stuff
        }
    )
    
    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        return

    data = resp.json()
    
    print(f"✅ Found {len(data)} sports.")
    print("-" * 40)
    
    # Filter for Esports specifically
    found_esports = False
    for sport in data:
        key = sport['key']
        if "esports" in key or "lol" in key or "league" in key:
            print(f"🎮 ESPORT FOUND: {sport['title']}")
            print(f"   Key: '{key}'") # <--- THIS IS WHAT YOU NEED
            print("-" * 40)
            found_esports = True
            
    if not found_esports:
        print("❌ No esports keys found. (Check if your plan includes them)")

if __name__ == "__main__":
    get_keys()