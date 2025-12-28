from pathlib import Path

# Polymarket API Constants
GIAYN_ADDRESS: str = "0x507e52ef684ca2dd91f90a9d26d149dd3288beae"
REST_URL: str = "https://data-api.polymarket.com/activity"
GAMMA_URL: str = "https://gamma-api.polymarket.com/events"
WSS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WSS_USER_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
CLOB_URL = "https://clob.polymarket.com"

# These are used primarily for edge_scanner.py
POLY_TAG_ID: int = 450  # 306 for EPL Soccer, 450 for NFL
ODDS_SPORT_KEY: str = "americanfootball_nfl"

# File Paths
OUTPUT_ROOT: Path = Path("output")
TRADES_CSV_PATH: Path = OUTPUT_ROOT / "giayn_trades.csv"
