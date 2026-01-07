import json
import re
from typing import List, Optional, Tuple, TypedDict, Any, cast
from thefuzz import fuzz # type: ignore

from polymarket_bot.models import GammaEvent
from polymarket_bot.utils import normalize_point

class EngineMarket(TypedDict):
    question: str
    outcomes: List[str]
    clobTokenIds: List[str]
    slug: str

class PolymarketEngine:
    def __init__(self) -> None:
        self.markets: List[EngineMarket] = []

    def ingest_events(self, events: List[GammaEvent]) -> None:
        self.markets = []
        for event in events:
            raw_markets = event.get('markets', [])
            if not raw_markets: continue

            for m in raw_markets:
                out_raw = m.get('outcomes', '[]')
                clob_raw = m.get('clobTokenIds', '[]')
                
                try:
                    outcomes_any = json.loads(out_raw)
                    clob_ids_any = json.loads(clob_raw)
                    
                    if isinstance(outcomes_any, list) and isinstance(clob_ids_any, list):
                        outcomes_list = cast(List[Any], outcomes_any)
                        clob_list = cast(List[Any], clob_ids_any)
                        
                        # FIX: Allow 2 OR 3 outcomes (Soccer H2H has 3)
                        if len(outcomes_list) in [2, 3]:
                            self.markets.append({
                                "question": m.get('question', ''),
                                "outcomes": [str(o) for o in outcomes_list],
                                "clobTokenIds": [str(c) for c in clob_list],
                                "slug": m.get('slug', '')
                            })
                except json.JSONDecodeError:
                    continue
        
        print(f"✅ Indexed {len(self.markets)} markets.")

    def find_match(self, team_a: str, team_b: str, market_type: str = "h2h", target_point: Optional[float] = None) -> Tuple[Optional[EngineMarket], int]:
        clean_a = team_a.split()[-1].lower()
        clean_b = team_b.split()[-1].lower()
        
        best_market: Optional[EngineMarket] = None
        best_score = 0
        
        # We removed "draw" from blocked keywords since we WANT 3-way markets now
        PROP_KEYWORDS = ["over", "under", "total", "handicap", "1h", "2h", "quarter", "spread", "double chance"]

        for m in self.markets:
            q = m['question'].lower()
            
            if market_type == "h2h":
                if any(k in q for k in PROP_KEYWORDS): continue
                # Block digit-only spreads/totals (e.g. "4.5"), but allow years (2025)
                if re.search(r'\d+\.\d+', q): continue 

            elif market_type == "totals":
                if not any(k in q for k in ["over", "under", "total", "o/u"]): continue
                if target_point is not None:
                    cp = normalize_point(target_point)
                    if cp not in q: continue

            score = int(fuzz.token_set_ratio(f"{clean_a} vs {clean_b}", q)) #type: ignore
            
            if score > best_score:
                best_score = score
                best_market = m
        
        if best_market and best_score > 85:
            return best_market, best_score
        return None, 0

    def get_h2h_ids(self, market: EngineMarket, team_a: str, team_b: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Intelligently finds ID for Team A and Team B in a list of 2 or 3 outcomes.
        Returns (id_a, id_b).
        """
        outcomes = market['outcomes']
        ids = market['clobTokenIds']
        
        best_a_idx = -1
        best_a_score = 0
        best_b_idx = -1
        best_b_score = 0
        
        # Find best match for Team A
        for i, out in enumerate(outcomes):
            score = int(fuzz.partial_ratio(team_a, out)) #type: ignore
            if score > best_a_score:
                best_a_score = score
                best_a_idx = i
                
        # Find best match for Team B
        for i, out in enumerate(outcomes):
            score = int(fuzz.partial_ratio(team_b, out)) #type: ignore
            if score > best_b_score:
                best_b_score = score
                best_b_idx = i

        # Validation: Ensure scores are decent and we didn't pick the same ID
        id_a = ids[best_a_idx] if best_a_score > 60 else None
        id_b = ids[best_b_idx] if best_b_score > 60 else None
        
        if best_a_idx == best_b_idx:
            return None, None
            
        return id_a, id_b

    def get_totals_ids(self, market: EngineMarket) -> Tuple[str, str]:
        outcomes = market['outcomes']
        ids = market['clobTokenIds']
        
        # Usually Over is first or has "Over" in text
        if "Over" in outcomes[0]:
            return ids[0], ids[1]
        return ids[1], ids[0]
