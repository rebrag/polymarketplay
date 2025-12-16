from __future__ import annotations
import sys
import os
from pathlib import Path
from typing import Optional, TypedDict, List, Dict
from py_clob_client.client import ClobClient # type: ignore
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.clients import PolyClient, OddsApiClient
from src.engine import PolymarketEngine
from src.utils import get_fair_prob
# FIX: Import the new generic config variables
from src.config import POLY_TAG_ID, ODDS_SPORT_KEY

load_dotenv()
ODDS_API_KEY = os.getenv('ODDS_KEY', '')
CLOB_URL = "https://clob.polymarket.com"
MIN_EDGE = 0.01
USE_LIVE_API = True

class EdgeResult(TypedDict):
    label: str
    price: float
    edge: float
    is_opp: bool

clob_client = ClobClient(CLOB_URL)

def check_price(token_id: str, fair_prob: float, label: str) -> Optional[EdgeResult]:
    try:
        ob = clob_client.get_order_book(token_id) # type: ignore
        if hasattr(ob, 'asks') and ob.asks and len(ob.asks) > 0:
            ask_price = float(ob.asks[-1].price)
            edge = fair_prob - ask_price
            return {
                "label": label, "price": ask_price, "edge": edge, 
                "is_opp": edge > MIN_EDGE
            }
    except Exception:
        pass
    return None

def main():
    poly_client = PolyClient()
    # FIX: Use the sport key from config
    odds_client = OddsApiClient(ODDS_API_KEY, sport=ODDS_SPORT_KEY)
    engine = PolymarketEngine()

    print(f"📥 Fetching Polymarket Data (Tag: {POLY_TAG_ID})...")
    gamma_events = poly_client.get_gamma_events(POLY_TAG_ID)
    engine.ingest_events(gamma_events)

    if USE_LIVE_API:
        print("📡 Checking API Quota...")
        used, rem = odds_client.get_usage()
        print(f"   📉 Used: {used} | Remaining: {rem}")
        print(f"📡 Fetching Live Odds ({ODDS_SPORT_KEY})...")
        pinnacle_events = odds_client.get_odds()
    else:
        pinnacle_events = []
    
    print(f"🚀 Scanning {len(pinnacle_events)} Pinnacle events...")

    unmatched_h2h: List[str] = []
    unmatched_totals: List[str] = []

    for event in pinnacle_events:
        bookmakers = event.get('bookmakers', [])
        if not bookmakers: continue
        
        markets = bookmakers[0].get('markets', [])
        if not markets: continue
        
        try:
            outcomes = markets[0]['outcomes']
            team_a = outcomes[0]['name']
            team_b = outcomes[1]['name']
        except IndexError: continue

        h2h_found = False

        for m in markets:
            key = m['key']
            outcomes = m['outcomes']
            
            # --- H2H ---
            if key == "h2h":
                prices = [o['price'] for o in outcomes]
                probs = get_fair_prob(*prices)
                
                team_probs: Dict[str, float] = {}
                for i, o in enumerate(outcomes):
                    team_probs[o['name']] = probs[i]

                poly_m, score = engine.find_match(team_a, team_b, "h2h")
                
                if poly_m:
                    h2h_found = True
                    print(f"\n✅ MATCH FOUND (H2H) (Score: {score})")
                    print(f"   🔗 URL: https://polymarket.com/event/{poly_m['slug']}")
                    print(f"   🔸 Pinnacle:   {team_a} vs {team_b}")
                    
                    id_a, id_b = engine.get_h2h_ids(poly_m, team_a, team_b)

                    if id_a and team_a in team_probs:
                        prob = team_probs[team_a]
                        res = check_price(id_a, prob, team_a)
                        if res: 
                            sym = "💰" if res['is_opp'] else "📉"
                            print(f"      {sym} {team_a}: Fair {prob:.3f} vs Ask {res['price']} (Edge: {res['edge']*100:.2f}%)")
                    
                    if id_b and team_b in team_probs:
                        prob = team_probs[team_b]
                        res = check_price(id_b, prob, team_b)
                        if res:
                            sym = "💰" if res['is_opp'] else "📉"
                            print(f"      {sym} {team_b}: Fair {prob:.3f} vs Ask {res['price']} (Edge: {res['edge']*100:.2f}%)")
            
            # --- TOTALS ---
            elif key == "totals":
                point = outcomes[0].get('point')
                if point is None: continue
                
                prices = [o['price'] for o in outcomes]
                probs = get_fair_prob(*prices)
                
                poly_m, score = engine.find_match(team_a, team_b, "totals", point)
                
                if poly_m:
                    print(f"\n✅ MATCH FOUND (O/U {point}) (Score: {score})")
                    print(f"   🔗 URL: https://polymarket.com/event/{poly_m['slug']}")
                    print(f"   🔸 Pinnacle:   {team_a} vs {team_b} (O/U {point})")
                    print(f"   🔹 Polymarket: {poly_m['question']}")
                    
                    id_o, id_u = engine.get_totals_ids(poly_m)
                    
                    idx_o = 0 if "Over" in outcomes[0]['name'] else 1
                    idx_u = 1 if idx_o == 0 else 0

                    r_o = check_price(id_o, probs[idx_o], f"Over {point}")
                    r_u = check_price(id_u, probs[idx_u], f"Under {point}")

                    if r_o: 
                        sym = "💰" if r_o['is_opp'] else "📉"
                        print(f"      {sym} Over {point}: Fair {probs[idx_o]:.3f} vs Ask {r_o['price']} (Edge: {r_o['edge']*100:.2f}%)")
                    if r_u: 
                        sym = "💰" if r_u['is_opp'] else "📉"
                        print(f"      {sym} Under {point}: Fair {probs[idx_u]:.3f} vs Ask {r_u['price']} (Edge: {r_u['edge']*100:.2f}%)")
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
    main()