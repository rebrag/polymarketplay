import json
import requests
from typing import List, Any, Dict, cast
from src.config import GAMMA_URL

def normalize_point(point: float | str | None) -> str:
    if point is None:
        return ""
    try:
        f_point = float(point)
        if f_point.is_integer():
            return str(int(f_point))
        return str(f_point)
    except (ValueError, TypeError):
        return str(point)

def get_fair_prob(*odds: float) -> List[float]:
    implied = [1 / o for o in odds if o > 1.0]
    if not implied:
        return [0.0] * len(odds)
    juice = sum(implied)
    return [i / juice for i in implied]

def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) # type: ignore
    except (ValueError, TypeError):
        return default

def get_tokens_from_game(user_input: str) -> str:
    slug = ""
    
    # Simple parsing logic
    if "polymarket.com/event/" in user_input:
        try:
            clean_url = user_input.split("?")[0]
            slug = clean_url.rstrip("/").split("/")[-1]
        except Exception:
            slug = user_input.strip()
    else:
        slug = user_input.strip()

    try:
        resp = requests.get(GAMMA_URL, params={"slug": slug}, timeout=10.0)
        resp.raise_for_status()
        
        # FIX: Strict casting of the JSON response
        data = cast(List[Dict[str, Any]], resp.json())
        
        if not data:
            return f"❌ No event found for input: '{user_input}'"
            
        event = data[0]
        
        event_title = str(event.get("title", "Unknown Title"))
        event_slug = str(event.get("slug", "Unknown Slug"))
        event_id = str(event.get("id", "N/A"))
        
        # FIX: Cast markets list
        markets = cast(List[Dict[str, Any]], event.get("markets", []))
        
        output_lines = [
            f"🎯 EVENT: {event_title}",
            f"🔗 SLUG:  {event_slug}",
            f"🆔 ID:    {event_id}",
            "-" * 40
        ]

        for m in markets:
            q = str(m.get("question", "No Question"))
            cond_id = str(m.get("conditionId", "N/A"))
            
            out_raw = m.get("outcomes", "[]")
            clob_raw = m.get("clobTokenIds", "[]")
            
            try:
                # Handle stringified JSON or raw lists
                outcomes_any = json.loads(out_raw) if isinstance(out_raw, str) else out_raw
                clob_ids_any = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                
                # FIX: Cast to list for Pylance
                outcomes = cast(List[Any], outcomes_any) if isinstance(outcomes_any, list) else []
                clob_ids = cast(List[Any], clob_ids_any) if isinstance(clob_ids_any, list) else []
            except json.JSONDecodeError:
                outcomes, clob_ids = [], []

            output_lines.append(f"  📌 MARKET: {q}")
            output_lines.append(f"     Condition ID: {cond_id}")
            
            if len(outcomes) == len(clob_ids):
                for i, outcome in enumerate(outcomes):
                    output_lines.append(f"     - {outcome}: {clob_ids[i]}")
            else:
                output_lines.append(f"     ⚠️ Token mismatch (Outcomes: {len(outcomes)}, IDs: {len(clob_ids)})")
            
            output_lines.append("")

        return "\n".join(output_lines)

    except Exception as e:
        return f"❌ Error resolving game info: {str(e)}"