import sys
from pathlib import Path

# Path Fix
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree
from src.utils import get_game_data

def main():
    console = Console()
    console.print("[bold cyan]📋 Polymarket Game Lookup Tool[/bold cyan]")
    console.print("Paste a URL, Slug, or ID below (Ctrl+C to quit)")
    
    try:
        while True:
            user_input = console.input("\n[green]>[/green] ")
            
            with console.status("[bold yellow]Searching...[/bold yellow]"):
                event = get_game_data(user_input)

            if not event:
                console.print("[bold red]❌ No event found.[/bold red]")
                continue

            # --- Display Logic ---
            title = event.get("title", "Unknown Event")
            slug = event.get("slug", "N/A")
            event_id = event.get("id", "N/A")

            root = Tree(f"[bold gold1]{title}[/bold gold1]")
            root.add(f"[dim]ID: {event_id}[/dim]")
            root.add(f"[dim]Slug: {slug}[/dim]")

            markets = event.get("markets", [])
            
            for m in markets:
                question = m.get("question", "Market")
                market_node = root.add(f"[bold blue]{question}[/bold blue]")
                
                outcomes = m.get("outcomes", [])
                clob_ids = m.get("clobTokenIds", [])

                if len(outcomes) == len(clob_ids):
                    for i, outcome in enumerate(outcomes):
                        market_node.add(f"{outcome}: [cyan]{clob_ids[i]}[/cyan]")
                else:
                    market_node.add("[red]⚠️ Token Mismatch[/red]")

            console.print(Panel(root, border_style="green"))

    except KeyboardInterrupt:
        console.print("\n[bold red]Exiting...[/bold red]")

if __name__ == "__main__":
    main()