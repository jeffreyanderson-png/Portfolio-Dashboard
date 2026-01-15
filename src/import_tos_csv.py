import pandas as pd
import hashlib
import re
import numpy as np
from datetime import datetime, timedelta
import io
import csv 

# --- CONFIG ---
DEBUG_MODE = False # Set to True to see why specific trades fail matching

def generate_hash(record_dict):
    raw_str = "".join(str(val) for val in record_dict.values())
    return hashlib.md5(raw_str.encode()).hexdigest()

def clean_currency(val):
    if isinstance(val, (int, float)):
        if pd.isna(val): return 0.0
        return float(val)
    val = str(val).replace('$', '').replace(',', '').replace('(', '-').replace(')', '').strip()
    if val == '' or val.lower() == 'nan': return 0.0
    try: return float(val)
    except ValueError: return 0.0

def clean_text(val):
    if pd.isna(val): return None
    val = str(val).strip()
    return val if val != '' else None

def extract_section(df_raw, start_idx, end_idx, key_col_candidates):
    if start_idx is None: return pd.DataFrame()
    sl = df_raw.iloc[start_idx+1 : end_idx] if end_idx else df_raw.iloc[start_idx+1 :]
    if sl.empty: return pd.DataFrame()

    header_idx = -1
    found_cols = []
    for i in range(min(10, len(sl))):
        row_vals = sl.iloc[i].astype(str).tolist()
        for key in key_col_candidates:
            if any(key in val for val in row_vals):
                header_idx = i
                found_cols = row_vals
                break
        if header_idx != -1: break
            
    if header_idx == -1: return pd.DataFrame()

    data_slice = sl.iloc[header_idx+1 :].copy()
    clean_headers = [str(c).strip() if pd.notna(c) and str(c).strip() != '' else f"UNK_{k}" for k, c in enumerate(found_cols)]
    
    if len(clean_headers) == len(data_slice.columns):
        data_slice.columns = clean_headers
    return data_slice

def find_section_start(df_raw, section_name):
    mask = df_raw[0].astype(str).str.strip().str.startswith(section_name, na=False)
    indices = df_raw.index[mask].tolist()
    return indices[0] if indices else None

def parse_file(uploaded_file):
    
    # --- 1. PRE-SCAN ---
    uploaded_file.seek(0)
    text_content = uploaded_file.getvalue().decode("utf-8", errors='replace')
    lines = text_content.splitlines()
    
    statement_date = None
    if len(lines) > 0:
        match = re.search(r"through\s+(\d{1,2}/\d{1,2}/\d{2,4})", lines[0])
        if match:
            try: statement_date = pd.to_datetime(match.group(1)).date()
            except: statement_date = datetime.now().date()
        else: statement_date = datetime.now().date()

    net_liq_value = 0.0
    reader = csv.reader(lines)
    for i, row in enumerate(reader):
        line_text = lines[i]
        if "Net Liquidating Value" in line_text:
            found_in_cells = False
            for cell in row:
                try:
                    if "Net Liquidating Value" in str(cell): continue
                    val = clean_currency(cell)
                    if val != 0.0:
                        net_liq_value = val
                        found_in_cells = True
                        break
                except: continue
            if found_in_cells: break
            match = re.search(r"Net Liquidating Value[^\d-]*(-?\$?[\d,]+(\.\d+)?)", line_text)
            if match:
                try:
                    val = clean_currency(match.group(1))
                    if val != 0.0:
                        net_liq_value = val
                        break
                except: pass
    
    # --- 2. LOAD RAW DATA ---
    uploaded_file.seek(0)
    dummy_cols = list(range(100)) 
    df_raw = pd.read_csv(uploaded_file, header=None, names=dummy_cols, engine='python')
    
    # --- 3. LOCATE SECTIONS ---
    idx_cash = find_section_start(df_raw, "Cash Balance")
    idx_trade = find_section_start(df_raw, "Account Trade History")
    idx_eq = find_section_start(df_raw, "Equities")
    idx_opt = find_section_start(df_raw, "Options")
    idx_prof = find_section_start(df_raw, "Profits and Losses")
    idx_summary = find_section_start(df_raw, "Account Summary")
    
    all_indices = sorted([i for i in [idx_cash, idx_trade, idx_eq, idx_opt, idx_prof, idx_summary] if i is not None])
    
    def get_end_idx(start_idx):
        if start_idx is None: return None
        next_indices = [i for i in all_indices if i > start_idx]
        return next_indices[0] if next_indices else None

    # --- 4. EXTRACT DATAFRAMES ---
    df_cash = pd.DataFrame()
    if idx_cash is not None:
        df_cash = extract_section(df_raw, idx_cash, get_end_idx(idx_cash), ["DATE", "Date"])
        if not df_cash.empty:
            date_col = 'DATE' if 'DATE' in df_cash.columns else ('Date' if 'Date' in df_cash.columns else None)
            if date_col:
                df_cash['dt_obj'] = pd.to_datetime(df_cash[date_col], errors='coerce')

    df_equities = pd.DataFrame()
    if idx_eq is not None:
        df_equities = extract_section(df_raw, idx_eq, get_end_idx(idx_eq), ["Symbol"])

    df_options = pd.DataFrame()
    if idx_opt is not None:
        df_options = extract_section(df_raw, idx_opt, get_end_idx(idx_opt), ["Option Code", "Symbol"])

    df_history = pd.DataFrame()
    if idx_trade is not None:
        df_history = extract_section(df_raw, idx_trade, get_end_idx(idx_trade), ["Exec Time", "DATE", "Date"])

    # --- 5. PARSE POSITIONS ---
    current_positions = []
    
    if not df_equities.empty and 'Symbol' in df_equities.columns:
        df_equities = df_equities.dropna(subset=['Symbol'])
        for _, row in df_equities.iterrows():
            if str(row['Symbol']) == 'Total': continue
            current_positions.append({
                "symbol": clean_text(row['Symbol']),
                "description": clean_text(row.get('Description')),
                "qty": clean_currency(row.get('Qty')),
                "mark_price": clean_currency(row.get('Mark')),
                "market_value": clean_currency(row.get('Market Value')),
                "asset_type": "STOCK" 
            })

    if not df_options.empty:
        col_name = 'Option Code' if 'Option Code' in df_options.columns else 'Symbol'
        if col_name in df_options.columns:
            df_options = df_options.dropna(subset=[col_name])
            for _, row in df_options.iterrows():
                if str(row[col_name]) == 'Total': continue
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

    # --- 6. PARSE SNAPSHOTS ---
    snapshots_list = []
    if not df_cash.empty:
        type_col = 'TYPE' if 'TYPE' in df_cash.columns else ('Type' if 'Type' in df_cash.columns else None)
        bal_col = 'BALANCE' if 'BALANCE' in df_cash.columns else ('Balance' if 'Balance' in df_cash.columns else None)
        
        if type_col and bal_col:
            df_bals = df_cash[df_cash[type_col] == 'BAL']
            for _, row in df_bals.iterrows():
                try: snap_date = pd.to_datetime(row.get('DATE', row.get('Date'))).date()
                except: continue
                is_valid_liq = (snap_date == statement_date)
                snapshots_list.append({
                    "snapshot_date": snap_date,
                    "total_cash_balance": clean_currency(row.get(bal_col, 0)),
                    "net_liquidating_value": net_liq_value if is_valid_liq else None,
                    "is_net_liq_valid": is_valid_liq,
                    "positions": current_positions if is_valid_liq else []
                })

    # --- 7. PARSE TRANSACTIONS ---
    transactions = []
    
    if not df_cash.empty:
        amt_col = 'AMOUNT' if 'AMOUNT' in df_cash.columns else ('Amount' if 'Amount' in df_cash.columns else None)
        desc_col = 'DESCRIPTION' if 'DESCRIPTION' in df_cash.columns else ('Description' if 'Description' in df_cash.columns else None)
        
        if amt_col: df_cash['clean_amount'] = df_cash[amt_col].apply(clean_currency)
        else: df_cash['clean_amount'] = 0.0
        
        df_cash['is_matched'] = False
        df_cash['match_id'] = df_cash.index

    if not df_history.empty:
        # Safe Fill
        for c in ['Exec Time', 'Spread']:
            if c in df_history.columns:
                df_history[c] = df_history[c].replace(r'^\s*$', np.nan, regex=True).ffill()
        
        if 'Exec Time' in df_history.columns:
            df_history.dropna(subset=['Exec Time'], inplace=True)
            
            # Safe Group Fill
            def group_fill(group):
                cols = [c for c in ['Symbol', 'Exp'] if c in group.columns]
                group[cols] = group[cols].replace(r'^\s*$', np.nan, regex=True).ffill()
                return group
            
            df_history = df_history.groupby('Exec Time', group_keys=False).apply(group_fill)
            df_history['group_id'] = df_history.groupby(['Exec Time', 'Symbol']).ngroup()
            
            for gid, group in df_history.groupby('group_id'):
                
                # 1. METADATA
                group_gross_total = 0.0
                trade_dt_obj = None
                trade_symbol = None
                leg_amounts = []
                
                for index, trade in group.iterrows():
                    raw_datetime = str(trade.get('Exec Time', ''))
                    if ' ' in raw_datetime and trade_dt_obj is None:
                        try: trade_dt_obj = pd.to_datetime(raw_datetime.split(' ')[0])
                        except: pass
                    
                    trade_symbol = clean_text(trade.get('Symbol'))
                    qty_val = clean_currency(trade.get('Qty'))
                    price_val = clean_currency(trade.get('Price'))
                    exp_val = clean_text(trade.get('Exp') or trade.get('EXP'))
                    spread_val = clean_text(trade.get('Spread') or trade.get('SPREAD'))
                    
                    # --- FUND FIX ---
                    # Treat 'FUND' exactly like 'STOCK' (Multiplier 1)
                    spread_check = str(spread_val).strip().upper()
                    is_stock_spread = spread_val and spread_check in ['STOCK', 'FUND']
                    is_option = (exp_val is not None) or (spread_val is not None and not is_stock_spread)
                    multiplier = 100 if is_option else 1
                    
                    leg_amt = -(qty_val * price_val * multiplier)
                    leg_amounts.append(leg_amt)
                    group_gross_total += leg_amt

                # 2. TIER 1: CLUSTER MATCH
                cluster_matched = False
                cluster_fees = 0.0
                cluster_comm = 0.0
                cluster_desc = None
                
                if not df_cash.empty and trade_symbol and trade_dt_obj and desc_col:
                    safe_symbol = re.escape(str(trade_symbol))
                    start_date = trade_dt_obj
                    end_date = trade_dt_obj + timedelta(days=5) # Expanded to 5 for Funds
                    
                    # Try Regex first
                    candidates = df_cash[
                        (df_cash['dt_obj'] >= start_date) & 
                        (df_cash['dt_obj'] <= end_date) &
                        (~df_cash['is_matched']) &
                        (df_cash[desc_col].astype(str).str.contains(rf'\b{safe_symbol}\b', regex=True, na=False))
                    ]
                    
                    # Fallback: Simple text search if regex fails (Handles "FUND (SWPPX)")
                    if candidates.empty:
                        candidates = df_cash[
                            (df_cash['dt_obj'] >= start_date) & 
                            (df_cash['dt_obj'] <= end_date) &
                            (~df_cash['is_matched']) &
                            (df_cash[desc_col].astype(str).str.contains(str(trade_symbol), regex=False, na=False))
                        ]
                    
                    if not candidates.empty:
                        candidates_cluster = candidates.copy()
                        candidates_cluster['diff'] = (candidates_cluster['clean_amount'] - group_gross_total).abs()
                        candidates_cluster = candidates_cluster.sort_values('diff')
                        
                        if candidates_cluster.iloc[0]['diff'] < 20.0:
                            best_idx = candidates_cluster.iloc[0]['match_id']
                            match_row = df_cash.loc[best_idx]
                            
                            misc_col = 'Misc Fees' if 'Misc Fees' in df_cash.columns else 'MISC FEES'
                            comm_col = 'Commissions & Fees' if 'Commissions & Fees' in df_cash.columns else 'COMMISSIONS & FEES'
                            
                            cluster_fees = clean_currency(match_row.get(misc_col, 0))
                            cluster_comm = clean_currency(match_row.get(comm_col, 0))
                            cluster_desc = clean_text(match_row.get(desc_col))
                            
                            df_cash.loc[best_idx, 'is_matched'] = True
                            cluster_matched = True

                # 3. GENERATE RECORDS
                for i, (index, trade) in enumerate(group.iterrows()):
                    # Re-extract
                    raw_datetime = str(trade.get('Exec Time', ''))
                    trade_date_str, trade_time_str = None, "00:00:00"
                    if ' ' in raw_datetime:
                        parts = raw_datetime.split(' ')
                        trade_date_str = parts[0]
                        trade_time_str = parts[1]
                        if len(trade_time_str.split(':')) == 2: trade_time_str += ":00"

                    gross_leg_amount = leg_amounts[i]
                    row_fees, row_comm, row_desc = 0.0, 0.0, None
                    is_matched = False
                    match_diff = 0.0

                    if cluster_matched:
                        is_matched = True
                        if i == 0:
                            row_fees, row_comm, row_desc = cluster_fees, cluster_comm, cluster_desc
                        else:
                            row_desc = cluster_desc + " (Spread Part)"
                    else:
                        # TIER 2: INDIVIDUAL MATCH
                        if not candidates.empty:
                            live_candidates = df_cash.loc[candidates.index]
                            live_candidates = live_candidates[~live_candidates['is_matched']]
                            
                            if not live_candidates.empty:
                                live_candidates = live_candidates.copy()
                                live_candidates['diff'] = (live_candidates['clean_amount'] - gross_leg_amount).abs()
                                live_candidates = live_candidates.sort_values('diff')
                                
                                best_diff = live_candidates.iloc[0]['diff']
                                
                                if best_diff < 5.0:
                                    best_idx = live_candidates.iloc[0]['match_id']
                                    match_row = df_cash.loc[best_idx]
                                    
                                    misc_col = 'Misc Fees' if 'Misc Fees' in df_cash.columns else 'MISC FEES'
                                    comm_col = 'Commissions & Fees' if 'Commissions & Fees' in df_cash.columns else 'COMMISSIONS & FEES'
                                    
                                    row_fees = clean_currency(match_row.get(misc_col, 0))
                                    row_comm = clean_currency(match_row.get(comm_col, 0))
                                    row_desc = clean_text(match_row.get(desc_col))
                                    
                                    df_cash.loc[best_idx, 'is_matched'] = True
                                    is_matched = True
                                    match_diff = best_diff
                    
                    # Validation Logic
                    manual_review = False
                    review_reason = None
                    
                    if not is_matched:
                        manual_review = True
                        review_reason = "No Cash Match Found"
                        if DEBUG_MODE:
                            print(f"DEBUG FAIL: {trade_symbol} | Expect: {gross_leg_amount}")
                    elif match_diff > 5.0 and not cluster_matched:
                        manual_review = True
                        review_reason = f"Math Mismatch: Diff ${match_diff:.2f}"

                    # Record Generation
                    qty_val = clean_currency(trade.get('Qty'))
                    price_val = clean_currency(trade.get('Price'))
                    exp_val = clean_text(trade.get('Exp') or trade.get('EXP'))
                    spread_val = clean_text(trade.get('Spread') or trade.get('SPREAD'))
                    calculated_net = gross_leg_amount + row_fees + row_comm

                    record = {
                        "Exec_Date": trade_date_str,
                        "Exec_Time": trade_time_str,
                        "Symbol": clean_text(trade.get('Symbol')),
                        "Qty": qty_val,
                        "Price": price_val,
                        "Side": clean_text(trade.get('Side')),
                        "spread": spread_val,
                        "pos_effect": clean_text(trade.get('Pos Effect')),
                        "exp_date_str": exp_val,
                        "strike": clean_currency(trade.get('Strike') or trade.get('STRIKE')),
                        "option_type": clean_text(trade.get('Type') or trade.get('TYPE')),
                        "cb_description": row_desc,
                        "cb_misc_fees": row_fees,
                        "cb_commissions": row_comm,
                        "cb_amount": calculated_net,
                        "transaction_type": "TRADE",
                        "manual_review": manual_review,
                        "review_reason": review_reason
                    }
                    record['row_hash'] = generate_hash(record)
                    transactions.append(record)

    return transactions, snapshots_list
