from __future__ import annotations

from fastapi import APIRouter, HTTPException

from polymarket_bot.config import ODDS_SPORT_KEY
from polymarket_bot.server.helpers import _extract_team_from_question, _normalize_name, _ratio, _to_float
from polymarket_bot.server.odds_service import get_cached_odds, get_cached_odds_sports

router = APIRouter()


@router.get("/odds/implied")
def get_odds_implied(
    event_title: str,
    outcome: str,
    sport: str | None = None,
) -> dict[str, object]:
    sport_key = (sport or ODDS_SPORT_KEY).strip()
    if not sport_key:
        raise HTTPException(status_code=400, detail="Missing ODDS_SPORT in environment.")
    try:
        odds = get_cached_odds(sport_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    title_norm = _normalize_name(event_title)
    outcome_norm = _normalize_name(outcome)
    yes_no_outcome = outcome_norm in {"yes", "no"}
    hinted_team = _extract_team_from_question(event_title)
    hinted_team_norm = _normalize_name(hinted_team) if hinted_team else ""
    best_event: dict[str, object] | None = None
    best_score = 0

    for ev in odds:
        if not isinstance(ev, dict):
            continue
        home = _normalize_name(str(ev.get("home_team", "")))
        away = _normalize_name(str(ev.get("away_team", "")))
        name = _normalize_name(str(ev.get("name", "")))
        score = 0
        if home and home in title_norm:
            score += 40
        if away and away in title_norm:
            score += 40
        if hinted_team_norm:
            if home and hinted_team_norm in home:
                score += 40
            if away and hinted_team_norm in away:
                score += 40
        if score == 0:
            score = _ratio(title_norm, name)
        if score > best_score:
            best_score = score
            best_event = ev

    if not best_event or best_score < 50:
        raise HTTPException(status_code=404, detail="No matching odds event found.")

    bookmakers = best_event.get("bookmakers", [])
    if not isinstance(bookmakers, list):
        raise HTTPException(status_code=404, detail="No bookmakers for odds event.")

    best_price: float | None = None
    for bookmaker in bookmakers:
        if not isinstance(bookmaker, dict):
            continue
        markets = bookmaker.get("markets", [])
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            if str(market.get("key", "")) != "h2h":
                continue
            outcomes = market.get("outcomes", [])
            if not isinstance(outcomes, list):
                continue
            for item in outcomes:
                if not isinstance(item, dict):
                    continue
                name = _normalize_name(str(item.get("name", "")))
                if not name:
                    continue
                target = outcome_norm
                if yes_no_outcome and hinted_team_norm:
                    target = hinted_team_norm
                match_score = _ratio(target, name)
                if (
                    name == target
                    or name in target
                    or target in name
                    or match_score >= 70
                ):
                    price = _to_float(item.get("price", 0), 0.0)
                    if price > 0:
                        best_price = price
                        break
            if best_price:
                break
        if best_price:
            break

    if best_price is None or best_price <= 0:
        raise HTTPException(status_code=404, detail="No matching outcome odds found.")

    implied = 1.0 / best_price
    if yes_no_outcome and outcome_norm == "no":
        implied_no = max(0.0, min(1.0, 1.0 - implied))
        implied = implied_no
        best_price = (1.0 / implied_no) if implied_no > 0 else best_price
    return {
        "event_title": best_event.get("name", ""),
        "outcome": outcome,
        "price_decimal": best_price,
        "implied_probability": implied,
        "sport": sport_key,
    }


@router.get("/odds/raw")
def get_odds_raw(sport: str | None = None) -> dict[str, object]:
    sport_key = (sport or ODDS_SPORT_KEY).strip()
    if not sport_key:
        raise HTTPException(status_code=400, detail="Missing ODDS_SPORT in environment.")
    try:
        odds = get_cached_odds(sport_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"sport": sport_key, "count": len(odds), "events": odds}


@router.get("/odds/sports")
def get_odds_sports() -> dict[str, object]:
    try:
        sports = get_cached_odds_sports()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"count": len(sports), "sports": sports}
