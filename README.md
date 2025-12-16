# Polymarket Algo-Trading Bot

A modular, high-performance Python framework for interacting with the Polymarket CLOB (Central Limit Order Book) and Gamma APIs.

This project is a quantitative trading tool designed to:
1.  **Identify Arbitrage Edges:** Calculates "Fair Value" probabilities derived from **Pinnacle** (via The Odds API) and compares them against live Ask prices on Polymarket.
2.  **Automate Execution:** Provides tools for copy-trading, limit order management, and real-time book verification.

## 📂 Project Structure

This project is designed with a "Scripts & Source" architecture. The heavy lifting is done in the `src/` directory, while `scripts/` contains the executable tools you will actually run.

```text
├── scripts/                 # <--- 🚀 RUN THESE FILES
│   ├── verify_book.py       # Real-time WebSocket order book visualizer (Highly Recommended)
│   ├── trades_and_books.py  # Tracks trades and book updates simultaneously
│   ├── edge_scanner.py      # Scans for +EV bets vs Pinnacle odds (The "Brain")
│   ├── copytrader.py        # Automates copying a specific wallet's trades
│   ├── check_orders.py      # Checks your current open orders
│   └── lookup_game.py       # Quick utility to find Market IDs/Slugs
│
├── src/                     # Core logic (Do not edit unless developing)
│   ├── clients.py           # API Wrappers (HTTP & WebSocket)
│   ├── engine.py            # Matching engine for market reconciliation
│   ├── book.py              # Local OrderBook management
│   └── models.py            # Strict Type definitions
│
├── .env                     # API Keys and Secrets
└── pyproject.toml           # Package configuration

⚡ Quick Start
1. Prerequisites
Python 3.10+ (Tested on 3.12)

A Polymarket Account (with USDC on Polygon)

(Optional) An API Key from The Odds API for edge scanning

2. Installation
Clone the repo and install the project in editable mode. This ensures all scripts can find the src module automatically without path hacks.

```
# 1. Clone the repository
git clone <your-repo-url>
cd polymarket_bot

# 2. Install dependencies & project
pip install -e .
```

3. Configuration
Create a .env file in the root directory:
(.env.example is provided for context)

```
touch .env
```
Add your credentials to .env:
```
# Polymarket Credentials (Required for Trading/Orders)
PRIVATE_KEY=0xYourPolygonPrivateKeyHere
POLY_KEY=YourPolymarketApiKey
POLY_SECRET=YourPolymarketApiSecret
POLY_PASSPHRASE=YourPolymarketPassphrase
POLY_FUNDER=0xYourProxyWalletAddress  # Optional (if using proxy/magic link)

# Odds API (Required for Edge Scanner)
ODDS_KEY=YourTheOddsApiKey

# Copy Trading Target (Required for CopyTrader)
TARGET_WALLET=0xTargetAddressToCopy
```

🛠️ Usage Guide
🔍 1. Real-Time Market Analysis
These are the primary tools for monitoring the market state.

Verify Book (verify_book.py) Connects to the WebSocket and reconstructs the local order book in real-time. Useful for debugging latency or verifying liquidity for a specific market token.

```
python -m scripts.verify_book
```
Trades & Books Tracker (trades_and_books.py) Monitors live trades and order book updates simultaneously. Great for watching market activity on specific assets.
```
python -m scripts.trades_and_books
```

🤖 2. Automation & Trading
Edge Scanner (edge_scanner.py) The core arbitrage logic. It:

Fetches fresh odds from Pinnacle.

Uses fuzzy matching to align teams with Polymarket markets.

Calculates Edge: (Fair Probability) - (Polymarket Ask Price).

Outputs buy signals if the edge > 1%.
```
python -m scripts.edge_scanner
```
Check Orders (check_orders.py) A simple utility to view your currently open limit orders.
```
python -m scripts.check_orders
```

⚠️ Risk Warning
This software involves financial risk. The py-clob-client executes real transactions on the Polygon network.

Always test with small sizes first.

Secure your .env file. Never commit your Private Key to GitHub.

The authors are not responsible for financial losses incurred by using this software.

🤝 Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please ensure strict typing (mypy --strict) is maintained when modifying src/.