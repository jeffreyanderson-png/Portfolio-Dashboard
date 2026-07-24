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
REDIRECT_URI = "https://127.0.0.1:8080" 
TOKEN_FILE = os.path.join("data", "aw_token.json")

if not AW_APP_KEY:
    print("WARNING: Alpine Wind App Key not found. Check your .env file.")

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
        tokens['fetched_at'] = time.time()
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f)
        return tokens
    else:
        print("Error fetching initial AW token:", response.text)
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
        if 'refresh_token' not in new_tokens:
            new_tokens['refresh_token'] = refresh_token
            
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump(new_tokens, f)
        return new_tokens['access_token']
    else:
        print("Failed to refresh AW token:", response.text)
        return None

def get_valid_access_token():
    """Loads the token, checks if it's expired, and refreshes it if necessary."""
    if not os.path.exists(TOKEN_FILE):
        print("AW Token file missing. Needs authentication.")
        return None
        
    with open(TOKEN_FILE, "r") as f:
        tokens = json.load(f)
        
    elapsed_time = time.time() - tokens.get('fetched_at', 0)
    if elapsed_time > (tokens.get('expires_in', 1800) - 60):
        print("AW Token expired. Refreshing silently...")
        return refresh_access_token(tokens['refresh_token'])
    
    return tokens.get('access_token')

# --- MARKET DATA SPECIFIC FUNCTIONS ---

def get_latest_closes(tickers: list):
    """Fetches the latest closing price for a list of tickers."""
    access_token = get_valid_access_token()
    if not access_token:
        return {}

    symbol_string = ",".join(tickers)
    quotes_url = f"https://api.schwabapi.com/marketdata/v1/quotes?symbols={symbol_string}"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(quotes_url, headers=headers)
    if response.status_code != 200:
        print(f"Error fetching quotes: {response.text}")
        return {}

    data = response.json()
    prices = {}
    
    for symbol, details in data.items():
        if 'quote' in details and 'closePrice' in details['quote']:
            prices[symbol] = details['quote']['closePrice']
            
    return prices