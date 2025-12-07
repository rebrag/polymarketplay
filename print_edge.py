import requests
import json
import os

# CONFIG
USE_LIVE_API = False
ODDS_API_KEY = str(os.getenv('ODDS_KEY'))
SPORT = "upcoming" # or 'americanfootball_nfl'
REGIONS = "eu" # Pinnacle is usually in 'eu' or 'uk' region data
MARKETS = "h2h" # Head to head (Win/Loss)

def get_fair_probability(odds_a, odds_b):
    """
    Converts Decimal Odds to True Probability (Removing the Vig/Fee).
    Pinnacle might offer 1.90 vs 1.90 (Implied 52.6% + 52.6% = 105.2%).
    The 5.2% is their fee. We must remove it to get the REAL odds.
    """
    implied_a = 1 / odds_a
    implied_b = 1 / odds_b
    
    # Total Market Percentage (usually > 100% due to fees)
    market_juice = implied_a + implied_b
    
    # "Devigged" (Fair) Probability
    true_prob_a = implied_a / market_juice
    true_prob_b = implied_b / market_juice
    
    return true_prob_a, true_prob_b

def scan_for_edges():
    if USE_LIVE_API:
        print("Fetching Pinnacle Odds...")
        # 1. Capture the raw response object first (don't .json() yet)
        raw_response = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds",
            params={
                "api_key": ODDS_API_KEY,
                "regions": REGIONS,
                "markets": MARKETS,
                "bookmakers": "pinnacle",
                "oddsFormat": "decimal"
            }
        )
        remaining = raw_response.headers.get('x-requests-remaining')
        used = raw_response.headers.get('x-requests-used')
        print(f"📉 API QUOTA: {used} used. {remaining} remaining.")

        # 3. Convert to JSON for the rest of the script
        resp = raw_response.json()
        
    else:
        print("📂 Loading from local file (Free)...")
        with open("odds_snapshot.json", "r") as f:
            resp = json.load(f)

    # ... The rest of your loop continues below ...
    print(f"Found {len(resp)} events. Scanning for EV...")
    # ...

    for event in resp:
        # We only care if Pinnacle has lines for this
        bookmakers = event.get('bookmakers', [])
        if not bookmakers: continue
        
        # Get Pinnacle's odds
        pinnacle = bookmakers[0]
        outcomes = pinnacle['markets'][0]['outcomes']
        
        # Assume 2-way market (Team A vs Team B)
        if len(outcomes) != 2: continue
        
        team_a = outcomes[0]['name']
        price_a = outcomes[0]['price']
        
        team_b = outcomes[1]['name']
        price_b = outcomes[1]['price']
        
        # CALCULATE TRUE PROBABILITY
        true_prob_a, true_prob_b = get_fair_probability(price_a, price_b)
        
        print(f"\nMatch: {team_a} vs {team_b}")
        print(f"Pinnacle Prices: {price_a} | {price_b}")
        print(f"True Probability: {round(true_prob_a*100, 1)}% | {round(true_prob_b*100, 1)}%")
        
        # HERE IS THE MONEY LOGIC:
        # If Polymarket Price < True Probability, it is +EV.
        # Example: True Prob is 60% (0.60). Polymarket is trading at 55 cents (0.55).
        # Edge = 5%.
        
        # You would insert your Polymarket lookup here to compare.
        # if polymarket_price_a < true_prob_a:
        #     print(f"💰 BUY {team_a}! Edge: {true_prob_a - poly_price}")

if __name__ == "__main__":
    scan_for_edges()