import numpy as np # Make sure to import numpy at the top
import pandas as pd
import hashlib
import io
import re  # Added for Regex parsing

def generate_hash(row): #Creates a unique fingerprint for a transaction row.
    #Combines core fields: Date + Time + Symbol + Side + Qty + Price
    # We concatenate values into a single string. 
    # Example: "2026-01-1310:30:00AMDTOCLOSE-15.50"
    raw_str = f"{row['Exec_Date']}{row['Exec_Time']}{row['Symbol']}{row['Side']}{row['Qty']}{row['Price']}"
    
    # Return the MD5 hash of that string
    return hashlib.md5(raw_str.encode()).hexdigest()

def clean_currency(value): #Converts strings like '$1,200.50' or '(5.00)' to floats.
    
    if pd.isna(value) or value == '':
        return 0.0
    
    str_val = str(value).replace('$', '').replace(',', '')
    
    # Handle parentheses for negative numbers: (5.00) -> -5.00
    if '(' in str_val and ')' in str_val:
        str_val = '-' + str_val.replace('(', '').replace(')', '')
        
    try:
        return float(str_val)
    except ValueError:
        return 0.0

def parse_file(file_object):
    content = file_object.getvalue().decode("utf-8")
    lines = content.splitlines()

    # --- 1. SECTION FINDER (Updated for "Futures Statements") ---
    sections = {}
    for i, line in enumerate(lines):
        clean_line = line.strip()
        if clean_line.startswith("Account Trade History"):
            sections['history_start'] = i + 1
        elif clean_line.startswith("Equities"):
            sections['history_end'] = i
        elif clean_line.startswith("Cash Balance"):
            sections['cash_start'] = i + 1
        elif clean_line.startswith("Futures Statements"): # Updated per your request
            sections['cash_end'] = i
        elif clean_line.startswith("Account Summary"):
            sections['summary_start'] = i + 1
            
    # --- UPDATED: 2. EXTRACT SNAPSHOT DATA ---
    net_liq = 0.0
    summary_end = sections.get('summary_start', len(lines)) + 20
    summary_lines = lines[sections['summary_start']:summary_end]
    
    for line in summary_lines:
        if "Net Liquidating Value" in line:
            # Strategy: Split by comma, look for the first valid number
            parts = line.split(',')
            for part in parts:
                try:
                    # Clean it, try to convert. If it works and isn't 0, we take it.
                    val = clean_currency(part)
                    if val > 0:
                        net_liq = val
                        break
                except:
                    continue
            if net_liq > 0: 
                break

    # --- 3. LOAD DATAFRAMES ---
    h_end = sections.get('history_end', len(lines))
    c_end = sections.get('cash_end', len(lines))
    
    def read_section(start, end):
        raw = "\n".join(lines[start:end])
        return pd.read_csv(io.StringIO(raw))

    df_history = read_section(sections['history_start'], h_end)
    df_cash = read_section(sections['cash_start'], c_end)

    # --- 4. EXTRACT CASH TOTALS & CLEANUP ---
    cash_total = 0.0
    
    # Find the TOTAL row (Case Sensitive check)
    if 'DESCRIPTION' in df_cash.columns:
        total_row = df_cash[df_cash['DESCRIPTION'] == 'TOTAL']
        if not total_row.empty:
            # Assuming 'Amount' or 'Balance' holds the total. Check your CSV header.
            # Usually the last column is the running balance.
            # Let's assume user wants the 'Amount' column from the total line
            cash_total = clean_currency(total_row.iloc[0].get('AMOUNT', 0))
            
        # Remove the TOTAL row so it doesn't mess up trade matching
        df_cash = df_cash[df_cash['DESCRIPTION'] != 'TOTAL']

    # Create the Snapshot Object (return this to app.py later)
    snapshot_data = {
        "net_liquidating_value": net_liq,
        "total_cash_balance": cash_total
    }

    # --- 5. MERGING LOGIC (TRADES) ---
    transactions = []

    # 1. CLEANUP EMPTY ROWS
    # First, drop rows that are COMPLETELY empty (all columns are NaN)
    df_history.dropna(how='all', inplace=True)

    # 2. HANDLE SPREAD GROUPING (The Fix)
    # Convert empty strings/whitespace to real 'NaN' so Pandas can see them
    df_history.replace(r'^\s*$', np.nan, regex=True, inplace=True)
    
    # Define which columns are safe to copy down from the parent trade
    # We ONLY want Date, Time, and Spread type. 
    # We DO NOT want to fill Strike, Exp, or Side.
    columns_to_fill = ['Exec Time', 'Spread'] # Add 'Date' if your CSV splits them
    
    # Check if these columns exist before trying to fill (safety check)
    existing_cols_to_fill = [c for c in columns_to_fill if c in df_history.columns]
    
    # Apply Forward Fill (ffill) only to these specific columns
    df_history[existing_cols_to_fill] = df_history[existing_cols_to_fill].ffill()

    # 3. NOW it is safe to drop rows that still lack a Date
    # (This catches truly garbage lines, but preserves the spread legs we just filled)
    df_history.dropna(subset=['Exec Time'], inplace=True)
    
    # --- PART A: STANDARD TRADES (From History) ---
    for index, trade in df_history.iterrows():
        
        # 1. Parse Date and Time explicitly
        raw_datetime = str(trade.get('Exec Time', ''))

        # Default values
        trade_date_str = None
        trade_time_str = "00:00:00"

        if ' ' in raw_datetime:
            parts = raw_datetime.split(' ')
            trade_date_str = parts[0]  # "12/23/2025"
            trade_time_str = parts[1]  # "9:32"

            # Fix: Ensure time has seconds (9:32 -> 9:32:00) for consistency
            if len(trade_time_str.split(':')) == 2:
                trade_time_str += ":00"
        
        #trade_date_str = trade.get('Exec Time', '').split(' ')[0] 
        trade_symbol = trade.get('Symbol')

        # --- FIX: STRICT MATCHING ---
        # We use \b (Word Boundary) so "UP" matches " UP " but NOT "GROUP" or "UPON"
        # We also use re.escape() to handle symbols like "BRK.B" safely
        safe_symbol = re.escape(str(trade_symbol))

        # Filter matching fees in Cash Balance
        matches = df_cash[
            (df_cash['DATE'] == trade_date_str) & 
            (df_cash['DESCRIPTION'].str.contains(rf'\b{safe_symbol}\b', regex=True, na=False))
        ]
        
        fees = 0.0
        commissions = 0.0
        
        # Capture Description from the matching cash row if it exists
        cash_desc = None
        if not matches.empty:
            cash_desc = matches.iloc[0].get('DESCRIPTION')

        if not matches.empty:
            # Take the first match as agreed
            first_match = matches.iloc[0]
            fees = clean_currency(first_match.get('Misc Fees', 0))
            commissions = clean_currency(first_match.get('Commissions & Fees', 0))
        
        # ---- Calculate cb_amount for the trade type transactions ----
        # 1. Determine Multiplier (100 for Options, 1 for Stock or ETF)
        # If the row has an 'Exp', it's for sure an option
        raw_exp = str(trade.get('Exp', '')).strip()
        is_option = raw_exp != '' and raw_exp.lower() != 'nan'
        multiplier = 100 if is_option else 1
        
        # 2. Get values safely
        qty_val = clean_currency(trade.get('Qty'))
        price_val = clean_currency(trade.get('Price'))

        # 3. The Math: -(Qty * Price * Mult) # Fees can be excluded because they aren't a part of the amount column
        # Example Buy: -(1 * 5.00 * 100) - 0.65 = -500.65 (Cash leaves account)
        # Example Sell: -(-1 * 5.00 * 100) - 0.65 = +500 - 0.65 = +499.35 (Cash enters)
        calculated_net = -(qty_val * price_val * multiplier) #- fees - commissions
        
        record = {
            "Exec_Date": trade_date_str, # We pass the clean string "12/23/2025"
            "Exec_Time": trade_time_str,
            "Symbol": trade_symbol,
            "Qty": qty_val,
            "Price": price_val,
            "Side": trade.get('Side'),
            
            # Use lowercase keys to match what we expect in dbfunctions later
            "spread": trade.get('Spread'),         # Capture Spread
            "pos_effect": trade.get('Pos Effect'), # Capture Open/Close
            
            # --- NEW: Capture Option Data ---
            # We grab the raw string for Date, handle conversion in dbfunctions
            "exp_date_str": trade.get('Exp'), # Pass raw "16-Jan-26"
            "strike": clean_currency(trade.get('Strike')),
            "option_type": trade.get('Type'), # Call/Put
            
            # --- NEW: Cash Data ---
            "cb_description": cash_desc,
            "cb_misc_fees": fees,
            "cb_commissions": commissions,
            "cb_amount": calculated_net, # Calulating cb_amount for trades to avoid reading it from cash balance
            
            # --- RENAMED: Avoid conflict with Option 'Type' column ---
            "transaction_type": "TRADE" 
        }
        record['row_hash'] = generate_hash(record)
        transactions.append(record)

    # --- PART B: ASSIGNMENTS / EXPIRATIONS (From Cash Balance) ---
    # Filter for TYPE == 'EXP' (Expiration/Assignment/Exercise)
    if 'TYPE' in df_cash.columns:
        assignment_rows = df_cash[df_cash['TYPE'] == 'EXP']
        
        for index, row in assignment_rows.iterrows():
            desc = row.get('DESCRIPTION', '')
            amount = clean_currency(row.get('AMOUNT', 0))
            
            # Skip if amount is 0 (Pure Expiration usually has 0 cash flow)
            if amount == 0:
                continue

            # Regex to Parse: "SOLD -100.0 LAC UPON..." or "BOT 100 LAC..."
            # Pattern: Look for (SOLD or BOT) followed by a Number, then the Ticker
            match = re.search(r'(SOLD|BOT)\s+([-\d\.]+)\s+(\w+)', desc)
            
            if match:
                side_str = match.group(1) # "SOLD" or "BOT"
                qty_str = match.group(2)  # "-100.0" or "100"
                symbol_str = match.group(3) # "LAC"
                
                qty = float(qty_str)
                
                # Calculate Price per share
                # Avoid division by zero
                price = 0.0
                if qty != 0:
                    price = abs(amount / qty)

                # Map "BOT/SOLD" to "BUY/SELL" for consistency
                final_side = "SELL" if side_str == "SOLD" else "BUY"

                assign_record = {
                    "Exec_Date": row.get('DATE'),
                    "Exec_Time": "00:00:00", # Cash balance usually has no time
                    "Symbol": symbol_str,
                    "Qty": qty,
                    "Price": price,
                    "Side": final_side,
                    "cb_misc_fees": clean_currency(row.get('Misc Fees', 0)),
                    "cb_commissions": 0.0, # Assignments usually have no comms
                    #"Type": "ASSIGNMENT",
                    "transaction_type": "ASSIGNMENT",
                    "cb_amount": amount # Useful to track the raw cash impact
                }
                assign_record['row_hash'] = generate_hash(assign_record)
                transactions.append(assign_record)

    return pd.DataFrame(transactions), snapshot_data
