import sys
from pathlib import Path

# Path Fix
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.utils import get_tokens_from_game

def main():
    print("📋 Polymarket Game Lookup Tool")
    print("Paste a URL, Slug, or ID below (Ctrl+C to quit)")
    user_input = input("\n> ")
    
    
    print("\n🔎 Searching...")
    result = get_tokens_from_game(user_input)
    print(result)
    

if __name__ == "__main__":
    main()