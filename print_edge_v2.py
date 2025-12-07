import requests
import json
import os
import time
from thefuzz import fuzz, process
from py_clob_client.client import ClobClient
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
USE_LIVE_PINNACLE = False  # Set True to refresh Pinnacle odds
ODDS_API_KEY = os.getenv('ODDS_KEY') 
SPORT = "upcoming"
MATCH_THRESHOLD = 85 
MIN_EDGE = 0.01 # Only show bets with >1% edge

# Initialize Read-Only Client for Prices
poly_client = ClobClient("https://clob.polymarket.com")

class PolymarketEngine:
    def __init__(self):
        self.markets = []
        
    def fetch_active_markets(self):
        print("🔍 Downloading Polymarket 'World State' (Top 1000)...")
        # We fetch MORE markets (1000) to ensure we find the niche sports
        url = "https://gamma-api.polymarket.com/events"
        params = {
            "limit": 1000,
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false"
        }
        
        try:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            print(f"   (Raw API returned {len(data)} events)")

            for event in data:
                # Safety check: Event must exist
                if not event: continue

                event_title = event.get('title', 'Unknown')
                markets = event.get('markets', [])
                
                for m in markets:
                    # --- CRASH FIX: Check if data exists before parsing ---
                    raw_outcomes = m.get('outcomes')
                    raw_clob_ids = m.get('clobTokenIds')
                    
                    if not raw_outcomes or not raw_clob_ids:
                        continue 

                    try:
                        # Handle Strings vs Lists automatically
                        outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
                        clob_ids = json.loads(raw_clob_ids) if isinstance(raw_clob_ids, str) else raw_clob_ids
                    except Exception:
                        continue # Skip malformed JSON

                    # We only match 2-outcome markets (Team A vs Team B)
                    if isinstance(outcomes, list) and len(outcomes) == 2:
                        self.markets.append({
                            "question": m.get('question'),
                            "outcomes": outcomes,
                            "clobTokenIds": clob_ids,
                            "market_slug": m.get('slug')
                        })
                        
            print(f"✅ Indexed {len(self.markets)} active 2-outcome markets.")
            
        except Exception as e:
            print(f"❌ Error fetching Polymarket data: {e}")

    def find_match(self, team_a, team_b):
        """ Fuzzy matches Pinnacle teams to Polymarket Questions """
        query = f"{team_a} vs {team_b}"
        choices = [m['question'] for m in self.markets]
        
        # Safety Check: If no markets loaded, return fail
        if not choices:
            return None, 0

        # Extract best match
        # We assign to a single variable 'result' to handle (Match, Score) OR (Match, Score, Index)
        result = process.extractOne(query, choices)
        
        if result:
            best_match = result[0]
            score = result[1]
            
            if score > MATCH_THRESHOLD:
                # Find the full market object that corresponds to the matched question
                return next(m for m in self.markets if m['question'] == best_match), score
        
        return None, 0

def get_fair_probability(odds_a, odds_b):
    """ Converts Pinnacle Decimal Odds to Fair Probability (No Vig) """
    if odds_a <= 1 or odds_b <= 1: return 0, 0
    implied_a = 1 / odds_a
    implied_b = 1 / odds_b
    market_juice = implied_a + implied_b
    return implied_a / market_juice, implied_b / market_juice

def get_poly_price(token_id):
    """ Fetches the current CHEAPEST SELL price (The price you buy at) """
    try:
        ob = poly_client.get_order_book(token_id)
        # We want the lowest ASK (Sell order) because we are buying
        if ob.asks and len(ob.asks) > 0:
            return float(ob.asks[-1].price) # [-1] is usually the best price in py-clob
    except Exception:
        return None
    return None

def scan_for_edges():
    # 1. Setup Polymarket
    poly = PolymarketEngine()
    poly.fetch_active_markets()

    # 2. Get Pinnacle Odds
    if USE_LIVE_PINNACLE:
        print("📡 Fetching Live Pinnacle Odds...")
        try:
            resp = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds",
                params={
                    "api_key": ODDS_API_KEY,
                    "regions": "eu", # Pinnacle is EU
                    "markets": "h2h",
                    "bookmakers": "pinnacle",
                    "oddsFormat": "decimal"
                }
            ).json()
            # Save for backup
            with open("odds_snapshot.json", "w") as f:
                json.dump(resp, f)
        except Exception as e:
            print(f"❌ Pinnacle API Error: {e}")
            return
    else:
        print("📂 Loading local odds...")
        with open("odds_snapshot.json", "r") as f:
            resp = json.load(f)

    if not isinstance(resp, list):
        print("⚠️ API returned an error message, not a list. Check your API Key.")
        print(resp)
        return

    # 3. Compare
    print(f"\n🚀 Scanning {len(resp)} events for arbitrage...")
    
    for event in resp:
        # Validate Event Data
        bookmakers = event.get('bookmakers', [])
        if not bookmakers: continue
        
        pinnacle = bookmakers[0]
        outcomes = pinnacle['markets'][0]['outcomes']
        if len(outcomes) != 2: continue 
        
        team_a = outcomes[0]['name']
        price_a = outcomes[0]['price']
        team_b = outcomes[1]['name']
        price_b = outcomes[1]['price']
        
        # Get Truth
        prob_a, prob_b = get_fair_probability(price_a, price_b)
        
        # Find Match
        poly_market, score = poly.find_match(team_a, team_b)
        
        if poly_market:
            # Check which team is which in Polymarket (Outcome 0 vs Outcome 1)
            # Simple check: Does Polymarket Outcome[0] match Team A?
            poly_outcome_0 = poly_market['outcomes'][0]
            
            # Match Team A to the correct Token ID
            # (We use fuzzy match again briefly to be sure we aren't betting on the wrong team)
            if fuzz.partial_ratio(team_a, poly_outcome_0) > 80:
                token_id_a = poly_market['clobTokenIds'][0]
                token_id_b = poly_market['clobTokenIds'][1]
            else:
                token_id_a = poly_market['clobTokenIds'][1]
                token_id_b = poly_market['clobTokenIds'][0]

            # --- THE MONEY CHECK ---
            # We check the price for Team A
            current_price = get_poly_price(token_id_a)
            
            if current_price:
                edge = prob_a - current_price
                
                # Output only if we found a match, regardless of edge, so you can see it working
                print(f"\n✅ MATCH: {team_a} vs {team_b} (Score: {score})")
                print(f"   📊 Pinnacle Truth: {round(prob_a, 3)} ({round(prob_a*100,1)}%)")
                print(f"   🛒 Polymarket Ask: {current_price}")
                
                if edge > MIN_EDGE:
                    print(f"   💰 BUY SIGNAL! Edge: {round(edge*100, 2)}% ROI")
                    print(f"      Action: Buy {team_a} (ID: {token_id_a})")
                else:
                    print(f"   📉 No Edge ({round(edge*100, 2)}%)")
            else:
                print(f"   ⚠️ Match found, but no sellers on Polymarket for {team_a}")

if __name__ == "__main__":
    scan_for_edges()