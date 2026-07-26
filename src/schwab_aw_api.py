import os
import json
import requests
import base64
import time
import concurrent.futures # IMPORT ADDED FOR MULTITHREADING
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
    return f"https://api.schwabapi.com/v1/oauth/authorize?client_id={AW_APP_KEY}&redirect_uri={REDIRECT_URI}"

def fetch_initial_token(auth_code):
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
    if not os.path.exists(TOKEN_FILE):
        return None
        
    with open(TOKEN_FILE, "r") as f:
        tokens = json.load(f)
        
    elapsed_time = time.time() - tokens.get('fetched_at', 0)
    if elapsed_time > (tokens.get('expires_in', 1800) - 60):
        print("AW Token expired. Refreshing silently...")
        return refresh_access_token(tokens['refresh_token'])
    
    return tokens.get('access_token')

# --- MARKET DATA SPECIFIC FUNCTIONS ---

def get_quotes(tickers: list):
    """Fetches rich quote data for a list of tickers."""
    access_token = get_valid_access_token()
    if not access_token or not tickers:
        return {}

    symbol_string = ",".join(tickers)
    quotes_url = f"https://api.schwabapi.com/marketdata/v1/quotes?symbols={symbol_string}"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(quotes_url, headers=headers)
    if response.status_code != 200:
        print(f"Error fetching quotes: {response.text}")
        return {}

    data = response.json()
    quotes = {}
    
    for symbol, details in data.items():
        q = details.get('quote', {})
        quotes[symbol] = {
            "mark": q.get("mark"),
            "close": q.get("closePrice"),
            "open": q.get("openPrice"),
            "high": q.get("highPrice"),
            "low": q.get("lowPrice"),
            "netChange": q.get("netChange"),
            "52WkHigh": q.get("52WeekHigh"),
            "52WkLow": q.get("52WeekLow")
        }
            
    return quotes

def get_latest_closes(tickers: list):
    """Backward-compatible wrapper function."""
    quotes_data = get_quotes(tickers)
    simple_prices = {}
    for ticker, data in quotes_data.items():
        if data.get("close"):
            simple_prices[ticker] = data["close"]
    return simple_prices

# Helper function for the thread pool
def _fetch_single_chain_iv(ticker, headers):
    """Worker function to fetch a single ticker's IV."""
    chains_url = f"https://api.schwabapi.com/marketdata/v1/chains?symbol={ticker}&strikeCount=1"
    try:
        response = requests.get(chains_url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return ticker, data.get('volatility', None)
        else:
            return ticker, None
    except Exception:
        return ticker, None

def get_implied_volatility(tickers: list):
    """
    Fetches the aggregate Implied Volatility for a list of tickers concurrently.
    Returns a dictionary: {"SPY": 0.152, "AAPL": 0.221}
    """
    access_token = get_valid_access_token()
    if not access_token or not tickers:
        return {}

    headers = {"Authorization": f"Bearer {access_token}"}
    iv_data = {}
    
    # Use a ThreadPoolExecutor to fire requests concurrently.
    # We cap max_workers at 10 to avoid slamming the Schwab API too hard.
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # submit all tasks to the pool
        future_to_ticker = {
            executor.submit(_fetch_single_chain_iv, ticker, headers): ticker 
            for ticker in tickers
        }
        
        # As each task finishes, grab the result
        for future in concurrent.futures.as_completed(future_to_ticker):
            ticker, volatility = future.result()
            iv_data[ticker] = volatility
            
    return iv_data