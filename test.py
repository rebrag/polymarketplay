import requests

def get_asset_info(asset_id):
    # The Gamma API allows filtering markets directly by token_id (asset_id)
    url = f"https://gamma-api.polymarket.com/markets?token_id={asset_id}"
    
    try:
        response = requests.get(url)
        data = response.json()

        if not data:
            return "Asset not found"

        # The API returns a list of markets (usually just one if searching by token_id)
        market = data[0]
        
        # 1. Get the Market Title (The Question)
        question = market.get('question')
        
        # 2. Find which specific outcome this asset_id belongs to (YES or NO)
        outcome_label = "Unknown"
        for token in market.get('tokens', []):
            if token.get('token_id') == asset_id:
                outcome_label = token.get('outcome') # e.g., "Yes", "No", "Trump", "Biden"
                break
        
        return f"{question} [{outcome_label}]"

    except Exception as e:
        return f"Error: {e}"

# Example Usage
# This is a real asset_id for a specific outcome
asset_id = "107253887545612747914420197722364948250199317318878713566101889311301417062844" 
print(get_asset_info(asset_id))