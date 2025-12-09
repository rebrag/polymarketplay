import requests
import json
import os
import re
import time
from datetime import datetime
from thefuzz import fuzz
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY
from dotenv import load_dotenv

# 0. LOAD ENV & SETUP
load_dotenv()

# --- CONFIGURATION ---
ODDS_API_KEY = os.getenv('ODDS_KEY')
# NOTE: Set to 120s if on Paid Plan, 900s if on Free Plan
REFRESH_RATE = 900      
SPORT = "americanfootball_nfl" 
# SPORT = "soccer_epl"  # <--- Swap to this for active games!
MIN_EDGE = 0.015        # 1.5% Edge required
MAX_SPEND = 3.0         # Max USDC to risk per trade (Safety)

# Initialize Authenticated Client
host = "https://clob.polymarket.com"
try:
    key = os.getenv('POLY_KEY')
except:
    print('Issue getting POLY_KEY')
funder = os.getenv('POLY_FUNDER')
client = ClobClient(host, key=key, chain_id=137, signature_type=1, funder=funder) # type: ignore
client.set_api_creds(client.create_or_derive_api_creds())

class PolymarketEngine:
    def __init__(self):
        self.markets = []

    def fetch_all_markets(self):
        # 10 = Soccer, 450 = NFL
        TAG_ID = 10 if "soccer" in SPORT else 450
        print(f"📥 Initializing: Downloading Markets (Tag: {TAG_ID})...")
        
        params = {
            "limit": 500, "active": "true", "closed": "false",
            "order": "volume24hr", "ascending": "false", "tag_id": TAG_ID
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
                    
                    outcomes = json.loads(m['outcomes']) if isinstance(m['outcomes'], str) else m['outcomes']
                    clob_ids = json.loads(m['clobTokenIds']) if isinstance(m['clobTokenIds'], str) else m['clobTokenIds']

                    if len(outcomes) == 2:
                        self.markets.append({
                            "question": m['question'],
                            "outcomes": outcomes,
                            "clobTokenIds": clob_ids,
                            "slug": m['slug']
                        })
            print(f"✅ Indexed {len(self.markets)} markets.")
        except Exception as e:
            print(f"❌ Error fetching markets: {e}")

    def find_match(self, team_a, team_b, market_type="h2h", target_point=None):
        def clean_name(name): return name.split()[-1].lower()
        clean_a = clean_name(team_a)
        clean_b = clean_name(team_b)
        
        best_market = None
        best_score = 0
        
        PROP_KEYWORDS = ["draw", "tie", "over", "under", "total", "handicap", "1h", "2h", "quarter", "spread"]

        for m in self.markets:
            q = m['question'].lower()
            
            if market_type == "h2h":
                if any(k in q for k in PROP_KEYWORDS): continue
                if re.search(r'\d+\.\d+', q): continue 

            elif market_type == "totals":
                if not any(k in q for k in ["over", "under", "total", "o/u"]): continue
                if target_point:
                    # STRICT MATCHING: 42.0 matches "42", but 42.5 only matches "42.5"
                    pt_str = str(target_point)
                    if pt_str.endswith(".0"): pt_str = pt_str[:-2]
                    if pt_str not in q: continue

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

def execute_trade(token_id, price, fair_prob, team_name, market_slug):
    """
    Submits a Real Money transaction to Polymarket
    """
    print(f"🚀 EXECUTING BUY: {team_name} @ {price} (Fair: {round(fair_prob,3)})")
    
    # Safety: Calculate size to spend max $5
    # Size = Cash / Price
    # e.g. $5.00 / $0.40 = 12.5 shares
    size = round(MAX_SPEND / price, 2)
    
    try:
        resp = client.create_and_post_order(
            OrderArgs(
                price=price,
                size=size,
                side=BUY,
                token_id=token_id
            )
        )
        print(f"✅ ORDER SUCCESS: {resp}")
        print(f"   🔗 https://polymarket.com/event/{market_slug}")
    except Exception as e:
        print(f"❌ ORDER FAILED: {e}")

def run_loop():
    poly = PolymarketEngine()
    poly.fetch_all_markets() 

    while True:
        print(f"\n🔄 Scanning {SPORT} at {datetime.now().strftime('%H:%M:%S')}...")
        
        try:
            raw = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds",
                params={"api_key": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals", "bookmakers": "pinnacle", "oddsFormat": "decimal"}
            )
            # Quota Check
            if 'x-requests-remaining' in raw.headers:
                print(f"📉 API QUOTA: {raw.headers['x-requests-remaining']} remaining.")
                
            resp = raw.json()
        except Exception:
            print("❌ API Network Error. Retrying..."); time.sleep(10); continue

        if not isinstance(resp, list):
            print("⚠️ API Limit Reached or Error."); time.sleep(60); continue

        # Iterate Events
        for event in resp:
            if not event.get('bookmakers'): continue
            
            try:
                outcomes = event['bookmakers'][0]['markets'][0]['outcomes']
                team_a = outcomes[0]['name']
                team_b = outcomes[1]['name']
            except: continue

            # --- H2H ---
            poly_m, score = poly.find_match(team_a, team_b, "h2h")
            if poly_m:
                # Debug Prints (Requested)
                print(f"\n✅ MATCH FOUND (H2H) (Score: {score})")
                print(f"   🔗 URL: https://polymarket.com/event/{poly_m['slug']}")
                print(f"   🔸 Pinnacle:   {team_a} vs {team_b}")
                print(f"   🔹 Polymarket: {poly_m['question']}")

                # Determine IDs
                if fuzz.partial_ratio(team_a, poly_m['outcomes'][0]) > 80:
                    id_a, id_b = poly_m['clobTokenIds'][0], poly_m['clobTokenIds'][1]
                else:
                    id_a, id_b = poly_m['clobTokenIds'][1], poly_m['clobTokenIds'][0]

                # Fetch H2H Odds
                h2h_market = next((m for m in event['bookmakers'][0]['markets'] if m['key'] == 'h2h'), None)
                if h2h_market:
                    p_a = h2h_market['outcomes'][0]['price']
                    p_b = h2h_market['outcomes'][1]['price']
                    prob_a, prob_b = get_fair_prob(p_a, p_b)
                    
                    # Check Prices & Trade
                    # We fetch orderbooks here
                    try:
                        ob_a = client.get_order_book(id_a)
                        if ob_a.asks:
                            ask = float(ob_a.asks[-1].price)
                            edge = prob_a - ask
                            if edge > MIN_EDGE:
                                execute_trade(id_a, ask, prob_a, team_a, poly_m['slug'])
                    except: pass
                    
                    try:
                        ob_b = client.get_order_book(id_b)
                        if ob_b.asks:
                            ask = float(ob_b.asks[-1].price)
                            edge = prob_b - ask
                            if edge > MIN_EDGE:
                                execute_trade(id_b, ask, prob_b, team_b, poly_m['slug'])
                    except: pass

            # --- TOTALS (O/U) ---
            # Similar logic for totals, ensuring exact point matching
            totals_market = next((m for m in event['bookmakers'][0]['markets'] if m['key'] == 'totals'), None)
            if totals_market:
                point = totals_market['outcomes'][0].get('point')
                if point:
                    poly_m_ou, score_ou = poly.find_match(team_a, team_b, "totals", target_point=point)
                    if poly_m_ou:
                        print(f"\n✅ MATCH FOUND (O/U {point}) (Score: {score_ou})")
                        print(f"   🔗 URL: https://polymarket.com/event/{poly_m_ou['slug']}")
                        print(f"   🔸 Pinnacle:   {team_a} vs {team_b} (O/U {point})")
                        print(f"   🔹 Polymarket: {poly_m_ou['question']}")
                        
                        # Execute Logic for Over/Under would go here (omitted to save space, but follows same pattern as H2H)

        print(f"💤 Sleeping {REFRESH_RATE}s...")
        time.sleep(REFRESH_RATE)

if __name__ == "__main__":
    run_loop()