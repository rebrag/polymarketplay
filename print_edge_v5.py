import requests
import json
import os
import re
from thefuzz import fuzz
from py_clob_client.client import ClobClient
from dotenv import load_dotenv

# 0. LOAD ENVIRONMENT VARIABLES
load_dotenv()

# --- CONFIG ---
ODDS_API_KEY = os.getenv('ODDS_KEY')
USE_LIVE_API = False    # Set TRUE to refresh data (Costs 1 Credit)
SPORT = "americanfootball_nfl"
MIN_EDGE = 0.01         # 1.0% Edge

client = ClobClient("https://clob.polymarket.com")

class PolymarketEngine:
    def __init__(self):
        self.markets = []

    def fetch_all_markets(self):
        NFL_TAG_ID = 450 
        print(f"📥 Downloading NFL Markets (Tag: {NFL_TAG_ID})...")
        
        params = {
            "limit": 500, "active": "true", "closed": "false",
            "order": "volume24hr", "ascending": "false", "tag_id": NFL_TAG_ID
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

                    # NFL markets are always 2-outcome
                    if len(outcomes) == 2:
                        self.markets.append({
                            "question": m['question'],
                            "outcomes": outcomes,
                            "clobTokenIds": clob_ids,
                            "slug": m['slug']
                        })
            print(f"✅ Indexed {len(self.markets)} NFL markets.")
        except Exception as e:
            print(f"❌ Error fetching NFL markets: {e}")

    def find_match(self, team_a, team_b, market_type="h2h", target_point=None):
        def clean_name(name):
            return name.split()[-1].lower()

        clean_a = clean_name(team_a)
        clean_b = clean_name(team_b)
        
        best_market = None
        best_score = 0
        
        # KEYWORDS TO BLOCK OR REQUIRE
        PROP_KEYWORDS = ["draw", "tie", "over", "under", "total", "handicap", "1h", "2h", "quarter", "spread"]

        for m in self.markets:
            q = m['question'].lower()
            
            # --- LOGIC BRANCHING ---
            if market_type == "h2h":
                # 1. BLOCK PROPS
                if any(k in q for k in PROP_KEYWORDS): continue
                
                # 2. BLOCK NUMBERS (Fixes the "O/U 43.5" leak)
                # If question contains a decimal number like "43.5", skip it
                if re.search(r'\d+\.\d+', q): continue 

            elif market_type == "totals":
                # Must look like a total
                if not any(k in q for k in ["over", "under", "total", "o/u"]): continue
                
                # Must contain the exact point number (e.g., "43.5")
                if target_point:
                    if str(target_point) not in q: continue

            # --- MATCHING ---
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

def check_price(token_id, fair_prob, label):
    try:
        ob = client.get_order_book(token_id)
        if ob.asks and len(ob.asks) > 0:
            ask_price = float(ob.asks[-1].price)
            edge = fair_prob - ask_price
            if edge > MIN_EDGE:
                return {"label": label, "price": ask_price, "edge": edge, "is_opp": True}
            return {"label": label, "price": ask_price, "edge": edge, "is_opp": False}
    except:
        pass
    return None

def scan_for_edges():
    poly = PolymarketEngine()
    poly.fetch_all_markets()

    if USE_LIVE_API:
        print(f"📡 Fetching Live Pinnacle Odds (H2H + Totals)...")
        try:
            raw = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds",
                params={"api_key": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "bookmakers": "pinnacle", "oddsFormat": "decimal"}
            )
            print(f"📉 API QUOTA: {raw.headers.get('x-requests-used')} used.")
            resp = raw.json()
            with open("odds_snapshot.json", "w") as f: json.dump(resp, f)
        except Exception as e: print(f"❌ API Error: {e}"); return
    else:
        print("📂 Loading local odds...")
        with open("odds_snapshot.json", "r") as f: resp = json.load(f)

    if not isinstance(resp, list): print("⚠️ API Error"); return

    print(f"🚀 Scanning {len(resp)} Pinnacle events...")
    
    unmatched_h2h = []
    unmatched_totals = []

    for event in resp:
        if not event.get('bookmakers'): continue
        
        # Identify Teams
        try:
            outcomes = event['bookmakers'][0]['markets'][0]['outcomes']
            team_a = outcomes[0]['name']
            team_b = outcomes[1]['name']
        except: continue

        h2h_found = False
        
        # Loop through markets inside this event
        for market in event['bookmakers'][0]['markets']:
            key = market['key']
            
            # --- HANDLE H2H ---
            if key == "h2h":
                outcomes = market['outcomes']
                price_a, price_b = outcomes[0]['price'], outcomes[1]['price']
                prob_a, prob_b = get_fair_prob(price_a, price_b)
                
                poly_m, score = poly.find_match(team_a, team_b, market_type="h2h")
                
                if poly_m:
                    h2h_found = True
                    
                    # PRINT BLOCK (H2H)
                    print(f"\n✅ MATCH FOUND (H2H) (Score: {score})")
                    print(f"   🔗 URL: https://polymarket.com/event/{poly_m['slug']}")
                    print(f"   🔸 Pinnacle:   {team_a} vs {team_b}")
                    print(f"   🔹 Polymarket: {poly_m['question']}")
                    
                    if fuzz.partial_ratio(team_a, poly_m['outcomes'][0]) > 80:
                        id_a, id_b = poly_m['clobTokenIds'][0], poly_m['clobTokenIds'][1]
                    else:
                        id_a, id_b = poly_m['clobTokenIds'][1], poly_m['clobTokenIds'][0]

                    res_a = check_price(id_a, prob_a, team_a)
                    res_b = check_price(id_b, prob_b, team_b)
                    
                    if res_a:
                        sym = "💰" if res_a['is_opp'] else "📉"
                        print(f"      {sym} {team_a}: Fair {round(prob_a,3)} vs Ask {res_a['price']} (Edge: {round(res_a['edge']*100,2)}%)")
                    if res_b:
                        sym = "💰" if res_b['is_opp'] else "📉"
                        print(f"      {sym} {team_b}: Fair {round(prob_b,3)} vs Ask {res_b['price']} (Edge: {round(res_b['edge']*100,2)}%)")

            # --- HANDLE TOTALS (OVER/UNDER) ---
            elif key == "totals":
                outcomes = market['outcomes']
                point = outcomes[0].get('point')
                if not point: continue
                
                price_over = next((o['price'] for o in outcomes if o['name'] == 'Over'), 0)
                price_under = next((o['price'] for o in outcomes if o['name'] == 'Under'), 0)
                prob_over, prob_under = get_fair_prob(price_over, price_under)
                
                poly_m, score = poly.find_match(team_a, team_b, market_type="totals", target_point=point)
                
                if poly_m:
                    # RESTORED PRINT BLOCK (TOTALS)
                    print(f"\n✅ MATCH FOUND (O/U {point}) (Score: {score})")
                    print(f"   🔗 URL: https://polymarket.com/event/{poly_m['slug']}")
                    print(f"   🔸 Pinnacle:   {team_a} vs {team_b} (O/U {point})")
                    print(f"   🔹 Polymarket: {poly_m['question']}")

                    if "Over" in poly_m['outcomes'][0]:
                        id_over, id_under = poly_m['clobTokenIds'][0], poly_m['clobTokenIds'][1]
                    else:
                        id_over, id_under = poly_m['clobTokenIds'][1], poly_m['clobTokenIds'][0]

                    res_o = check_price(id_over, prob_over, f"Over {point}")
                    res_u = check_price(id_under, prob_under, f"Under {point}")

                    if res_o:
                        sym = "💰" if res_o['is_opp'] else "📉"
                        print(f"      {sym} Over {point}: Fair {round(prob_over,3)} vs Ask {res_o['price']} (Edge: {round(res_o['edge']*100,2)}%)")
                    if res_u:
                        sym = "💰" if res_u['is_opp'] else "📉"
                        print(f"      {sym} Under {point}: Fair {round(prob_under,3)} vs Ask {res_u['price']} (Edge: {round(res_u['edge']*100,2)}%)")
                else:
                    unmatched_totals.append(f"{team_a} vs {team_b} (O/U {point})")

        if not h2h_found:
            unmatched_h2h.append(f"{team_a} vs {team_b}")

    print("\n" + "="*50)
    print(f"📉 UNMATCHED H2H EVENTS ({len(unmatched_h2h)}):")
    for e in unmatched_h2h: print(f"   ❌ {e}")
    print("\n📉 UNMATCHED TOTALS (Sample):")
    for e in unmatched_totals[:10]: print(f"   ❌ {e}")
    print("="*50)

if __name__ == "__main__":
    scan_for_edges()