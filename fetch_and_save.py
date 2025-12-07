import json
import requests
import os
from dotenv import load_dotenv


load_dotenv()
API_KEY = os.getenv('ODDS_KEY')
print(API_KEY)
url = f"https://api.the-odds-api.com/v4/sports/upcoming/odds?regions=eu&markets=h2h&apiKey={API_KEY}"

print("Fetching live data...")
data = requests.get(url).json()

with open("odds_snapshot.json", "w") as f:
    json.dump(data, f, indent=4)

print("✅ Data saved to 'odds_snapshot.json'. You can now code offline!")