import json
import requests
from datetime import datetime, timezone
from src.schwab_account_api import get_valid_access_token, get_account_hashes

def order_desk_test():
    print("🔍 Bypassing Ledger... Hitting the Schwab Order Desk for *3489...")
    access_token = get_valid_access_token()
    hashes = get_account_hashes()
    
    target_hash = next((acct.get('hashValue') for acct in hashes if acct.get('accountNumber', '').endswith('3489')), None)
        
    url = f"https://api.schwabapi.com/trader/v1/accounts/{target_hash}/orders"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    # Schwab's Order API uses different parameter names for time
    start_str = "2026-01-01T00:00:00.000Z"
    end_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    params = {
        "fromEnteredTime": start_str,
        "toEnteredTime": end_str,
        "status": "FILLED"
    }
    
    response = requests.get(url, headers=headers, params=params)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Filled Orders Found: {len(data)}")
        if len(data) > 0:
            print("\n✅ We breached the silo! Here is the first order:")
            print(json.dumps(data[0].get('orderLegCollection', [{}])[0].get('instrument'), indent=2))
        else:
            print("\n❌ The Order Desk is empty too.")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    order_desk_test()