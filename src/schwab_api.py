import os
import json
import requests
import base64
import time
from dotenv import load_dotenv, find_dotenv

env_path = find_dotenv()
load_dotenv(env_path)

AW_APP_KEY = os.getenv("SCHWAB_AW_APP_KEY")
AW_APP_SECRET = os.getenv("SCHWAB_AW_APP_SECRET")
REDIRECT_URI = "https://127.0.0.1" 
TOKEN_FILE = os.path.join("data", "aw_token.json")

if not AW_APP_KEY:
    raise ValueError("ERROR: App Key not found. Check your .env file and variable names.")

def get_auth_url():
    """Step 1: Generates the login link for manual authentication."""
    return f"https://api.schwabapi.com/v1/oauth/authorize?client_id={AW_APP_KEY}&redirect_uri={REDIRECT_URI}"

def fetch_initial_token(auth_code):
    """Step 2: Trades the auth code for the first set of tokens."""
    token_url = "https://api.schwabapi.com/v1/oauth/token"
    auth_string = f"{AW_APP_KEY}:{AW_APP_SECRET}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI
    }
    
    response = requests.post(token_url, headers=headers, data=payload)
    if response.status_code == 200:
        tokens = response.json()
        # Add a timestamp so we know when it expires
        tokens['fetched_at'] = time.time()
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f)
        return tokens
    else:
        print("Error fetching initial token:", response.text)
        return None

def refresh_access_token(refresh_token):
    """Silently grabs a new access token using the 7-day refresh token."""
    token_url = "https://api.schwabapi.com/v1/oauth/token"
    auth_string = f"{AW_APP_KEY}:{AW_APP_SECRET}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    response = requests.post(token_url, headers=headers, data=payload)
    if response.status_code == 200:
        new_tokens = response.json()
        new_tokens['fetched_at'] = time.time()
        # Keep the old refresh token if the API doesn't issue a new one
        if 'refresh_token' not in new_tokens:
            new_tokens['refresh_token'] = refresh_token
            
        with open(TOKEN_FILE, "w") as f:
            json.dump(new_tokens, f)
        return new_tokens['access_token']
    else:
        print("Failed to refresh token:", response.text)
        return None

def get_valid_access_token():
    """Loads the token, checks if it's expired, and refreshes it if necessary."""
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError("Token file missing. You need to authenticate first.")
        
    with open(TOKEN_FILE, "r") as f:
        tokens = json.load(f)
        
    # Check expiration (Schwab tokens usually last 1800 seconds / 30 mins)
    # We buffer by 60 seconds just to be safe
    elapsed_time = time.time() - tokens.get('fetched_at', 0)
    if elapsed_time > (tokens.get('expires_in', 1800) - 60):
        print("Token expired. Refreshing silently...")
        return refresh_access_token(tokens['refresh_token'])
    
    return tokens['access_token']

def get_latest_closes(tickers: list):
    """Fetches the latest closing price for a list of tickers."""
    access_token = get_valid_access_token()
    if not access_token:
        return {}

    # The Schwab Market Data API accepts a comma-separated list of symbols
    symbol_string = ",".join(tickers)
    quotes_url = f"https://api.schwabapi.com/marketdata/v1/quotes?symbols={symbol_string}"
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(quotes_url, headers=headers)
    if response.status_code != 200:
        print(f"Error fetching quotes: {response.text}")
        return {}

    data = response.json()
    prices = {}
    
    # Parse out just the closing prices
    for symbol, details in data.items():
        # 'quote' contains 'closePrice' (previous close) or 'mark' (current price)
        # Using 'closePrice' for stability in a 401k dashboard
        if 'quote' in details and 'closePrice' in details['quote']:
            prices[symbol] = details['quote']['closePrice']
            
    return prices

# --- QUICK TEST ---
if __name__ == "__main__":
    test_tickers = ["AVUV", "AVUS", "VGSH"]
    print(f"Fetching quotes for: {test_tickers}")
    prices = get_latest_closes(test_tickers)
    print("Results:")
    for ticker, price in prices.items():
        print(f"{ticker}: ${price}")
        