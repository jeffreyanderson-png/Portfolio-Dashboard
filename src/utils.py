import streamlit as st
from sqlmodel import create_engine
import os
import re
from datetime import datetime, date

def parse_occ_expiration(occ_string):
    if not occ_string: return None
    match = re.search(r'(\d{6})([CP])(\d{8})$', occ_string.upper())
    if match:
        try:
            return datetime.strptime(match.group(1), "%y%m%d").date()
        except ValueError:
            pass
    return None

def get_days_to_expiration(exp_date):
    if not exp_date: return 999 
    return (exp_date - date.today()).days

def parse_occ_type_and_strike(occ_string):
    if not occ_string: return None, None
    match = re.search(r'(\d{6})([CP])(\d{8})$', occ_string.upper())
    if match:
        return match.group(2), int(match.group(3)) / 1000.0
    return None, None

@st.cache_resource
def get_db_engine():
    db_url = "sqlite:///data/portfolio.db"
    os.makedirs("data", exist_ok=True)
    return create_engine(db_url, connect_args={"check_same_thread": False})


# ==========================================
# LIVE POSITION METRICS (The Ground Truth)
# ==========================================
def get_live_positions_dict(acct_data):
    """
    Takes raw Schwab account data and groups all currently open positions by root ticker.
    Returns: { 'AAPL': [pos1, pos2], 'SPXW': [pos1] }
    """
    positions_by_root = {}
    if not acct_data:
        return positions_by_root
        
    for acct in acct_data:
        positions = acct.get('securitiesAccount', {}).get('positions', [])
        for pos in positions:
            instr = pos.get('instrument', {})
            sym = instr.get('symbol', '')
            
            # Schwab sometimes uses 'assetType' in transactions but 'type' in positions
            a_type = instr.get('assetType', instr.get('type', 'UNKNOWN'))
            
            if a_type == 'OPTION':
                root = instr.get('underlyingSymbol', sym[:6].strip())
            elif a_type == 'FUTURE' or a_type == 'FUTURES':
                root = sym.split(':')[0][:-3] if ':' in sym else sym
            else:
                root = sym
                
            if root not in positions_by_root:
                positions_by_root[root] = []
            positions_by_root[root].append(pos)
            
    return positions_by_root

def calculate_live_deployed_capital(positions):
    """
    Calculates deployed capital based ONLY on live, currently open positions.
    Relies on Schwab's official averagePrice and shortQuantity.
    """
    deployed_capital = 0.0
    
    for pos in positions:
        instr = pos.get('instrument', {})
        sym = instr.get('symbol', '')
        a_type = instr.get('assetType', instr.get('type', 'UNKNOWN'))
        
        long_qty = pos.get('longQuantity', 0)
        short_qty = pos.get('shortQuantity', 0)
        
        # 1. Stock Capital (Schwab provides the exact average price)
        if a_type == 'EQUITY' and long_qty > 0:
            avg_price = pos.get('averagePrice', 0.0)
            deployed_capital += (long_qty * avg_price)
            
        # 2. Options Capital (Put Collateral)
        elif a_type == 'OPTION' and short_qty > 0:
            opt_type, strike = parse_occ_type_and_strike(sym)
            if opt_type == 'P' and strike:
                # short_qty is an absolute positive number in the positions array
                deployed_capital += (strike * 100.0 * short_qty)
                
    return deployed_capital