from __future__ import annotations
import time
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import box
from src.clients import PolyClient, PolySocket
from src.book import OrderBook

TARGET_SLUG = "lol-lng-jdg-2025-12-21"
TARGET_OUTCOME = "LNG Esports"

def generate_table(book: OrderBook) -> Panel:
    bids, asks = book.get_snapshot(limit=50)
    
    # REFACTOR: Use the method inside OrderBook instead of the standalone function
    bid_cum = book.get_cumulative_values(bids)
    ask_cum = book.get_cumulative_values(asks)

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold white")
    table.add_column("Price", justify="right", style="cyan", width=10)
    table.add_column("Size", justify="right", style="white", width=10)
    table.add_column("Cum Val ($)", justify="right", style="green", width=15)

    # Asks (Red, Sorted Ascending but printed Top-Down for ladder view)
    for i in range(len(asks) - 1, -1, -1):
        p, s = asks[i]
        c = ask_cum[i]
        table.add_row(f"{p:.2f}", f"{s:.2f}", f"${c:,.2f}", style="red")

    table.add_row("---", "---", "---", style="yellow")

    # Bids (Green, Sorted Descending)
    for i in range(len(bids)):
        p, s = bids[i]
        c = bid_cum[i]
        table.add_row(f"{p:.2f}", f"{s:.2f}", f"${c:,.2f}", style="green")

    status = "Active" if book.ready else "Waiting..."
    color = "green" if book.ready else "red"
    
    return Panel(
        table,
        title=f"{TARGET_SLUG} [{TARGET_OUTCOME}]",
        subtitle=f"Status: {status} | Msgs: {book.msg_count}",
        border_style=color
    )

def main():
    client = PolyClient()
    print(f"🔎 Resolving {TARGET_OUTCOME}...")
    asset_id = client.find_asset_id(TARGET_SLUG, TARGET_OUTCOME)
    
    if not asset_id:
        print("❌ Asset not found")
        return

    book = OrderBook(asset_id)
    ws = PolySocket([asset_id])
    ws.on_book = book.on_book_snapshot
    ws.on_price_change = book.on_price_change
    ws.start()

    console = Console()
    try:
        with Live(console=console, refresh_per_second=10) as live:
            while True:
                live.update(generate_table(book))
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        ws.stop()

if __name__ == "__main__":
    main()