import json
import os
from thefuzz import fuzz

# FILES
POLY_FILE = "poly_markets_dump.json"
ODDS_FILE = "odds_snapshot.json"

def smart_match_debug(team_a, team_b, poly_markets):
    """
    Scans ALL markets and returns the absolute best candidate,
    along with a breakdown of why it was chosen.
    """
    best_market = "No Data"
    best_score = 0
    
    # Pre-clean names for better accuracy
    clean_a = team_a.replace(" FC", "").replace("FK ", "").lower()
    clean_b = team_b.replace(" FC", "").replace("FK ", "").lower()
    
    for m in poly_markets:
        q = m['question'].lower()
        
        # Check both teams individually
        score_a = fuzz.partial_ratio(clean_a, q)
        score_b = fuzz.partial_ratio(clean_b, q)
        
        # The score is the average of both teams matching
        avg_score = (score_a + score_b) / 2
        
        if avg_score > best_score:
            best_score = avg_score
            best_market = m['question']

    return best_market, best_score

def run_debug_v3():
    print("📂 Loading data...")
    try:
        with open(POLY_FILE, "r") as f:
            poly_markets = json.load(f)
        with open(ODDS_FILE, "r") as f:
            pinnacle_data = json.load(f)
    except FileNotFoundError:
        print("❌ Missing data files. Please run find_edge_v4.py first to download them.")
        return

    print(f"\n🕵️‍♂️ MATCH VERIFICATION LOG ({len(pinnacle_data)} events) 🕵️‍♂️")
    print("=" * 70)

    matches_found = 0
    
    for event in pinnacle_data:
        if not event.get('bookmakers'): continue
        
        # Get Pinnacle Names
        outcomes = event['bookmakers'][0]['markets'][0]['outcomes']
        team_a = outcomes[0]['name']
        team_b = outcomes[1]['name']
        
        print(f"🔸 Pinnacle:   {team_a} vs {team_b}")
        
        # Find the best candidate (Good or Bad)
        poly_name, score = smart_match_debug(team_a, team_b, poly_markets)
        
        print(f"🔹 Poly Best:  {poly_name}")
        print(f"   Score:      {score:.1f}/100")
        
        # VERDICT
        if score > 85:
            print("   ✅ VERDICT: MATCH CONFIRMED")
            matches_found += 1
        elif score > 65:
            print("   ⚠️ VERDICT: NEAR MISS (Review Manually)")
        else:
            print("   ❌ VERDICT: NO MATCH (Likely not listed)")
            
        print("-" * 70)

    print(f"🏁 Summary: {matches_found} valid matches found out of {len(pinnacle_data)} events.")

if __name__ == "__main__":
    run_debug_v3()