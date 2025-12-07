import requests
import json
import os
import time
import csv
from datetime import datetime
from thefuzz import fuzz, process
from py_clob_client.client import ClobClient
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
ODDS_API_KEY = os.getenv('ODDS_KEY')
SPORT = "upcoming"
CHECK_INTERVAL = 1800 # 30 Minutes (Safe for Free Tier)
MIN_EDGE = 0.01      # Log >1.5% edge

LOG_FILE = "sleep_log.csv"
client = ClobClient("https://clob.polymarket.com")

def log_opportunity(team, poly_price, true_prob, edge, url, event_start):
    """ Log with timestamp to verify 'freshness' """
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Time Found", "Match", "Poly Price", "True Prob", "Edge %", "Starts At", "URL"])
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([now, team, poly_price, round(true_prob, 3), round(edge*100, 2), event_start, url])
        print(f"📝 LOGGED: {team} (Edge: {round(edge*100, 1)}%)")

class PolymarketEngine:
    def __init__(self):
        self.markets = []

    def fetch_markets(self):
        # Fetch Top 1000 to catch everything
        try:
            url = "https://gamma-api.polymarket.com/events?limit=1000&active=true&closed=false&order=volume24hr&ascending=false"
            data = requests.get(url).json()
            
            self.markets = []
            for event in data:
                for m in event.get('markets', []):
                    if not m.get('outcomes') or not m.get('clobTokenIds'): continue
                    
                    # Handle raw strings if needed
                    outcomes = m['outcomes']
                    if isinstance(outcomes, str): outcomes = json.loads(outcomes)
                    clob_ids = m['clobTokenIds']
                    if isinstance(clob_ids, str): clob_ids = json.loads(clob_ids)

                    if len(outcomes) == 2:
                        self.markets.append({
                            "question": m['question'],
                            "outcomes": outcomes,
                            "clobTokenIds": clob_ids,
                            "slug": m['slug']
                        })
            print(f"✅ Updated Market List: {len(self.markets)} markets indexed.")
        except Exception as e:
            print(f"❌ Poly Error: {e}")

    def find_match(self, team_a, team_b):
        query = f"{team_a} vs {team_b}"
        choices = [m['question'] for m in self.markets]
        if not choices: return None, 0
        
        # Unpack safely
        result = process.extractOne(query, choices)
        if result:
            match_name = result[0]
            score = result[1]
            if score > 85:
                return next(m for m in self.markets if m['question'] == match_name), score
        return None, 0

def get_fair_prob(odds_a, odds_b):
    if odds_a <= 1 or odds_b <= 1: return 0,0
    imp_a = 1/odds_a
    imp_b = 1/odds_b
    juice = imp_a + imp_b
    return imp_a/juice, imp_b/juice

def run_scan():
    poly = PolymarketEngine()
    poly.fetch_markets()

    print(f"📡 Fetching Pinnacle Odds for '{SPORT}'...")
    try:
        raw = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds",
            params={"api_key": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "bookmakers": "pinnacle", "oddsFormat": "decimal"}
        )
        
        # Check Quota
        used = raw.headers.get('x-requests-used')
        remaining = raw.headers.get('x-requests-remaining')
        print(f"   📉 Quota: {used} used. {remaining} remaining.")
        
        resp = raw.json()
    except Exception:
        print("❌ API Error"); return

    if not isinstance(resp, list): print("⚠️ API Quota Error or Invalid Key"); return

    print(f"🔍 Scanning {len(resp)} events...")
    
    for event in resp:
        if not event.get('bookmakers'): continue
        pinnacle = event['bookmakers'][0]['markets'][0]['outcomes']
        if len(pinnacle) != 2: continue
        
        team_a = pinnacle[0]['name']
        team_b = pinnacle[1]['name']
        price_a = pinnacle[0]['price']
        price_b = pinnacle[1]['price']
        
        prob_a, prob_b = get_fair_prob(price_a, price_b)
        
        market, score = poly.find_match(team_a, team_b)
        
        if market:
            # Fuzzy match team names to outcomes
            if fuzz.partial_ratio(team_a, market['outcomes'][0]) > 80:
                tid_a = market['clobTokenIds'][0]
            else:
                tid_a = market['clobTokenIds'][1]

            try:
                ob = client.get_order_book(tid_a)
                if ob.asks:
                    ask_price = float(ob.asks[-1].price)
                    edge = prob_a - ask_price
                    
                    if edge > MIN_EDGE:
                        url = f"https://polymarket.com/event/{market['slug']}"
                        log_opportunity(team_a, ask_price, prob_a, edge, url, event.get('commence_time'))
            except:
                pass

if __name__ == "__main__":
    print(f"💤 Sleep Bot Activated. Interval: {CHECK_INTERVAL/60} mins.")
    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"Crash prevention: {e}")
        
        print(f"Waiting {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)