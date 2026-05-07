import os
import json
import requests
import base64
import time
from dotenv import load_dotenv, find_dotenv

env_path = find_dotenv()
load_dotenv(env_path)

AF_APP_KEY = os.getenv("SCHWAB_AF_APP_KEY")
AF_APP_SECRET = os.getenv("SCHWAB_AF_APP_SECRET")
REDIRECT_URI = "https://127.0.0.1" 
TOKEN_FILE = os.path.join("data", "af_token.json")

if not AF_APP_KEY:
    raise ValueError("ERROR: AlpineFire App Key not found. Check your .env file.")

def fetch_initial_token(auth_code):
    """Step 2: Trades the auth code for the first set of tokens."""
    token_url = "https://api.schwabapi.com/v1/oauth/token"
    auth_string = f"{AF_APP_KEY}:{AF_APP_SECRET}"
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
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f)
        return tokens
    else:
        print("Error fetching initial token:", response.text)
        return None

def refresh_access_token(refresh_token):
    """Silently grabs a new access token using the 7-day refresh token."""
    token_url = "https://api.schwabapi.com/v1/oauth/token"
    auth_string = f"{AF_APP_KEY}:{AF_APP_SECRET}"
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
        
    elapsed_time = time.time() - tokens.get('fetched_at', 0)
    if elapsed_time > (tokens.get('expires_in', 1800) - 60):
        print("Token expired. Refreshing silently...")
        return refresh_access_token(tokens['refresh_token'])
    
    return tokens['access_token']

def get_account_data():
    """Fetches all linked accounts, balances, and current positions."""
    access_token = get_valid_access_token()
    if not access_token:
        return None
        
    # Schwab Trader API endpoint for accounts and positions
    accounts_url = "https://api.schwabapi.com/trader/v1/accounts?fields=positions"
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(accounts_url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching account data: {response.text}")
        return None

def get_transactions(account_hash, start_date_iso, end_date_iso):
    """Fetches all transactions for a specific account within a date range."""
    access_token = get_valid_access_token()
    if not access_token:
        return None
        
    transactions_url = f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/transactions"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    # Schwab requires exactly this format: 2026-01-01T00:00:00.000Z
    params = {
        "startDate": start_date_iso,
        "endDate": end_date_iso,
#        "types": "TRADE" # Filters out dividend payouts, wire transfers, etc.
    }
    
    response = requests.get(transactions_url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching transactions for {account_hash}: {response.text}")
        return []

def get_account_hashes():
    """Fetches the encrypted account hashes needed for transaction lookups."""
    access_token = get_valid_access_token()
    if not access_token:
        return []
        
    hash_url = "https://api.schwabapi.com/trader/v1/accounts/accountNumbers"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(hash_url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching account hashes: {response.text}")
        return []
        