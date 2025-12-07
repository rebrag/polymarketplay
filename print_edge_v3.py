import requests
import json
import os
import time
from datetime import datetime, timezone
from thefuzz import fuzz, process
from py_clob_client.client import ClobClient
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
# 1. API KEYS
ODDS_API_KEY = os.getenv('ODDS_KEY')

# 2. STRATEGY & CACHING
USE_LIVE_API = False    # <--- SET TO TRUE TO REFRESH DATA (Costs 1 Credit)
SPORT = "upcoming"      # Use "upcoming" to catch everything
MIN_EDGE = 0.015        # 1.5% Edge required to bet
MATCH_THRESHOLD = 75    # Fuzzy match confidence

# 3. FILTERS
FETCH_LIMIT = 1000      # How many Polymarket events to index

# Initialize Read-Only Client
client = ClobClient("https://clob.polymarket.com")

class PolymarketEngine:
    def __init__(self):
        self.markets = []
        self.sports_tag_id = None

    def get_sports_tag_id(self):
        """ Dynamically finds the Tag ID for 'Sports' to filter out Politics """
        print("🔎 Looking up 'Sports' Tag ID...")
        try:
            resp = requests.get("https://gamma-api.polymarket.com/tags")
            tags = resp.json()
            for t in tags:
                if t.get('label') == "Sports":
                    self.sports_tag_id = t.get('id')
                    print(f"✅ Found Tag ID for Sports: {self.sports_tag_id}")
                    return
            print("⚠️ Could not find 'Sports' tag. Fetching ALL markets (slower).")
        except Exception as e:
            print(f"⚠️ Tag lookup failed: {e}")

    def fetch_markets(self):
        print(f"📥 Downloading Sports markets by Category...")
        
        # Known Polymarket Tag IDs for major sports
        # 10=Soccer, 13=Basketball, 21=Football(NFL), 74=Fighting
        target_tags = [10, 13, 21, 74] 
        
        self.markets = []
        
        for tag_id in target_tags:
            params = {
                "limit": 500, # Get top 500 of EACH sport
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
                "tag_id": tag_id
            }

            try:
                url = "https://gamma-api.polymarket.com/events"
                resp = requests.get(url, params=params)
                data = resp.json()
                
                for event in data:
                    if not event.get('markets'): continue
                    for m in event['markets']:
                        if not m.get('outcomes') or not m.get('clobTokenIds'): continue
                        
                        outcomes = json.loads(m['outcomes']) if isinstance(m['outcomes'], str) else m['outcomes']
                        clob_ids = json.loads(m['clobTokenIds']) if isinstance(m['clobTokenIds'], str) else m['clobTokenIds']

                        if len(outcomes) == 2:
                            self.markets.append({
                                "question": m['question'],
                                "outcomes": outcomes,
                                "clobTokenIds": clob_ids,
                                "slug": m['slug']
                            })
            except Exception as e:
                print(f"❌ Error fetching Tag {tag_id}: {e}")
                
        print(f"✅ Indexed {len(self.markets)} targeted Sports markets.")
        
    def find_match(self, team_a, team_b):
        query = f"{team_a} vs {team_b}"
        choices = [m['question'] for m in self.markets]
        if not choices: return None, 0
        
        # Flexible unpacking for different versions of thefuzz
        result = process.extractOne(query, choices)
        
        # Handle (Match, Score) or (Match, Score, Index)
        if result:
            best_match = result[0]
            score = result[1]
            if score > MATCH_THRESHOLD:
                return next(m for m in self.markets if m['question'] == best_match), score
        return None, 0

def get_fair_prob(odds_a, odds_b):
    """ Converts Pinnacle Decimal Odds to True Probability """
    if odds_a <= 1 or odds_b <= 1: return 0, 0
    imp_a = 1 / odds_a
    imp_b = 1 / odds_b
    juice = imp_a + imp_b
    return imp_a / juice, imp_b / juice

def check_price(token_id, fair_prob, team_name):
    """ Checks ONE side of the bet for an edge """
    try:
        ob = client.get_order_book(token_id)
        # We buy from the 'asks' (Sellers)
        if ob.asks and len(ob.asks) > 0:
            ask_price = float(ob.asks[-1].price) # Best Ask
            edge = fair_prob - ask_price
            
            if edge > MIN_EDGE:
                return {
                    "team": team_name,
                    "price": ask_price,
                    "prob": fair_prob,
                    "edge": edge,
                    "is_opportunity": True
                }
            return {"team": team_name, "price": ask_price, "edge": edge, "is_opportunity": False}
    except:
        pass
    return None

def scan_for_edges():
    # 1. Initialize Polymarket Engine
    poly = PolymarketEngine()
    poly.fetch_markets()

    # 2. Get Pinnacle Odds (Live or Cached)
    resp = []
    
    if USE_LIVE_API:
        print(f"📡 Fetching Live Pinnacle Odds for '{SPORT}'...")
        try:
            raw = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds",
                params={
                    "api_key": ODDS_API_KEY, 
                    "regions": "eu", 
                    "markets": "h2h", 
                    "bookmakers": "pinnacle", 
                    "oddsFormat": "decimal"
                }
            )
            
            # Quota Check
            used = raw.headers.get('x-requests-used')
            rem = raw.headers.get('x-requests-remaining')
            print(f"   📉 Quota: {used} used. {rem} remaining.")

            resp = raw.json()

            # Save to file
            with open("odds_snapshot.json", "w") as f:
                json.dump(resp, f)
                print("   💾 Snapshot saved to 'odds_snapshot.json'")

        except Exception as e:
            print(f"❌ Odds API Error: {e}"); return
    else:
        print("📂 Loading local odds from 'odds_snapshot.json'...")
        try:
            with open("odds_snapshot.json", "r") as f:
                resp = json.load(f)
        except FileNotFoundError:
            print("❌ No local file found! Please set USE_LIVE_API = True for one run.")
            return

    if not isinstance(resp, list): 
        print("⚠️ API Limit Reached or Error in data."); return

    print(f"🚀 Scanning {len(resp)} Pinnacle events...")
    
    for event in resp:
        # Validate Pinnacle Data
        if not event.get('bookmakers'): continue
        pinnacle = event['bookmakers'][0]['markets'][0]['outcomes']
        if len(pinnacle) != 2: continue
        
        team_a = pinnacle[0]['name']
        team_b = pinnacle[1]['name']
        price_a = pinnacle[0]['price']
        price_b = pinnacle[1]['price']
        
        # 1. Get True Probability
        prob_a, prob_b = get_fair_prob(price_a, price_b)
        
        # 2. Find Polymarket Match
        market, score = poly.find_match(team_a, team_b)
        
        if market:
            # 3. Identify Token IDs (Who is who?)
            # We match Team A to the outcomes list
            if fuzz.partial_ratio(team_a, market['outcomes'][0]) > 80:
                tid_a = market['clobTokenIds'][0]
                tid_b = market['clobTokenIds'][1]
            else:
                tid_a = market['clobTokenIds'][1]
                tid_b = market['clobTokenIds'][0]

            print(f"\n✅ MATCH FOUND: {team_a} vs {team_b} (Score: {score})")
            
            # 4. CHECK BOTH SIDES
            res_a = check_price(tid_a, prob_a, team_a)
            res_b = check_price(tid_b, prob_b, team_b)

            # Print Results
            if res_a:
                symbol = "💰" if res_a['is_opportunity'] else "📉"
                print(f"   {symbol} {team_a}: Fair {round(prob_a,3)} vs Ask {res_a['price']} (Edge: {round(res_a['edge']*100, 2)}%)")
            
            if res_b:
                symbol = "💰" if res_b['is_opportunity'] else "📉"
                print(f"   {symbol} {team_b}: Fair {round(prob_b,3)} vs Ask {res_b['price']} (Edge: {round(res_b['edge']*100, 2)}%)")

            # Buy Signal Logic
            if (res_a and res_a['is_opportunity']) or (res_b and res_b['is_opportunity']):
                print(f"   🚨 OPPORTUNITY DETECTED! URL: https://polymarket.com/event/{market['slug']}")

if __name__ == "__main__":
    scan_for_edges()