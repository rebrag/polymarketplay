import requests
import json
import os
import time
from datetime import datetime
from thefuzz import fuzz, process
from py_clob_client.client import ClobClient
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
ODDS_API_KEY = os.getenv('ODDS_KEY')
USE_LIVE_API = False    # Set TRUE only once to refresh Pinnacle data
SPORT = "americanfootball_nfl"      
MIN_EDGE = 0.01        # 1.5% Edge
MATCH_THRESHOLD = 70    

client = ClobClient("https://clob.polymarket.com")

class PolymarketEngine:
    def __init__(self):
        self.markets = []

    def fetch_all_markets(self):
        # NFL Tag ID found in your JSON: 450
        NFL_TAG_ID = 450 
        
        print(f"📥 Downloading ONLY NFL Markets (Tag: {NFL_TAG_ID})...")
        
        # We don't need a loop anymore because there are only ~30 active NFL markets
        params = {
            "limit": 100,
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
            "tag_id": NFL_TAG_ID 
        }
        
        try:
            url = "https://gamma-api.polymarket.com/events"
            resp = requests.get(url, params=params)
            data = resp.json()
            
            self.markets = []
            
            for event in data:
                if not event.get('markets'): continue
                for m in event['markets']:
                    if not m.get('outcomes') or not m.get('clobTokenIds'): continue
                    
                    # Safe Parse
                    outcomes = json.loads(m['outcomes']) if isinstance(m['outcomes'], str) else m['outcomes']
                    clob_ids = json.loads(m['clobTokenIds']) if isinstance(m['clobTokenIds'], str) else m['clobTokenIds']

                    # NFL markets are 2-outcome
                    if len(outcomes) == 2:
                        self.markets.append({
                            "question": m['question'],
                            "outcomes": outcomes,
                            "clobTokenIds": clob_ids,
                            "slug": m['slug']
                        })
            
            print(f"✅ Indexed {len(self.markets)} NFL markets.")
            
            # DEBUG: Prove it works
            if len(self.markets) > 0:
                print(f"   Sample: {self.markets[0]['question']}")
                
        except Exception as e:
            print(f"❌ Error fetching NFL markets: {e}")

    def find_match(self, team_a, team_b):
        # Clean Team Names (e.g. "Buffalo Bills" -> "Bills")
        ignore_words = ["City", "United", "FC", "Real", "Inter", "AC", "St.", "Saint"]
        def clean_name(name):
            return name.split()[-1].lower()

        clean_a = clean_name(team_a)
        clean_b = clean_name(team_b)
        
        best_market = None
        best_score = 0
        
        # EXPANDED BLACKLIST: Catch all the "Prop" markets
        FORBIDDEN_WORDS = [
            "draw", "tie", 
            "over", "under", "o/u", 
            "total", "handicap", "spread",
            "1h", "2h", "1q", "2q", "3q", "4q", # Quarters/Halves
            "points", "touchdown", "yards", "passing", "rushing" # Player Props
        ]

        for m in self.markets:
            q = m['question'].lower()
            
            # 1. TRAP FILTER: If it contains ANY forbidden word, skip it.
            if any(bad_word in q for bad_word in FORBIDDEN_WORDS):
                continue

            # 2. MATCHING LOGIC
            score = fuzz.token_set_ratio(f"{clean_a} vs {clean_b}", q)
            
            if score > best_score:
                best_score = score
                best_market = m
        
        if best_market and best_score > 85:
            return best_market, best_score
            
        return None, 0
    
def get_fair_prob(odds_a, odds_b):
    if odds_a <= 1 or odds_b <= 1: return 0, 0
    imp_a = 1 / odds_a
    imp_b = 1 / odds_b
    juice = imp_a + imp_b
    return imp_a / juice, imp_b / juice

def check_price(token_id, fair_prob, team_name):
    try:
        ob = client.get_order_book(token_id)
        if ob.asks and len(ob.asks) > 0:
            ask_price = float(ob.asks[-1].price)
            edge = fair_prob - ask_price
            
            if edge > MIN_EDGE:
                return {"team": team_name, "price": ask_price, "edge": edge, "is_opp": True}
            return {"team": team_name, "price": ask_price, "edge": edge, "is_opp": False}
    except:
        pass
    return None

def scan_for_edges():
    poly = PolymarketEngine()
    poly.fetch_all_markets()

    # Load Pinnacle Data
    if USE_LIVE_API:
        print(f"📡 Fetching Live Pinnacle Odds...")
        try:
            resp = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds",
                params={"api_key": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "bookmakers": "pinnacle", "oddsFormat": "decimal"}
            ).json()
            with open("odds_snapshot.json", "w") as f:
                json.dump(resp, f)
        except Exception as e:
            print(f"❌ Odds API Error: {e}"); return
    else:
        print("📂 Loading local odds...")
        try:
            with open("odds_snapshot.json", "r") as f:
                resp = json.load(f)
        except:
            print("❌ No local file. Set USE_LIVE_API=True."); return

    if not isinstance(resp, list): print("⚠️ API Error"); return

    print(f"🚀 Scanning {len(resp)} Pinnacle events against {len(poly.markets)} Poly markets...")
    
    matches_found = 0
    for event in resp:
        if not event.get('bookmakers'): continue
        pinnacle = event['bookmakers'][0]['markets'][0]['outcomes']
        if len(pinnacle) != 2: continue
        
        team_a = pinnacle[0]['name']
        team_b = pinnacle[1]['name']
        price_a = pinnacle[0]['price']
        price_b = pinnacle[1]['price']
        
        # 1. Get Fair Prob
        prob_a, prob_b = get_fair_prob(price_a, price_b)
        
        # 2. Find Match
        market, score = poly.find_match(team_a, team_b)
        
        if market:
            matches_found += 1
            
            # --- NEW PRINT BLOCK ---
            print(f"\n✅ MATCH FOUND (Score: {score})")
            print(f"   🔗 URL: https://polymarket.com/event/{market['slug']}") # <--- ADDED THIS
            print(f"   🔸 Pinnacle:   {team_a} vs {team_b}")
            print(f"   🔹 Polymarket: {market['question']}")
            
            # Determine which Token ID belongs to which team
            # We match Team A to the first outcome in Polymarket
            if fuzz.partial_ratio(team_a, market['outcomes'][0]) > 80:
                tid_a, tid_b = market['clobTokenIds'][0], market['clobTokenIds'][1]
                name_a_poly, name_b_poly = market['outcomes'][0], market['outcomes'][1]
            else:
                tid_a, tid_b = market['clobTokenIds'][1], market['clobTokenIds'][0]
                name_a_poly, name_b_poly = market['outcomes'][1], market['outcomes'][0]

            # Check Edges
            res_a = check_price(tid_a, prob_a, team_a)
            res_b = check_price(tid_b, prob_b, team_b)

            if res_a:
                sym = "💰" if res_a['is_opp'] else "📉"
                print(f"      {sym} {team_a}: Fair {round(prob_a,3)} vs Ask {res_a['price']} (Edge: {round(res_a['edge']*100,2)}%)")
            
            if res_b:
                sym = "💰" if res_b['is_opp'] else "📉"
                print(f"      {sym} {team_b}: Fair {round(prob_b,3)} vs Ask {res_b['price']} (Edge: {round(res_b['edge']*100,2)}%)")

            # Buy Signal
            if (res_a and res_a['is_opp']) or (res_b and res_b['is_opp']):
                print(f"   🚨 OPPORTUNITY! {market['slug']}")

        else:
            # Debug Near Misses
            query = f"{team_a} vs {team_b}"
            choices = [m['question'] for m in poly.markets]
            if choices:
                result = process.extractOne(query, choices)
                if result and result[1] > 60:
                    print(f"⚠️ Near Miss: '{query}' | Poly: '{result[0]}' ({result[1]})")

    print(f"\n🏁 Scan Complete. Found {matches_found} matches out of {len(resp)} events.")

if __name__ == "__main__":
    scan_for_edges()