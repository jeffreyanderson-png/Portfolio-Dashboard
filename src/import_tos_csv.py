import pandas as pd
import hashlib
import re
import numpy as np
from datetime import datetime
import io
import csv

def generate_hash(record_dict):
    """Creates a unique hash for a row to prevent duplicates."""
    raw_str = "".join(str(val) for val in record_dict.values())
    return hashlib.md5(raw_str.encode()).hexdigest()
def clean_currency(val):
    """Converts string currency ($1,000.00) or ((1,000.00)) to float."""
    # 1. Handle direct numeric types (float/int/numpy types)
    if isinstance(val, (int, float)):
        # CRITICAL FIX: Check for NaN (Not a Number)
        if pd.isna(val): 
            return 0.0
        return float(val)
        
    # 2. Handle Strings
    val = str(val).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
    
    # Check for empty strings or 'nan' text
    if val == '' or val.lower() == 'nan':
        return 0.0
        
    try:
        return float(val)
    except ValueError:
        return 0.0
def clean_text(val):
    """Converts NaN/Empty strings to None (Database NULL)."""
    if pd.isna(val):
        return None
    val = str(val).strip()
    return val if val != '' else None
def find_idx(df, keyword):
    """Helper to find the row index where a specific keyword appears in column 0."""
    matches = df[df[0].astype(str).str.startswith(keyword, na=False)]
    return matches.index[0] if not matches.empty else None
def parse_file(uploaded_file):
    """
    Parses ThinkOrSwim CSV.
    Returns:
    1. transactions (List of Dicts)
    2. snapshots_list (List of Dicts)
    """
    
    # --- 1. PRE-SCAN (Text Mode) ---
    uploaded_file.seek(0)
    text_content = uploaded_file.getvalue().decode("utf-8", errors='replace')
    lines = text_content.splitlines()
    
    # A. Find Statement End Date
    statement_date = None
    if len(lines) > 0:
        match = re.search(r"through\s+(\d{1,2}/\d{1,2}/\d{2,4})", lines[0])
        if match:
            try:
                statement_date = pd.to_datetime(match.group(1)).date()
            except:
                statement_date = datetime.now().date()
        else:
            statement_date = datetime.now().date()

    # B. Find Net Liquidating Value (Robust CSV Parsing)
    net_liq_value = 0.0
    
    # Use csv.reader to handle quoted numbers like "$1,234.56" correctly
    reader = csv.reader(lines[:100]) # Scan first 100 lines
    for row in reader:
        # row is a list of fields, e.g. ['Net Liquidating Value', '$123,456.78']
        if any("Net Liquidating Value" in str(cell) for cell in row):
            for cell in row:
                try:
                    val = clean_currency(cell)
                    if val > 0:
                        net_liq_value = val
                        break
                except: continue
            if net_liq_value > 0: 
                break

    # --- 2. LOAD RAW DATA (Pandas Mode) ---
    uploaded_file.seek(0)
    df_raw = pd.read_csv(uploaded_file, header=None, low_memory=False)
    
    idx_eq = find_idx(df_raw, "Equities")
    idx_opt = find_idx(df_raw, "Options")
    idx_prof = find_idx(df_raw, "Profits and Losses")
    idx_cash = find_idx(df_raw, "Cash Balance")
    idx_trade = find_idx(df_raw, "Account Trade History")

    # --- 3. PARSE POSITIONS (Held on Statement Date) ---
    current_positions = []
    
    # A. Equities
    if idx_eq:
        end_eq = idx_opt if idx_opt else (idx_prof if idx_prof else idx_cash)
        if end_eq:
            uploaded_file.seek(0)
            df_equities = pd.read_csv(uploaded_file, skiprows=idx_eq+1, nrows=end_eq-(idx_eq+2))
            
            if 'Symbol' in df_equities.columns:
                df_equities = df_equities.dropna(subset=['Symbol'])
                for _, row in df_equities.iterrows():
                    if row['Symbol'] == 'Total': continue
                    
                    current_positions.append({
                        "symbol": clean_text(row['Symbol']),
                        "description": clean_text(row.get('Description')),
                        "qty": clean_currency(row.get('Qty')),
                        "mark_price": clean_currency(row.get('Mark')),
                        "market_value": clean_currency(row.get('Market Value')),
                        "asset_type": "STOCK" # Requested Change
                    })

    # B. Options
    if idx_opt:
        end_opt = idx_prof if idx_prof else idx_cash
        if end_opt:
            uploaded_file.seek(0)
            df_options = pd.read_csv(uploaded_file, skiprows=idx_opt+1, nrows=end_opt-(idx_opt+2))
            
            col_name = 'Option Code' if 'Option Code' in df_options.columns else 'Symbol'
            
            if col_name in df_options.columns:
                df_options = df_options.dropna(subset=[col_name])
                for _, row in df_options.iterrows():
                    if row[col_name] == 'Total': continue
                    
                    current_positions.append({
                        "symbol": clean_text(row[col_name]),
                        "description": clean_text(row.get('Exp')),
                        "qty": clean_currency(row.get('Qty')),
                        "mark_price": clean_currency(row.get('Mark')),
                        "market_value": clean_currency(row.get('Market Value')),
                        "asset_type": "OPTION",
                        "exp_date_str": clean_text(row.get('Exp')),
                        "strike": clean_currency(row.get('Strike')),
                        "option_type": clean_text(row.get('Type'))
                    })

    # --- 4. PARSE CASH BALANCE ---
    snapshots_list = []
    if idx_cash:
        nrows = (idx_trade - (idx_cash + 2)) if idx_trade else None
        
        uploaded_file.seek(0)
        df_cash = pd.read_csv(uploaded_file, skiprows=idx_cash+1, nrows=nrows)
        
        if 'TYPE' in df_cash.columns:
            df_bals = df_cash[df_cash['TYPE'] == 'BAL']
            
            for _, row in df_bals.iterrows():
                try:
                    snap_date = pd.to_datetime(row['DATE']).date()
                except:
                    continue
                
                is_valid_liq = (snap_date == statement_date)
                
                snapshots_list.append({
                    "snapshot_date": snap_date,
                    "total_cash_balance": clean_currency(row.get('BALANCE', 0)),
                    "net_liquidating_value": net_liq_value if is_valid_liq else None,
                    "is_net_liq_valid": is_valid_liq,
                    "positions": current_positions if is_valid_liq else []
                })

    # --- 5. PARSE TRANSACTIONS ---
    transactions = []
    if idx_trade:
        uploaded_file.seek(0)
        df_history = pd.read_csv(uploaded_file, skiprows=idx_trade+1)
        
        df_history.replace(r'^\s*$', np.nan, regex=True, inplace=True)
        columns_to_fill = ['Exec Time', 'Spread']
        existing_cols = [c for c in columns_to_fill if c in df_history.columns]
        df_history[existing_cols] = df_history[existing_cols].ffill()
        df_history.dropna(subset=['Exec Time'], inplace=True)

        for index, trade in df_history.iterrows():
            # Date/Time Logic
            raw_datetime = str(trade.get('Exec Time', ''))
            trade_date_str = None
            trade_time_str = "00:00:00"

            if ' ' in raw_datetime:
                parts = raw_datetime.split(' ')
                trade_date_str = parts[0]
                trade_time_str = parts[1]
                if len(trade_time_str.split(':')) == 2:
                    trade_time_str += ":00"

            trade_symbol = clean_text(trade.get('Symbol'))

            # Fee Matching
            fees = 0.0
            commissions = 0.0
            cash_desc = None
            
            if 'df_cash' in locals():
                safe_symbol = re.escape(str(trade_symbol)) if trade_symbol else ""
                if safe_symbol:
                    matches = df_cash[
                        (df_cash['DATE'] == trade_date_str) & 
                        (df_cash['DESCRIPTION'].str.contains(rf'\b{safe_symbol}\b', regex=True, na=False))
                    ]
                    if not matches.empty:
                        fees = matches['Misc Fees'].apply(clean_currency).sum()
                        commissions = matches['Commissions & Fees'].apply(clean_currency).sum()
                        cash_desc = clean_text(matches.iloc[0].get('DESCRIPTION'))

            # Calculation
            raw_exp = str(trade.get('Exp', '')).strip()
            is_option = (raw_exp != '' and raw_exp.lower() != 'nan') or (pd.notna(trade.get('Spread')) and trade.get('Spread') != 'STOCK')
            multiplier = 100 if is_option else 1
            
            qty_val = clean_currency(trade.get('Qty'))
            price_val = clean_currency(trade.get('Price'))
            calculated_net = -(qty_val * price_val * multiplier) - fees - commissions

            record = {
                "Exec_Date": trade_date_str,
                "Exec_Time": trade_time_str,
                "Symbol": trade_symbol,
                "Qty": qty_val,
                "Price": price_val,
                "Side": clean_text(trade.get('Side')),
                "spread": clean_text(trade.get('Spread')),
                "pos_effect": clean_text(trade.get('Pos Effect')),
                "exp_date_str": clean_text(trade.get('Exp')),
                "strike": clean_currency(trade.get('Strike')),
                "option_type": clean_text(trade.get('Type')),
                "cb_description": cash_desc,
                "cb_misc_fees": fees,
                "cb_commissions": commissions,
                "cb_amount": calculated_net,
                "transaction_type": "TRADE"
            }
            record['row_hash'] = generate_hash(record)
            transactions.append(record)

    return transactions, snapshots_list