import streamlit as st
from sqlmodel import create_engine
import os
import re
from datetime import datetime, date

def parse_occ_expiration(occ_string):
    if not occ_string: 
        return None
    match = re.search(r'(\d{6})([CP])(\d{8})$', occ_string.upper())
    if match:
        try:
            return datetime.strptime(match.group(1), "%y%m%d").date()
        except ValueError:
            pass
    return None

def get_days_to_expiration(exp_date):
    if not exp_date: 
        return 999 
    return (exp_date - date.today()).days

def parse_occ_type_and_strike(occ_string):
    if not occ_string: 
        return None, None
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
# AUTO-CLASSIFIER & SPREAD MATCHER
# ==========================================
def get_live_positions_dict(acct_data):
    """Groups open positions by root ticker."""
    positions_by_root = {}
    if not acct_data: 
        return positions_by_root
        
    for acct in acct_data:
        positions = acct.get('securitiesAccount', {}).get('positions', [])
        for pos in positions:
            instr = pos.get('instrument', {})
            sym = instr.get('symbol', '')
            a_type = instr.get('assetType', instr.get('type', 'UNKNOWN'))
            
            if a_type == 'OPTION':
                root = instr.get('underlyingSymbol', sym[:6].strip())
            elif a_type in ('FUTURE', 'FUTURES'):
                root = sym.split(':')[0][:-3] if ':' in sym else sym
            else:
                root = sym
                
            if root not in positions_by_root:
                positions_by_root[root] = []
            positions_by_root[root].append(pos)
            
    return positions_by_root

def auto_classify_strategy(positions):
    """Dynamically determines the strategy based on current holdings."""
    has_stock = False
    short_puts, long_puts = 0, 0
    short_calls, long_calls = 0, 0
    
    for pos in positions:
        instr = pos.get('instrument', {})
        a_type = instr.get('assetType', instr.get('type', 'UNKNOWN'))
        net_qty = pos.get('longQuantity', 0) - pos.get('shortQuantity', 0)
        
        if a_type == 'EQUITY' and net_qty > 0:
            has_stock = True
        elif a_type == 'OPTION' and net_qty != 0:
            opt_type, _ = parse_occ_type_and_strike(instr.get('symbol', ''))
            if opt_type == 'P':
                if net_qty < 0: 
                    short_puts += abs(net_qty)
                else: 
                    long_puts += net_qty
            elif opt_type == 'C':
                if net_qty < 0: 
                    short_calls += abs(net_qty)
                else: 
                    long_calls += net_qty

    # Classification Tree
    if has_stock and short_calls > 0 and short_puts > 0: 
        return "Wheel (Active)"
    if has_stock and short_calls > 0: 
        return "Covered Call"
    if has_stock and short_puts > 0: 
        return "Stock + Short Put"
    if has_stock: 
        return "Long Stock"
    
    if short_puts > 0 and long_puts > 0 and short_calls > 0 and long_calls > 0: 
        return "Iron Condor"
    if short_puts > 0 and long_puts > 0: 
        return "Put Credit Spread"
    if short_calls > 0 and long_calls > 0: 
        return "Call Credit/Debit Spread"
    
    if short_puts > 0: 
        return "Short Puts"
    if short_calls > 0: 
        return "Naked Calls"
    if long_calls > 0 and long_puts > 0: 
        return "Straddle/Strangle"
    if long_calls > 0: 
        return "Long Calls"
    if long_puts > 0: 
        return "Long Puts"
    
    return "Mixed/Other"

def calculate_live_deployed_capital(positions):
    """
    Calculates deployed capital handling Equity, and matching Option Spreads 
    to reduce false 'naked' collateral obligations.
    """
    deployed_capital = 0.0
    puts = []
    calls = []
    
    for pos in positions:
        instr = pos.get('instrument', {})
        sym = instr.get('symbol', '')
        a_type = instr.get('assetType', instr.get('type', 'UNKNOWN'))
        
        long_qty = pos.get('longQuantity', 0)
        short_qty = pos.get('shortQuantity', 0)
        net_qty = long_qty - short_qty
        
        # 1. Stock Capital
        if a_type == 'EQUITY' and net_qty > 0:
            avg_price = pos.get('averagePrice', 0.0)
            deployed_capital += (net_qty * avg_price)
            
        # Separate Options for Spread Matching
        elif a_type == 'OPTION' and net_qty != 0:
            opt_type, strike = parse_occ_type_and_strike(sym)
            if opt_type == 'P' and strike:
                puts.append({'strike': strike, 'qty': net_qty})
            elif opt_type == 'C' and strike:
                calls.append({'strike': strike, 'qty': net_qty})

    # 2. Put Spread Matcher (Calculates Risk Width instead of Naked Collateral)
    short_puts = sorted([p for p in puts if p['qty'] < 0], key=lambda x: x['strike'], reverse=True)
    long_puts = sorted([p for p in puts if p['qty'] > 0], key=lambda x: x['strike'], reverse=True)
    
    for sp in short_puts:
        unhedged_qty = abs(sp['qty'])
        strike_risk = sp['strike']
        
        for lp in long_puts:
            if lp['qty'] > 0 and lp['strike'] < sp['strike']: # Valid hedge found
                hedged_amt = min(unhedged_qty, lp['qty'])
                spread_width = sp['strike'] - lp['strike']
                deployed_capital += (spread_width * 100.0 * hedged_amt)
                
                lp['qty'] -= hedged_amt
                unhedged_qty -= hedged_amt
            if unhedged_qty <= 0: 
                break
                
        if unhedged_qty > 0:
            # Unhedged naked put
            deployed_capital += (strike_risk * 100.0 * unhedged_qty)

    # 3. Call Spread Matcher (Assuming Covered Calls tie up 0 extra capital beyond stock)
    short_calls = sorted([c for c in calls if c['qty'] < 0], key=lambda x: x['strike'])
    long_calls = sorted([c for c in calls if c['qty'] > 0], key=lambda x: x['strike'])
    
    for sc in short_calls:
        unhedged_qty = abs(sc['qty'])
        for lc in long_calls:
            if lc['qty'] > 0 and lc['strike'] > sc['strike']:
                hedged_amt = min(unhedged_qty, lc['qty'])
                spread_width = lc['strike'] - sc['strike']
                deployed_capital += (spread_width * 100.0 * hedged_amt)
                lc['qty'] -= hedged_amt
                unhedged_qty -= hedged_amt
        # Note: We ignore naked call infinite risk here to prevent skewing graphs, 
        # as it is usually covered by stock or standard margin.

    return deployed_capital