# Polymarket NFL Arbitrage Bot (Proof of Concept)

This project is a quantitative trading tool designed to identify and exploit arbitrage opportunities ("edges") on the [Polymarket](https://polymarket.com/) prediction market.

The bot calculates "Fair Value" probabilities derived from **Pinnacle** (a sharp sportsbook) via The Odds API and compares them against live Ask prices on the Polymarket CLOB (Central Limit Order Book).

## ⚠️ Current Status: Proof of Concept

This repository currently contains **two primary Proof of Concept (PoC) files** that demonstrate the core logic of the strategy:

1.  **`find_edge_v6.py`**: The **Scanner**. It finds the trades.
2.  **`submitting_transactions.py`**: The **Executor**. It places the trades.

---

## 📂 File Breakdown

### 1. `find_edge_v6.py` (The Scanner)
This is the "Brain" of the operation. It performs the following steps:
* **Data Ingestion:** Fetches fresh NFL odds from Pinnacle (via The Odds API) and downloads all active NFL markets from Polymarket using pagination and Tag ID filtering.
* **Entity Resolution:** Uses **Fuzzy Matching** (`thefuzz`) and strict keyword filtering (e.g., ignoring "1H", "O/U" for Moneyline bets) to align Pinnacle team names with Polymarket market questions.
* **Math & Logic:**
    * Converts Pinnacle's decimal odds into "Fair Value" probability (removing the vig/fee).
    * Fetches the live Order Book for the matched Polymarket ID.
    * Calculates the Edge: `(Fair Probability) - (Polymarket Ask Price)`.
* **Output:** Prints a list of matched markets. If `Edge > 1%` (configurable), it flags a **💰 BUY SIGNAL** and provides the URL.

### 2. `submitting_transactions.py` (The Executor)
This is the "Hands" of the operation. It validates network connectivity and order execution capability.
* **Authentication:** Connects to the Polymarket CLOB API using L1 (Private Key) and L2 (API Key) authentication.
* **Proxy Support:** Specifically configured with `signature_type=1` and a `funder` address to support **Magic Link / Email Wallets**.
* **Market Check:** Fetches the live orderbook for a specific hardcoded Token ID to calculate the spread.
* **Execution:** Submits a live **Limit Order** to the Polygon blockchain.
    * *Note: Currently hardcoded to place a test bid (Buy 5 shares @ $0.01).*

---

## 🚀 Setup & Installation

### 1. Prerequisites
* Python 3.10+ (I used python 3.12)
* A Polymarket Account (with USDC deposited on Polygon)
* An API Key from [The Odds API](https://the-odds-api.com/)

### 2. Install Dependencies
```bash
pip install requests python-dotenv py-clob-client thefuzz