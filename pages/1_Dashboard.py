import streamlit as st
import pandas as pd
import os
from datetime import date, timedelta
from sqlmodel import Session, select, func, col
from src.models import Transaction, AccountSnapshot, PositionSnapshot
from src.dbfunctions import create_engine_func

import pandas_ta_classic as ta  # Efficient technical analysis library

st.set_page_config(page_title="Dashboard", layout="wide")

@st.cache_resource
def get_db_engine():
    db_file = os.path.join("data", "portfolio.db")
    db_url = f"sqlite:///{db_file}"
    return create_engine_func(db_url)

engine = get_db_engine()

st.title("🚀 Portfolio Dashboard")

# --- HELPER: DATES ---
today = date.today()
start_of_year = date(today.year, 1, 1)
d30_start = today - timedelta(days=30)
d60_start = today - timedelta(days=60)

# --- SECTION 1: PREMIUM ENGINE (Income) ---
st.header("💸 Premium Income (Net)")

with Session(engine) as session:
    # 1. FETCH OPTION TRANSACTIONS
    # STRICT FILTER: Must be explicitly CALL or PUT.
    # We also keep the +/- 5000 limit to catch any accidental large assignments.
    
    def get_premium_sum(start_date, end_date=None):
        query = select(func.sum(Transaction.cb_amount)).where(
            col(Transaction.option_type).in_(["CALL", "PUT", "Call", "Put"]), # Handle case sensitivity
            Transaction.exec_date >= start_date,
            Transaction.cb_amount.between(-5000, 5000) 
        )
        if end_date:
            query = query.where(Transaction.exec_date < end_date)
        
        result = session.exec(query).first()
        return result if result else 0.0

    ytd_premium = get_premium_sum(start_of_year)
    last_30_premium = get_premium_sum(d30_start)
    prior_30_premium = get_premium_sum(d60_start, d30_start)
    
    delta_30 = last_30_premium - prior_30_premium

    c1, c2, c3 = st.columns(3)
    c1.metric("YTD Option Income", f"${ytd_premium:,.2f}")
    c2.metric("Last 30 Days", f"${last_30_premium:,.2f}", delta=f"{delta_30:,.2f} vs Prior")
    c3.metric("Prior 30 Days", f"${prior_30_premium:,.2f}")

    st.divider()

    # --- SECTION 2: CAPITAL & RISK ---
    st.header("🛡️ Capital & Risk")
    
    latest_snap = session.exec(select(AccountSnapshot).order_by(AccountSnapshot.snapshot_date.desc())).first()
    
    if not latest_snap:
        st.warning("No data found.")
        st.stop()
        
    positions = session.exec(select(PositionSnapshot).where(PositionSnapshot.snapshot_id == latest_snap.id)).all()
    
    csp_collateral = 0.0
    stock_value = 0.0
    put_risk_total = 0.0
    
    for p in positions:
        if p.asset_type == 'STOCK':
            stock_value += p.market_value
        elif p.asset_type == 'OPTION' and str(p.option_type).upper() == 'PUT' and p.qty < 0:
            collateral = abs(p.qty) * (p.strike or 0) * 100
            csp_collateral += collateral
            put_risk_total += collateral

    # Capital Display
    col_cap1, col_cap2, col_cap3 = st.columns(3)
    col_cap1.metric("Stock Holdings", f"${stock_value:,.2f}")
    col_cap2.metric("Cash Securing Puts", f"${csp_collateral:,.2f}")
    col_cap3.metric("Total Put Risk", f"${put_risk_total:,.0f}")
    
    st.divider()
